import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_prompt_library.prompt_store import PromptStore
import comfyui_prompt_library.nodes as nodes


def test_loader_input_types_use_prompt_library_names(monkeypatch, tmp_path):
    store = PromptStore(tmp_path / "prompts.json")
    store.save("Portrait", positive="positive text")
    monkeypatch.setattr(nodes, "get_store", lambda: store)

    input_types = nodes.PromptLibraryLoader.INPUT_TYPES()

    assert input_types["required"]["prompt_name"][0] == ["Portrait"]


def test_loader_returns_positive_negative_and_metadata(monkeypatch, tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")
    store.save("Portrait", positive="soft light", negative="watermark", notes="headshot")
    monkeypatch.setattr(nodes, "get_store", lambda: store)

    positive, negative, metadata_json = nodes.PromptLibraryLoader().load_prompt("Portrait")

    assert positive == "soft light"
    assert negative == "watermark"
    assert json.loads(metadata_json) == {
        "name": "Portrait",
        "positive": "soft light",
        "negative": "watermark",
        "notes": "headshot",
        "updated_at": "2026-06-14T22:00:00Z",
    }


def test_saver_persists_prompt_and_passes_text_through(monkeypatch, tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")
    monkeypatch.setattr(nodes, "get_store", lambda: store)

    result = nodes.PromptLibrarySaver().save_prompt(
        "Portrait",
        positive="soft light",
        negative="watermark",
        notes="headshot",
        overwrite=True,
    )

    assert result == ("soft light", "watermark")
    assert store.get("Portrait")["notes"] == "headshot"
