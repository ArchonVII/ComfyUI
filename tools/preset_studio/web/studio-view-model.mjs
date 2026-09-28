export const DESTINATIONS = Object.freeze([
  Object.freeze({id: 'compose', label: 'Compose'}),
  Object.freeze({id: 'builder', label: 'Builder'}),
  Object.freeze({id: 'characters', label: 'Characters'}),
  Object.freeze({id: 'workflows', label: 'Workflows'}),
  Object.freeze({id: 'results', label: 'Results'}),
  Object.freeze({id: 'settings', label: 'Settings'}),
]);
export const CHARACTER_VIEWS = Object.freeze([
  Object.freeze({id: 'overview', label: 'Overview'}),
  Object.freeze({id: 'images', label: 'Images'}),
  Object.freeze({id: 'families', label: 'Families'}),
  Object.freeze({id: 'sources', label: 'Sources'}),
  Object.freeze({id: 'find', label: 'Find New Pics'}),
  Object.freeze({id: 'review', label: 'Review'}),
]);

const DESTINATION_IDS = new Set(DESTINATIONS.map(({id}) => id));
const CHARACTER_VIEW_IDS = new Set(CHARACTER_VIEWS.map(({id}) => id));
const EMPTY_CATALOG = Object.freeze({
  presets: Object.freeze([]),
  workflows: Object.freeze([]),
  references: Object.freeze({}),
  runs: Object.freeze([]),
  characters: Object.freeze([]),
  comfy_url: '',
});

function catalogSnapshot(value = {}) {
  return Object.freeze({
    presets: Object.freeze([...(value.presets ?? [])]),
    workflows: Object.freeze([...(value.workflows ?? [])]),
    references: Object.freeze({...value.references}),
    runs: Object.freeze([...(value.runs ?? [])]),
    characters: Object.freeze([...(value.characters ?? [])]),
    comfy_url: String(value.comfy_url ?? ''),
  });
}

function stateSnapshot(value) {
  return Object.freeze({
    activeDestination: value.activeDestination,
    selectedPresetIds: Object.freeze([...value.selectedPresetIds]),
    selectedCharacterId: value.selectedCharacterId,
    activeCharacterView: value.activeCharacterView,
    catalog: value.catalog,
  });
}

export function createReviewQueueViewModel() {
  let activeJobId = null;
  const selection = new Map();

  const pendingItem = item => item?.decision === 'pending';
  return Object.freeze({
    hydrate(jobId, items) {
      if (typeof jobId !== 'string' || !jobId) throw new TypeError('Review job ID required');
      if (!Array.isArray(items)) throw new TypeError('Review items must be an array');
      if (jobId !== activeJobId) {
        activeJobId = jobId;
        selection.clear();
      }
      for (const item of items) {
        if (!item?.id) continue;
        if (!pendingItem(item)) selection.delete(item.id);
        else if (!selection.has(item.id)) selection.set(item.id, true);
      }
    },
    isSelected(reviewId) {
      return selection.get(reviewId) === true;
    },
    setSelected(reviewId, selected) {
      if (!selection.has(reviewId)) return;
      selection.set(reviewId, Boolean(selected));
    },
    selectVisible(items, selected) {
      if (!Array.isArray(items)) throw new TypeError('Review items must be an array');
      for (const item of items) {
        if (pendingItem(item) && selection.has(item.id)) {
          selection.set(item.id, Boolean(selected));
        }
      }
    },
    forget(reviewIds) {
      for (const reviewId of reviewIds) selection.delete(reviewId);
    },
    clear() {
      selection.clear();
    },
    selectedIds() {
      return [...selection].filter(([, selected]) => selected).map(([id]) => id);
    },
  });
}

export function createScopedSelectionViewModel() {
  let activeScope = null;
  const available = new Set();
  const selected = new Set();
  return Object.freeze({
    hydrate(scope, ids) {
      if (typeof scope !== 'string' || !scope) throw new TypeError('Selection scope required');
      if (!Array.isArray(ids)) throw new TypeError('Selection IDs must be an array');
      if (scope !== activeScope) {
        activeScope = scope;
        selected.clear();
        available.clear();
      }
      for (const id of ids) if (typeof id === 'string' && id) available.add(id);
    },
    isSelected(id) {
      return selected.has(id);
    },
    setSelected(id, value) {
      if (!available.has(id)) return;
      if (value) selected.add(id);
      else selected.delete(id);
    },
    selectVisible(ids, value) {
      for (const id of ids) {
        if (!available.has(id)) continue;
        if (value) selected.add(id);
        else selected.delete(id);
      }
    },
    selectedIds() {
      return [...selected];
    },
  });
}

export function createStudioViewModel(initial = {}) {
  const listeners = new Set();
  let state = stateSnapshot({
    activeDestination: 'compose',
    selectedPresetIds: initial.selectedPresetIds ?? [],
    selectedCharacterId: null,
    activeCharacterView: 'overview',
    catalog: EMPTY_CATALOG,
  });

  const publish = next => {
    state = stateSnapshot(next);
    for (const listener of listeners) listener(state);
  };

  return Object.freeze({
    get snapshot() {
      return state;
    },
    subscribe(listener) {
      if (typeof listener !== 'function') throw new TypeError('ViewModel listener must be a function');
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    navigate(destination) {
      if (!DESTINATION_IDS.has(destination)) {
        throw new Error(`Unknown Preset Studio destination: ${destination}`);
      }
      if (destination === state.activeDestination) return;
      publish({...state, activeDestination: destination});
    },
    hydrate(value) {
      const catalog = catalogSnapshot(value);
      const available = new Set(catalog.presets.map(({id}) => id));
      const availableCharacters = new Set(catalog.characters.map(({id}) => id));
      publish({
        ...state,
        catalog,
        selectedPresetIds: state.selectedPresetIds.filter(id => available.has(id)),
        selectedCharacterId: availableCharacters.has(state.selectedCharacterId)
          ? state.selectedCharacterId
          : null,
      });
    },
    selectCharacter(characterId) {
      if (!state.catalog.characters.some(({id}) => id === characterId)) {
        throw new Error('Unknown character: ' + characterId);
      }
      publish({...state, selectedCharacterId: characterId, activeCharacterView: 'overview'});
    },
    showCharacterView(view) {
      if (!CHARACTER_VIEW_IDS.has(view)) {
        throw new Error('Unknown character view: ' + view);
      }
      publish({...state, activeCharacterView: view});
    },
  });
}
