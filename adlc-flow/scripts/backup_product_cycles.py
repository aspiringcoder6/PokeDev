"""Back up local SQLite stores and rehearse H8B on a separate copy.

Never migrates the live database or changes a run. Start the normal backend
after reviewing the rehearsal; Alembic then applies the registered revision.
"""

import argparse
import hashlib
import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def fingerprint(connection, table, where=""):
    quoted = '"' + table.replace('"', '""') + '"'
    rows = connection.execute(f"SELECT * FROM {quoted} {where}").fetchall()  # noqa: S608 - fixed table names below.
    encoded = sorted(json.dumps(list(row), default=str, ensure_ascii=False, separators=(",", ":")) for row in rows)
    return {"count": len(rows), "digest": "sha256:" + hashlib.sha256("\n".join(encoded).encode()).hexdigest()}


def critical_records(database):
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        available = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {
            table: fingerprint(connection, table)
            for table in (
                "adlc_delivery",
                "adlc_execution_plan",
                "adlc_project_access",
                "adlc_project_resource",
                "adlc_project_revision",
                "adlc_project_decision",
                "authz_role",
                "authz_role_assignment",
            )
            if table in available
        }
        result["owned_flows"] = fingerprint(connection, "flow", "WHERE user_id IS NOT NULL")
        return result


def backup(source, target):
    with (
        sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as origin,
        sqlite3.connect(target) as destination,
    ):
        origin.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            message = "SQLite backup integrity check failed"
            raise RuntimeError(message)


def main():
    root = Path(__file__).resolve().parents[1]
    database = root / "adlc-local.db"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="Compare the live database to an existing H8B backup manifest")
    parser.add_argument("--label", choices=("h8b", "h8c"), default="h8b")
    parser.add_argument(
        "--backup-only", action="store_true", help="No rehearsal/migration, suitable for H8C's existing schema"
    )
    arguments = parser.parse_args()
    if arguments.verify:
        previous = json.loads((arguments.verify / "manifest.json").read_text(encoding="utf-8"))["before"]
        current = critical_records(database)
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            head = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            foreign_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        report = {
            "legacy_records_unchanged": previous == current,
            "alembic_heads": [row[0] for row in head],
            "foreign_key_errors": foreign_errors,
            "changed_tables": [table for table in previous if previous[table] != current.get(table)],
        }
        (arguments.verify / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        if previous != current or foreign_errors:
            message = "H8B activation changed protected legacy records or foreign-key integrity"
            raise RuntimeError(message)
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "data" / "backups" / f"{arguments.label}-{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    sources = [database, *sorted((root / "data").glob("*.sqlite3"))]
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "files": [], "before": critical_records(database)}
    for source in sources:
        target = directory / source.name
        backup(source, target)
        with target.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        manifest["files"].append({"name": source.name, "bytes": target.stat().st_size, "sha256": checksum})
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if arguments.backup_only:
        print(
            json.dumps(
                {"backup_directory": str(directory), "database_count": len(sources), "live_database_modified": False}
            )
        )
        return
    rehearsal = directory / "h8b-rehearsal.db"
    backup(directory / database.name, rehearsal)
    spec = importlib.util.spec_from_file_location(
        "h8b_revision", root / "langflow/alembic/versions/h8b1c2d3e4f5_add_product_cycles.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{rehearsal.as_posix()}")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        counts = {
            table: connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar_one()  # noqa: S608 - fixed revision-owned names.
            for table in (item.name for item in module.tables())
        }
        foreign_key_errors = len(connection.exec_driver_sql("PRAGMA foreign_key_check").all())
    engine.dispose()
    unchanged = critical_records(rehearsal) == manifest["before"]
    result = {
        "backup_directory": str(directory),
        "database_count": len(sources),
        "legacy_records_unchanged": unchanged,
        "cycle_table_counts": counts,
        "foreign_key_errors": foreign_key_errors,
        "live_database_modified": False,
    }
    (directory / "rehearsal.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if not unchanged or foreign_key_errors:
        message = "H8B rehearsal did not preserve database invariants"
        raise RuntimeError(message)


if __name__ == "__main__":
    main()
