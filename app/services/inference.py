"""Azure AI Inference service for LLM-powered prompt generation.

Uses the azure-ai-inference SDK to call Foundry-deployed models
for generating system prompts and call briefs from scenario descriptions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger("app.inference")

# Load meta-prompt at module level (read once)
_META_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "meta_generate.md"
_meta_prompt: str | None = None


def _load_meta_prompt() -> str:
    """Load the meta-prompt from disk, caching after first read."""
    global _meta_prompt
    if _meta_prompt is None:
        try:
            _meta_prompt = _META_PROMPT_PATH.read_text(encoding="utf-8")
            logger.info(
                "Loaded meta-prompt from %s (%d chars)",
                _META_PROMPT_PATH,
                len(_meta_prompt),
            )
        except FileNotFoundError:
            logger.error("Meta-prompt not found at %s", _META_PROMPT_PATH)
            raise RuntimeError(f"Meta-prompt file not found: {_META_PROMPT_PATH}")
    return _meta_prompt


async def generate_scenario(
    scenario_description: str,
    tone: str = "warm and professional",
    language: str = "English",
) -> dict[str, str]:
    """Generate a system prompt and call brief from a scenario description.

    Args:
        scenario_description: Plain-language description of the call scenario.
        tone: Desired voice tone for the agent.
        language: Language for the conversation.

    Returns:
        Dict with ``system_prompt`` and ``call_brief`` keys.

    Raises:
        RuntimeError: If inference endpoint is not configured or call fails.
    """
    if not settings.foundry_inference_endpoint:
        raise RuntimeError(
            "FOUNDRY_INFERENCE_ENDPOINT not configured. "
            "Set it in .env to enable AI prompt generation."
        )

    # Build a concise system prompt that avoids content filter triggers.
    # The detailed meta_generate.md was triggering Azure's jailbreak filter
    # when combined with healthcare scenarios, so we use a shorter inline prompt.
    system_msg = (
        "You generate JSON configuration templates for a voice call demo application. "
        "Given a scenario description, produce valid JSON with two fields:\n"
        '- "system_prompt": instructions for a demo voice agent (role, tone, call flow, safety rules)\n'
        '- "call_brief": fictional sample data the agent references during a test call '
        "(fictional names, IDs, dates, context)\n\n"
        "All data must be fictional. Return valid JSON only — no markdown fences, no explanation."
    )

    user_message = (
        f"Scenario: {scenario_description}\n"
        f"Desired tone: {tone}\n"
        f"Language: {language}\n\n"
        "The system_prompt should include: agent role and organization, voice style "
        "(warm, concise, 1-2 sentences per turn), call flow steps, safety boundaries. "
        "Wrap in BEGIN SYSTEM / END SYSTEM.\n\n"
        "The call_brief should include: fictional participant names, relevant IDs/codes, "
        "context summary, key details. Wrap in BEGIN CALL_BRIEF / END CALL_BRIEF."
    )

    try:
        from azure.ai.inference.aio import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential

        # Credential: use dedicated key, fall back to Voice Live key
        api_key = settings.foundry_inference_api_key or settings.voicelive_api_key
        if not api_key:
            raise RuntimeError(
                "No API key available for inference "
                "(set FOUNDRY_INFERENCE_API_KEY or AZURE_VOICELIVE_API_KEY)"
            )

        client = ChatCompletionsClient(
            endpoint=settings.foundry_inference_endpoint.rstrip("/"),
            credential=AzureKeyCredential(api_key),
        )

        async with client:
            response = await client.complete(
                model=settings.foundry_inference_model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
                max_tokens=4000,
            )

        # Extract content from response
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Empty response from inference model")

        logger.info(
            "Scenario generated model=%s chars=%d",
            settings.foundry_inference_model,
            len(content),
        )

        # Parse JSON response — strip markdown fences if the model
        # wraps them despite instructions
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        result = json.loads(cleaned)

        if "system_prompt" not in result or "call_brief" not in result:
            raise RuntimeError(
                "Response missing required fields (system_prompt, call_brief)"
            )

        return {
            "system_prompt": result["system_prompt"],
            "call_brief": result["call_brief"],
        }

    except ImportError:
        logger.error("azure-ai-inference not installed")
        raise RuntimeError(
            "azure-ai-inference package not installed. "
            "Run: pip install azure-ai-inference"
        )
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse inference response as JSON: %s", exc)
        raise RuntimeError(f"Model returned invalid JSON: {exc}")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Inference call failed: %s", exc)
        raise RuntimeError(f"Inference call failed: {exc}")
