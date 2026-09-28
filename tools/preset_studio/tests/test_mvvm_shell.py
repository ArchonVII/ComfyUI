import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MvvmShellContractTests(unittest.TestCase):
    def test_shell_declares_compact_navigation_and_full_destinations(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="app-nav"', html)
        for destination in ("compose", "builder", "characters", "workflows", "results", "settings"):
            self.assertIn(f'data-view="{destination}"', html)
        clear_button = html.split('id="clear"', 1)[1].split(">", 1)[0]
        self.assertNotIn("wide", clear_button)

    def test_browser_controller_uses_the_application_view_model(self):
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("from './studio-view-model.mjs'", javascript)
        self.assertIn("createStudioViewModel", javascript)
        self.assertIn("studioViewModel.navigate", javascript)
        self.assertIn("studioViewModel.subscribe", javascript)

    def test_builder_has_catalog_canvas_properties_and_option_regions(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        for element_id in (
            "builder-catalog", "builder-positive", "builder-negative",
            "builder-properties", "builder-options",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("builder/experiment/create", javascript)
        self.assertIn("builder/option/update", javascript)
        self.assertIn("data-builder-node-input", javascript)
        self.assertIn("builder/workflow/basic", javascript)
        self.assertIn("text/preset-studio-block", javascript)
        self.assertIn("data-builder-lora", javascript)
        self.assertIn("data-builder-model", javascript)
        self.assertIn("builder/option/delete", javascript)
        self.assertIn("builder/workflow/save", javascript)
        self.assertIn("character/use-in-builder", javascript)
        self.assertIn("data-builder-reference", javascript)

    def test_local_server_exposes_the_view_model_module(self):
        service = (ROOT / "service.py").read_text(encoding="utf-8")

        self.assertIn("'/studio-view-model.mjs': 'studio-view-model.mjs'", service)

    def test_character_folder_assignment_is_click_driven(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        for element_id in (
            "folder-dialog",
            "folder-current",
            "folder-list",
            "folder-recursive",
            "assign-folder",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("browseFolders", javascript)
        self.assertIn("'character/assignment/start'", javascript)
        self.assertIn("watchAssignmentJob", javascript)

    def test_exact_copy_removal_is_reviewed_and_recoverable(self):
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("character/duplicates", javascript)
        self.assertIn("data-quarantine-location", javascript)
        self.assertIn("recoverable quarantine", javascript)
        self.assertIn("character/duplicate/restore", javascript)

    def test_family_source_is_an_independent_replaceable_action(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="family-dialog"', html)
        self.assertIn("character/family/create", javascript)
        self.assertIn("character/family/source", javascript)
        self.assertIn("Use recommended", javascript)
        self.assertIn('id="lineage-dialog"', html)
        self.assertIn("character/generated", javascript)
        self.assertIn("data-view-lineage", javascript)

    def test_catalog_image_has_direct_compose_handoff(self):
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-use-compose", javascript)
        self.assertIn("character/use-in-compose", javascript)
        self.assertIn("Character source staged in Compose", javascript)


if __name__ == "__main__":
    unittest.main()
