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

function megapixels(value) {
  const numeric = strictNumber(value, "pixel budget", { min: 0.01 });
  // Older saved configurations use raw pixels; normalize explicitly to MP.
  return numeric > 1000 ? numeric / 1_048_576 : numeric;
}

function parseSetup(raw) {
  const checkpoints = (Array.isArray(raw.checkpoints) ? raw.checkpoints : [raw.checkpoints]).filter(Boolean);
  if (!checkpoints.length || checkpoints.some((name) => typeof name !== "string" || !name.trim())) throw new Error("select at least one checkpoint");
  const loras = (raw.loras ?? []).filter((item) => item?.name?.trim()).slice(0, 3).map((item) => ({
    name: item.name.trim(), strength: strictNumber(item.strength, "LoRA strength", { min: Number.EPSILON, max: 1 }),
  }));
  const sampler = String(raw.sampler || "euler"); const scheduler = String(raw.scheduler || "simple");
  if (Array.isArray(raw.samplers) && raw.samplers.length && !raw.samplers.includes(sampler)) throw new Error("sampler is not available in the local Comfy catalog");
  if (Array.isArray(raw.schedulers) && raw.schedulers.length && !raw.schedulers.includes(scheduler)) throw new Error("scheduler is not available in the local Comfy catalog");
  return {
    mode: raw.mode === "face_swap" || raw.mode === "identity_i2i" ? raw.mode : (() => { throw new Error("mode must be face_swap or identity_i2i"); })(),
    checkpoints, loras, seeds: parseSeeds(raw.seeds),
    steps: strictNumber(raw.steps, "steps", { integer: true, min: 1, max: 10000 }),
    cfg: strictNumber(raw.cfg, "guidance", { min: 0, max: 100 }),
    denoise: strictNumber(raw.denoise, "denoise", { min: 0, max: 1 }),
    pixelBudget: strictNumber(megapixels(raw.pixelBudget), "pixel budget", { min: Number.EPSILON, max: 16 }),
    sampler, scheduler,
  };
}

function formatEstimate(estimate) {
  return `${estimate.run_count} runs • ${estimate.estimated_seconds}s (${estimate.time_source}) • ${estimate.estimated_bytes} bytes (${estimate.disk_source}) • ${estimate.free_bytes} bytes free • ${estimate.can_launch ? "ready" : "insufficient space"}`;
}

async function previewEstimate(fetchApi, settings, runCount, endpoint = `${LAB_ROOT}/estimates`) {
  const estimate = await responseJson(await fetchApi(endpoint, { method: "POST", body: JSON.stringify({ run_count: runCount }) }));
  return { settings: JSON.stringify(settings), estimate, text: formatEstimate(estimate) };
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
    if (lora) inputs.lora_name = lora.name;
    inputs.strength_model = lora?.strength ?? 0; inputs.strength_clip = lora?.strength ?? 0;
  });
  const sampler = roles.IDENTITY_LAB_SAMPLER[1].inputs ??= {};
  Object.assign(sampler, { seed: settings.seed ?? settings.seeds?.[0], steps: settings.steps, cfg: settings.cfg, sampler_name: settings.sampler, scheduler: settings.scheduler, denoise: settings.denoise });
  Object.assign(roles.IDENTITY_LAB_PIXEL_BUDGET[1].inputs ??= {}, { megapixels: settings.pixelBudget });
  Object.assign(roles.IDENTITY_LAB_SCORE[1].inputs ??= {}, { experiment_id: settings.experimentId, run_id: settings.runId, experiment_mode: settings.mode });
  return prompt;
}

function effectiveRunSettings(setup, plan = {}) {
  const refine = plan.refine ?? {};
  return { ...setup, ...refine, pixelBudget: refine.pixel_budget ?? refine.megapixels ?? setup.pixelBudget, checkpoint: plan.checkpoint ?? setup.checkpoint, seed: plan.seed ?? setup.seed, loras: plan.loras ?? setup.loras ?? [] };
}

async function responseJson(response) {
  const jsonResponse = typeof response.clone === "function" ? response.clone() : response;
  const data = await jsonResponse.json().catch(() => ({}));
  if (!response.ok) { const text = typeof response.text === "function" ? await response.text().catch(() => "") : ""; throw new Error(data.error || data.message || text || `request failed (${response.status})`); }
  return data;
}

async function submitOne({ fetchApi = api.fetchApi.bind(api), workflow, experimentId, run, settings }) {
  await responseJson(await fetchApi(`${LAB_ROOT}/runs/${run.id}/queued`, { method: "POST", body: JSON.stringify({ experiment_id: experimentId }) }));
  const prompt = patchPrompt(workflow, { ...effectiveRunSettings(settings, run.plan), experimentId, runId: run.id });
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
        const active = detail.runs.find((item) => ["queued", "running"].includes(item.state));
        if (active) {
          this.onUpdate({ ...detail, status: `waiting for queued or running run ${active.id}` });
          break;
        }
        const run = detail.runs.find((item) => item.state === "planned");
        if (!run) { this.onUpdate(detail); break; }
        const workflow = detail.experiment.settings.workflow_template;
        if (!workflow) throw new Error("experiment has no persisted workflow template");
        roleMap(workflow);
        const prompt = await submitOne({ fetchApi: this.fetchApi, workflow, experimentId, run, settings: detail.experiment.settings.setup ?? {} });
        const terminal = await this.waitForTerminal(experimentId, run.id, prompt.prompt_id);
        if (terminal?.state === "monitoring_timeout") { this.onUpdate({ status: "monitoring timed out; generation may still be running" }); break; }
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
      const historyEntry = history?.[promptId] ?? history;
      const historyStatus = String(historyEntry?.status?.status_str ?? historyEntry?.status ?? "").toLowerCase();
      if (["success", "error", "failed", "interrupted"].some((state) => historyStatus.includes(state))) {
        const error = historyStatus.includes("success") ? "prompt completed without DualIdentityScore result" : `prompt execution ${historyStatus}`;
        await this.recordFailure(experimentId, runId, error);
        return { ...run, state: "failed" };
      }
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
    }
    return { id: runId, state: "monitoring_timeout" };
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
  if (stage === "lora_single" && !loraMap.size) for (const lora of settings.loras ?? []) { const [name, strength] = Array.isArray(lora) ? lora : [lora.name, lora.strength]; if (name) loraMap.set(`${name}:${strength}`, [name, strength]); }
  const payload = { checkpoints, seeds, loras: [...loraMap.values()], stages: [stage] };
  if (!checkpoints.length || !seeds.length) throw new Error("selected candidates need checkpoint and seed values");
  if (stage === "focused_refine") payload.refine_settings = { steps: settings.steps, cfg: settings.cfg, denoise: settings.denoise, pixel_budget: megapixels(settings.pixelBudget), sampler: settings.sampler, scheduler: settings.scheduler };
  return payload;
}
function galleryMetadata(run, setup = {}) {
  const report = normalizeReport(run); const plan = run.plan ?? {}; const effective = effectiveRunSettings(setup, plan); const detection = report.detection;
  const loras = (plan.loras ?? []).map((item) => Array.isArray(item) ? `${item[0]} @ ${item[1]}` : `${item.name} @ ${item.strength}`).join(", ") || "no LoRA";
  return `active ${report.activeScore ?? "—"} • reference ${report.referenceScore ?? "—"} • base ${report.baseScore ?? "—"} • ${report.rankable ? "rankable" : "not rankable"} • detections base:${!!detection.base} reference:${!!detection.reference} generated:${!!detection.generated} • ${plan.checkpoint ?? "—"} • ${loras} • seed ${plan.seed ?? "—"} • steps ${effective.steps ?? "—"} cfg ${effective.cfg ?? "—"} ${effective.sampler ?? "—"}/${effective.scheduler ?? "—"} denoise ${effective.denoise ?? "—"} MP ${effective.pixelBudget ?? "—"} • runtime ${report.runtimeSeconds ?? "—"}`;
}
function filterAndSortResults(results, filters) {
  const filtered = results.filter((run) => {
    const plan = run.plan ?? {}; const loras = (plan.loras ?? []).map((item) => Array.isArray(item) ? item[0] : item.name).join(" ");
    return (!filters.stage || plan.stage === filters.stage) && (!filters.checkpoint || plan.checkpoint === filters.checkpoint) && (!filters.lora || loras.includes(filters.lora)) && (!filters.state || run.state === filters.state) && (!filters.favorite || run.favorite) && (!filters.rating || run.rating === Number(filters.rating));
  });
  const sorters = { active: (a, b) => activeScore(b) - activeScore(a), rating: (a, b) => (b.rating ?? 0) - (a.rating ?? 0), newest: (a, b) => String(b.completed_at ?? b.updated_at ?? "").localeCompare(String(a.completed_at ?? a.updated_at ?? "")) };
  const sorter = sorters[filters.sort] ?? sorters.active;
  return filtered.sort((a, b) => Number(normalizeReport(b).rankable) - Number(normalizeReport(a).rankable) || sorter(a, b));
}

function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function safeAction(status, operation) { return async (...args) => { try { return await operation(...args); } catch (error) { if (status) status.textContent = `Error: ${String(error.message || error)}`; } }; }
function statusSummary(detail) {
  const counts = (detail?.runs ?? []).reduce((all, run) => (all[run.state] = (all[run.state] ?? 0) + 1, all), {});
  return Object.entries(counts).map(([state, count]) => `${state}: ${count}`).join(" • ") || "No runs planned";
}
function selectFilter(label, values, onChange) {
  const control = el("select"); control.append(new Option(label, ""));
  for (const value of values) control.append(new Option(value, value));
  control.addEventListener("change", onChange); return control;
}
function renderGallery(container, detail, refresh, selected = new Set(), filters = {}, status) {
  const allRuns = detail.runs ?? []; const values = (key) => [...new Set(allRuns.map((run) => run.plan?.[key]).filter(Boolean))];
  const toolbar = el("div", undefined, "identity-lab-filters");
  const rerender = () => renderGallery(container, detail, refresh, selected, filters, status);
  const loraValues = [...new Set(allRuns.flatMap((run) => (run.plan?.loras ?? []).map((item) => Array.isArray(item) ? item[0] : item.name)).filter(Boolean))];
  [["stage", values("stage")], ["checkpoint", values("checkpoint")], ["lora", loraValues], ["state", [...new Set(allRuns.map((run) => run.state))]], ["rating", ["1", "2", "3", "4", "5"]]].forEach(([key, options]) => toolbar.append(selectFilter(key, options, (event) => { filters[key] = event.target.value; rerender(); })));
  const sort = selectFilter("sort: active score", ["active", "rating", "newest"], (event) => { filters.sort = event.target.value || "active"; rerender(); }); toolbar.append(sort);
  const favorite = el("label", " favorites only"); const favoriteInput = el("input"); favoriteInput.type = "checkbox"; favoriteInput.checked = !!filters.favorite; favoriteInput.addEventListener("change", (event) => { filters.favorite = event.target.checked; rerender(); }); favorite.prepend(favoriteInput); toolbar.append(favorite);
  const results = filterAndSortResults(allRuns, filters); container.replaceChildren(toolbar);
  for (const run of results) {
    const card = el("article", undefined, "identity-lab-card");
    if (run.state === "completed") { const image = el("img"); image.src = `${LAB_ROOT}/runs/${encodeURIComponent(run.id)}/output`; image.alt = `Result ${run.id}`; card.append(image); }
    const choose = el("input"); choose.type = "checkbox"; choose.setAttribute("aria-label", `Select run ${run.id} for promotion`); choose.checked = selected.has(run.id); choose.addEventListener("change", (event) => { event.target.checked ? selected.add(run.id) : selected.delete(run.id); }); card.append(choose);
    card.append(el("p", galleryMetadata(run, detail.experiment?.settings?.setup ?? {}))); if (run.state === "failed" && run.identity_report?.error) card.append(el("p", `Failure: ${run.identity_report.error}`));
    const controls = el("div", undefined, "identity-lab-card-controls");
    if (run.state === "completed") for (let rating = 1; rating <= 5; rating++) { const button = el("button", String(rating)); button.setAttribute("aria-label", `Rate run ${run.id} ${rating} stars`); button.addEventListener("click", safeAction(status, async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ rating }) })); refresh(); })); controls.append(button); }
    const favorite = el("button", run.favorite ? "★" : "☆"); favorite.setAttribute("aria-label", `${run.favorite ? "Remove favorite from" : "Favorite"} run ${run.id}`); favorite.addEventListener("click", safeAction(status, async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ favorite: !run.favorite }) })); refresh(); })); controls.append(favorite); card.append(controls); container.append(card);
    if (run.state === "completed") { const reject = el("button", "Reject (1)"); reject.setAttribute("aria-label", `Reject run ${run.id} with rating 1`); reject.addEventListener("click", safeAction(status, async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ rating: 1, favorite: false }) })); refresh(); })); const notes = el("textarea"); notes.value = run.notes ?? ""; notes.placeholder = "Local review notes"; notes.setAttribute("aria-label", `Review notes for run ${run.id}`); notes.addEventListener("change", safeAction(status, async () => { await responseJson(await api.fetchApi(`${LAB_ROOT}/runs/${run.id}/review`, { method: "PATCH", body: JSON.stringify({ notes: notes.value }) })); })); card.append(reject, notes); }
  }
}

function formValue(form, name) { return form.querySelector(`[name="${name}"]`)?.value; }
function renderPanel(container) {
  css(); container.replaceChildren(); const title = el("h2", "Identity Lab"); const status = el("p", "Load a workflow with stable Identity Lab roles."); status.setAttribute("aria-live", "polite"); const form = el("form", undefined, "identity-lab-setup");
  const labeled = (text, control) => { const label = el("label", text); label.append(control); return label; };
  const mode = el("select"); mode.name = "mode"; mode.append(new Option("Face swap", "face_swap"), new Option("Identity i2i", "identity_i2i")); form.append(labeled("Mode", mode));
  const sampler = el("select"); sampler.name = "sampler"; sampler.append(new Option("Euler", "euler"), new Option("Euler ancestral", "euler_ancestral"), new Option("DPM++ 2M", "dpmpp_2m")); const scheduler = el("select"); scheduler.name = "scheduler"; scheduler.append(new Option("Simple", "simple"), new Option("Karras", "karras"), new Option("Normal", "normal")); form.append(labeled("Sampler", sampler), labeled("Scheduler", scheduler));
  const fields = [["name", "Experiment name", "Identity sweep"], ["seeds", "Seeds", "1, 2, 3"], ["steps", "Steps", "28"], ["cfg", "Guidance / CFG", "3.5"], ["denoise", "Denoise", "0.8"], ["pixelBudget", "Pixel budget (MP; raw pixels accepted)", "1.048576"]];
  for (const [name, label, value] of fields) { const input = el("input"); input.name = name; input.value = value; input.placeholder = label; form.append(labeled(label, input)); }
  const catalogArea = el("fieldset"); catalogArea.append(el("legend", "Local Flux 9B catalog")); form.append(catalogArea); const launch = el("button", "Create & run one at a time"); launch.type = "submit"; launch.disabled = true; form.append(launch); const actions = el("section", undefined, "identity-lab-actions"); const gallery = el("section", undefined, "identity-lab-gallery"); container.append(title, status, form, actions, gallery);
  let liveCatalog = {};
  const selectedSetup = () => ({ mode: formValue(form, "mode"), checkpoints: [...form.querySelectorAll('input[name="checkpoint"]:checked')].map((input) => input.value), loras: [1, 2, 3].map((index) => ({ name: formValue(form, `lora-${index}`), strength: formValue(form, `lora-strength-${index}`) })).filter((lora) => lora.name), seeds: formValue(form, "seeds"), steps: formValue(form, "steps"), cfg: formValue(form, "cfg"), denoise: formValue(form, "denoise"), pixelBudget: formValue(form, "pixelBudget"), sampler: formValue(form, "sampler"), scheduler: formValue(form, "scheduler"), samplers: liveCatalog.samplers, schedulers: liveCatalog.schedulers });
  const hydrateSetup = (setup = {}) => { mode.value = setup.mode ?? mode.value; for (const name of ["seeds", "steps", "cfg", "denoise", "pixelBudget", "sampler", "scheduler"]) { const control = form.querySelector(`[name="${name}"]`); if (control && setup[name] !== undefined) control.value = Array.isArray(setup[name]) ? setup[name].join(", ") : String(setup[name]); } const checkpoints = new Set(setup.checkpoints ?? []); for (const control of form.querySelectorAll('input[name="checkpoint"]')) control.checked = checkpoints.has(control.value); for (let index = 1; index <= 3; index++) { const lora = setup.loras?.[index - 1]; const name = form.querySelector(`[name="lora-${index}"]`); const strength = form.querySelector(`[name="lora-strength-${index}"]`); if (name) name.value = lora?.name ?? ""; if (strength && lora?.strength !== undefined) strength.value = String(lora.strength); } };
  let freshEstimate = null, freshPromotion = null;
  const previewSetup = async () => { try { const setup = parseSetup(selectedSetup()); const count = setup.checkpoints.length * setup.seeds.length; freshEstimate = null; freshPromotion = null; status.textContent = "Refreshing local estimate…"; freshEstimate = await previewEstimate(api.fetchApi.bind(api), setup, count); status.textContent = freshEstimate.text; } catch (error) { freshEstimate = null; freshPromotion = null; status.textContent = `Setup: ${String(error.message || error)}`; } };
  form.addEventListener("input", previewSetup);
  const catalogPromise = api.fetchApi(`${LAB_ROOT}/catalog`).then(responseJson).then((catalog) => { liveCatalog = catalog; const replaceOptions = (control, values) => { if (!values?.length) return; control.replaceChildren(...values.map((value) => new Option(value, value))); }; replaceOptions(sampler, catalog.samplers); replaceOptions(scheduler, catalog.schedulers); const checkpoints = el("div", "Checkpoints"); for (const [index, name] of catalog.diffusion_models.entries()) { const label = el("label", name); const input = el("input"); input.type = "checkbox"; input.name = "checkpoint"; input.value = name; input.checked = index === 0; label.prepend(input); checkpoints.append(label); } const loras = el("div", "Up to three candidate LoRAs"); for (let index = 1; index <= 3; index++) { const select = el("select"); select.name = `lora-${index}`; select.append(new Option(`No LoRA ${index}`, "")); for (const name of catalog.loras) select.append(new Option(name, name)); const strength = el("input"); strength.name = `lora-strength-${index}`; strength.value = "0.7"; strength.inputMode = "decimal"; loras.append(labeled(`LoRA ${index}`, select), labeled(`LoRA ${index} strength`, strength)); } catalogArea.append(checkpoints, loras); launch.disabled = false; previewSetup(); return catalog; }).catch((error) => { status.textContent = `Catalog error: ${String(error.message || error)}`; throw error; });
  let queue; const selected = new Set(); const refresh = async (id) => { const detail = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}`)); status.textContent = statusSummary(detail); renderGallery(gallery, detail, () => refresh(id), selected, {}, status); return detail; };
  const updateQueue = (id, update) => { if (update.runs) renderGallery(gallery, update, () => refresh(id), selected, {}, status); if (update.error) status.textContent = `Error: ${update.error}`; else if (update.status) status.textContent = update.status; else if (update.runs) status.textContent = statusSummary(update); };
  const createQueue = (id) => new SerialQueue({ onUpdate: (update) => updateQueue(id, update) });
  const existing = el("select"); existing.name = "active-experiment"; existing.append(new Option("Load active experiment", "")); const archivedView = el("input"); archivedView.type = "checkbox"; archivedView.name = "include-archived"; const archivedLabel = el("label", " Include archived experiments"); archivedLabel.prepend(archivedView); form.prepend(archivedLabel, existing);
  const promotionRunCount = (payload) => {
    const loras = payload.loras.length; const multipliers = { lora_single: loras, lora_pair: loras * Math.max(0, loras - 1) / 2, lora_triple: loras * Math.max(0, loras - 1) * Math.max(0, loras - 2) / 6, focused_refine: 1 };
    return payload.checkpoints.length * payload.seeds.length * multipliers[payload.stages[0]];
  };
  const renderExperimentActions = (id, setup, state = "active") => {
    const pause = el("button", "Pause after current"); pause.addEventListener("click", () => queue?.pause());
    const resume = el("button", "Resume planned or confirmed-stale work"); resume.disabled = state !== "active"; resume.addEventListener("click", safeAction(status, () => queue?.resume(id)));
    const stage = el("select"); stage.append(new Option("LoRA singles", "lora_single"), new Option("LoRA pairs", "lora_pair"), new Option("LoRA triples", "lora_triple"), new Option("Focused refine", "focused_refine"));
    const previewPromotion = el("button", "Preview promotion"); const confirmPromotion = el("button", "Confirm promotion");
    previewPromotion.addEventListener("click", safeAction(status, async () => { const detail = await refresh(id); const refinement = parseSetup(selectedSetup()); const payload = buildPromotionPayload(detail.runs.filter((run) => selected.has(run.id)), stage.value, refinement); const estimate = await previewEstimate(api.fetchApi.bind(api), payload, promotionRunCount(payload), `${LAB_ROOT}/experiments/${id}/estimates`); freshPromotion = { payload, settings: JSON.stringify(refinement), estimate }; status.textContent = `Promotion preview: ${estimate.text}`; }));
    confirmPromotion.addEventListener("click", safeAction(status, async () => { if (!freshPromotion?.estimate.estimate.can_launch || freshPromotion.settings !== JSON.stringify(parseSetup(selectedSetup()))) throw new Error("preview a fresh, launchable promotion before confirming"); await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/promote`, { method: "POST", body: JSON.stringify(freshPromotion.payload) })); freshPromotion = null; await refresh(id); }));
    const archive = el("button", "Archive"); archive.disabled = state !== "active"; archive.addEventListener("click", safeAction(status, async () => { queue?.pause(); const detail = await refresh(id); if (detail.runs.some((run) => ["queued", "running"].includes(run.state))) { status.textContent = "Wait for current run, then archive."; return; } await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/archive`, { method: "POST", body: "{}" })); status.textContent = "Archived. Outputs retained."; renderExperimentActions(id, setup, "archived"); }));
    const preview = el("button", "Preview deletion"); const confirmation = el("input"); confirmation.placeholder = "Type exact DELETE confirmation"; const remove = el("button", "Delete archived experiment"); let deleteToken = "", expectedConfirmation = "";
    preview.addEventListener("click", safeAction(status, async () => { const value = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}/delete-preview`)); deleteToken = value.token; expectedConfirmation = value.confirmation; status.textContent = `Delete preview — DB rows: ${value.runs.join(", ") || "none"}; files: ${value.files.join(", ") || "none"}`; confirmation.placeholder = expectedConfirmation; }));
    remove.addEventListener("click", safeAction(status, async () => { if (!deleteToken || confirmation.value !== expectedConfirmation) { status.textContent = "Deletion confirmation must exactly match the preview."; return; } const value = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments/${id}`, { method: "DELETE", body: JSON.stringify({ token: deleteToken, confirmation: confirmation.value }) })); status.textContent = `Deleted ${value.runs.length} rows; recoverable trash: ${(value.recoverable_trash ?? []).join(", ") || "none"}`; gallery.replaceChildren(); }));
    actions.replaceChildren(pause, resume, stage, previewPromotion, confirmPromotion, archive, preview, confirmation, remove); if (state !== "active") { pause.disabled = true; previewPromotion.disabled = true; confirmPromotion.disabled = true; }
  };
  const activateExisting = async (id) => { if (!id) return; await catalogPromise; const detail = await refresh(id); if (!detail.experiment.settings.workflow_template) throw new Error("selected experiment has no persisted workflow template"); hydrateSetup(detail.experiment.settings.setup); queue = createQueue(id); renderExperimentActions(id, detail.experiment.settings.setup ?? {}, detail.experiment.state); status.textContent = `${statusSummary(detail)} • loaded persisted experiment`; };
  existing.addEventListener("change", async () => { try { await activateExisting(existing.value); } catch (error) { status.textContent = `Error: ${String(error.message || error)}`; } });
  const loadExperiments = async () => { try { const suffix = archivedView.checked ? "?archived=1" : ""; const { experiments } = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments${suffix}`)); existing.replaceChildren(new Option(archivedView.checked ? "Load experiment" : "Load active experiment", "")); for (const experiment of experiments) existing.append(new Option(`${experiment.name}${experiment.state === "archived" ? " (archived)" : ""}`, experiment.id)); } catch (error) { status.textContent = `Experiment list error: ${String(error.message || error)}`; } };
  archivedView.addEventListener("change", loadExperiments); loadExperiments();
  form.addEventListener("submit", async (event) => { event.preventDefault(); try {
    await catalogPromise; const graph = await app.graphToPrompt(); const workflow = graph.output ?? graph.prompt ?? graph; roleMap(workflow); const settings = parseSetup(selectedSetup()); const count = settings.checkpoints.length * settings.seeds.length;
    if (!freshEstimate || freshEstimate.settings !== JSON.stringify(settings) || freshEstimate.estimate.run_count !== count || !freshEstimate.estimate.can_launch) throw new Error("wait for a fresh launchable backend estimate");
    status.textContent = freshEstimate.text; const created = await responseJson(await api.fetchApi(`${LAB_ROOT}/experiments`, { method: "POST", body: JSON.stringify({ name: formValue(form, "name"), mode: settings.mode, checkpoints: settings.checkpoints, seeds: settings.seeds, loras: settings.loras.map((l) => [l.name, l.strength]), stages: ["baseline"], settings: { setup: settings }, workflow }) }));
    const id = created.experiment.id; renderExperimentActions(id, settings);
    queue = createQueue(id); await refresh(id); await queue.run(id);
  } catch (error) { status.textContent = `Error: ${String(error.message || error)}`; } });
}

css();
app.registerExtension({ name: "arch.identity-lab", setup() { css(); } });
app.extensionManager.registerSidebarTab({ id: "arch.identity-lab", icon: "pi pi-flask", title: "Identity Lab", type: "custom", render: renderPanel });

const seam = { parseSetup, estimatePreview, patchPrompt, effectiveRunSettings, submitOne, normalizeReport, buildPromotionPayload, filterAndSortResults, galleryMetadata, SerialQueue, renderPanel };
globalThis.__identityLab = seam;
export { parseSetup, estimatePreview, patchPrompt, effectiveRunSettings, normalizeReport, buildPromotionPayload, submitOne, filterAndSortResults, galleryMetadata, SerialQueue };
