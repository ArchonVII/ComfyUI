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
