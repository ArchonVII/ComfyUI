import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "web" / "reference_browser.js"


def test_browser_scroll_selection_target_and_stale_responses():
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.events = {}; this.style = {}; this.attributes = {}; this.dataset = {};
    this.className = ''; this.value = ''; this.textContent = ''; this.scrollTop = 0;
    this.classList = {
      contains: name => this.className.split(' ').includes(name),
      add: name => { if (!this.classList.contains(name)) this.className += ' ' + name; },
      remove: name => { this.className = this.className.split(' ').filter(n => n !== name).join(' '); },
      toggle: (name, on) => on ? this.classList.add(name) : this.classList.remove(name),
    };
  }
  append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
  replaceChildren(...items) { for (const item of this.children) item.parent = null; this.children = []; this.append(...items); }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  setAttribute(name, value) { this.attributes[name] = value; }
  fire(name) { for (const fn of this.events[name] || []) fn({stopPropagation() {}}); this['on' + name]?.(); }
  showModal() { this.open = true; }
  close() { this.open = false; this.fire('close'); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); this.parent = null; }
  get childElementCount() { return this.children.length; }
  get isConnected() { return this === body || this === head || Boolean(this.parent?.isConnected); }
}
const body = new Element('body'), head = new Element('head');
function all(root) { return [root, ...root.children.flatMap(all)]; }
function byClass(root, name) { return all(root).find(n => n.classList.contains(name)); }
function byText(root, text) { return all(root).find(n => n.textContent === text); }
function byAria(root, label) { return all(root).find(n => n.attributes['aria-label'] === label); }
const document = { body, head, createElement: tag => new Element(tag),
  getElementById: id => [...all(body), ...all(head)].find(n => n.id === id) };
const context = {document, console, setTimeout, clearTimeout, window: {confirm: () => true}};
vm.runInNewContext(fs.readFileSync(SCRIPT, 'utf8').replace(/^export /gm, ''), context);
assert.equal(context.imagePaths('"C:/last, first.png"\nC:/plain.png')[0], 'C:/last, first.png');
const nodes = [1, 2].map(id => ({id, title: 'Source ' + id, widgets: []}));
const payload = {source_mode: 'folder', folder: 'C:/fixtures', selected_images: '', favorite: 'None',
  selection_policy: 'random_each_queue', seed: 1, include_subfolders: false};
const drafts = {1: {text:'', name:'', favorite:'None', saved:false, modified:false, baseline:''},
                2: {text:'', name:'', favorite:'None', saved:false, modified:false, baseline:''}};
let sidebar, selected, requests = [], pending = [], folderCalls = [], dialogCalls = [], dialogResult = {};
let delayed = false;
let saveCalls = [], saveError = false, combinedText = 'instruction\n\nmain prompt';
const page = (id, offset, count) => ({pool_size: 27, filtered_size: 27, has_more: offset === 0,
  images: Array.from({length: count}, (_, i) => ({path: `C:/${id}/${offset+i}.png`, name: `${id}-${offset+i}.png`, thumbnail_data_url: 'data:image/png;base64,fixture'}))});
context.installReferenceBrowser({extensionManager: {registerSidebarTab: tab => sidebar = tab}}, {
  nodes: () => nodes, payload: () => ({...payload}), presets: async () => ({'Portraits': {kind:'folder', folder:'C:/portraits'}}),
  preview: (node, options) => {
    requests.push([node.id, options]);
    if (delayed) return new Promise(resolve => pending.push({id: node.id, options, resolve}));
    return Promise.resolve(page(node.id, options.offset || 0, options.offset ? 3 : 24));
  },
  selectImages: (node, paths) => { selected = {id:node.id, paths}; },
  selectFolder: (node, path) => folderCalls.push([node.id, path]),
  promptState: node => drafts[node.id],
  setPromptName: (node, name) => { drafts[node.id].name = name; },
  revertPrompt: node => { drafts[node.id].text = drafts[node.id].baseline; drafts[node.id].modified = false; },
  setField: (node, name, value) => { if (name === 'favorite_prompt') { drafts[node.id].text = value; drafts[node.id].modified = value !== drafts[node.id].baseline; } },
  favorite() {},
  save: async (node, name, mode) => {
    saveCalls.push([node.id, name, mode]);
    if (saveError) throw new Error('Cannot save favorite');
    const draft = drafts[node.id]; draft.favorite = name; draft.saved = true;
    draft.baseline = draft.text; draft.modified = false;
  },
  combinedPreview: async () => [{id:'65',title:'Combined prompt',text:combinedText,
    contributions:[{label:'Main reference',enabled:true,text:'main prompt'},{label:'Auxiliary 1',enabled:false,text:''}]}],
  delete() {},
  dialog: async (...args) => { dialogCalls.push(args); return dialogResult; },
});
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  assert.equal(sidebar.title, 'Reference Favorites');
  context.openReferenceBrowser(nodes[0]); await tick();
  let dialog = body.children[0], grid = byClass(dialog, 'rr-grid'), scroll = byClass(dialog, 'rr-scroll');
  assert.equal(grid.children.length, 24);
  byText(dialog, 'Folder').fire('click'); await tick();
  assert.equal(dialogCalls[0][0], 'browse-folder');
  assert.equal(folderCalls.length, 0, 'cancel must preserve the existing source');
  dialogResult = {path: 'C:/chosen'};
  byText(dialog, 'Folder').fire('click'); await tick();
  assert.deepEqual(folderCalls[0], [1, 'C:/chosen']);
  dialogResult = {};
  byText(dialog, 'Selected images').fire('click'); await tick();
  assert.equal(dialogCalls.at(-1)[0], 'pick-images');
  assert.equal(selected, undefined, 'cancel image picker must keep the current source');
  scroll.scrollHeight = 1000; scroll.clientHeight = 500; scroll.scrollTop = 600; scroll.fire('scroll'); await tick();
  assert.equal(grid.children.length, 27);
  assert.equal(requests.at(-1)[1].offset, 24);
  const requestCount = requests.length;
  payload.seed = 123;
  context.refreshReferenceBrowser(nodes[0]); await tick();
  assert.equal(scroll.scrollTop, 600, 'seed changes must preserve gallery position');
  assert.equal(grid.children.length, 27);
  assert.equal(requests.length, requestCount, 'seed changes do not reload the pool');
  assert.ok(byText(dialog, 'Prompt output is disconnected. Connect prompt_with_favorite to the prompt chain to use this text. Drafts are preserved when switching sources; save the workflow to keep them across reloads.'));
  const check = all(grid.children[0]).find(n => n.type === 'checkbox');
  check.checked = true; check.fire('change');
  byText(dialog, 'Use 1 checked image').fire('click');
  assert.equal(selected.id, 1); assert.equal(selected.paths[0], 'C:/1/0.png');
  drafts[1] = {text:'saved text',name:'',favorite:'Portraits',saved:true,modified:false,baseline:'saved text'};
  context.refreshReferencePrompt(nodes[0]);
  const promptEditor = byAria(dialog, 'Reference prompt text');
  promptEditor.value = 'edited text'; promptEditor.fire('input');
  const newName = byAria(dialog, 'New favorite name'); newName.value = 'Separate favorite'; newName.fire('input');
  promptEditor.value = 'more edits'; promptEditor.fire('input');
  assert.equal(newName.value, 'Separate favorite', 'typing text preserves the proposed name');
  assert.equal(byText(dialog, 'Save changes').disabled, false);
  byText(dialog, 'Save changes').fire('click'); await tick();
  assert.deepEqual(saveCalls.at(-1), [1, 'Portraits', 'update'], 'Save changes never targets the new-name field');
  assert.equal(byText(dialog, 'Save changes').disabled, true);
  saveError = true;
  byText(dialog, 'Save as new').fire('click'); await tick();
  assert.deepEqual(saveCalls.at(-1), [1, 'Separate favorite', 'create']);
  assert.equal(promptEditor.value, 'more edits');
  assert.equal(newName.value, 'Separate favorite');
  assert.ok(byText(dialog, 'Cannot save favorite'));
  promptEditor.value = 'discard this'; promptEditor.fire('input');
  byText(dialog, 'Revert').fire('click');
  assert.equal(promptEditor.value, 'more edits');
  await new Promise(resolve => setTimeout(resolve, 240));
  assert.equal(byAria(dialog, 'Combined prompt 65').value, combinedText);
  assert.ok(byText(dialog, 'Off'));
  combinedText = 'instruction changed'; context.refreshReferencePrompt(nodes[0]);
  await new Promise(resolve => setTimeout(resolve, 240));
  assert.equal(byAria(dialog, 'Combined prompt 65').value, combinedText);
  dialog.close(); assert.equal(body.children.length, 0);

  delayed = true; requests = []; pending = [];
  context.openReferenceBrowser(nodes[0]); await tick();
  dialog = body.children[0];
  byAria(dialog, 'New favorite name').value = 'Node one draft name';
  byAria(dialog, 'New favorite name').fire('input');
  const editor = byAria(dialog, 'Reference prompt text');
  editor.value = 'unsaved prompt'; editor.fire('input');
  assert.equal(byAria(dialog, 'New favorite name').value, 'Node one draft name');
  byAria(dialog, 'Search image filenames').value = 'old search';
  const target = byAria(dialog, 'Target reference node'); target.value = '2'; target.fire('change'); await tick();
  assert.equal(byAria(dialog, 'New favorite name').value, '');
  assert.equal(byAria(dialog, 'Reference prompt text').value, '');
  assert.equal(drafts[1].text, 'unsaved prompt');
  assert.equal(byAria(dialog, 'Search image filenames').value, '');
  assert.equal(pending.length, 2);
  pending[1].resolve(page(2, 0, 1)); await tick();
  pending[0].resolve(page(1, 0, 24)); await tick();
  grid = byClass(dialog, 'rr-grid');
  assert.equal(grid.children.length, 1);
  assert.equal(all(grid).find(n => n.tag === 'img').alt, '2-0.png');
  assert.ok(byClass(dialog, 'rr-status').textContent.includes('Source 2'));
  dialog.close();
  const style = head.children[0].textContent;
  assert.match(style, /\.rr-scroll\{[^}]*min-height:0;overflow-y:auto/);
  assert.match(style, /\[hidden\][^{]*\{display:none!important\}/);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace("SCRIPT", json.dumps(str(SCRIPT)))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
