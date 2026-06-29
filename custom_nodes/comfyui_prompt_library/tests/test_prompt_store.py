import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_prompt_library.prompt_store import EMPTY_PROMPT_NAME, PromptStore


def test_save_and_load_prompt_round_trip(tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")

    saved = store.save(
        "  Cinematic portrait  ",
        positive="close portrait, soft window light",
        negative="blur, watermark",
        notes="Good default for headshots.",
    )

    assert saved["name"] == "Cinematic portrait"
    assert store.list_names() == ["Cinematic portrait"]
    assert store.get("Cinematic portrait") == {
        "name": "Cinematic portrait",
        "positive": "close portrait, soft window light",
        "negative": "blur, watermark",
        "notes": "Good default for headshots.",
        "updated_at": "2026-06-14T22:00:00Z",
    }

    data = json.loads((tmp_path / "prompts.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["prompts"]["Cinematic portrait"]["positive"] == "close portrait, soft window light"


def test_save_refuses_duplicate_without_overwrite(tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")
    store.save("Portrait", positive="first", overwrite=True)

    with pytest.raises(ValueError, match="already exists"):
        store.save("Portrait", positive="second", overwrite=False)

    assert store.get("Portrait")["positive"] == "first"


def test_dropdown_names_use_empty_sentinel_until_prompts_exist(tmp_path):
    store = PromptStore(tmp_path / "prompts.json")

    assert store.dropdown_names() == [EMPTY_PROMPT_NAME]

    store.save("z prompt", positive="")
    store.save("A prompt", positive="")

    assert store.dropdown_names() == ["A prompt", "z prompt"]


@pytest.mark.parametrize("bad_name", ["", "   ", "line\nbreak", "tab\tname"])
def test_prompt_names_must_be_non_empty_single_line(tmp_path, bad_name):
    store = PromptStore(tmp_path / "prompts.json")

    with pytest.raises(ValueError):
        store.save(bad_name, positive="")
