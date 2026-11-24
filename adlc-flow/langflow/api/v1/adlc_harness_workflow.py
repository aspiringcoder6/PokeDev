"""Authenticated read-only starter; normal flow creation/plan/run APIs own all writes."""

import os

from fastapi import APIRouter, HTTPException, Response

from langflow.adlc.harness_workflow import workflow_enabled
from langflow.adlc.harness_workflow_starter import starter
from langflow.api.v1.adlc_verification import Owner

router = APIRouter(prefix="/adlc/harness-workflows", tags=["ADLC Agent Harness"])


@router.get("/starter")
async def get_starter(user: Owner, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not workflow_enabled() or str(user.id) != os.getenv("ADLC_DEMO_GITHUB_OWNER_ID"):
        raise HTTPException(404, {"code": "HARNESS_WORKFLOW_NOT_CONFIGURED"})
    return starter()
