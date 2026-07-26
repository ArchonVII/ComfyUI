import concurrent.futures
import json
import os
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import load_catalog
from custom_nodes.comfyui_arch_prompt_tools.engine import assemble, replace_group_select
from custom_nodes.comfyui_arch_prompt_tools.store import (
    ID_GENERATION_ATTEMPTS,
    STORE_VERSION,
    OptionNotFoundError,
    OptionStore,
    OptionStoreDataError,
    OptionValidationError,
    ProtectedOptionError,
    default_user_options_path,
)


@pytest.fixture(scope="module")
def catalog():
    data = Path(__file__).parents[1] / "data"
    return load_catalog(data / "schemas.json", data / "builtin_options.json")


def valid_option(**changes):
    value = {
        "label": "My person",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "model_family": "flux",
        "phrase": "one distinct person",
        "builtin": False,
    }
    value.update(changes)
    return value


def additive_option(**changes):
    value = {
        "label": "Custom body detail",
        "node": "identity",
        "field": "body_snippets",
        "model_family": "flux",
        "phrase": "a custom body detail",
        "builtin": False,
    }
    value.update(changes)
    return value


def copied_fragment(option, instance_id):
    return {
        "instance_id": instance_id,
        "source_option_id": option.id,
        "label": option.label,
        "node": option.node,
        "field": option.field,
        "group": option.group,
        "text": option.phrase,
        "model_family": option.model_family,
        "lora_enabled": option.lora_enabled,
    }


def test_default_path_is_resolved_from_comfy_user_directory_only_when_called(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "folder_paths",
        SimpleNamespace(get_user_directory=lambda: str(tmp_path / "comfy-user")),
    )

    assert default_user_options_path() == tmp_path / "comfy-user" / "arch_prompt_tools" / "options.json"


def test_missing_store_reads_empty_without_creating_a_file(tmp_path, catalog):
    path = tmp_path / "options.json"
    store = OptionStore(catalog, path)

    assert store.list_options() == ()
    assert not path.exists()


def test_create_update_delete_are_explicit_and_keep_a_stable_opaque_id(tmp_path, catalog):
    ids = iter(("user.first", "user.second"))
    store = OptionStore(catalog, tmp_path / "options.json", id_factory=lambda: next(ids))

    first = store.create(valid_option())
    second = store.create(valid_option())
    updated = store.update(first.id, {"label": "Renamed", "phrase": "edited copied wording"})

    assert first.id == "user.first"
    assert second.id == "user.second"
    assert first.label == second.label
    assert updated.id == first.id
    assert updated.label == "Renamed"
    assert updated.phrase == "edited copied wording"
    assert [item.id for item in store.list_options()] == ["user.first", "user.second"]
    assert store.delete(first.id).id == first.id
    assert [item.id for item in store.list_options()] == ["user.second"]


def test_additive_user_options_get_stable_per_id_groups_and_stack_in_assembly(
    tmp_path, catalog
):
    ids = iter(("user.additive-one", "user.additive-two"))
    store = OptionStore(
        catalog, tmp_path / "options.json", id_factory=lambda: next(ids)
    )

    first = store.create(additive_option(label="First", phrase="first detail"))
    second = store.create(additive_option(label="Second", phrase="second detail"))
    updated = store.update(first.id, {"label": "First renamed"})
    state = {
        "version": 1,
        "node": "identity",
        "model_family": "flux",
        "fields": {},
    }
    state = replace_group_select(state, copied_fragment(updated, "copy-one"))
    state = replace_group_select(state, copied_fragment(second, "copy-two"))

    assert first.group == "user_option:user.additive-one"
    assert second.group == "user_option:user.additive-two"
    assert updated.group == first.group
    assert assemble(catalog, state).prompt == "first detail, second detail"


def test_duplicated_additive_builtin_gets_a_new_stable_user_group(
    tmp_path, catalog
):
    builtin = next(
        option
        for option in catalog.options
        if (option.node, option.field) == ("identity", "body_snippets")
    )
    store = OptionStore(
        catalog,
        tmp_path / "options.json",
        id_factory=lambda: "user.duplicate-snippet",
    )

    duplicate = store.create(
        additive_option(
            label=builtin.label,
            phrase=builtin.phrases["flux"],
        )
    )

    assert duplicate.id == "user.duplicate-snippet"
    assert duplicate.group == "user_option:user.duplicate-snippet"
    assert duplicate.group != builtin.group


def test_grouped_user_options_share_schema_group_and_replace_in_assembly(
    tmp_path, catalog
):
    ids = iter(("user.grouped-one", "user.grouped-two"))
    store = OptionStore(
        catalog, tmp_path / "options.json", id_factory=lambda: next(ids)
    )
    first = store.create(valid_option(label="First", phrase="first subject"))
    second = store.create(valid_option(label="Second", phrase="second subject"))
    state = {
        "version": 1,
        "node": "identity",
        "model_family": "flux",
        "fields": {},
    }
    state = replace_group_select(state, copied_fragment(first, "grouped-one"))
    state = replace_group_select(state, copied_fragment(second, "grouped-two"))

    assert first.group == second.group == "subject_type"
    assert assemble(catalog, state).prompt == "second subject"


def test_additive_group_is_system_assigned_on_create_and_move_but_corruption_is_rejected(
    tmp_path, catalog
):
    store = OptionStore(
        catalog, tmp_path / "options.json", id_factory=lambda: "user.movable"
    )
    grouped = store.create(valid_option())

    moved_additive = store.update(
        grouped.id,
        {
            "field": "body_snippets",
            "label": "Moved detail",
            "phrase": "moved detail",
        },
    )
    moved_grouped = store.update(
        grouped.id,
        {
            "field": "subject_type",
            "group": "subject_type",
            "label": "Moved subject",
            "phrase": "moved subject",
        },
    )

    assert moved_additive.id == grouped.id
    assert moved_additive.group == "user_option:user.movable"
    assert moved_grouped.id == grouped.id
    assert moved_grouped.group == "subject_type"
    with pytest.raises(OptionValidationError, match="assigned automatically"):
        store.create(additive_option(group="body_detail"))
    with pytest.raises(OptionValidationError, match="stable"):
        store.update(
            grouped.id,
            {"field": "body_snippets", "group": "corrupt-group"},
        )


def test_invalid_additive_group_on_disk_is_rejected_without_rewriting_file(
    tmp_path, catalog
):
    path = tmp_path / "options.json"
    store = OptionStore(
        catalog, path, id_factory=lambda: "user.strict-additive"
    )
    created = store.create(additive_option())
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["options"][0]["group"] = "body_detail"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(OptionStoreDataError, match="stable"):
        store.list_options()

    assert created.group == "user_option:user.strict-additive"
    assert path.read_bytes() == before


def test_generated_id_collision_retries_until_a_unique_id_is_found(tmp_path, catalog):
    path = tmp_path / "options.json"
    first = OptionStore(catalog, path, id_factory=lambda: "user.collision")
    first.create(valid_option())
    candidates = iter(("user.collision", "user.unique"))
    second = OptionStore(catalog, path, id_factory=lambda: next(candidates))

    created = second.create(valid_option(label="Second"))

    assert created.id == "user.unique"
    assert [item.id for item in second.list_options()] == [
        "user.collision",
        "user.unique",
    ]


def test_generated_id_collision_retries_are_bounded_and_fail_clearly(tmp_path, catalog):
    path = tmp_path / "options.json"
    OptionStore(catalog, path, id_factory=lambda: "user.existing").create(
        valid_option()
    )
    calls = 0

    def colliding_id():
        nonlocal calls
        calls += 1
        return "user.existing"

    store = OptionStore(catalog, path, id_factory=colliding_id)

    with pytest.raises(OptionValidationError, match="unique.*attempts"):
        store.create(valid_option(label="Never written"))
    assert calls == ID_GENERATION_ATTEMPTS
    assert [item.id for item in store.list_options()] == ["user.existing"]


def test_generated_id_retries_include_protected_collisions(tmp_path, catalog):
    candidates = iter(("user.protected", "user.allowed"))
    store = OptionStore(
        catalog, tmp_path / "options.json", id_factory=lambda: next(candidates)
    )
    store._protected_ids = frozenset({*store._protected_ids, "user.protected"})

    assert store.create(valid_option()).id == "user.allowed"


def test_records_are_immutable_and_do_not_share_nested_lora_state(tmp_path, catalog):
    payload = valid_option(
        lora={"name": "phone_pose.safetensors", "strength": 0.75, "tags": ["phone"]},
        lora_enabled=True,
    )
    store = OptionStore(catalog, tmp_path / "options.json", id_factory=lambda: "user.lora")
    record = store.create(payload)
    payload["lora"]["name"] = "mutated"
    payload["lora"]["tags"].append("mutated")

    assert isinstance(record.lora, MappingProxyType)
    assert record.lora["name"] == "phone_pose.safetensors"
    assert record.lora["tags"] == ("phone",)
    with pytest.raises(TypeError):
        record.lora["name"] = "cannot mutate"
    assert store.list_options()[0] == record


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"node": "unknown"}, "unknown node"),
        ({"field": "unknown"}, "unknown field"),
        ({"group": "unknown"}, "unknown group"),
        ({"model_family": "sdxl"}, "unknown model family"),
        ({"label": ""}, "label"),
        ({"phrase": 4}, "phrase"),
        ({"builtin": True}, "built-in"),
        ({"builtin": 0}, "builtin"),
        ({"lora": []}, "lora"),
        ({"lora_enabled": 1}, "lora_enabled"),
        ({"lora_enabled": True}, "requires lora"),
        ({"lora": {"strength": True}}, "boolean"),
        ({"extra": "not allowed"}, "unexpected"),
        ({"id": "identity.subject_type.single_person"}, "id"),
    ],
)
def test_create_validates_scope_types_and_ownership(tmp_path, catalog, changes, match):
    store = OptionStore(catalog, tmp_path / "options.json")

    with pytest.raises(OptionValidationError, match=match):
        store.create(valid_option(**changes))


def test_update_revalidates_the_complete_record_and_rejects_identity_or_ownership_changes(tmp_path, catalog):
    store = OptionStore(catalog, tmp_path / "options.json", id_factory=lambda: "user.one")
    record = store.create(valid_option())

    with pytest.raises(OptionValidationError, match="id"):
        store.update(record.id, {"id": "user.other"})
    with pytest.raises(OptionValidationError, match="built-in"):
        store.update(record.id, {"builtin": True})
    with pytest.raises(OptionValidationError, match="unknown group"):
        store.update(record.id, {"group": "not-a-group"})


def test_builtins_are_protected_from_create_update_and_delete(tmp_path, catalog):
    store = OptionStore(catalog, tmp_path / "options.json")
    builtin_id = catalog.options[0].id

    with pytest.raises(OptionValidationError, match="built-in"):
        store.create(valid_option(builtin=True))
    with pytest.raises(ProtectedOptionError, match="protected"):
        store.update(builtin_id, {"label": "Changed"})
    with pytest.raises(ProtectedOptionError, match="protected"):
        store.delete(builtin_id)


def test_missing_user_ids_are_reported_distinctly(tmp_path, catalog):
    store = OptionStore(catalog, tmp_path / "options.json")

    with pytest.raises(OptionNotFoundError, match="not found"):
        store.update("user.missing", {"label": "Changed"})
    with pytest.raises(OptionNotFoundError, match="not found"):
        store.delete("user.missing")


@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        b"\xff\xfe",
        b'{"version":true,"options":[]}',
        b'{"version":2,"options":[]}',
        b'{"version":1,"options":{}}',
        b'{"version":1,"options":[{"id":"user.bad"}]}',
    ],
)
def test_invalid_files_fail_clearly_and_are_preserved_byte_for_byte(tmp_path, catalog, raw):
    path = tmp_path / "options.json"
    path.write_bytes(raw)
    store = OptionStore(catalog, path)

    with pytest.raises(OptionStoreDataError):
        store.list_options()
    with pytest.raises(OptionStoreDataError):
        store.create(valid_option())
    assert path.read_bytes() == raw


def test_store_writes_a_versioned_validated_envelope_and_uses_same_directory_atomic_replace(
    tmp_path, catalog, monkeypatch
):
    path = tmp_path / "nested" / "options.json"
    observed = {}
    real_replace = os.replace

    def inspecting_replace(source, target):
        source_path = Path(source)
        observed["same_parent"] = source_path.parent == path.parent
        observed["payload"] = json.loads(source_path.read_text(encoding="utf-8"))
        observed["target"] = Path(target)
        real_replace(source, target)

    monkeypatch.setattr("custom_nodes.comfyui_arch_prompt_tools.store.os.replace", inspecting_replace)
    store = OptionStore(catalog, path, id_factory=lambda: "user.atomic")
    store.create(valid_option())

    assert observed["same_parent"] is True
    assert observed["target"] == path
    assert observed["payload"]["version"] == STORE_VERSION
    assert observed["payload"]["options"][0]["id"] == "user.atomic"
    assert json.loads(path.read_text(encoding="utf-8")) == observed["payload"]


def test_successful_replace_attempts_directory_fsync_after_target_exists(
    tmp_path, catalog, monkeypatch
):
    path = tmp_path / "options.json"
    observed = []

    def recording_directory_fsync(directory):
        observed.append((Path(directory), path.exists()))

    monkeypatch.setattr(
        "custom_nodes.comfyui_arch_prompt_tools.store._fsync_directory",
        recording_directory_fsync,
    )
    OptionStore(catalog, path, id_factory=lambda: "user.durable").create(
        valid_option()
    )

    assert observed == [(tmp_path, True)]


def test_unsupported_directory_fsync_is_best_effort(tmp_path, monkeypatch):
    from custom_nodes.comfyui_arch_prompt_tools import store as store_module

    monkeypatch.setattr(store_module, "_DIRECTORY_FSYNC_SUPPORTED", True)
    monkeypatch.setattr(
        store_module.os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("directory handles unsupported")
        ),
    )

    store_module._fsync_directory(tmp_path)


def test_failed_replace_preserves_prior_target_and_cleans_temporary_file(tmp_path, catalog, monkeypatch):
    path = tmp_path / "options.json"
    path.write_text('{"version":1,"options":[]}\n', encoding="utf-8")
    before = path.read_bytes()

    def failed_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr("custom_nodes.comfyui_arch_prompt_tools.store.os.replace", failed_replace)
    store = OptionStore(catalog, path, id_factory=lambda: "user.failure")

    with pytest.raises(OptionStoreDataError, match="write"):
        store.create(valid_option())
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_fdopen_closes_raw_descriptor_and_removes_temporary_file(
    tmp_path, catalog, monkeypatch
):
    path = tmp_path / "options.json"
    observed = {}
    real_mkstemp = tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        descriptor, temp_name = real_mkstemp(*args, **kwargs)
        observed["descriptor"] = descriptor
        observed["temp_path"] = Path(temp_name)
        return descriptor, temp_name

    def failed_fdopen(_descriptor, *_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(
        "custom_nodes.comfyui_arch_prompt_tools.store.tempfile.mkstemp",
        recording_mkstemp,
    )
    monkeypatch.setattr(
        "custom_nodes.comfyui_arch_prompt_tools.store.os.fdopen", failed_fdopen
    )
    store = OptionStore(catalog, path, id_factory=lambda: "user.fdopen-failure")

    with pytest.raises(OptionStoreDataError, match="write"):
        store.create(valid_option())

    with pytest.raises(OSError):
        os.fstat(observed["descriptor"])
    assert not observed["temp_path"].exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_extreme_lora_integer_is_rejected_before_persistence(tmp_path, catalog):
    extreme = 10**400
    store = OptionStore(
        catalog, tmp_path / "options.json", id_factory=lambda: "user.extreme-int"
    )

    with pytest.raises(OptionValidationError, match="JavaScript-safe"):
        store.create(valid_option(lora={"seed": extreme}))
    assert not store.path.exists()


def test_process_wide_per_path_lock_prevents_lost_updates_across_store_instances(tmp_path, catalog):
    path = tmp_path / "options.json"

    def create(index):
        store = OptionStore(catalog, path, id_factory=lambda: f"user.concurrent-{index}")
        return store.create(valid_option(label=f"Option {index}")).id

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        ids = tuple(executor.map(create, range(24)))

    records = OptionStore(catalog, path).list_options()
    assert {record.id for record in records} == set(ids)
    assert len(records) == 24
