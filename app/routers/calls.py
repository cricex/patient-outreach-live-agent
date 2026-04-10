"""Call lifecycle routes: start, hangup, webhook events."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..models.requests import (
    CallEventsResponse,
    HangupResponse,
    StartCallRequest,
    StartCallResponse,
)
from ..services.call_manager import call_manager

logger = logging.getLogger("app.main")
router = APIRouter(prefix="/call", tags=["calls"])


@router.post("/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest):
    """Initiate an outbound call or simulate locally."""
    try:
        # Combine system prompt and call brief into a single instruction set
        prompt_parts = []
        if payload.system_prompt:
            prompt_parts.append(payload.system_prompt)
        if payload.call_brief:
            prompt_parts.append(payload.call_brief)
        combined_prompt = "\n\n".join(prompt_parts) if prompt_parts else None

        call_id, dest, prompt = await call_manager.start_call(
            target_phone=payload.target_phone_number,
            system_prompt=combined_prompt,
            simulate=payload.simulate,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    return StartCallResponse(call_id=call_id, to=dest, prompt_used=prompt)


@router.post("/hangup", response_model=HangupResponse)
async def hangup():
    """Terminate the active call."""
    if not call_manager.current_session:
        raise HTTPException(409, "No active call")
    call_id = await call_manager.end_call(reason="ManualHangup")
    return HangupResponse(ok=True, call_id=call_id or "unknown")


@router.post("/events", response_model=CallEventsResponse)
async def call_events(request: Request):
    """ACS webhook receiver for call lifecycle events."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    events = body if isinstance(body, list) else [body]
    ended: list[str] = []

    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = ev.get("type") or ev.get("eventType") or ev.get("publicEventType")
        data = ev.get("data") or {}
        call_id = data.get("callConnectionId") or ev.get("callConnectionId")

        if not et or not call_id:
            continue

        await call_manager.handle_event(et, call_id, data)

        if et.endswith("CallDisconnected") or et.endswith("CallEnded"):
            ended.append(et)

    return CallEventsResponse(ok=True, processed=len(events), ended=ended)
