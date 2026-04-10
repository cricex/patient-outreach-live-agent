"""REST API endpoints for the React frontend.

Provides prompt set CRUD and (future) LLM prompt generation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


# ---- Prompt Generation (placeholder for Phase 2 LLM integration) ----


class GeneratePromptRequest(BaseModel):
    """Request to generate a system prompt from a scenario description."""

    scenario: str
    tone: str = "warm and professional"
    language: str = "English"


class GeneratePromptResponse(BaseModel):
    """Generated system prompt draft."""

    system_prompt: str
    call_brief: str


@router.post("/prompts/generate", response_model=GeneratePromptResponse)
async def generate_prompt(req: GeneratePromptRequest):
    """Generate a system prompt from a scenario description.

    Currently returns a template-based draft. Phase 2+ will call Azure OpenAI.
    """
    system_prompt = f"""BEGIN SYSTEM
ROLE: Scheduling assistant for Microsoft Health Clinic. Goal: help the patient schedule care.
LANGUAGE: {req.language} only. Plain text. No emojis.
STYLE: {req.tone}. 8-18 words per turn. Contractions OK.
PRIVACY: First name only. Share details after identity confirmed.

SCENARIO: {req.scenario}

FLOW: greet → confirm identity → purpose → answer Qs → schedule → confirm → close.
ONE QUESTION RULE: Ask one question at a time.
SAFETY: No diagnoses. Urgent symptoms → advise emergency services.
END SYSTEM"""

    call_brief = f"""BEGIN CALL_BRIEF
TOP_NEED: (fill in based on scenario)
PRIORITY: routine
PATIENT_NAME: (patient first name)
TIMING: next 2-4 weeks
WHY: {req.scenario}
END CALL_BRIEF"""

    return GeneratePromptResponse(system_prompt=system_prompt, call_brief=call_brief)
