// Resolve text locally from ComfyUI's flattened API graph. Never queue a job or
// invent text for a node that requires execution.
export function buildCombinedPromptPreview(graph) {
  const isLink = value => Array.isArray(value) && value.length === 2;
  const resolve = (value, seen = new Set()) => {
    if (!isLink(value)) return value ?? "";
    const [id, slot] = value;
    const key = `${id}:${slot}`;
    if (seen.has(key)) throw new Error("A prompt connection contains a cycle.");
    const next = new Set(seen); next.add(key);
    const node = graph[id];
    if (!node) throw new Error("A prompt source is disconnected or disabled.");
    const inputs = node.inputs || {};
    if (["PrimitiveString", "PrimitiveStringMultiline", "PrimitiveBoolean", "PrimitiveInt"].includes(node.class_type) && slot === 0)
      return resolve(inputs.value, next);
    if (node.class_type === "RandomReferenceImageSource" && slot === 5) {
      const prefix = String(resolve(inputs.favorite_prompt, next)).trim().replace(/[ ,]+$/, "");
      const incoming = String(resolve(inputs.prompt, next)).trim().replace(/^[ ,]+/, "");
      return [prefix, incoming].filter(Boolean).join(", ");
    }
    if (node.class_type === "ComfySwitchNode" && slot === 0) {
      const enabled = resolve(inputs.switch, next);
      if (typeof enabled !== "boolean") throw new Error("A switch value is unavailable before execution.");
      return resolve(inputs[enabled ? "on_true" : "on_false"], next);
    }
    if (node.class_type === "ReferencePromptCompose" && slot === 0) return compose(inputs, next).text;
    throw new Error(`${node._meta?.title || node.class_type} requires execution; its text cannot be previewed yet.`);
  };
  const compose = (inputs, seen) => {
    const contributions = [{label: "Edit instruction", enabled: true, text: String(resolve(inputs.text, seen)).trim()}];
    for (const [lane, label] of [["main", "Main reference"], ["identity", "Identity reference"],
      ["aux1", "Auxiliary 1"], ["aux2", "Auxiliary 2"], ["aux3", "Auxiliary 3"]]) {
      const enabled = lane === "main" ? true : resolve(inputs[`use_${lane}`], seen);
      if (typeof enabled !== "boolean") throw new Error(`${label} switch is unavailable before execution.`);
      const source = isLink(inputs[lane]) ? graph[inputs[lane][0]] : null;
      contributions.push({label: source?._meta?.title || label, enabled,
        text: enabled ? String(resolve(inputs[lane], seen)).trim() : ""});
    }
    return {contributions, text: contributions.filter(part => part.enabled && part.text).map(part => part.text).join("\n\n")};
  };
  return Object.entries(graph).filter(([, node]) => node.class_type === "ReferencePromptCompose").map(([id, node]) => {
    const title = `${node._meta?.title || "Combined prompt"} · #${id}`;
    try { return {id, title, ...compose(node.inputs || {}, new Set([`${id}:0`]))}; }
    catch (error) { return {id, title, error: error.message}; }
  });
}
