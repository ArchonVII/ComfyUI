// A character group consumes one workflow slot even when it produces many runs.
export function referenceRequest(presets, choices, batch) {
  const result = {reference_ids: []};
  for (const preset of presets) {
    const isBatch = batch?.preset_id === preset.id && preset.kind === 'character';
    const source = isBatch ? batch.image_ids : (choices[preset.id] || []);
    const images = [...new Set(source.filter(id => preset.references.includes(id)))];
    if (isBatch) {
      result.reference_batch = {preset_id: preset.id, image_ids: images, slot: result.reference_ids.length};
    }
    result.reference_ids.push(...(preset.kind === 'character' ? images.slice(0, 1) : images));
  }
  return result;
}

export function choicesFromReferences(presets, references) {
  return Object.fromEntries(presets.map(p => [p.id, references.filter(id => p.references.includes(id))]));
}
