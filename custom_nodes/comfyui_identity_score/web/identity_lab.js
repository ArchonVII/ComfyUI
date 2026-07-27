import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROLE_TYPES = {
  IDENTITY_LAB_BASE_IMAGE: ["LoadImage"],
  IDENTITY_LAB_REFERENCE_IMAGE: ["LoadImage"],
  IDENTITY_LAB_MODEL: ["UNETLoader", "CheckpointLoaderSimple"],
  IDENTITY_LAB_LORA_1: ["LoraLoader"],
  IDENTITY_LAB_LORA_2: ["LoraLoader"],
  IDENTITY_LAB_LORA_3: ["LoraLoader"],
  IDENTITY_LAB_SAMPLER: ["KSampler"],
  IDENTITY_LAB_PIXEL_BUDGET: ["ImageScaleToTotalPixels"],
  IDENTITY_LAB_SCORE: ["DualIdentityScore"],
};
const LAB_ROOT = "/identity-lab";
const clone = (value) => globalThis.structuredClone ? structuredClone(value) : JSON.parse(JSON.stringify(value));

function css() {
  if (document.querySelector?.("link[data-identity-lab-css]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.dataset.identityLabCss = "true";
  link.href = new URL("./identity_lab.css", import.meta.url).href;
  document.head.append(link);
}

function strictNumber(value, name, { integer = false, min = 0, max = Infinity } = {}) {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error(`${name} must be finite`);
    if (integer && !Number.isInteger(value)) throw new Error(`${name} must be an integer`);
    if (value < min) throw new Error(`${name} must be at least ${min}`);
    if (value > max) throw new Error(`${name} must be at most ${max}`);
    return value;
  }
  if (typeof value !== "string" || !/^[+-]?(?:\d+|\d*\.\d+)$/.test(value.trim())) throw new Error(`${name} must be numeric`);
  return strictNumber(Number(value.trim()), name, { integer, min, max });
}

function parseSeeds(value) {
  const raw = Array.isArray(value) ? value : String(value ?? "").split(",");
  if (!raw.length || raw.some((seed) => String(seed).trim() === "")) throw new Error("at least one seed is required");
  return raw.map((seed) => strictNumber(seed, "seed", { integer: true, min: 0 }));
}

function parseSetup(raw) {
  const checkpoints = (Array.isArray(raw.checkpoints) ? raw.checkpoints : [raw.checkpoints]).filter(Boolean);
  if (!checkpoints.length || checkpoints.some((name) => typeof name !== "string" || !name.trim())) throw new Error("select at least one checkpoint");
  const loras = (raw.loras ?? []).filter((item) => item?.name?.trim()).slice(0, 3).map((item) => ({
    name: item.name.trim(), strength: strictNumber(item.strength, "LoRA strength", { min: Number.EPSILON, max: 1 }),
  }));
  return {
    mode: raw.mode === "face_swap" || raw.mode === "identity_i2i" ? raw.mode : (() => { throw new Error("mode must be face_swap or identity_i2i"); })(),
    checkpoints, loras, seeds: parseSeeds(raw.seeds),
    steps: strictNumber(raw.steps, "steps", { integer: true, min: 1 }),
    cfg: strictNumber(raw.cfg, "guidance", { min: 0 }),
    denoise: strictNumber(raw.denoise, "denoise", { min: 0, max: 1 }),
    pixelBudget: strictNumber(raw.pixelBudget, "pixel budget", { integer: true, min: 1 }),
    sampler: String(raw.sampler || "euler"), scheduler: String(raw.scheduler || "simple"),
  };
}

function estimatePreview(settings, count) {
  const runs = Number.isInteger(count) ? count : settings.checkpoints.length * settings.seeds.length;
  const loraMultiplier = Math.max(1, settings.loras.length);
  const seconds = Math.max(1, Math.round((settings.steps * settings.pixelBudget / 1_000_000) * loraMultiplier));
  const bytes = Math.round(settings.pixelBudget * 3.5);
  return `${runs} runs • ~${seconds * runs}s • ~${Math.round(bytes * runs / 1_000_000)} MB`;
}

function roleMap(prompt) {
  const found = {};
  for (const [id, node] of Object.entries(prompt ?? {})) {
    const title = node?._meta?.title;
    if (!(title in ROLE_TYPES)) continue;
    if (found[title]) throw new Error(`duplicate workflow role: ${title}`);
    if (!ROLE_TYPES[title].includes(node.class_type)) throw new Error(`workflow role ${title} has an incompatible type`);
    found[title] = [id, node];
  }
  for (const role of Object.keys(ROLE_TYPES)) if (!found[role]) throw new Error(`missing workflow role: ${role}`);
  return found;
}

function patchPrompt(workflow, settings) {
  const prompt = clone(workflow);
  const roles = roleMap(prompt);
  // Base/reference image roles are deliberately inspected but never mutated.
  void roles.IDENTITY_LAB_BASE_IMAGE; void roles.IDENTITY_LAB_REFERENCE_IMAGE;
  const model = roles.IDENTITY_LAB_MODEL[1].inputs ??= {};
  model.unet_name = settings.checkpoint ?? settings.checkpoints?.[0];
  if (roles.IDENTITY_LAB_MODEL[1].class_type === "CheckpointLoaderSimple") model.ckpt_name = model.unet_name;
  ["IDENTITY_LAB_LORA_1", "IDENTITY_LAB_LORA_2", "IDENTITY_LAB_LORA_3"].forEach((role, index) => {
    const inputs = roles[role][1].inputs ??= {}; const lora = settings.loras?.[index];
    inputs.lora_name = lora?.name ?? ""; inputs.strength_model = lora?.strength ?? 0; inputs.strength_clip = lora?.strength ?? 0;
  });
  const sampler = roles.IDENTITY_LAB_SAMPLER[1].inputs ??= {};
  Object.assign(sampler, { seed: settings.seed ?? settings.seeds?.[0], steps: settings.steps, cfg: settings.cfg, sampler_name: settings.sampler, scheduler: settings.scheduler, denoise: settings.denoise });
  Object.assign(roles.IDENTITY_LAB_PIXEL_BUDGET[1].inputs ??= {}, { total_pixels: settings.pixelBudget });
  Object.assign(roles.IDENTITY_LAB_SCORE[1].inputs ??= {}, { experiment_id: settings.experimentId, run_id: settings.runId, experiment_mode: settings.mode });
  return prompt;
}

async function responseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || `request failed (${response.status})`);
  return data;
}

async function submitOne({ fetchApi = api.fetchApi.bind(api), workflow, experimentId, run, settings }) {
  await responseJson(await fetchApi(`${LAB_ROOT}/runs/${run.id}/queued`, { method: "POST", body: JSON.stringify({ experiment_id: experimentId }) }));
  const prompt = patchPrompt(workflow, { ...settings, checkpoint: run.plan.checkpoint, seed: run.plan.seed, loras: run.plan.loras ?? [], experimentId, runId: run.id });
  try {
    return await responseJson(await fetchApi("/prompt", { method: "POST", body: JSON.stringify({ prompt }) }));
  } catch (error) {
    await fetchApi(`${LAB_ROOT}/runs/${run.id}/failed`, { method: "POST", body: JSON.stringify({ experiment_id: experimentId, error: String(error.message || error) }) }).catch(() => undefined);
    throw error;
  }
}

class SerialQueue {
  constructor({ fetchApi = api.fetchApi.bind(api), onUpdate = () => {}, pollMs = 2000, maxPolls = 180 } = {}) {
    Object.assign(this, { fetchApi, onUpdate, pollMs: Math.max(250, pollMs), maxPolls: Math.max(1, maxPolls), paused: false, running: false });
  }
  pause() { this.paused = true; this.onUpdate({ status: "pausing" }); }
  async resume(experimentId) { await responseJson(await this.fetchApi(`${LAB_ROOT}/experiments/${experimentId}/resume`, { method: "POST", body: JSON.stringify({ stale_after_seconds: 300 }) })); this.paused = false; return this.run(experimentId); }
  async run(experimentId) {
    if (this.running) return; this.running = true;
    try {
      while (!this.paused) {
        const detail = await responseJson(await this.fetchApi(`${LAB_ROOT}/experiments/${experimentId}`));
        const run = detail.runs.find((item) => item.state === "planned");
        if (!run) { this.onUpdate(detail); break; }
        const workflow = detail.experiment.settings.workflow_template;
        if (!workflow) throw new Error("experiment has no persisted workflow template");
        roleMap(workflow);
        const prompt = await submitOne({ fetchApi: this.fetchApi, workflow, experimentId, run, settings: detail.experiment.settings.setup ?? {} });
        await this.waitForTerminal(experimentId, run.id, prompt.prompt_id);
      }
    } catch (error) { this.onUpdate({ error: String(error.message || error) }); }
    finally { this.running = false; }
  }
  async waitForTerminal(experimentId, runId, promptId) {
    for (let attempt = 0; attempt < this.maxPolls; attempt++) {
      const [detail, history] = await Promise.all([
        responseJson(await this.fetchApi(`${LAB_ROOT}/experiments/${experimentId}`)),
        promptId ? responseJson(await this.fetchApi(`/history/${encodeURIComponent(promptId)}`)).catch(() => ({})) : Promise.resolve({}),
      ]);
      const run = detail.runs.find((item) => item.id === runId);
      this.onUpdate(detail);
      if (!run || ["completed", "failed", "archived"].includes(run.state)) return run;
      const historyStatus = String(history?.status?.status_str ?? history?.status ?? "").toLowerCase();
      if (["success", "error", "failed", "interrupted"].some((state) => historyStatus.includes(state))) {
        const error = historyStatus.includes("success") ? "prompt completed without DualIdentityScore result" : `prompt execution ${historyStatus}`;
        await this.recordFailure(experimentId, runId, error);
        return { ...run, state: "failed" };
      }
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
    }
    await this.recordFailure(experimentId, runId, `prompt timed out after ${this.maxPolls} polls`);
    return { id: runId, state: "failed" };
  }
  async recordFailure(experimentId, runId, error) {
    await this.fetchApi(`${LAB_ROOT}/runs/${runId}/failed`, { method: "POST", body: JSON.stringify({ experiment_id: experimentId, error: String(error).slice(0, 500) }) }).catch(() => undefined);
  }
}

function scoreValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value.cosine_similarity === "number" && Number.isFinite(value.cosine_similarity)) return value.cosine_similarity;
  return null;
}
function normalizeReport(run) {
  const report = run.identity_report ?? run ?? {};
  return {
    activeScore: scoreValue(report.active_score),
    referenceScore: scoreValue(report.reference_to_output) ?? scoreValue(report.reference_score),
    baseScore: scoreValue(report.base_to_output) ?? scoreValue(report.base_score),
    rankable: report.rankable === true,
    detection: report.face_detection ?? {},
    runtimeSeconds: report.runtime_seconds ?? report.scorer_seconds ?? null,
  };
}
function activeScore(run) { return normalizeReport(run).activeScore ?? -Infinity; }
function buildPromotionPayload(candidates, stage, settings) {
  if (!["lora_single", "lora_pair", "lora_triple", "focused_refine"].includes(stage)) throw new Error("choose a valid next stage");
  if (!Array.isArray(candidates) || !candidates.length) throw new Error("select at least one result or candidate");
  const checkpoints = [...new Set(candidates.map((run) => run.plan?.checkpoint).filter(Boolean))];
  const seeds = [...new Set(candidates.map((run) => run.plan?.seed).filter((seed) => Number.isInteger(seed)))];
  const loraMap = new Map();
  for (const run of candidates) for (const lora of run.plan?.loras ?? []) { const [name, strength] = Array.isArray(lora) ? lora : [lora.name, lora.strength]; if (name) loraMap.set(`${name}:${strength}`, [name, strength]); }
  const payload = { checkpoints, seeds, loras: [...loraMap.values()], stages: [stage] };
  if (!checkpoints.length || !seeds.length) throw new Error("selected candidates need checkpoint and seed values");
  if (stage === "focused_refine") payload.refine_settings = { steps: settings.steps, cfg: settings.cfg, denoise: settings.denoise, pixel_budget: settings.pixelBudget, sampler: settings.sampler, scheduler: settings.scheduler };
  return payload;
}
function galleryMetadata(run) {
  const report = normalizeReport(run); const plan = run.plan ?? {}; const detection = report.detection;
  const loras = (plan.loras ?? []).map((item) => Array.isArray(item) ? `${item[0]} @ ${item[1]}` : `${item.name} @ ${item.strength}`).join(", ") || "no LoRA";
  const refine = plan.refine ?? {}; return `active ${report.activeScore ?? "—"} • reference ${report.referenceScore ?? "—"} • base ${report.baseScore ?? "—"} • ${report.rankable ? "rankable" : "not rankable"} • detections base:${!!detection.base} reference:${!!detection.reference} generated:${!!detection.generated} • ${plan.checkpoint ?? "—"} • ${loras} • seed ${plan.seed ?? "—"} • steps ${refine.steps ?? plan.steps ?? "—"} cfg ${refine.cfg ?? plan.cfg ?? "—"} ${refine.sampler ?? plan.sampler ?? "—"}/${refine.scheduler ?? plan.scheduler ?? "—"} denoise ${refine.denoise ?? plan.denoise ?? "—"} pixels ${refine.pixel_budget ?? plan.pixel_budget ?? "—"} • runtime ${report.runtimeSeconds ?? "—"}`;
}
function filterAndSortResults(results, filters) {
  const filtered = results.filter((run) => {
    const plan = run.plan ?? {}; const loras = (plan.loras ?? []).map((item) => Array.isArray(item) ? item[0] : item.name).join(" ");
    return (!filters.stage || plan.stage === filters.stage) && (!filters.checkpoint || plan.checkpoint === filters.checkpoint) && (!filters.lora || loras.includes(filters.lora)) && (!filters.state || run.state === filters.state) && (!filters.favorite || run.favorite) && (!filters.rating || run.rating === Number(filters.rating));
  });
  const sorters = { active: (a, b) => activeScore(b) - activeScore(a), rating: (a, b) => (b.rating ?? 0) - (a.rating ?? 0), newest: (a, b) => String(b.completed_at ?? b.updated_at ?? "").localeCompare(String(a.completed_at ?? a.updated_at ?? "")) };
  return filtered.sort(sorters[filters.sort] ?? sorters.active);
}

function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function statusSummary(detail) {
  const counts = (detail?.runs ?? []).reduce((all, run) => (all[run.state] = (all[run.state] ?? 0) + 1, all), {});
  return Object.entries(counts).map(([state, count]) => `${state}: ${count}`).join(" • ") || "No runs planned";
}
function selectFilter(label, values, onChange) {
  const control = el("select"); control.append(new Option(label, ""));
  for (const value of values) control.append(new Option(value, value));
  control.addEventListener("change", onChange); return control;
}
function renderGallery(container, detail, refresh, selected = new Set(), filters = {}) {
  const allRuns = detail.runs ?? []; const values = (key) => [...new Set(allRuns.map((run) => run.plan?.[key]).filter(Boolean))];
  const toolbar = el("div", undefined, "identity-lab-filters");
  const rerender = () => renderGallery(container, detail, refresh, selected, filters);
  const loraValues = [...new Set(allRuns.flatMap((run) => (run.plan?.loras ?? []).map((item) => Array.isArray(item) ? item[0] : item.name)).filter(Boolean))];
  [["stage", values("stage")], ["checkpoint", values("checkpoint")], ["lora", loraValues], ["state", [...new Set(allRuns.map((run) => run.state))]], ["rating", ["1", "2", "3", "4", "5"]]].forEach(([key, options]) => toolbar.append(selectFilter(key, options, (event) => { filters[key] = event.target.value; rerender(); })));
  const sort = selectFilter("sort: active score", ["active", "rating", "newest"], (event) => { filters.sort = event.target.value || "active"; rerender(); }); toolbar.append(sort);
  const favorite = el("label", " favorites only"); const favoriteInput = el("input"); favoriteInput.type = "checkbox"; favoriteInput.checked = !!filters.favorite; favoriteInput.addEventListener("change", (event) => { filters.favorite = event.target.checked; rerender(); }); favorite.prepend(favoriteInput); toolbar.append(favorite);
  const results = filterAndSortResults(allRuns, filters); container.replaceChildren(toolbar);
  for (const run of results) {
    const card = el("article", undefined, "identity-lab-card");
    if (run.state === "completed") { const image = el("img"); image.src = `${LAB_ROOT}/runs/${encodeURIComponent(run.id)}/output`; image.alt = `Result ${run.id}`; card.append(image); }
    const choose = el("input"); choose.type = "checkbox"; choose.checked = selected.has(run.id); choose.addEventListener("change", (event) => { event.target.checked ? selected.add(run.id) : selected.delete(run.id); }); card.append(choose);
    card.append(el("p", galleryMetadata(run)));
    const controls = el("div", undefined, "identity-lab-card-controls");
    if (run.state === "completed") for (let rating = 1; rating <= 5; rating++) { const button = el("button", String(rating)); button.addEventListener("click", async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ rating }) })); refresh(); }); controls.append(button); }
    const favorite = el("button", run.favorite ? "★" : "☆"); favorite.addEventListener("click", async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ favorite: !run.favorite }) })); refresh(); }); controls.append(favorite); card.append(controls); container.append(card);
    if (run.state === "completed") { const reject = el("button", "Reject (1)"); reject.addEventListener("click", async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ rating: 1, favorite: false }) })); refresh(); }); const notes = el("textarea"); notes.value = run.notes ?? ""; notes.placeholder = "Local review notes"; notes.addEventListener("change", async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ notes: notes.value }) })); }); card.append(reject, notes); }
  }
}

function formValue(form, name) { return form.querySelector(`[name="${name}"]`)?.value; }
function renderPanel(container) {
  css(); container.replaceChildren(); const title = el("h2", "Identity Lab"); const status = el("p", "Load a workflow with stable Identity Lab roles."); const form = el("form", undefined, "identity-lab-setup");
  const mode = el("select"); mode.name = "mode"; mode.append(new Option("Face swap", "face_swap"), new Option("Identity i2i", "identity_i2i")); form.append(mode);
  const sampler = el("select"); sampler.name = "sampler"; sampler.append(new Option("Euler", "euler"), new Option("Euler ancestral", "euler_ancestral"), new Option("DPM++ 2M", "dpmpp_2m")); const scheduler = el("select"); scheduler.name = "scheduler"; scheduler.append(new Option("Simple", "simple"), new Option("Karras", "karras"), new Option("Normal", "normal")); form.append(sampler, scheduler);
  const fields = [["name", "Experiment name", "Identity sweep"], ["seeds", "Seeds", "1, 2, 3"], ["steps", "Steps", "28"], ["cfg", "Guidance / CFG", "3.5"], ["denoise", "Denoise", "0.8"], ["pixelBudget", "Pixel budget", "1048576"]];
  for (const [name, label, value] of fields) { const input = el("input"); input.name = name; input.value = value; input.placeholder = label; form.append(input); }
  const catalogArea = el("fieldset"); catalogArea.append(el("legend", "Local Flux 9B catalog")); form.append(catalogArea); const launch = el("button", "Create & run one at a time"); launch.type = "submit"; launch.disabled = true; form.append(launch); const actions = el("section", undefined, "identity-lab-actions"); const gallery = el("section", undefined, "identity-lab-gallery"); container.append(title, status, form, actions, gallery);
  const selectedSetup = () => ({ mode: formValue(form, "mode"), checkpoints: [...form.querySelectorAll('input[name="checkpoint"]:checked')].map((input) => input.value), loras: [1, 2, 3].map((index) => ({ name: formValue(form, `lora-${index}`), strength: formValue(form, `lora-strength-${index}`) })).filter((lora) => lora.name), seeds: formValue(form, "seeds"), steps: formValue(form, "steps"), cfg: formValue(form, "cfg"), denoise: formValue(form, "denoise"), pixelBudget: formValue(form, "pixelBudget"), sampler: formValue(form, "sampler"), scheduler: formValue(form, "scheduler") });
  const previewSetup = () => { try { const setup = parseSetup(selectedSetup()); status.textContent = estimatePreview(setup, setup.checkpoints.length * setup.seeds.length); } catch (error) { status.textContent = `Setup: ${String(error.message || error)}`; } };
  form.addEventListener("input", previewSetup);
  const catalogPromise = api.fetchApi(`${LAB_ROOT}/catalog`).then(responseJson).then((catalog) => { const checkpoints = el("div", "Checkpoints"); for (const [index, name] of catalog.diffusion_models.entries()) { const label = el("label", name); const input = el("input"); input.type = "checkbox"; input.name = "checkpoint"; input.value = name; input.checked = index === 0; label.prepend(input); checkpoints.append(label); } const loras = el("div", "Up to three candidate LoRAs"); for (let index = 1; index <= 3; index++) { const select = el("select"); select.name = `lora-${index}`; select.append(new Option(`No LoRA ${index}`, "")); for (const name of catalog.loras) select.append(new Option(name, name)); const strength = el("input"); strength.name = `lora-strength-${index}`; strength.value = "0.7"; strength.inputMode = "decimal"; loras.append(select, strength); } catalogArea.append(checkpoints, loras); launch.disabled = false; previewSetup(); return catalog; }).catch((error) => { status.textContent = `Catalog error: ${String(error.message || error)}`; throw error; });
  let queue; const selected = new Set(); const refresh = async (id) => { const detail = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}`)); status.textContent = statusSummary(detail); renderGallery(gallery, detail, () => refresh(id), selected); return detail; };
  const existing = el("select"); existing.name = "active-experiment"; existing.append(new Option("Load active experiment", "")); form.prepend(existing);
  const activateExisting = async (id) => { if (!id) return; const detail = await refresh(id); if (!detail.experiment.settings.workflow_template) throw new Error("selected experiment has no persisted workflow template"); queue = new SerialQueue({ onUpdate: (update) => { if (update.runs) { status.textContent = statusSummary(update); renderGallery(gallery, update, () => refresh(id), selected); } } }); const pause = el("button", "Pause after current"); pause.addEventListener("click", () => queue.pause()); const resume = el("button", "Resume planned or confirmed-stale work"); resume.addEventListener("click", () => queue.resume(id)); actions.replaceChildren(pause, resume); status.textContent = `${statusSummary(detail)} • loaded persisted experiment`; };
  existing.addEventListener("change", async () => { try { await activateExisting(existing.value); } catch (error) { status.textContent = `Error: ${String(error.message || error)}`; } });
  api.fetchApi(`${LAB_ROOT}/experiments`).then(responseJson).then(({ experiments }) => { for (const experiment of experiments) existing.append(new Option(experiment.name, experiment.id)); }).catch((error) => { status.textContent = `Experiment list error: ${String(error.message || error)}`; });
  form.addEventListener("submit", async (event) => { event.preventDefault(); try {
    await catalogPromise; const graph = await app.graphToPrompt(); const workflow = graph.output ?? graph.prompt ?? graph; roleMap(workflow); const settings = parseSetup(selectedSetup());
    status.textContent = estimatePreview(settings, settings.checkpoints.length * settings.seeds.length); const created = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments`, { method: "POST", body: JSON.stringify({ name: formValue(form, "name"), mode: settings.mode, checkpoints: settings.checkpoints, seeds: settings.seeds, loras: settings.loras.map((l) => [l.name, l.strength]), stages: ["baseline"], settings: { setup: settings }, workflow }) }));
    const id = created.experiment.id; const pause = el("button", "Pause after current"); pause.addEventListener("click", () => queue?.pause()); const resume = el("button", "Resume planned or confirmed-stale work"); resume.addEventListener("click", () => queue?.resume(id)); const stage = el("select"); stage.append(new Option("LoRA singles", "lora_single"), new Option("LoRA pairs", "lora_pair"), new Option("LoRA triples", "lora_triple"), new Option("Focused refine", "focused_refine")); const promote = el("button", "Promote selected candidates"); promote.addEventListener("click", async () => { const detail = await refresh(id); const candidates = detail.runs.filter((run) => selected.has(run.id)); const payload = buildPromotionPayload(candidates, stage.value, settings); await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/promote`, { method: "POST", body: JSON.stringify(payload) })); await refresh(id); }); const archive = el("button", "Archive"); archive.addEventListener("click", async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/archive`, { method: "POST", body: "{}" })); status.textContent = "Archived. Outputs retained."; }); const preview = el("button", "Preview deletion"); const confirmation = el("input"); confirmation.placeholder = "Type exact DELETE confirmation"; const remove = el("button", "Delete archived experiment"); let deleteToken = ""; preview.addEventListener("click", async () => { const value = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/delete-preview`)); deleteToken = value.token; status.textContent = `Delete preview — DB rows: ${value.runs.join(", ") || "none"}; files: ${value.files.join(", ") || "none"}`; confirmation.placeholder = value.confirmation; }); remove.addEventListener("click", async () => { const value = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}`, { method: "DELETE", body: JSON.stringify({ token: deleteToken, confirmation: confirmation.value }) })); status.textContent = `Deleted ${value.runs.length} rows; recoverable trash: ${(value.recoverable_trash ?? []).join(", ") || "none"}`; gallery.replaceChildren(); }); actions.replaceChildren(pause, resume, stage, promote, archive, preview, confirmation, remove);
    queue = new SerialQueue({ onUpdate: (detail) => { if (detail.runs) { status.textContent = statusSummary(detail); renderGallery(gallery, detail, () => refresh(id), selected); } } }); refresh(id); queue.run(id);
  } catch (error) { status.textContent = `Error: ${String(error.message || error)}`; } });
}

css();
app.registerExtension({ name: "arch.identity-lab", setup() { css(); } });
app.extensionManager.registerSidebarTab({ id: "arch.identity-lab", icon: "pi pi-flask", title: "Identity Lab", type: "custom", render: renderPanel });

const seam = { parseSetup, estimatePreview, patchPrompt, submitOne, normalizeReport, buildPromotionPayload, filterAndSortResults, galleryMetadata, SerialQueue, renderPanel };
globalThis.__identityLab = seam;
export { parseSetup, estimatePreview, patchPrompt, normalizeReport, buildPromotionPayload, submitOne, filterAndSortResults, galleryMetadata, SerialQueue };
