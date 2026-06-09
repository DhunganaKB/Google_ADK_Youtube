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
    """
    Handle a chat request and trace every agent step to Langfuse.

    Trace structure in Langfuse:
        Trace: chat-request
          ├── Span: tool:search_youtube       input: {query}  output: [{...}]
          ├── Span: tool:get_video_details     input: {ids}    output: [{...}]
          ├── Span: tool:calculate_engagement  input: {...}    output: {...}
          ├── ...  (one span per tool call)
          └── Generation: agent-response       output: "Here are the top 5..."
    """
    with tracer.start_trace(
        name="chat-request",
        input={"message": request.message},
        metadata={
            "user_id": request.user_id,
            "session_id": request.session_id,
            "app": config.app_name,
        },
        tags=["youtube-analyst", "chat"],
    ):
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

            # ── Collect every agent step from the ADK event stream ─────────────
            # tool_calls:  pending calls waiting for their response  {name -> args}
            # tool_spans:  completed {name, input, output} ready to send to Langfuse
            tool_calls: dict[str, list] = {}   # name → [args, ...] (list for repeated calls)
            tool_spans: list[dict] = []

            async for event in runner.run_async(
                new_message=message,
                user_id=request.user_id,
                session_id=session_id,
            ):
                # ── Tool calls — Gemini decided to call a tool ─────────────────
                for fc in event.get_function_calls():
                    pending = tool_calls.setdefault(fc.name, [])
                    pending.append(dict(fc.args or {}))

                # ── Tool responses — tool executed and returned a result ────────
                for fr in event.get_function_responses():
                    pending = tool_calls.get(fr.name, [])
                    args = pending.pop(0) if pending else {}
                    tool_spans.append({
                        "name": fr.name,
                        "input": args,
                        "output": fr.response,
                    })

                # ── Text — collect final answer ────────────────────────────────
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            response_text += part.text

            if not response_text:
                response_text = "The agent did not provide a text response."

            # ── Send all collected spans to Langfuse ───────────────────────────
            if tracer.client:
                # One span per completed tool call
                for span in tool_spans:
                    with tracer.client.start_as_current_span(
                        name=f"tool:{span['name']}",
                        input=span["input"],
                        output=span["output"],
                    ):
                        pass

                # Final generation — the agent's text response to the user
                with tracer.client.start_as_current_generation(
                    name="agent-response",
                    model=config.agent_settings.model,
                    input=[{"role": "user", "content": request.message}],
                    output=response_text,
                    metadata={
                        "session_id": session_id,
                        "user_id": request.user_id,
                        "tool_calls_count": len(tool_spans),
                    },
                ):
                    pass

                tracer.flush()

            return ChatResponse(response=response_text, session_id=session_id)

        except Exception as e:
            if tracer.client:
                with tracer.client.start_as_current_generation(
                    name="agent-error",
                    model=config.agent_settings.model,
                    input=[{"role": "user", "content": request.message}],
                    output=str(e),
                    metadata={"error": True},
                ):
                    pass
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
