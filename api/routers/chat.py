"""
api/routers/chat.py — Results chat endpoints (B-025, ADR-014).

POST /api/chat                  — ask a question about a project's latest scan (blocking)
POST /api/chat/stream           — same, as a Server-Sent Events stream
GET  /api/chat/{workspace_id}   — conversation history, totals and whether a scan exists

Stream events (all "data:" JSON with a "type"):
  {"type": "tool",  "tool", "args", "ok", "label"}   a tool the model used (e.g. read a file)
  {"type": "token", "text"}                          next piece of the answer
  {"type": "done",  "answer", "tool_activity", "usage", "thread_totals", ...}
  error event: {"code", "message"}
If the client disconnects (Stop), generation ends and the partial answer is saved.
"""

import asyncio
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.sse import sse_event
from core.chat import ChatError, chat_turn, get_chat_history, prepare_turn, run_turn

router = APIRouter(tags=["chat"])

_STATUS = {"empty_message": 422, "no_scan": 409, "no_api_key": 409, "llm_error": 502}
_DONE = object()


class ChatRequest(BaseModel):
    workspace_id: int = Field(..., gt=0)
    message: str


def _http_error(exc: ChatError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 400),
                         detail={"code": exc.code, "message": exc.message})


class _Pump:
    """Lets the async stream pull from the sync turn generator and close it safely.

    close() waits for an in-flight next() to finish, then closes the generator, which is what
    makes the turn save the partial answer.
    """

    def __init__(self, gen):
        self._gen = gen
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            return next(self._gen, _DONE)

    def close(self):
        with self._lock:
            self._gen.close()


@router.post("/api/chat")
def post_chat(body: ChatRequest):
    """Blocking turn; runs in FastAPI's thread pool because the LLM call is synchronous."""
    try:
        return chat_turn(body.workspace_id, body.message)
    except ChatError as exc:
        raise _http_error(exc)


@router.post("/api/chat/stream")
async def post_chat_stream(body: ChatRequest, request: Request):
    loop = asyncio.get_running_loop()
    try:
        ctx = await loop.run_in_executor(None, prepare_turn, body.workspace_id, body.message)
    except ChatError as exc:          # validation errors keep their HTTP status
        raise _http_error(exc)

    pump = _Pump(run_turn(ctx, streaming=True))

    async def events():
        try:
            while not await request.is_disconnected():
                event = await loop.run_in_executor(None, pump.next)
                if event is _DONE:
                    break
                yield sse_event(event)
        except ChatError as exc:
            yield sse_event({"code": exc.code, "message": exc.message}, event="error")
        except Exception as exc:       # unexpected: tell the client instead of hanging
            yield sse_event({"code": "internal", "message": str(exc)}, event="error")
        finally:
            loop.run_in_executor(None, pump.close)   # not awaited: must also run if cancelled

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/chat/{workspace_id}")
def get_chat(workspace_id: int):
    return get_chat_history(workspace_id)
