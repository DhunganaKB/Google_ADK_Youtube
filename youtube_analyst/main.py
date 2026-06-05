import os
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from .common.firestore_session_service import FirestoreSessionService
from .common.tracer import tracer
from google.genai import types

from .agent import root_agent
from .config import config

app = FastAPI(title="YouTube Analyst API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup ADK services
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Using FirestoreSessionService for persistence.
session_service = FirestoreSessionService(
    database="(default)", project=config.GOOGLE_CLOUD_PROJECT
)

# Using FileArtifactService for persisting artifacts like plots/reports
artifact_dir = os.path.join(project_root, ".adk", "artifacts")
os.makedirs(artifact_dir, exist_ok=True)
artifact_service = FileArtifactService(root_dir=artifact_dir)

runner = Runner(
    agent=root_agent,
    session_service=session_service,
    artifact_service=artifact_service,
    app_name=config.app_name,
    auto_create_session=True,
)

class ChatRequest(BaseModel):
    message: str
    user_id: str = "user"
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # Open a Langfuse trace for this request.
    # If tracing is disabled (missing keys or LANGFUSE_ENABLED=false),
    # start_trace() returns None and all trace.* calls below are no-ops.
    trace = tracer.start_trace(
        name="chat-request",
        input={"message": request.message},
        metadata={
            "user_id": request.user_id,
            "session_id": request.session_id,
            "app": config.app_name,
        },
        tags=["youtube-analyst", "chat"],
    )

    try:
        if not request.session_id:
            session = await session_service.create_session(
                user_id=request.user_id, app_name=config.app_name
            )
            session_id = session.id
        else:
            session_id = request.session_id

        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=request.message)],
        )

        response_text = ""
        async for event in runner.run_async(
            new_message=message,
            user_id=request.user_id,
            session_id=session_id,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text

        if not response_text:
            response_text = "The agent did not provide a text response."

        # Record the agent's full response as a generation span.
        if trace:
            trace.generation(
                name="agent-response",
                model=config.agent_settings.model,
                input=[{"role": "user", "content": request.message}],
                output=response_text,
                metadata={"session_id": session_id, "user_id": request.user_id},
            )
            tracer.flush()

        return ChatResponse(response=response_text, session_id=session_id)

    except Exception as e:
        # Record the error in the trace before re-raising.
        if trace:
            trace.generation(
                name="agent-error",
                model=config.agent_settings.model,
                input=[{"role": "user", "content": request.message}],
                output=str(e),
                metadata={"error": True},
            )
            tracer.flush()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

def start():
    """Start the FastAPI server."""
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("youtube_analyst.main:app", host="0.0.0.0", port=port, reload=True)

if __name__ == "__main__":
    start()
