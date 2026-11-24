"""Administrative access to the existing shared Workloop/Slack service."""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, SecretStr

from langflow.adlc.workloop_integration import WorkloopIntegration
from langflow.adlc.document_intake import document_intake
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1.adlc_team_access import TeamUser

router = APIRouter(tags=["Workspace integrations"])


class SlackCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


def slack_admin(actor):
    if not getattr(actor, "is_superuser", False):
        raise HTTPException(403, {"code": "WORKSPACE_INTEGRATION_ADMIN_REQUIRED"})


@router.get("/integrations/slack-notifications")
async def slack_notifications(actor: TeamUser, response: Response):
    slack_admin(actor)
    response.headers["Cache-Control"] = "no-store"
    return document_intake().notifications.settings(str(actor.id))


@router.put("/integrations/slack-notifications")
async def save_slack_notifications(command: SlackCredential, actor: TeamUser):
    slack_admin(actor)
    try:
        result = await document_intake().notifications.connect(str(actor.id), command.token.get_secret_value().strip())
        document_intake().progress.wake.set()
        return result
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None
    except Exception:
        raise HTTPException(503, {"code": "SLACK_SECRET_STORAGE_UNAVAILABLE"}) from None


@router.delete("/integrations/slack-notifications")
async def remove_slack_notifications(actor: TeamUser):
    slack_admin(actor)
    return document_intake().notifications.disconnect(str(actor.id))


@router.get("/integrations/workloop")
async def workloop_integration(actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not getattr(actor, "is_superuser", False):
        raise HTTPException(403, {"code": "WORKSPACE_INTEGRATION_ADMIN_REQUIRED"})
    try:
        return await WorkloopIntegration().inspect()
    except ValueError:
        raise HTTPException(503, {"code": "WORKSPACE_INTEGRATION_CONFIG_INVALID"}) from None
