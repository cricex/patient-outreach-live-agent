"""Tests for the prompt_store CRUD operations."""
from __future__ import annotations

from app.services.prompt_store import (
    PromptSet,
    delete_prompt,
    get_prompt,
    list_prompts,
    save_prompt,
)


def test_save_creates_json_file(tmp_prompts_dir):
    """save_prompt() should write a .json file to the prompts directory."""
    prompt = PromptSet(id="test-save", name="Test Save", system_prompt="Hello")
    result = save_prompt(prompt)

    assert result.id == "test-save"
    path = tmp_prompts_dir / "test-save.json"
    assert path.exists()


def test_list_returns_saved_prompts(tmp_prompts_dir):
    """list_prompts() should return all previously saved prompt sets."""
    save_prompt(PromptSet(id="alpha", name="Alpha"))
    save_prompt(PromptSet(id="beta", name="Beta"))

    results = list_prompts()
    ids = {p.id for p in results}
    assert "alpha" in ids
    assert "beta" in ids
    assert len(results) == 2


def test_get_prompt_retrieves_by_id(tmp_prompts_dir):
    """get_prompt() should load a saved prompt by its ID."""
    save_prompt(PromptSet(id="lookup", name="Lookup Test", description="desc"))

    loaded = get_prompt("lookup")
    assert loaded is not None
    assert loaded.name == "Lookup Test"
    assert loaded.description == "desc"


def test_delete_removes_file(tmp_prompts_dir):
    """delete_prompt() should remove the JSON file and return True."""
    save_prompt(PromptSet(id="doomed", name="Doomed"))
    assert (tmp_prompts_dir / "doomed.json").exists()

    assert delete_prompt("doomed") is True
    assert not (tmp_prompts_dir / "doomed.json").exists()


def test_delete_nonexistent_returns_false(tmp_prompts_dir):
    """delete_prompt() should return False for a missing ID."""
    assert delete_prompt("ghost") is False


def test_get_nonexistent_returns_none(tmp_prompts_dir):
    """get_prompt() should return None for a missing ID."""
    assert get_prompt("nonexistent") is None


def test_save_generates_id_from_name(tmp_prompts_dir):
    """save_prompt() should slugify the name when id is empty."""
    prompt = PromptSet(id="", name="My Cool Prompt")
    result = save_prompt(prompt)

    assert result.id == "my-cool-prompt"
    assert (tmp_prompts_dir / "my-cool-prompt.json").exists()


def test_save_preserves_created_at_on_update(tmp_prompts_dir):
    """Updating an existing prompt should keep the original created_at."""
    original = save_prompt(PromptSet(id="evolve", name="V1"))
    original_created = original.created_at

    updated = save_prompt(PromptSet(id="evolve", name="V2"))
    assert updated.created_at == original_created
    assert updated.name == "V2"
