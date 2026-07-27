import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "web" / "identity_lab.js"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_identity_lab_sidebar_registers_and_exposes_safe_experiment_seams():
    """The browser module is covered without a browser by a deliberately tiny VM harness."""
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
let source = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8");
source = source.replace(/^import[^\\n]*\\n/gm, "").replaceAll("import.meta.url", JSON.stringify("https://local/identity_lab.js")).replace(/export \\{{[^}}]+\\}};?\\s*$/m, "");

let extension, sidebar;
const links = [];
const app = {{
  registerExtension(value) {{ extension = value; }},
  extensionManager: {{ registerSidebarTab(value) {{ sidebar = value; }} }},
}};
const document = {{
  head: {{ append(node) {{ links.push(node); }} }},
  createElement(tag) {{ return {{ tagName: tag, className: "", textContent: "", append() {{}}, addEventListener() {{}}, setAttribute() {{}}, style: {{}}, dataset: {{}} }}; }},
}};
const context = {{ app, document, URL, console, setTimeout, clearTimeout, structuredClone }};
vm.runInNewContext(source, context);
const api = context.__identityLab;
if (!extension || !sidebar || sidebar.id !== "arch.identity-lab" || sidebar.type !== "custom") throw new Error("sidebar was not registered");
if (!links.some((link) => String(link.href).includes("identity_lab.css"))) throw new Error("panel CSS was not loaded");

const workflow = {{
  "1": {{ class_type: "LoadImage", inputs: {{ image: "locked-base.png" }}, _meta: {{ title: "IDENTITY_LAB_BASE_IMAGE" }} }},
  "2": {{ class_type: "LoadImage", inputs: {{ image: "locked-ref.png" }}, _meta: {{ title: "IDENTITY_LAB_REFERENCE_IMAGE" }} }},
  "3": {{ class_type: "UNETLoader", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_MODEL" }} }},
  "4": {{ class_type: "LoraLoader", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_LORA_1" }} }},
  "5": {{ class_type: "LoraLoader", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_LORA_2" }} }},
  "6": {{ class_type: "LoraLoader", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_LORA_3" }} }},
  "7": {{ class_type: "KSampler", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_SAMPLER" }} }},
  "8": {{ class_type: "DualIdentityScore", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_SCORE" }} }},
}};
const settings = api.parseSetup({{ checkpoints: ["flux.safetensors"], loras: [{{name: "face.safetensors", strength: "0.7"}}], seeds: "11, 12", steps: "28", cfg: "3.5", denoise: "0.8", pixelBudget: "1048576", sampler: "euler", scheduler: "simple" }});
if (settings.seeds.join(",") !== "11,12" || settings.loras[0].strength !== 0.7 || settings.steps !== 28 || settings.cfg !== 3.5) throw new Error("strict setup parsing failed");
let badDenoise = false; try {{ api.parseSetup({{ ...settings, denoise: "1.1" }}); }} catch {{ badDenoise = true; }}
if (!badDenoise) throw new Error("out-of-range denoise was accepted");
if (!api.estimatePreview(settings, 2).includes("runs")) throw new Error("estimate preview missing");
const patched = api.patchPrompt(workflow, {{ ...settings, experimentId: "exp", runId: "run", mode: "face_swap" }});
if (patched["1"].inputs.image !== "locked-base.png" || patched["2"].inputs.image !== "locked-ref.png") throw new Error("locked image roles changed");
if (patched["3"].inputs.unet_name !== "flux.safetensors" || patched["8"].inputs.run_id !== "run") throw new Error("stable role patch failed");
const duplicate = structuredClone(workflow); duplicate["9"] = structuredClone(duplicate["8"]);
let rejected = false; try {{ api.patchPrompt(duplicate, {{...settings, experimentId: "exp", runId: "run", mode: "face_swap" }}); }} catch {{ rejected = true; }}
if (!rejected) throw new Error("duplicate roles were accepted");

const calls = [];
const fetchApi = async (path, options = {{}}) => {{
  calls.push([path, options]);
  if (path.includes("/queued")) return {{ ok: true, json: async () => ({{state: "queued"}}) }};
  if (path === "/prompt") return {{ ok: true, json: async () => ({{prompt_id: "p"}}) }};
  return {{ ok: true, json: async () => ({{}}) }};
}};
(async () => {{
  await api.submitOne({{ fetchApi, workflow, experimentId: "exp", run: {{ id: "run", plan: {{ checkpoint: "flux.safetensors", loras: [], seed: 1, stage: "baseline" }} }}, settings }});
  if (calls.filter(([path]) => path === "/prompt").length !== 1 || calls[0][0].includes("/prompt")) throw new Error("serial submit order failed");
  const cards = api.filterAndSortResults([
    {{ id: "a", state: "completed", favorite: false, rating: 3, plan: {{ checkpoint: "a", loras: [] }}, identity_report: {{ active_score: 0.4, rankable: true }} }},
    {{ id: "b", state: "completed", favorite: true, rating: 5, plan: {{ checkpoint: "b", loras: [] }}, identity_report: {{ active_score: 0.9, rankable: true }} }},
  ], {{}});
  if (cards[0].id !== "b") throw new Error("gallery did not default-sort by active score");
  if (api.filterAndSortResults(cards, {{ checkpoint: "a" }}).length !== 1) throw new Error("gallery checkpoint filter failed");
  const details = api.galleryMetadata({{ id: "b", state: "completed", plan: {{ checkpoint: "flux", loras: [["face", 0.7]], steps: 28, cfg: 3.5, sampler: "euler", scheduler: "simple", denoise: 0.8 }}, identity_report: {{ active_score: 0.9, reference_score: 0.8, base_score: 0.2, rankable: true, face_detection: {{base:true, reference:true, generated:true}}, runtime_seconds: 12 }} }});
  if (!details.includes("reference 0.8") || !details.includes("runtime 12")) throw new Error("gallery metadata is incomplete");
}})().catch((error) => {{ console.error(error.stack || error.message); process.exit(1); }});
"""
    result = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
