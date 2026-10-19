"""
api/routers/chat.py — Results chat endpoints (B-025, ADR-014).

POST /api/chat                  — ask a question about a project's latest scan
GET  /api/chat/{workspace_id}   — conversation history, totals and whether a scan exists
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.chat import ChatError, chat_turn, get_chat_history

router = APIRouter(tags=["chat"])

_STATUS = {"empty_message": 422, "no_scan": 409, "no_api_key": 409, "llm_error": 502}


class ChatRequest(BaseModel):
    workspace_id: int = Field(..., gt=0)
    message: str


@router.post("/api/chat")
def post_chat(body: ChatRequest):
    """Blocking (non-streaming) turn; runs in FastAPI's thread pool because the LLM call is sync."""
    try:
        return chat_turn(body.workspace_id, body.message)
    except ChatError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.code, 400),
                            detail={"code": exc.code, "message": exc.message})


@router.get("/api/chat/{workspace_id}")
def get_chat(workspace_id: int):
    return get_chat_history(workspace_id)
