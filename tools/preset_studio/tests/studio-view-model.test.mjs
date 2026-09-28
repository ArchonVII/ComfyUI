import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';

const moduleURL = new URL('../web/studio-view-model.mjs', import.meta.url);

async function subject() {
  assert.ok(existsSync(moduleURL), 'The Preset Studio application ViewModel is not implemented');
  return import(moduleURL);
}

test('application shell exposes the approved full destinations', async () => {
  const {DESTINATIONS, createStudioViewModel} = await subject();
  assert.deepEqual(DESTINATIONS.map(({id, label}) => [id, label]), [
    ['compose', 'Compose'],
    ['builder', 'Builder'],
    ['characters', 'Characters'],
    ['workflows', 'Workflows'],
    ['results', 'Results'],
    ['settings', 'Settings'],
  ]);
  assert.equal(createStudioViewModel().snapshot.activeDestination, 'compose');
});

test('navigation publishes immutable snapshots and rejects unknown destinations', async () => {
  const {createStudioViewModel} = await subject();
  const viewModel = createStudioViewModel();
  const initial = viewModel.snapshot;
  const published = [];
  const unsubscribe = viewModel.subscribe(snapshot => published.push(snapshot));

  viewModel.navigate('characters');

  assert.equal(initial.activeDestination, 'compose');
  assert.equal(viewModel.snapshot.activeDestination, 'characters');
  assert.notEqual(viewModel.snapshot, initial);
  assert.deepEqual(published.map(snapshot => snapshot.activeDestination), ['characters']);
  assert.throws(() => viewModel.navigate('unknown'), /Unknown Preset Studio destination/);

  unsubscribe();
  viewModel.navigate('results');
  assert.equal(published.length, 1);
});

test('hydration keeps only selections that exist in authoritative state', async () => {
  const {createStudioViewModel} = await subject();
  const viewModel = createStudioViewModel({selectedPresetIds: ['kept', 'missing']});

  viewModel.hydrate({
    presets: [{id: 'kept', kind: 'character', name: 'Kept'}],
    workflows: [],
    references: {},
    runs: [],
    comfy_url: 'http://127.0.0.1:8188',
  });

  assert.deepEqual(viewModel.snapshot.selectedPresetIds, ['kept']);
  assert.equal(viewModel.snapshot.catalog.presets[0].name, 'Kept');
});

test('character selection and workspace tabs are validated by the ViewModel', async () => {
  const {CHARACTER_VIEWS, createStudioViewModel} = await subject();
  const viewModel = createStudioViewModel();
  viewModel.hydrate({
    presets: [],
    workflows: [],
    references: {},
    runs: [],
    characters: [{id: 'alice', name: 'Alice'}],
  });

  viewModel.selectCharacter('alice');
  viewModel.showCharacterView('images');

  assert.deepEqual(CHARACTER_VIEWS.map(({id}) => id), ['overview', 'images', 'families', 'sources', 'find', 'review']);
  assert.equal(viewModel.snapshot.selectedCharacterId, 'alice');
  assert.equal(viewModel.snapshot.activeCharacterView, 'images');
  assert.throws(() => viewModel.selectCharacter('missing'), /Unknown character/);
  assert.throws(() => viewModel.showCharacterView('unknown'), /Unknown character view/);
});

test('review selection survives polling and defaults newly discovered matches on', async () => {
  const {createReviewQueueViewModel} = await subject();
  const review = createReviewQueueViewModel();

  review.hydrate('job-a', [
    {id: 'one', decision: 'pending'},
    {id: 'two', decision: 'pending'},
  ]);
  review.setSelected('one', false);
  review.hydrate('job-a', [
    {id: 'one', decision: 'pending'},
    {id: 'two', decision: 'pending'},
    {id: 'three', decision: 'pending'},
  ]);

  assert.deepEqual(review.selectedIds(), ['two', 'three']);
  assert.equal(review.isSelected('one'), false);
  assert.equal(review.isSelected('three'), true);

  review.hydrate('job-a', [
    {id: 'one', decision: 'pending'},
    {id: 'two', decision: 'accepted'},
    {id: 'three', decision: 'pending'},
  ]);
  assert.deepEqual(review.selectedIds(), ['three']);
});

test('review bulk selection changes only the visible pending matches', async () => {
  const {createReviewQueueViewModel} = await subject();
  const review = createReviewQueueViewModel();
  const firstPage = [
    {id: 'one', decision: 'pending'},
    {id: 'accepted', decision: 'accepted'},
  ];
  review.hydrate('job-a', [...firstPage, {id: 'off-page', decision: 'pending'}]);

  review.selectVisible(firstPage, false);
  assert.deepEqual(review.selectedIds(), ['off-page']);
  review.selectVisible(firstPage, true);
  assert.deepEqual(review.selectedIds(), ['one', 'off-page']);
  review.forget(['one']);
  assert.deepEqual(review.selectedIds(), ['off-page']);
  review.clear();
  assert.deepEqual(review.selectedIds(), []);

  review.hydrate('job-b', [{id: 'fresh', decision: 'pending'}]);
  assert.deepEqual(review.selectedIds(), ['fresh']);
});

test('scoped image selection survives pagination and resets for another character', async () => {
  const {createScopedSelectionViewModel} = await subject();
  const selection = createScopedSelectionViewModel();

  selection.hydrate('alice', ['one', 'two']);
  selection.setSelected('one', true);
  selection.hydrate('alice', ['one', 'two', 'three']);
  selection.setSelected('three', true);
  assert.deepEqual(selection.selectedIds(), ['one', 'three']);

  selection.selectVisible(['two', 'three'], false);
  assert.deepEqual(selection.selectedIds(), ['one']);
  selection.hydrate('bob', ['different']);
  assert.deepEqual(selection.selectedIds(), []);
});
