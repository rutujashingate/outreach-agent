"""Assemble the API and manage database/checkpointer/network lifetimes."""

from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.errors import GraphRecursionError

from app.api.approvals import router as approvals_router
from app.api.dependencies import require_access
from app.api.memory import router as memory_router
from app.api.outreach import router as outreach_router
from app.api.runs import router as runs_router
from app.models.client import ModelClientError
from app.orchestration.runtime import open_runtime
from app.orchestration.runs import ConfigurationError, RunConflict, RunManager, RunNotFound
from app.security.limits import LimitExceeded
from app.settings import Settings
from app.tools.search import ToolError


def create_app(*, settings: Settings | None = None, manager: RunManager | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        configured = settings or (manager.settings if manager is not None else Settings.from_env())
        application.state.settings = configured
        application.state.request_window = deque()
        if manager is None:
            async with open_runtime(configured) as ready_manager:
                application.state.manager = ready_manager
                yield
        else:
            application.state.manager = manager
            yield

    application = FastAPI(title="Outreach Agent", version="0.2.0",
        description="Research goals or run a complete, checkpointed outreach workflow with human approval.",
        lifespan=lifespan)
    for router in (outreach_router, runs_router, approvals_router, memory_router):
        application.include_router(router, dependencies=[Depends(require_access)])

    async def known_error(request: Request, error: Exception):
        code, message = 502, "An external service or model could not complete the request."
        if isinstance(error, ConfigurationError):
            code, message = 503, str(error)
        elif isinstance(error, RunNotFound):
            code, message = 404, str(error)
        elif isinstance(error, RunConflict):
            code, message = 409, str(error)
        elif isinstance(error, LimitExceeded):
            code, message = 429, str(error)
        elif isinstance(error, GraphRecursionError):
            code, message = 429, "Workflow step limit reached; inspect the saved run."
        elif isinstance(error, TimeoutError):
            code, message = 504, "An external tool exceeded its time limit."
        elif isinstance(error, ValueError):
            code, message = 422, str(error)
        content = {"detail": message}
        if getattr(error, "run_id", None):
            content["run_id"] = error.run_id
        return JSONResponse(status_code=code, content=content)

    for exception in (ConfigurationError, RunNotFound, RunConflict, LimitExceeded, GraphRecursionError,
                      TimeoutError, ModelClientError, ToolError, ValueError):
        application.add_exception_handler(exception, known_error)
    return application


# Importing creates routes only. Connections open and close in the lifespan.
app = create_app()
