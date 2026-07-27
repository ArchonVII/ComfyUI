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
function makeNode(tag) {{
  return {{ tagName: tag, className: "", textContent: "", children: [], dataset: {{}}, style: {{}}, listeners: {{}},
    append(...nodes) {{ this.children.push(...nodes); }}, prepend(...nodes) {{ this.children.unshift(...nodes); }}, replaceChildren(...nodes) {{ this.children = nodes; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }}, setAttribute() {{}},
    querySelector(selector) {{ return this.querySelectorAll(selector)[0]; }},
    querySelectorAll(selector) {{ const found = []; const visit = (node) => {{ if (!node || !node.children) return; for (const child of node.children) {{ const match = selector.match(/^([a-z]+)?\\[name=\"([^\"]+)\"\\](?::checked)?$/); if (match && (!match[1] || child.tagName === match[1]) && child.name === match[2] && (!selector.endsWith(":checked") || child.checked)) found.push(child); visit(child); }} }}; visit(this); return found; }},
  }};
}}
const document = {{
  head: {{ append(node) {{ links.push(node); }} }},
  createElement: makeNode,
}};
const apiBackend = {{ fetchApi: async (path) => ({{ ok: true, json: async () => path.endsWith("/catalog") ? {{diffusion_models:["flux.safetensors"], loras:["face.safetensors"]}} : {{experiments:[]}} }}) }};
const context = {{ app, api: apiBackend, document, Option: function(text, value) {{ const node = makeNode("option"); node.textContent = text; node.value = value; return node; }}, URL, console, setTimeout, clearTimeout, structuredClone }};
vm.runInNewContext(source, context);
const api = context.__identityLab;
if (!extension || !sidebar || sidebar.id !== "arch.identity-lab" || sidebar.type !== "custom") throw new Error("sidebar was not registered");
if (!links.some((link) => String(link.href).includes("identity_lab.css"))) throw new Error("panel CSS was not loaded");
const panelRoot = makeNode("section"); sidebar.render(panelRoot);
if (!panelRoot.querySelector('form[name="missing"]') && !panelRoot.children.some((node) => node.tagName === "form")) throw new Error("sidebar render did not mount setup controls");

const workflow = {{
  "1": {{ class_type: "LoadImage", inputs: {{ image: "locked-base.png" }}, _meta: {{ title: "IDENTITY_LAB_BASE_IMAGE" }} }},
  "2": {{ class_type: "LoadImage", inputs: {{ image: "locked-ref.png" }}, _meta: {{ title: "IDENTITY_LAB_REFERENCE_IMAGE" }} }},
  "3": {{ class_type: "UNETLoader", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_MODEL" }} }},
  "4": {{ class_type: "LoraLoader", inputs: {{lora_name:"default-1.safetensors", strength_model:1, strength_clip:1}}, _meta: {{ title: "IDENTITY_LAB_LORA_1" }} }},
  "5": {{ class_type: "LoraLoader", inputs: {{lora_name:"default-2.safetensors", strength_model:1, strength_clip:1}}, _meta: {{ title: "IDENTITY_LAB_LORA_2" }} }},
  "6": {{ class_type: "LoraLoader", inputs: {{lora_name:"default-3.safetensors", strength_model:1, strength_clip:1}}, _meta: {{ title: "IDENTITY_LAB_LORA_3" }} }},
  "7": {{ class_type: "KSampler", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_SAMPLER" }} }},
  "8": {{ class_type: "DualIdentityScore", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_SCORE" }} }},
  "9": {{ class_type: "ImageScaleToTotalPixels", inputs: {{}}, _meta: {{ title: "IDENTITY_LAB_PIXEL_BUDGET" }} }},
}};
const settings = api.parseSetup({{ mode: "face_swap", checkpoints: ["flux.safetensors"], loras: [{{name: "face.safetensors", strength: "0.7"}}], seeds: "11, 12", steps: "28", cfg: "3.5", denoise: "0.8", pixelBudget: "1048576", sampler: "euler", scheduler: "simple" }});
if (settings.seeds.join(",") !== "11,12" || settings.loras[0].strength !== 0.7 || settings.steps !== 28 || settings.cfg !== 3.5) throw new Error("strict setup parsing failed");
let badDenoise = false; try {{ api.parseSetup({{ ...settings, denoise: "1.1" }}); }} catch {{ badDenoise = true; }}
if (!badDenoise) throw new Error("out-of-range denoise was accepted");
let badMode = false; try {{ api.parseSetup({{ ...settings, mode: "txt2img" }}); }} catch {{ badMode = true; }}
if (!badMode) throw new Error("invalid experiment mode was accepted");
let badCatalogValue = false; try {{ api.parseSetup({{ ...settings, samplers: ["heun"], schedulers: ["simple"] }}); }} catch {{ badCatalogValue = true; }}
if (!badCatalogValue) throw new Error("unavailable sampler was accepted");
if (!api.estimatePreview(settings, 2).includes("runs")) throw new Error("estimate preview missing");
const patched = api.patchPrompt(workflow, {{ ...settings, experimentId: "exp", runId: "run", mode: "face_swap" }});
if (patched["1"].inputs.image !== "locked-base.png" || patched["2"].inputs.image !== "locked-ref.png") throw new Error("locked image roles changed");
if (patched["3"].inputs.unet_name !== "flux.safetensors" || patched["8"].inputs.run_id !== "run") throw new Error("stable role patch failed");
if (patched["4"].inputs.lora_name !== "face.safetensors" || patched["5"].inputs.lora_name !== "default-2.safetensors" || patched["5"].inputs.strength_model !== 0 || patched["9"].inputs.megapixels !== 1) throw new Error("inactive LoRA or megapixel patching is invalid");
const duplicate = structuredClone(workflow); duplicate["9"] = structuredClone(duplicate["8"]);
let rejected = false; try {{ api.patchPrompt(duplicate, {{...settings, experimentId: "exp", runId: "run", mode: "face_swap" }}); }} catch {{ rejected = true; }}
if (!rejected) throw new Error("duplicate roles were accepted");
const normalized = api.normalizeReport({{ identity_report: {{ active_score: {{ cosine_similarity: 0.91 }}, reference_to_output: {{ cosine_similarity: 0.91 }}, base_to_output: {{ cosine_similarity: 0.20 }}, face_detection: {{ base: true, reference: true, generated: true }}, runtime_seconds: 12 }} }});
if (normalized.activeScore !== 0.91 || normalized.referenceScore !== 0.91 || normalized.baseScore !== 0.2) throw new Error("persisted score schema was not normalized");
const promotion = api.buildPromotionPayload([{{ plan: {{ checkpoint: "flux", seed: 7, loras: [["face", 0.7]] }} }}], "focused_refine", {{ steps: 30, cfg: 4, denoise: 0.8, pixelBudget: 1048576, sampler: "euler", scheduler: "simple" }});
if (promotion.stages[0] !== "focused_refine" || promotion.loras[0][0] !== "face" || promotion.refine_settings.pixel_budget !== 1) throw new Error("promotion discarded selected candidates");
const baselinePromotion = api.buildPromotionPayload([{{ plan: {{ checkpoint: "flux", seed: 7, loras: [] }} }}], "lora_single", settings);
if (baselinePromotion.loras[0][0] !== "face.safetensors") throw new Error("baseline promotion lost persisted LoRA candidates");

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
  const rankableFirst = api.filterAndSortResults([{{ id:"partial", state:"completed", plan:{{loras:[]}}, identity_report:{{active_score:.99,rankable:false}} }}, {{ id:"rankable", state:"completed", plan:{{loras:[]}}, identity_report:{{active_score:.1,rankable:true}} }}], {{}});
  if (rankableFirst[0].id !== "rankable") throw new Error("non-rankable partial score outranked a rankable result");
  const details = api.galleryMetadata({{ id: "b", state: "completed", plan: {{ checkpoint: "flux", loras: [["face", 0.7]], steps: 28, cfg: 3.5, sampler: "euler", scheduler: "simple", denoise: 0.8 }}, identity_report: {{ active_score: 0.9, reference_score: 0.8, base_score: 0.2, rankable: true, face_detection: {{base:true, reference:true, generated:true}}, runtime_seconds: 12 }} }});
  if (!details.includes("reference 0.8") || !details.includes("runtime 12")) throw new Error("gallery metadata is incomplete");
  let detailCalls = 0; const queueCalls = [];
  const persisted = {{ experiment: {{ settings: {{ workflow_template: workflow, setup: settings }} }}, runs: [{{ id: "serial", state: "planned", plan: {{ checkpoint: "flux.safetensors", loras: [], seed: 3 }} }}] }};
  const queueFetch = async (path, options = {{}}) => {{
    queueCalls.push(path);
    if (path === "/identity-lab/experiments/exp") {{ detailCalls++; return {{ok:true, json:async()=> detailCalls > 1 ? {{...persisted, runs:[{{...persisted.runs[0], state:"completed"}}]}} : persisted }}; }}
    if (path === "/prompt") return {{ok:true, json:async()=>({{prompt_id:"prompt-1"}})}};
    if (path === "/history/prompt-1") return {{ok:true, json:async()=>({{ "prompt-1": {{prompt_id:"prompt-1", status:{{status_str:"success"}}}} }})}};
    return {{ok:true, json:async()=>({{state:"queued"}})}};
  }};
  const serial = new api.SerialQueue({{ fetchApi: queueFetch, graphToPrompt: async () => {{ throw new Error("persisted workflow must be used"); }}, pollMs: 0, maxPolls: 3 }});
  await serial.run("exp");
  if (queueCalls.filter((path) => path === "/prompt").length !== 1 || !queueCalls.includes("/history/prompt-1")) throw new Error("serial queue did not persist and poll one prompt");
  const failureCalls = []; let failedRecorded = false;
  const failingQueue = new api.SerialQueue({{ fetchApi: async (path) => {{ failureCalls.push(path); if (path === "/identity-lab/experiments/bad") return {{ok:true, json:async()=> failedRecorded ? {{...persisted, runs:[{{...persisted.runs[0], state:"failed"}}]}} : persisted}}; if (path === "/prompt") return {{ok:true, json:async()=>({{prompt_id:"bad-prompt"}})}}; if (path === "/history/bad-prompt") return {{ok:true, json:async()=>({{ "bad-prompt": {{status:{{status_str:"error"}}}} }})}}; if (path.endsWith("/failed")) {{ failedRecorded = true; return {{ok:true, json:async()=>({{state:"failed"}})}}; }} return {{ok:true, json:async()=>({{}})}}; }}, maxPolls: 1 }});
  await failingQueue.run("bad");
  if (!failureCalls.some((path) => path.endsWith("/runs/serial/failed"))) throw new Error("terminal execution failure was not recorded");
  const timeoutCalls = []; const timeoutQueue = new api.SerialQueue({{ fetchApi: async (path) => {{ timeoutCalls.push(path); if (path === "/identity-lab/experiments/timeout") return {{ok:true,json:async()=>persisted}}; if (path === "/prompt") return {{ok:true,json:async()=>({{prompt_id:"still-running"}})}}; if (path === "/history/still-running") return {{ok:true,json:async()=>({{}})}}; return {{ok:true,json:async()=>({{state:"queued"}})}}; }}, maxPolls: 1 }});
  await timeoutQueue.run("timeout"); if (timeoutCalls.some((path) => path.endsWith("/failed"))) throw new Error("poll timeout incorrectly failed a potentially running prompt");
  const activeCalls = []; const updates = []; const activeQueue = new api.SerialQueue({{ fetchApi: async (path) => {{ activeCalls.push(path); if (path === "/identity-lab/experiments/active") return {{ok:true,json:async()=>({{...persisted, runs:[{{...persisted.runs[0], id:"already-queued", state:"queued"}}, {{...persisted.runs[0], id:"must-not-submit", state:"planned"}}]}})}}; throw new Error(`unexpected request ${{path}}`); }}, onUpdate: (update) => updates.push(update) }});
  await activeQueue.run("active");
  if (activeCalls.includes("/prompt")) throw new Error("serial queue submitted while an earlier run was active");
  if (!updates.some((update) => update.status && update.status.includes("queued or running"))) throw new Error("serial queue did not surface active-run monitoring status");
}})().catch((error) => {{ console.error(error.stack || error.message); process.exit(1); }});
"""
    result = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
