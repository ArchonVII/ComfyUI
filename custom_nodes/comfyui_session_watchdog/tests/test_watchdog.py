import logging
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_session_watchdog.watchdog import (
    SessionWatchdogLoggingHandler,
    WatchdogEventStore,
    classify_message,
    current_lora_name,
    lora_context,
    track_lora_source,
)


def test_classifies_lora_key_not_loaded_as_model_warning():
    event = classify_message(
        "lora key not loaded: lora_unet_double_blocks_1_img_mod_lin.alpha",
        level="WARNING",
        lora_name="bad-flux-lora.safetensors",
    )

    assert event is not None
    assert event["kind"] == "lora_load_failed"
    assert event["severity"] == "warning"
    assert event["title"] == "LoRA did not load"
    assert "bad-flux-lora.safetensors" in event["summary"]
    assert "active base model" in event["summary"]
    assert "lora_unet_double_blocks" not in event["summary"]
    assert event["details"]["lora_name"] == "bad-flux-lora.safetensors"


def test_classifies_lora_shape_error_as_model_warning():
    event = classify_message(
        "ERROR lora diffusion_model.double_blocks.0.img_attn.qkv.weight "
        "shape '[12288, 4096]' is invalid for input of size 28311552",
        level="ERROR",
        lora_name="bad-flux-lora.safetensors",
    )

    assert event is not None
    assert event["kind"] == "lora_load_failed"
    assert event["severity"] == "warning"
    assert event["title"] == "LoRA did not load"
    assert "bad-flux-lora.safetensors" in event["summary"]
    assert "diffusion_model.double_blocks" not in event["summary"]


def test_classifies_comfy_shape_mismatch_as_model_warning():
    event = classify_message(
        "WARNING SHAPE MISMATCH diffusion_model.foo.weight WEIGHT NOT MERGED "
        "torch.Size([1, 2]) != torch.Size([3, 4])",
        level="WARNING",
        lora_name="bad-flux-lora.safetensors",
    )

    assert event is not None
    assert event["kind"] == "lora_load_failed"
    assert event["severity"] == "warning"
    assert "bad-flux-lora.safetensors" in event["summary"]
    assert "diffusion_model.foo.weight" not in event["summary"]


def test_lora_diagnostics_share_one_fingerprint_per_model():
    first = classify_message(
        "lora key not loaded: lora_unet_double_blocks_1_img_mod_lin.alpha",
        lora_name="bad-flux-lora.safetensors",
    )
    second = classify_message(
        "ERROR lora diffusion_model.double_blocks.0.img_attn.qkv.weight "
        "shape '[12288, 4096]' is invalid for input of size 28311552",
        lora_name="bad-flux-lora.safetensors",
    )

    assert first["fingerprint"] == second["fingerprint"]


def test_lora_context_uses_tracked_loaded_file_name():
    lora_state_dict = {}
    track_lora_source(lora_state_dict, r"C:\models\loras\bad-flux-lora.safetensors")

    with lora_context(lora_state_dict):
        assert current_lora_name() == "bad-flux-lora.safetensors"
        event = classify_message("lora key not loaded: lora_unet_double_blocks_1_img_mod_lin.alpha")

    assert event["details"]["lora_name"] == "bad-flux-lora.safetensors"


def test_store_deduplicates_repeated_messages():
    store = WatchdogEventStore(clock=lambda: "2026-06-14T23:00:00Z")
    first = store.add_event({"kind": "x", "severity": "warning", "message": "same"})
    second = store.add_event({"kind": "x", "severity": "warning", "message": "same"})

    assert first["id"] == second["id"]
    assert second["count"] == 2
    assert store.snapshot()["events"][0]["count"] == 2


def test_logging_handler_emits_classified_events_only():
    seen = []
    store = WatchdogEventStore(clock=lambda: "2026-06-14T23:00:00Z")
    handler = SessionWatchdogLoggingHandler(store=store, sender=seen.append)

    ignored = logging.LogRecord("test", logging.INFO, __file__, 1, "plain info", (), None)
    handler.emit(ignored)
    assert seen == []

    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "ERROR lora diffusion_model.block.weight shape '[1, 2]' is invalid",
        (),
        None,
    )
    handler.emit(record)

    assert len(seen) == 1
    assert seen[0]["kind"] == "lora_load_failed"
    assert store.snapshot()["events"][0]["kind"] == "lora_load_failed"


def test_logging_handler_sends_duplicate_lora_warning_once():
    seen = []
    store = WatchdogEventStore(clock=lambda: "2026-06-14T23:00:00Z")
    handler = SessionWatchdogLoggingHandler(store=store, sender=seen.append)

    first = logging.LogRecord(
        "test",
        logging.WARNING,
        __file__,
        1,
        "lora key not loaded: lora_unet_double_blocks_1_img_mod_lin.alpha",
        (),
        None,
    )
    second = logging.LogRecord(
        "test",
        logging.WARNING,
        __file__,
        1,
        "lora key not loaded: lora_unet_double_blocks_1_img_mod_lin.lora_down.weight",
        (),
        None,
    )

    handler.emit(first)
    handler.emit(second)

    assert len(seen) == 1
    assert store.snapshot()["events"][0]["count"] == 2
