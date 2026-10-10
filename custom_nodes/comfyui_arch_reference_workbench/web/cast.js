import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const roles = ["subject", "clothing", "environment", "style"];
const widget = (node, name) => node.widgets?.find(value => value.name === name);

function readLocks(node) {
  try {
    const value = JSON.parse(widget(node, "locked_paths")?.value || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function writeLocks(node, locks) {
  const state = widget(node, "locked_paths");
  if (!state) return;
  state.value = JSON.stringify(locks);
  node.graph?.change?.();
  node.setDirtyCanvas?.(true, true);
}

function refreshFavorites(node, {presets = {}, renamedFrom, name}) {
  const values = ["None", ...Object.keys(presets).filter(value => value !== "None").sort()];
  for (const role of roles) {
    const control = widget(node, `${role}_favorite`);
    if (!control) continue;
    control.options ||= {};
    control.options.values = values;
    const next = control.value === renamedFrom && presets[name] ? name
      : values.includes(control.value) ? control.value : "None";
    if (next !== control.value) {
      control.value = next;
      control.callback?.();
      if (node.properties?.archReferenceCastLastUsed) delete node.properties.archReferenceCastLastUsed[role];
    }
  }
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "arch.ReferenceCast",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "ArchReferenceCast") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      const state = widget(this, "locked_paths");
      if (state) {
        state.hidden = true;
        state.type = "hidden";
        state.computeSize = () => [0, -4];
        state.draw = () => {};
        if (state.inputEl) state.inputEl.style.display = "none";
        if (state.element) state.element.hidden = true;
        // Preserve serialization: workflow and API requests carry the paths.
      }
      for (const role of roles) {
        for (const field of ["favorite", "locked"]) {
          const control = widget(this, `${role}_${field}`);
          if (!control) continue;
          const callback = control.callback;
          const node = this;
          control.callback = function () {
            const result = callback?.apply(this, arguments);
            const locks = readLocks(node);
            if (field === "favorite" && locks[role]?.favorite !== control.value ||
                field === "locked" && !control.value) {
              delete locks[role];
              writeLocks(node, locks);
            }
            if (field === "locked" && control.value) {
              const seen = node.properties?.archReferenceCastLastUsed?.[role];
              if (seen?.selected_file && seen.favorite === widget(node, `${role}_favorite`)?.value) {
                locks[role] = {favorite: seen.favorite, selected_file: seen.selected_file};
                writeLocks(node, locks);
              }
            }
            return result;
          };
        }
      }
      let revision = 0;
      const changed = event => {
        revision++;
        refreshFavorites(this, event.detail);
      };
      this._archCastPresetsChanged = changed;
      globalThis.addEventListener?.("arch-reference-presets-changed", changed);
      const initialRevision = revision;
      // Reopening a saved workflow must get groups created since page load.
      if (typeof api !== "undefined" && api.fetchApi) {
        api.fetchApi("/arch-random-reference/presets").then(async response => {
          if (!response.ok) return;
          const data = await response.json();
          if (revision === initialRevision && this._archCastPresetsChanged === changed) refreshFavorites(this, data);
        }).catch(() => {});
      }
      return result;
    };
    const removed = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      globalThis.removeEventListener?.("arch-reference-presets-changed", this._archCastPresetsChanged);
      delete this._archCastPresetsChanged;
      return removed?.apply(this, arguments);
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = executed?.apply(this, arguments);
      const lanes = message?.arch_reference_cast?.[0]?.lanes;
      if (!lanes) return result;
      const locks = readLocks(this);
      this.properties ||= {};
      this.properties.archReferenceCastLastUsed ||= {};
      for (const role of roles) {
        const lane = lanes[role];
        // Ignore old queued results after changing the group or unlocking.
        if (lane?.enabled && lane.selected_file &&
            Boolean(widget(this, `${role}_locked`)?.value) === Boolean(lane.locked) &&
            widget(this, `${role}_favorite`)?.value === lane.favorite) {
          const selected = {favorite: lane.favorite, selected_file: lane.selected_file};
          this.properties.archReferenceCastLastUsed[role] = selected;
          if (lane.locked) locks[role] = selected;
        }
      }
      writeLocks(this, locks);
      return result;
    };
  },
});
