import json
from pathlib import Path
import subprocess


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "web" / "reference_library.js"
CSS_PATH = Path(__file__).resolve().parents[1] / "web" / "reference_library.css"


def test_reference_library_frontend_is_valid_javascript_and_has_no_owner_data_inner_html():
    result = subprocess.run(
        ["node", "--check", str(SCRIPT_PATH)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert ".innerHTML" not in source
    assert "registerSidebarTab" in source
    assert "ArchSubjectReferenceSelector" in source
    assert "ArchEnvironmentReferenceSelector" in source
    assert CSS_PATH.is_file()


def test_sidebar_registration_and_pure_selection_helpers():
    node_script = rf"""
const fs = require("fs"), vm = require("vm");
let source = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8")
  .replace(/^import[^\n]*\n/gm, "")
  .replaceAll("import.meta.url", JSON.stringify("https://local/reference_library.js"))
  .replace(/export \{{[^}}]+\}};?\s*$/m, "");
let extension, sidebar;
const app = {{
  registerExtension(value) {{ extension = value; }},
  extensionManager: {{ registerSidebarTab(value) {{ sidebar = value; }} }},
}};
const document = {{
  querySelector() {{ return null; }},
  head: {{ append() {{}} }},
  createElement(tag) {{ return {{ tagName: tag, dataset: {{}}, style: {{}}, append() {{}}, addEventListener() {{}}, setAttribute() {{}} }}; }},
}};
const context = {{ app, api: {{fetchApi: async () => ({{ok:true,json:async()=>({{collections:[],tags:[],active:{{}},loras:[],detail:null}})}})}}, document, URL, console, setTimeout, clearTimeout, FormData, globalThis: null }};
context.globalThis = context;
vm.runInNewContext(source, context);
const seam = context.__archReferenceLibrary;
if (!extension || !sidebar || sidebar.id !== "arch.reference-library" || sidebar.type !== "custom") throw new Error("sidebar registration missing");
if (typeof sidebar.render !== "function") throw new Error("sidebar render missing");
if (!extension.beforeRegisterNodeDef) throw new Error("selector enhancement missing");
const filters = seam.normalizeFilters({{include_all:["a","a"],include_any:["b"],exclude:["c"]}});
if (filters.include_all.join(",") !== "a" || filters.include_any[0] !== "b" || filters.exclude[0] !== "c") throw new Error("filter normalization failed");
const add = seam.batchTagPayload("collection", ["one","one","two"], "portrait", "add");
if (add.image_ids.join(",") !== "one,two" || add.add_tag_ids[0] !== "portrait" || add.remove_tag_ids.length) throw new Error("batch add payload failed");
const remove = seam.batchTagPayload("collection", ["one"], "portrait", "remove");
if (remove.remove_tag_ids[0] !== "portrait" || remove.add_tag_ids.length) throw new Error("batch remove payload failed");
const slots = [1,2,3,4].map((slot) => ({{slot,image_id:`image-${{slot}}`,pinned:false}}));
const pinned = seam.pinSlot(slots, 2, "image-4");
if (!pinned.find((item)=>item.slot===2).pinned || pinned.find((item)=>item.slot===4).image_id !== null) throw new Error("pinning did not preserve distinct slots");
let rejected = false; try {{ seam.normalizeFilters({{include_all:"wrong"}}); }} catch {{ rejected = true; }}
if (!rejected) throw new Error("invalid filters were accepted");
"""
    result = subprocess.run(
        ["node", "-e", node_script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_frontend_contains_complete_local_management_actions():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for endpoint_fragment in (
        "/collections",
        "/active/",
        "/import/",
        "/tags",
        "/membership-tags",
        "/profiles",
        "/selections/",
        "/reroll",
    ):
        assert endpoint_fragment in source
    for control_text in (
        "Add collection",
        "Import images",
        "Add tag",
        "Apply tag",
        "Remove tag",
        "Reroll references",
        "Save profile",
        "Add LoRA",
        "Pin current sidebar selection",
        "Unassigned managed images",
        "Permanently delete",
    ):
        assert control_text in source
