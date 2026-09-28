import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools.character_catalog.catalog import CharacterCatalog


class CharacterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog = CharacterCatalog(self.root / "catalog")

    def tearDown(self):
        self.catalog.close()
        self.temporary.cleanup()

    def test_new_catalog_has_versioned_schema_and_scanning_is_off(self):
        self.assertEqual(self.catalog.schema_version(), 10)
        self.assertFalse(self.catalog.settings()["watch_enabled"])
        self.assertEqual(self.catalog.list_scan_roots(), [])
        self.assertEqual(self.catalog.list_characters(), [])

    def test_version_one_catalog_migrates_additively(self):
        with self.catalog.connection:
            self.catalog.connection.executescript(
                """
                DROP TABLE discovery_review;
                DROP TABLE discovery_jobs;
                DROP TABLE face_embeddings;
                PRAGMA user_version = 1;
                """
            )
        self.catalog.close()

        self.catalog = CharacterCatalog(self.root / "catalog")

        self.assertEqual(self.catalog.schema_version(), 10)
        character = self.catalog.create_character("Migrated")
        folder = self.root / "scan"
        folder.mkdir()
        job = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        self.assertEqual(job["state"], "pending")

    def test_characters_are_case_insensitively_unique_and_keep_preset_link(self):
        created = self.catalog.create_character(
            "Alice", preset_id="preset-alice", positive="silver hair"
        )

        self.assertEqual(created["name"], "Alice")
        self.assertEqual(created["preset_id"], "preset-alice")
        self.assertEqual(self.catalog.list_characters()[0]["positive"], "silver hair")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.catalog.create_character(" alice ")

    def test_exact_bytes_share_one_asset_but_keep_every_location(self):
        first = self.root / "first.png"
        second = self.root / "elsewhere" / "copy.png"
        second.parent.mkdir()
        first.write_bytes(b"same bytes")
        second.write_bytes(b"same bytes")

        original = self.catalog.register_file(first)
        duplicate = self.catalog.register_file(second)

        self.assertEqual(original["asset_id"], duplicate["asset_id"])
        self.assertEqual(original["sha256"], duplicate["sha256"])
        locations = self.catalog.list_asset_locations(original["asset_id"])
        self.assertEqual({Path(row["path"]) for row in locations}, {first.resolve(), second.resolve()})
        self.assertTrue(all(row["available"] for row in locations))

    def test_reused_path_with_new_bytes_never_inherits_old_asset(self):
        image = self.root / "reused.png"
        image.write_bytes(b"first")
        first = self.catalog.register_file(image)
        image.write_bytes(b"second")

        second = self.catalog.register_file(image)

        self.assertNotEqual(first["asset_id"], second["asset_id"])
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertFalse(self.catalog.list_asset_locations(first["asset_id"])[0]["available"])
        self.assertTrue(self.catalog.list_asset_locations(second["asset_id"])[0]["available"])

    def test_existing_character_presets_import_idempotently_without_moving_files(self):
        reference = self.root / "managed" / "alice.png"
        reference.parent.mkdir()
        reference.write_bytes(b"alice reference")
        presets = [
            {
                "id": "preset-alice",
                "kind": "character",
                "name": "Alice",
                "positive": "silver hair",
                "negative": "blurry",
                "references": ["reference-a"],
            },
            {"id": "concept", "kind": "concept", "name": "Film", "references": []},
        ]

        first = self.catalog.import_presets(
            presets, {"reference-a": {"path": reference, "name": "alice.png"}}
        )
        second = self.catalog.import_presets(
            presets, {"reference-a": {"path": reference, "name": "alice.png"}}
        )

        self.assertEqual(first, {"characters": 1, "assets": 1, "assignments": 1})
        self.assertEqual(second, {"characters": 0, "assets": 0, "assignments": 0})
        character = self.catalog.list_characters()[0]
        self.assertEqual(character["preset_id"], "preset-alice")
        self.assertEqual(len(self.catalog.list_character_assets(character["id"])), 1)
        self.assertEqual(reference.read_bytes(), b"alice reference")

    def test_scan_roots_are_explicit_and_watch_is_disabled_by_default(self):
        character = self.catalog.create_character("Alice")
        global_root = self.root / "outputs"
        character_root = self.root / "alice"
        global_root.mkdir()
        character_root.mkdir()

        first = self.catalog.add_scan_root(global_root, recursive=True)
        second = self.catalog.add_scan_root(
            character_root, character_id=character["id"], recursive=False
        )

        self.assertIsNone(first["character_id"])
        self.assertTrue(first["recursive"])
        self.assertFalse(first["watch_enabled"])
        self.assertEqual(second["character_id"], character["id"])
        self.assertFalse(second["recursive"])
        self.assertFalse(second["watch_enabled"])

    def test_assign_folder_adds_supported_images_without_changing_sources(self):
        character = self.catalog.create_character("Alice")
        folder = self.root / "pictures"
        nested = folder / "nested"
        nested.mkdir(parents=True)
        first = folder / "one.png"
        second = nested / "two.tiff"
        ignored = folder / "notes.txt"
        first.write_bytes(b"png bytes")
        second.write_bytes(b"tiff bytes")
        ignored.write_text("not an image", encoding="utf-8")

        shallow = self.catalog.assign_folder(character["id"], folder, recursive=False)
        recursive = self.catalog.assign_folder(character["id"], folder, recursive=True)

        self.assertEqual(shallow, {"found": 1, "assigned": 1, "already_assigned": 0, "failed": []})
        self.assertEqual(recursive["found"], 2)
        self.assertEqual(recursive["assigned"], 1)
        self.assertEqual(recursive["already_assigned"], 1)
        assets = self.catalog.list_character_assets(character["id"])
        self.assertEqual({Path(row["path"]) for row in assets}, {first.resolve(), second.resolve()})
        self.assertEqual(first.read_bytes(), b"png bytes")
        self.assertEqual(second.read_bytes(), b"tiff bytes")

    def test_discovery_job_is_explicit_and_does_not_scan_when_created(self):
        character = self.catalog.create_character("Alice")
        folder = self.root / "outputs"
        folder.mkdir()
        (folder / "candidate.png").write_bytes(b"candidate")

        job = self.catalog.create_discovery_job(
            character["id"], folder, recursive=True
        )

        self.assertEqual(job["state"], "pending")
        self.assertEqual(job["processed_count"], 0)
        self.assertEqual(self.catalog.list_review_items(job["id"]), [])
        self.assertEqual(self.catalog.list_asset_locations_for_path(folder / "candidate.png"), [])

    def test_discovery_matches_faces_and_bulk_accept_is_idempotent(self):
        class FakeAnalyzer:
            key = "fake-v1"

            def analyze(self, path):
                vectors = {
                    "reference.png": [[1.0, 0.0]],
                    "match.png": [[0.99, 0.01], [0.0, 1.0]],
                    "other.png": [[0.0, 1.0]],
                }
                return [
                    {
                        "vector": vector,
                        "box": [index * 10, 0, 8, 8],
                        "confidence": 0.95,
                        "image_size": [100, 100],
                    }
                    for index, vector in enumerate(vectors[path.name])
                ]

        character = self.catalog.create_character("Alice")
        reference = self.root / "reference.png"
        reference.write_bytes(b"reference")
        registered = self.catalog.register_file(reference)
        self.catalog.assign_asset(character["id"], registered["asset_id"], assignment_type="manual")
        folder = self.root / "outputs"
        folder.mkdir()
        (folder / "match.png").write_bytes(b"match")
        (folder / "other.png").write_bytes(b"other")
        job = self.catalog.create_discovery_job(character["id"], folder, recursive=False)

        completed = self.catalog.run_discovery_job(job["id"], FakeAnalyzer(), threshold=0.9)

        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["found_count"], 2)
        self.assertEqual(completed["processed_count"], 2)
        items = self.catalog.list_review_items(job["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(self.catalog.review_item_count(job["id"]), 1)
        self.assertEqual(
            self.catalog.list_review_items(job["id"], limit=1, offset=1), []
        )
        self.assertEqual(Path(items[0]["path"]).name, "match.png")
        self.assertEqual(items[0]["face_index"], 0)
        self.assertGreater(items[0]["score"], 0.99)
        first = self.catalog.apply_recommended(job["id"], [items[0]["id"]])
        second = self.catalog.apply_recommended(job["id"], [items[0]["id"]])
        self.assertEqual(first, {"assigned": 1, "already_applied": 0})
        self.assertEqual(second, {"assigned": 0, "already_applied": 1})
        self.assertEqual(self.catalog.list_review_items(job["id"])[0]["decision"], "accepted")

    def test_exact_copy_locations_are_reviewable_and_one_can_be_quarantined(self):
        character = self.catalog.create_character("Alice")
        keeper = self.root / "pictures" / "keeper.png"
        duplicate = self.root / "downloads" / "copy.png"
        keeper.parent.mkdir()
        duplicate.parent.mkdir()
        keeper.write_bytes(b"exact image bytes")
        duplicate.write_bytes(b"exact image bytes")
        registered = self.catalog.register_file(keeper)
        self.catalog.register_file(duplicate)
        self.catalog.assign_asset(
            character["id"], registered["asset_id"], assignment_type="manual"
        )

        groups = self.catalog.list_exact_duplicate_groups(character["id"])

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["copy_count"], 2)
        self.assertEqual(Path(groups[0]["recommended_keeper"]["path"]), keeper.resolve())
        duplicate_location = next(
            row for row in groups[0]["locations"] if Path(row["path"]) == duplicate.resolve()
        )
        operation = self.catalog.quarantine_duplicate(duplicate_location["id"])
        self.assertEqual(operation["state"], "database_done")
        self.assertTrue(keeper.exists())
        self.assertFalse(duplicate.exists())
        self.assertTrue(Path(operation["quarantine_path"]).exists())
        self.assertEqual(self.catalog.list_exact_duplicate_groups(character["id"]), [])

        restored = self.catalog.restore_quarantine(operation["id"])

        self.assertEqual(restored["state"], "restored")
        self.assertTrue(duplicate.exists())
        self.assertEqual(duplicate.read_bytes(), b"exact image bytes")

    def test_quarantine_never_removes_the_last_available_copy(self):
        image = self.root / "only.png"
        image.write_bytes(b"one copy")
        registered = self.catalog.register_file(image)
        location = self.catalog.list_asset_locations(registered["asset_id"])[0]

        with self.assertRaisesRegex(ValueError, "last available"):
            self.catalog.quarantine_duplicate(location["id"])

        self.assertTrue(image.exists())

    def test_quarantine_journal_recovers_a_move_interrupted_before_database_update(self):
        first = self.root / "first.png"
        second = self.root / "second.png"
        first.write_bytes(b"same")
        second.write_bytes(b"same")
        registered = self.catalog.register_file(first)
        self.catalog.register_file(second)
        second_location = next(
            row
            for row in self.catalog.list_asset_locations(registered["asset_id"])
            if Path(row["path"]) == second.resolve()
        )

        def move_then_interrupt(source, target):
            Path(source).replace(target)
            raise RuntimeError("simulated stop")

        with patch("tools.character_catalog.catalog.shutil.move", move_then_interrupt):
            with self.assertRaisesRegex(RuntimeError, "simulated stop"):
                self.catalog.quarantine_duplicate(second_location["id"])
        self.catalog.close()

        self.catalog = CharacterCatalog(self.root / "catalog")

        operation = self.catalog.list_quarantine_operations()[0]
        self.assertEqual(operation["state"], "database_done")
        self.assertTrue(Path(operation["quarantine_path"]).exists())
        self.assertFalse(second.exists())

    def test_restore_journal_recovers_a_move_interrupted_before_database_update(self):
        first = self.root / "first.png"
        second = self.root / "second.png"
        first.write_bytes(b"same")
        second.write_bytes(b"same")
        registered = self.catalog.register_file(first)
        self.catalog.register_file(second)
        second_location = next(
            row
            for row in self.catalog.list_asset_locations(registered["asset_id"])
            if Path(row["path"]) == second.resolve()
        )
        operation = self.catalog.quarantine_duplicate(second_location["id"])

        def move_then_interrupt(source, target):
            Path(source).replace(target)
            raise RuntimeError("simulated restore stop")

        with patch("tools.character_catalog.catalog.shutil.move", move_then_interrupt):
            with self.assertRaisesRegex(RuntimeError, "simulated restore stop"):
                self.catalog.restore_quarantine(operation["id"])
        self.catalog.close()

        self.catalog = CharacterCatalog(self.root / "catalog")

        recovered = self.catalog.list_quarantine_operations()[0]
        self.assertEqual(recovered["state"], "restored")
        self.assertTrue(second.exists())
        self.assertEqual(second.read_bytes(), b"same")

    def test_family_membership_is_separate_from_replaceable_source_role(self):
        character = self.catalog.create_character("Alice")
        low = self.root / "low.png"
        high = self.root / "high.png"
        Image.new("RGB", (64, 64), "red").save(low)
        Image.new("RGB", (256, 128), "blue").save(high)
        low_asset = self.catalog.register_file(low)["asset_id"]
        high_asset = self.catalog.register_file(high)["asset_id"]
        for asset_id in (low_asset, high_asset):
            self.catalog.assign_asset(character["id"], asset_id, assignment_type="manual")
        family = self.catalog.create_family(character["id"], "Blue dress")
        self.catalog.add_family_assets(family["id"], [low_asset, high_asset])

        self.catalog.set_family_source(family["id"], low_asset)
        listed = self.catalog.list_families(character["id"])[0]

        self.assertEqual({item["asset_id"] for item in listed["members"]}, {low_asset, high_asset})
        self.assertEqual(listed["designated_source_id"], low_asset)
        self.assertEqual(listed["recommended_source_id"], high_asset)
        self.catalog.set_family_source(family["id"], high_asset)
        promoted = self.catalog.list_families(character["id"])[0]
        self.assertEqual(promoted["designated_source_id"], high_asset)
        self.assertEqual(len(promoted["members"]), 2)

    def test_corrupt_family_member_stays_visible_without_breaking_source_recommendation(self):
        character = self.catalog.create_character("Alice")
        valid = self.root / "valid.png"
        corrupt = self.root / "corrupt.png"
        Image.new("RGB", (80, 40), "green").save(valid)
        corrupt.write_bytes(b"not an image")
        valid_id = self.catalog.register_file(valid)["asset_id"]
        corrupt_id = self.catalog.register_file(corrupt)["asset_id"]
        for asset_id in (valid_id, corrupt_id):
            self.catalog.assign_asset(character["id"], asset_id, assignment_type="manual")
        family = self.catalog.create_family(character["id"], "Mixed")
        self.catalog.add_family_assets(family["id"], [corrupt_id, valid_id])

        listed = self.catalog.list_families(character["id"])[0]

        self.assertEqual(len(listed["members"]), 2)
        self.assertEqual(listed["recommended_source_id"], valid_id)
        bad = next(item for item in listed["members"] if item["asset_id"] == corrupt_id)
        self.assertIsNone(bad["width"])

    def test_generation_lineage_links_output_to_exact_source_and_character(self):
        character = self.catalog.create_character("Alice", preset_id="alice-preset")
        source = self.root / "source.png"
        output = self.root / "output.png"
        Image.new("RGB", (64, 64), "red").save(source)
        Image.new("RGB", (96, 96), "blue").save(output)
        source_asset = self.catalog.register_file(source)["asset_id"]
        self.catalog.assign_asset(
            character["id"], source_asset, assignment_type="manual"
        )

        first = self.catalog.record_generation(
            "studio-run-1", character["id"], source_asset, output
        )
        second = self.catalog.record_generation(
            "studio-run-1", character["id"], source_asset, output
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["source_asset_id"], source_asset)
        self.assertEqual(Path(first["output_path"]), output.resolve())
        lineage = self.catalog.list_generated_from(source_asset)
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0]["run_id"], "studio-run-1")
        assigned = self.catalog.list_character_assets(character["id"])
        self.assertEqual({item["id"] for item in assigned}, {source_asset, first["output_asset_id"]})

    def test_discovery_cancel_request_stops_between_images(self):
        character = self.catalog.create_character("Alice")
        reference = self.root / "reference.png"
        reference.write_bytes(b"reference")
        registered = self.catalog.register_file(reference)
        self.catalog.assign_asset(character["id"], registered["asset_id"], assignment_type="manual")
        folder = self.root / "scan"
        folder.mkdir()
        (folder / "one.png").write_bytes(b"one")
        (folder / "two.png").write_bytes(b"two")
        job = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        catalog = self.catalog

        class CancellingAnalyzer:
            key = "cancel-v1"
            calls = 0

            def analyze(self, path):
                self.calls += 1
                if self.calls == 2:
                    catalog.request_discovery_cancel(job["id"])
                return [{
                    "vector": [1.0, 0.0], "box": [0, 0, 8, 8],
                    "confidence": 0.9, "image_size": [10, 10],
                }]

        stopped = self.catalog.run_discovery_job(job["id"], CancellingAnalyzer())

        self.assertEqual(stopped["state"], "cancelled")
        self.assertEqual(stopped["processed_count"], 1)
        self.assertLess(stopped["processed_count"], stopped["found_count"])

    def test_rejected_face_is_suppressed_on_later_jobs_but_defer_is_job_local(self):
        class FakeAnalyzer:
            key = "reject-v1"

            def analyze(self, path):
                return [{
                    "vector": [1.0, 0.0], "box": [0, 0, 8, 8],
                    "confidence": 0.9, "image_size": [10, 10],
                }]

        character = self.catalog.create_character("Alice")
        reference = self.root / "reference.png"
        reference.write_bytes(b"reference")
        source = self.catalog.register_file(reference)
        self.catalog.assign_asset(character["id"], source["asset_id"], assignment_type="manual")
        folder = self.root / "scan"
        folder.mkdir()
        (folder / "match.png").write_bytes(b"match")
        first = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        self.catalog.run_discovery_job(first["id"], FakeAnalyzer())
        item = self.catalog.list_review_items(first["id"])[0]

        deferred = self.catalog.decide_review_items(first["id"], [item["id"]], "deferred")
        self.assertEqual(deferred, {"updated": 1, "already_decided": 0})
        second = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        self.catalog.run_discovery_job(second["id"], FakeAnalyzer())
        second_item = self.catalog.list_review_items(second["id"])[0]
        self.catalog.decide_review_items(second["id"], [second_item["id"]], "rejected")
        third = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        self.catalog.run_discovery_job(third["id"], FakeAnalyzer())

        self.assertEqual(self.catalog.list_review_items(third["id"]), [])

    def test_thumbnail_is_bounded_and_reused(self):
        image = self.root / "large.png"
        Image.new("RGB", (640, 320), "orange").save(image)
        asset_id = self.catalog.register_file(image)["asset_id"]

        first = self.catalog.thumbnail_path(asset_id, 128)
        first_modified = first.stat().st_mtime_ns
        second = self.catalog.thumbnail_path(asset_id, 128)

        self.assertEqual(first, second)
        self.assertEqual(first_modified, second.stat().st_mtime_ns)
        with Image.open(first) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 128)
            self.assertEqual(thumbnail.format, "WEBP")

    def test_family_can_be_renamed_and_members_replaced(self):
        character = self.catalog.create_character("Alice")
        first_path = self.root / "first.png"
        second_path = self.root / "second.png"
        Image.new("RGB", (32, 32), "red").save(first_path)
        Image.new("RGB", (64, 64), "blue").save(second_path)
        first = self.catalog.register_file(first_path)["asset_id"]
        second = self.catalog.register_file(second_path)["asset_id"]
        self.catalog.assign_asset(character["id"], first, assignment_type="manual")
        self.catalog.assign_asset(character["id"], second, assignment_type="manual")
        family = self.catalog.create_family(character["id"], "Old name")
        self.catalog.add_family_assets(family["id"], [first])

        updated = self.catalog.update_family(family["id"], "Best portraits", [second])
        listed = self.catalog.list_families(character["id"])[0]

        self.assertEqual(updated["name"], "Best portraits")
        self.assertEqual([item["asset_id"] for item in listed["members"]], [second])

    def test_review_item_exposes_face_evidence_and_cached_crop(self):
        class FakeAnalyzer:
            key = "face-evidence-v1"

            def analyze(self, path):
                return [{
                    "vector": [1.0, 0.0], "box": [30, 20, 20, 30],
                    "confidence": 0.96, "image_size": [100, 80],
                }]

        character = self.catalog.create_character("Alice")
        reference = self.root / "reference.png"
        Image.new("RGB", (100, 80), "red").save(reference)
        source = self.catalog.register_file(reference)
        self.catalog.assign_asset(
            character["id"], source["asset_id"], assignment_type="manual"
        )
        folder = self.root / "matches"
        folder.mkdir()
        Image.new("RGB", (100, 80), "blue").save(folder / "match.png")
        job = self.catalog.create_discovery_job(character["id"], folder, recursive=False)
        self.catalog.run_discovery_job(job["id"], FakeAnalyzer(), threshold=0.9)

        item = self.catalog.list_review_items(job["id"])[0]
        crop = self.catalog.review_face_thumbnail_path(item["id"], 192)

        self.assertEqual(item["face_box"], [30, 20, 20, 30])
        self.assertEqual(item["face_confidence"], 0.96)
        with Image.open(crop) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertLessEqual(max(image.size), 192)

    def test_assignment_job_tracks_large_folder_work_outside_request_lifecycle(self):
        character = self.catalog.create_character("Alice")
        folder = self.root / "assign"
        folder.mkdir()
        Image.new("RGB", (16, 16), "red").save(folder / "one.png")
        Image.new("RGB", (16, 16), "blue").save(folder / "two.png")
        job = self.catalog.create_assignment_job(
            character["id"], folder, recursive=False
        )

        completed = self.catalog.run_assignment_job(job["id"])

        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["found_count"], 2)
        self.assertEqual(completed["processed_count"], 2)
        self.assertEqual(completed["assigned_count"], 2)
        self.assertEqual(self.catalog.character_asset_count(character["id"]), 2)

    def test_character_gallery_search_and_sort_are_server_paginated(self):
        character = self.catalog.create_character("Alice")
        for name, content in (
            ("portrait-small.png", b"x"),
            ("portrait-large.png", b"x" * 30),
            ("landscape.png", b"x" * 10),
        ):
            path = self.root / name
            path.write_bytes(content)
            asset = self.catalog.register_file(path)["asset_id"]
            self.catalog.assign_asset(character["id"], asset, assignment_type="manual")

        results = self.catalog.list_character_assets(
            character["id"], query="portrait", sort="largest", limit=1, offset=0
        )

        self.assertEqual([item["original_name"] for item in results], ["portrait-large.png"])
        self.assertEqual(
            self.catalog.character_asset_count(character["id"], query="portrait"), 2
        )


if __name__ == "__main__":
    unittest.main()
