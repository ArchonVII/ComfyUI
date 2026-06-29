import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_prompt_library.prompt_store import PromptStore
import comfyui_prompt_library.routes as routes


def test_prompt_payload_lists_names_records_and_storage_path(monkeypatch, tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")
    store.save("Portrait", positive="soft light", negative="watermark")
    monkeypatch.setattr(routes, "get_store", lambda: store)

    payload = routes.prompt_payload()

    assert payload["names"] == ["Portrait"]
    assert payload["prompts"][0]["positive"] == "soft light"
    assert payload["path"] == str(tmp_path / "prompts.json")


def test_save_prompt_payload_saves_and_returns_refreshed_library(monkeypatch, tmp_path):
    store = PromptStore(tmp_path / "prompts.json", clock=lambda: "2026-06-14T22:00:00Z")
    monkeypatch.setattr(routes, "get_store", lambda: store)

    payload = routes.save_prompt_payload(
        {
            "name": "Portrait",
            "positive": "soft light",
            "negative": "watermark",
            "notes": "headshot",
            "overwrite": True,
        }
    )

    assert payload["prompt"]["name"] == "Portrait"
    assert payload["names"] == ["Portrait"]
    assert store.get("Portrait")["notes"] == "headshot"
