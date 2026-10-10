import json
from pathlib import Path
import subprocess


def test_cast_lock_widget_persists_only_matching_paths_and_clears_on_edits():
    path = Path(__file__).parents[1] / 'web' / 'cast.js'
    assert path.exists(), 'Cast frontend missing'
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let extension;
vm.runInNewContext(fs.readFileSync(PATH, 'utf8').replace(/^import[^\n]*\n/gm, ''), {
  app: {registerExtension(value) {extension = value;}}
});
class Node {
  constructor() {
    this.widgets = [
      {name:'locked_paths', value:'{}'},
      {name:'subject_favorite', value:'A'},
      {name:'subject_locked', value:true},
      {name:'subject_enabled', value:true},
    ];
    this.graph = {change(){}};
  }
  setDirtyCanvas() {}
}
extension.beforeRegisterNodeDef(Node, {name:'ArchReferenceCast'});
const node = new Node(); node.onNodeCreated();
const state = node.widgets[0];
assert.equal(state.computeSize()[1], -4);
node.onExecuted({arch_reference_cast:[{lanes:{subject:{enabled:true,locked:true,favorite:'A',selected_file:'one.png',prompt:'must not persist'}}}]});
assert.deepEqual(JSON.parse(state.value), {subject:{favorite:'A',selected_file:'one.png'}});
node.widgets[1].value='B'; node.widgets[1].callback();
assert.deepEqual(JSON.parse(state.value), {});
node.onExecuted({arch_reference_cast:[{lanes:{subject:{enabled:true,locked:true,favorite:'A',selected_file:'old.png'}}}]});
assert.deepEqual(JSON.parse(state.value), {});
node.onExecuted({arch_reference_cast:[{lanes:{subject:{enabled:true,locked:true,favorite:'B',selected_file:'two.png'}}}]});
node.widgets[2].value=false; node.widgets[2].callback();
assert.deepEqual(JSON.parse(state.value), {});
node.onExecuted({arch_reference_cast:[{lanes:{subject:{enabled:true,locked:false,favorite:'B',selected_file:'seen.png'}}}]});
node.widgets[2].value=true; node.widgets[2].callback();
assert.deepEqual(JSON.parse(state.value), {subject:{favorite:'B',selected_file:'seen.png'}});
node.onExecuted({arch_reference_cast:[{lanes:{subject:{enabled:true,locked:false,favorite:'B',selected_file:'queued-old.png'}}}]});
assert.deepEqual(JSON.parse(state.value), {subject:{favorite:'B',selected_file:'seen.png'}});
'''.replace('PATH', json.dumps(str(path)))
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cast_refreshes_group_choices_and_invalidates_renamed_deleted_locks():
    path = Path(__file__).parents[1] / 'web' / 'cast.js'
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let extension;
const listeners = new Map();
const context = {
 app: {registerExtension(value) {extension = value;}},
 api: {fetchApi: async () => ({ok:true, json:async () => ({presets:{A:{},B:{}}})})},
 addEventListener(name, listener) {listeners.set(name, listener);},
 removeEventListener(name, listener) {if(listeners.get(name) === listener) listeners.delete(name);},
};
vm.runInNewContext(fs.readFileSync(PATH, 'utf8').replace(/^import[^\n]*\n/gm, ''), context);
class Node {
 constructor() {
  this.widgets = [{name:'locked_paths',value:'{"subject":{"favorite":"A","selected_file":"one.png"}}'},
   {name:'subject_favorite',value:'A',options:{values:['None','A']}},
   {name:'subject_locked',value:true}];
  this.graph = {change(){}};
 }
 setDirtyCanvas() {}
}
extension.beforeRegisterNodeDef(Node, {name:'ArchReferenceCast'});
(async () => {
 const node = new Node(); node.onNodeCreated();
 await new Promise(resolve => setImmediate(resolve));
 assert.deepEqual(Array.from(node.widgets[1].options.values), ['None','A','B']);
 const listener = listeners.get('arch-reference-presets-changed');
 assert.ok(listener);
 listener({detail:{presets:{Renamed:{},B:{}},renamedFrom:'A',name:'Renamed'}});
 assert.equal(node.widgets[1].value, 'Renamed');
 assert.deepEqual(JSON.parse(node.widgets[0].value), {});
 listener({detail:{presets:{B:{}}}});
 assert.equal(node.widgets[1].value, 'None');
 node.onRemoved();
 assert.equal(listeners.size, 0);
})().catch(error => {console.error(error); process.exitCode=1;});
'''.replace('PATH', json.dumps(str(path)))
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
