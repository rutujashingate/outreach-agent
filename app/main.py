"""Create the application object that Uvicorn serves as app.main:app."""

from fastapi import FastAPI

from app.api.outreach import router

# FastAPI provides the web application. These details also appear in /docs.
app = FastAPI(
    title="Outreach Agent",
    description="Accept an outreach goal and initialize its workflow state.",
    version="0.1.0",
)
# Attach the endpoint defined in api/outreach.py to this application.
app.include_router(router)
