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
const context = {document, console, setTimeout, clearTimeout, URLSearchParams, window: {confirm: () => true}};
vm.runInNewContext(fs.readFileSync(SCRIPT, 'utf8').replace(/^export /gm, ''), context);
assert.equal(context.imagePaths('"C:/last, first.png"\nC:/plain.png')[0], 'C:/last, first.png');
const nodes = [1, 2].map(id => ({id, title: 'Source ' + id, widgets: []}));
const payload = {source_mode: 'folder', folder: 'C:/fixtures', selected_images: '', favorite: 'None',
  selection_policy: 'random_each_queue', seed: 1, include_subfolders: false};
const drafts = {1: {text:'', name:'', favorite:'None', saved:false, modified:false, baseline:''},
                2: {text:'', name:'', favorite:'None', saved:false, modified:false, baseline:''}};
let sidebar, selected, requests = [], pending = [], folderCalls = [], dialogCalls = [], dialogResult = {};
let delayed = false;
let saveCalls = [], libraryCalls = [], savedGroupPaths, saveError = false, combinedText = 'instruction\n\nmain prompt';
let librarySelection, openedCollection;
let profileWait = null, sourceWait = null;
const page = (id, offset, count) => ({pool_size: 27, filtered_size: 27, has_more: offset === 0,
  selection_paths: payload.source_mode === 'selection' ? Array.from({length:27}, (_,i)=>`C:/${id}/${i}.png`) : [],
  images: Array.from({length: count}, (_, i) => ({path: `C:/${id}/${offset+i}.png`, name: `${id}-${offset+i}.png`, thumbnail_data_url: 'data:image/png;base64,fixture'}))});
context.installReferenceBrowser({extensionManager: {registerSidebarTab: tab => sidebar = tab}}, {
  nodes: () => nodes, payload: () => ({...payload}), presets: async () => ({'Portraits': {kind:'folder', folder:'C:/portraits'}}),
  encodePaths: paths => paths.map(path => '"' + path.replaceAll('"', '""') + '"').join('\n'),
  preview: (node, options) => {
    requests.push([node.id, options]);
    if(options.paths_only) return Promise.resolve({paths:Array.from({length:27},(_,i)=>`C:/${node.id}/${i}.png`)});
    if (delayed) return new Promise(resolve => pending.push({id: node.id, options, resolve}));
    return Promise.resolve(page(node.id, options.offset || 0, options.offset ? 3 : 24));
  },
  selectImages: (node, paths) => { selected = {id:node.id, paths}; },
  library: async (path, body) => {
    libraryCalls.push([path,body]);
    if(path.startsWith('/bootstrap?collection_id=') && profileWait) return profileWait;
    if(path.includes('/source?') && sourceWait) return sourceWait;
    if(path.startsWith('/bootstrap')) return {collections:[{id:'existing',name:'Existing character',kind:'subject'}, {id:'environment',name:'Studio',kind:'environment'}],detail:{profiles:[{id:'default',name:'Default'}]}};
    if(path.includes('/source?')) return {collection:{id:'environment',name:'Studio',kind:'environment'},profile:{id:'default',name:'Default'},paths:['C:/library/studio.png'],positive_prompt:'studio light',negative_prompt:'blur',loras:[],pool_count:1,total_count:2};
    if(path === '/collections') return {collection:{id:'created',name:body.name}};
    return {imports:body.paths.map(path=>({path}))};
  },
  selectLibrary: (node, data, includePrompt) => { librarySelection = {node, data, includePrompt}; },
  openLibrary: collection => { openedCollection = collection; },
  selectFolder: (node, path) => folderCalls.push([node.id, path]),
  promptState: node => drafts[node.id],
  setPromptName: (node, name) => { drafts[node.id].name = name; },
  revertPrompt: node => { drafts[node.id].text = drafts[node.id].baseline; drafts[node.id].modified = false; },
  setField: (node, name, value) => { if (name === 'favorite_prompt') { drafts[node.id].text = value; drafts[node.id].modified = value !== drafts[node.id].baseline; } },
  favorite() {},
  save: async (node, name, mode, paths) => {
    saveCalls.push([node.id, name, mode]);
    if (paths) savedGroupPaths = [...paths];
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
  await context.enlarge({node:nodes[0]}, {name:'Doe, Jane.png',path:'C:/Doe, Jane.png',thumbnail_data_url:'fixture'});
  assert.equal(requests.at(-1)[1].selected_images, '"C:/Doe, Jane.png"', 'enlarge quotes comma paths');
  body.children[0].close();
  context.openReferenceBrowser(nodes[0]); await tick();
  let dialog = body.children[0], grid = byClass(dialog, 'rr-grid'), scroll = byClass(dialog, 'rr-scroll');
  assert.equal(grid.children.length, 24);
  assert.ok(byAria(dialog, 'Checked images status').textContent.includes('0 checked'));
  assert.ok(byAria(dialog, 'Active run source and image connection').textContent.includes('Image output is disconnected'));
  nodes[0].outputs = [{type:'IMAGE',links:[101]}];
  context.refreshReferenceBrowser(nodes[0]); await tick();
  assert.ok(byAria(dialog, 'Active run source and image connection').textContent.includes('Image output has 1 connection'));
  assert.equal(all(grid).filter(n=>n.tag==='small').length,0,'grid has no filename captions');
  byText(dialog,'Select all').fire('click'); await tick();
  assert.ok(byText(dialog,'Use 27 checked images'),'Select all includes unloaded pages');
  assert.ok(byAria(dialog, 'Checked images status').textContent.includes('not applied'));
  byText(dialog,'Unselect all').fire('click');
  assert.ok(all(grid).filter(n=>n.type==='checkbox').every(n=>!n.checked));
  byText(dialog, 'Load folder…').fire('click'); await tick();
  assert.equal(dialogCalls[0][0], 'browse-folder');
  assert.equal(folderCalls.length, 0, 'cancel must preserve the existing source');
  dialogResult = {path: 'C:/chosen'};
  byText(dialog, 'Load folder…').fire('click'); await tick();
  assert.deepEqual(folderCalls[0], [1, 'C:/chosen']);
  dialogResult = {};
  byText(dialog, 'Load images…').fire('click'); await tick();
  assert.equal(dialogCalls.at(-1)[0], 'pick-images');
  assert.equal(selected, undefined, 'cancel image picker must keep the current source');
  let resolvePicker;
  dialogResult = new Promise(resolve => resolvePicker = resolve);
  const pickerCount = dialogCalls.length;
  byText(dialog, 'Load folder…').fire('click');
  byText(dialog, 'Load folder…').fire('click');
  assert.equal(dialogCalls.length, pickerCount + 1, 'double click cannot queue multiple native dialogs');
  assert.equal(byText(dialog, 'Load folder…').disabled, true);
  payload.folder = 'C:/newer-source';
  resolvePicker({path:'C:/late-picker-result'}); await tick();
  assert.equal(folderCalls.length, 1, 'late picker result cannot overwrite a newer source');
  assert.equal(byText(dialog, 'Load folder…').disabled, false);
  payload.folder = 'C:/fixtures'; dialogResult = {};
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
  byAria(dialog, 'Toggle selection of 1-0.png').fire('click');
  assert.equal(check.checked, false, 'photo click toggles selection instead of enlarging');
  byAria(dialog, 'Toggle selection of 1-0.png').fire('click');
  assert.ok(byAria(dialog, 'Checked images status').textContent.includes('1 checked'));
  byText(dialog, 'Save to favorite group…').fire('click'); await tick();
  const groupDialog = body.children[1];
  byAria(groupDialog, 'Favorite group name').value = 'One photo';
  byText(groupDialog, 'Create favorite group').fire('click'); await tick();
  assert.equal(savedGroupPaths.length, 1, 'group saves checks, not the whole folder');
  assert.equal(savedGroupPaths[0], 'C:/1/0.png');
  groupDialog.close();
  byText(dialog, 'Use 1 checked image').fire('click');
  assert.equal(selected.id, 1); assert.equal(selected.paths[0], 'C:/1/0.png');
  byText(dialog,'Save to library…').fire('click'); await tick();
  const characterDialog = body.children[1];
  byAria(characterDialog,'New collection name').value='Test character';
  byText(characterDialog,'Save 1 image').fire('click'); await tick();
  assert.equal(libraryCalls.at(-2)[1].kind,'subject');
  assert.equal(libraryCalls.at(-1)[0],'/collections/created/import-paths');
  assert.equal(libraryCalls.at(-1)[1].paths[0],'C:/1/0.png');
  const character = byAria(characterDialog,'Destination collection');
  character.value='existing'; character.fire('change');
  assert.equal(byAria(characterDialog,'New collection name').hidden,true);
  byText(characterDialog,'Save 1 image').fire('click'); await tick();
  assert.equal(libraryCalls.at(-1)[0],'/collections/existing/import-paths');
  characterDialog.close();
  byText(dialog,'Load from library…').fire('click'); await tick();
  const libraryDialog=body.children[1];
  const kind=byAria(libraryDialog,'Library collection kind'); kind.value='environment'; kind.fire('change'); await tick();
  assert.ok(all(libraryDialog).some(n=>n.tag==='option' && n.textContent==='Studio'));
  assert.ok(!all(libraryDialog).some(n=>n.tag==='option' && n.textContent==='Existing character'));
  const collection=byAria(libraryDialog,'Library collection'); collection.value='environment'; collection.fire('change'); await tick();
  const includePrompt=byAria(libraryDialog,'Use profile positive prompt'); includePrompt.checked=true;
  byText(libraryDialog,'Use collection images').fire('click'); await tick();
  assert.equal(librarySelection.node.id,1); assert.equal(librarySelection.data.paths[0],'C:/library/studio.png');
  assert.equal(librarySelection.includePrompt,true);
  assert.ok(libraryCalls.some(([path])=>path.includes('/collections/environment/source?') && path.includes('filtered=true')));
  assert.equal(body.children.length,1,'successful library selection closes picker');
  byText(dialog,'Load from library…').fire('click'); await tick();
  const slowDialog=body.children[1];
  const slowProfile=byAria(slowDialog,'Library prompt profile'); slowProfile.value='old-profile';
  let finishProfiles; profileWait=new Promise(resolve=>finishProfiles=resolve);
  const slowKind=byAria(slowDialog,'Library collection kind'); slowKind.value='environment'; slowKind.fire('change');
  assert.equal(slowProfile.value,'','old collection profile is cleared immediately');
  assert.equal(slowProfile.disabled,true);
  const filters=byAria(slowDialog,'Use library tag filters');
  assert.equal(filters.disabled,true,'filters cannot cancel an in-flight profile load');
  filters.fire('change');
  finishProfiles({detail:{profiles:[{id:'studio-profile',name:'Studio light'}]}}); profileWait=null; await tick();
  assert.equal(slowProfile.disabled,false);
  assert.ok(all(slowProfile).some(n=>n.value==='studio-profile'));
  let finishSource; sourceWait=new Promise(resolve=>finishSource=resolve);
  librarySelection=null;
  byText(slowDialog,'Use collection images').fire('click');
  payload.folder='C:/new-choice';
  finishSource({paths:['C:/stale.png']}); sourceWait=null; await tick();
  assert.equal(librarySelection,null,'late collection load cannot overwrite a newer node source');
  assert.ok(byClass(slowDialog,'rr-status').textContent.includes('source changed'));
  slowDialog.close(); payload.folder='C:/fixtures';
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
  context.openReferenceBrowser(nodes[0]); await tick();
  dialog=body.children[0];
  assert.ok(byAria(dialog,'Checked images status').textContent.includes('1 checked'), 'closing and reopening preserves unapplied checks');
  dialog.close();

  payload.source_mode='selection'; payload.selected_images='0.png';
  context.openReferenceBrowser(nodes[0]); await tick();
  dialog=body.children[0]; grid=byClass(dialog,'rr-grid');
  assert.ok(all(grid).filter(n=>n.type==='checkbox').every(n=>n.checked),'resolved selection starts checked');
  assert.ok(byText(dialog,'Use 27 checked images'));
  byText(dialog,'Unselect all').fire('click');
  byText(dialog,'Refresh').fire('click'); await tick();
  assert.ok(all(grid).filter(n=>n.type==='checkbox').every(n=>!n.checked),'refresh preserves cleared checks');
  dialog.close(); payload.source_mode='folder'; payload.selected_images='';

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
  assert.ok(all(dialog).find(n => n.attributes.role === 'status' && n.classList.contains('rr-status')).textContent.includes('Source 2'));
  dialog.close();
  const style = head.children[0].textContent;
  assert.match(style, /\.rr-scroll\{[^}]*min-height:0;overflow-y:auto/);
  assert.match(style, /\[hidden\][^{]*\{display:none!important\}/);
})().catch(error => { console.error(error); process.exit(1); });
'''.replace("SCRIPT", json.dumps(str(SCRIPT)))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
