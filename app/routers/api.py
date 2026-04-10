"""REST API endpoints for the React frontend.

Provides prompt set CRUD and LLM-powered prompt generation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.call_history import delete_call, get_call, list_calls
from ..services.inference import generate_scenario
from ..services.prompt_store import (
    PromptSet,
    delete_prompt,
    get_prompt,
    list_prompts,
    save_prompt,
)

logger = logging.getLogger("app.api")
router = APIRouter(prefix="/api", tags=["api"])


# ---- Prompt CRUD ----


@router.get("/prompts")
async def list_prompt_sets() -> list[PromptSet]:
    """List all saved prompt sets."""
    return list_prompts()


@router.get("/prompts/{prompt_id}")
async def get_prompt_set(prompt_id: str) -> PromptSet:
    """Get a single prompt set by ID."""
    prompt = get_prompt(prompt_id)
    if not prompt:
        raise HTTPException(404, f"Prompt set '{prompt_id}' not found")
    return prompt


@router.post("/prompts")
async def save_prompt_set(prompt: PromptSet) -> PromptSet:
    """Save or update a prompt set."""
    return save_prompt(prompt)


@router.delete("/prompts/{prompt_id}")
async def delete_prompt_set(prompt_id: str):
    """Delete a prompt set."""
    if not delete_prompt(prompt_id):
        raise HTTPException(404, f"Prompt set '{prompt_id}' not found")
    return {"ok": True, "deleted": prompt_id}


# ---- Prompt Generation (Azure AI Foundry) ----


class GeneratePromptRequest(BaseModel):
    """Request to generate a system prompt and call brief from a scenario description."""

    scenario: str
    tone: str = "warm and professional"
    language: str = "English"


class GeneratePromptResponse(BaseModel):
    """Generated system prompt and call brief."""

    scenario_title: str = ""
    system_prompt: str
    call_brief: str


@router.post("/prompts/generate", response_model=GeneratePromptResponse)
async def generate_prompt(req: GeneratePromptRequest):
    """Generate a system prompt and call brief from a scenario description.

    Uses Azure AI Foundry inference to produce contextually appropriate
    voice agent instructions and synthetic call data.
    """
    try:
        result = await generate_scenario(
            scenario_description=req.scenario,
            tone=req.tone,
            language=req.language,
        )
        return GeneratePromptResponse(
            scenario_title=result.get("scenario_title", ""),
            system_prompt=result["system_prompt"],
            call_brief=result["call_brief"],
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


# ---- Call History ----


@router.get("/calls")
async def list_call_history():
    """List all past calls (metadata only, no full transcripts)."""
    return list_calls()


@router.get("/calls/{call_id}")
async def get_call_record(call_id: str):
    """Get a complete call record including transcript."""
    record = get_call(call_id)
    if not record:
        raise HTTPException(404, f"Call '{call_id}' not found")
    return record


@router.delete("/calls/{call_id}")
async def delete_call_record(call_id: str):
    """Delete a call record."""
    if not delete_call(call_id):
        raise HTTPException(404, f"Call '{call_id}' not found")
    return {"ok": True, "deleted": call_id}
