import json
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / 'web' / 'review.js'


def test_review_ui_batch_selection_and_safe_rendering():
    source = SCRIPT.read_text(encoding='utf-8')
    assert '.innerHTML' not in source
    harness = '''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let source = fs.readFileSync(SCRIPT, 'utf8').replace(/^import .*;$/gm, '');
const extensions = [];
const context = {app: {registerExtension: x => extensions.push(x)}, api: {}, console};
vm.createContext(context); vm.runInContext(source, context);
const record = {results: [{path:'a.png'}, {path:'b.png'}, {path:'c.png'}]};
context.record = record;
assert.equal(JSON.stringify(vm.runInContext('selectedPaths(record, "all")', context)), '["a.png","b.png","c.png"]');
assert.equal(JSON.stringify(vm.runInContext('selectedPaths(record, "1")', context)), '["b.png"]');
assert.throws(() => vm.runInContext('selectedPaths(record, "99")', context));
assert.equal(extensions.length, 1);
'''.replace('SCRIPT', json.dumps(str(SCRIPT)))
    result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def test_library_dialog_imports_all_then_selected_and_reports_failures():
    harness = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let source = fs.readFileSync(SCRIPT, 'utf8').replace(/^import .*;$/gm, '');
class Element {
 constructor(tag) {this.tag=tag; this.children=[]; this.style={}; this.value=''; this.textContent='';}
 append(...items) { this.children.push(...items); if(this.tag==='select' && !this.value && items.length) this.value=items[0].value; }
 setAttribute() {} addEventListener() {} showModal() {} close() {} remove() {}
 get options() {return this.children;}
}
const body = new Element('body'), requests=[];
const context={app:{registerExtension(){}}, document:{createElement:tag=>new Element(tag),body}, api:{fetchApi:async (path, options)=>{
 requests.push([path,options]);
 return {ok:true,json:async()=>path.endsWith('bootstrap') ? {collections:[{id:'collection',kind:'subject',name:'Person'}]} : {imports:[{},{}],failures:[{error:'example failure'}]}};
}}};
vm.createContext(context); vm.runInContext(source,context);
context.record={results:[{path:'a.png',filename:'a.png'},{path:'b.png',filename:'b.png'}]};
(async()=>{
 await vm.runInContext('saveToLibrary(record)',context);
 const dialog=body.children[0], selects=dialog.children.filter(x=>x.tag==='select');
 const save=dialog.children.find(x=>x.textContent==='Save copies');
 assert.equal(selects[1].value,'all');
 await save.onclick();
 assert.deepEqual(JSON.parse(requests.at(-1)[1].body).paths,['a.png','b.png']);
 assert.ok(dialog.children.at(-1).textContent.includes('example failure'));
 selects[1].value='1'; await save.onclick();
 assert.deepEqual(JSON.parse(requests.at(-1)[1].body).paths,['b.png']);
 assert.ok(requests.at(-1)[0].endsWith('/collections/collection/import-paths'));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SCRIPT', json.dumps(str(SCRIPT)))
    result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def test_cached_execution_fetches_persisted_classification():
    harness = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let source = fs.readFileSync(SCRIPT, 'utf8').replace(/^import .*;$/gm, '');
let extension, shown, requested;
const context={app:{registerExtension:x=>extension=x},api:{fetchApi:async path=>{
 requested=path; return {ok:true,json:async()=>({id:'review-id',classification:'keep'})};
}}};
vm.createContext(context); vm.runInContext(source,context);
context.capture=record=>shown=record;
vm.runInContext('showReview = capture',context);
(async()=>{
 function Node(){};
 await extension.beforeRegisterNodeDef(Node,{name:'ArchResultReview'});
 const node=new Node();
 await node.onExecuted({arch_review:[{id:'review-id',classification:'unreviewed'}]});
 assert.equal(shown.classification,'keep');
 assert.equal(requested,'/arch-reference-workbench/reviews/review-id');
 assert.equal(node.properties.arch_review_id,'review-id');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SCRIPT', json.dumps(str(SCRIPT)))
    result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
