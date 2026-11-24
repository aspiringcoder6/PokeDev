"""H8B additive migration preserves legacy authority and matches runtime metadata."""

# ruff: noqa: S101, INP001 - isolated migration assertions.

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import Session, select

from langflow.adlc import delivery as d
from langflow.adlc import delivery_cycles as cycles
from langflow.services.database.models.adlc_delivery import AdlcDelivery
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_product_cycle import (
    AdlcCycleFeedback,
    AdlcCycleHead,
    AdlcCycleOperation,
    AdlcCyclePlanRevision,
    AdlcCycleSpec,
    AdlcProductCycle,
)
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User
from tests.unit.adlc.planning.test_plan_materialization import _graph, _stage
from tests.unit.adlc.test_delivery import service
from tests.unit.adlc.test_project_constraint_names import load_revision, runtime_convention

BASE_MODELS = (User, Folder, Flow, AdlcDelivery, AdlcExecutionPlan)
CYCLE_MODELS = (
    AdlcProductCycle,
    AdlcCycleHead,
    AdlcCycleSpec,
    AdlcCyclePlanRevision,
    AdlcCycleFeedback,
    AdlcCycleOperation,
)


def expected_schema():
    metadata = sa.MetaData(naming_convention=runtime_convention())
    for model in (*BASE_MODELS, *CYCLE_MODELS):
        model.__table__.to_metadata(metadata)
    return metadata


@pytest.mark.parametrize("precreated", [False, True])
def test_fresh_or_precreated_cycle_schema_has_no_drift(precreated):
    metadata = expected_schema()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection, tables=[metadata.tables[model.__tablename__] for model in BASE_MODELS])
        if precreated:
            metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            load_revision("h8b1c2d3e4f5_add_product_cycles.py").upgrade()
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


@pytest.mark.parametrize("linked", [False, True])
def test_legacy_plan_run_approvals_and_notes_are_imported_without_mutation(linked):
    metadata = expected_schema()
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine, tables=[metadata.tables[model.__tablename__] for model in BASE_MODELS])
    actor = User(username="cycle-migration", password="isolated-fixture-hash")  # noqa: S106
    identity = uuid4()
    graph = _graph(identity, include_approval=False)
    graph["nodes"] = [_stage(1, name="Release decision", package_id="approval")]
    graph["edges"] = []
    flow = Flow(id=identity, name="Cycle migration", user_id=actor.id, data=graph)
    plans = service()
    from langflow.adlc.planning.parser import BlueprintParseContext

    now = datetime.now(timezone.utc)
    plan = plans.create_plan_from_graph(
        graph,
        context=BlueprintParseContext(
            flow_id=identity,
            project_id=identity,
            name=flow.name,
            description="",
            created_by=str(actor.id),
            created_at=now,
            updated_at=now,
        ),
        owner_id=str(actor.id),
        generated_by=str(actor.id),
    )
    plan = plans.require_human_review(plan.execution_plan_id, owner_id=str(actor.id))
    plan = plans.approve_plan(plan.execution_plan_id, owner_id=str(actor.id), approved_by=str(actor.id))
    note = d.new_note(
        d.NoteCommand(expected_revision=5, command_id=uuid4(), kind="CHANGE_REQUEST", text="Next increment"), actor
    )
    row = AdlcDelivery(
        flow_id=flow.id,
        owner_id=actor.id,
        title=flow.name,
        requirement="Human release",
        revision=5,
        workflow_approved_digest=d.graph_digest(graph),
        workflow_approved_by=actor.id,
        workflow_approved_at=now,
        plan_id=plan.execution_plan_id,
        plan_approved_digest=d.plan_digest(plan),
        plan_approved_by=actor.id,
        plan_approved_at=now,
        dispatch_plan_id=plan.execution_plan_id,
        run_id=uuid4() if linked else None,
        notes=[note],
    )
    archive = AdlcExecutionPlan(
        id=plan.execution_plan_id,
        owner_id=str(actor.id),
        workflow_definition_id=identity,
        workflow_definition_version=plan.workflow_definition_version,
        plan_version=plan.plan_version,
        status=plan.status,
        validation_status=plan.validation_status,
        approval_required=True,
        plan_payload=plan.model_dump(mode="json"),
        workflow_payload=plans.get_materialization_snapshot(plan.execution_plan_id, owner_id=str(actor.id))[
            1
        ].model_dump(mode="json"),
        generated_at=now,
    )
    with Session(engine, expire_on_commit=False) as session:
        session.add(actor)
        session.flush()
        session.add(flow)
        session.flush()
        session.add_all([row, archive])
        session.commit()
    with engine.begin() as connection:
        original = connection.execute(sa.select(metadata.tables["adlc_delivery"])).mappings().all()
        original_plan = connection.execute(sa.select(metadata.tables["adlc_execution_plan"])).mappings().all()
        with Operations.context(MigrationContext.configure(connection)):
            load_revision("h8b1c2d3e4f5_add_product_cycles.py").upgrade()
        assert connection.execute(sa.select(metadata.tables["adlc_delivery"])).mappings().all() == original
        assert connection.execute(sa.select(metadata.tables["adlc_execution_plan"])).mappings().all() == original_plan
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    with Session(engine) as session:
        cycle = session.get(AdlcProductCycle, cycles.initial_cycle_id(row.id))
        assert cycle.plan_id == row.plan_id
        assert cycle.run_id == row.run_id
        assert cycle.authority["plan_approved_digest"] == row.plan_approved_digest
        assert session.get(AdlcCycleHead, row.id).execution_cycle_id == cycle.id
        spec = session.exec(select(AdlcCycleSpec)).one()
        assert spec.payload == cycles.spec_payload(row, graph, cycle.id, row.requirement)
        assert spec.digest == cycles.sha256_digest(spec.payload)
        binding = session.exec(select(AdlcCyclePlanRevision)).one()
        assert binding.plan_id == row.plan_id
        assert binding.plan_digest == d.plan_digest(plan)
        assert binding.approval["plan_approved_digest"] == row.plan_approved_digest
        assert session.exec(select(AdlcCycleFeedback)).one().payload == note
        operation = session.exec(select(AdlcCycleOperation)).one()
        assert operation.status == ("SUCCEEDED" if linked else "UNCONFIRMED")
        assert operation.result == ({"run_id": str(row.run_id)} if linked else {})
    engine.dispose()


def test_incompatible_lookalike_table_and_destructive_downgrade_are_rejected():
    metadata = expected_schema()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection, tables=[metadata.tables[model.__tablename__] for model in BASE_MODELS])
        connection.exec_driver_sql("CREATE TABLE adlc_product_cycle (id CHAR(32) PRIMARY KEY)")
        module = load_revision("h8b1c2d3e4f5_add_product_cycles.py")
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="Refusing to adopt"),
        ):
            module.upgrade()
        with pytest.raises(RuntimeError, match="preservation migration"):
            module.downgrade()
    engine.dispose()
