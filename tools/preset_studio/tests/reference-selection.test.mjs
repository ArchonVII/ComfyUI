import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';

const moduleURL = new URL('../web/reference-selection.mjs', import.meta.url);
const presets = [{id:'c',kind:'character',references:['a','b']},{id:'e',kind:'environment',references:['room']}];
async function subject() {
  assert.ok(existsSync(moduleURL), 'Character reference selection is not implemented');
  return import(moduleURL);
}
test('single character image replaces the subject without moving the environment slot', async()=>{
  const {referenceRequest}=await subject();
  assert.deepEqual(referenceRequest(presets,{c:['b'],e:['room']},null),{reference_ids:['b','room']});
});
test('selected group occupies one workflow slot and preserves selection order',async()=>{
  const {referenceRequest}=await subject();
  assert.deepEqual(referenceRequest(presets,{c:['a'],e:['room']},{preset_id:'c',image_ids:['b','a']}),{
    reference_ids:['b','room'],reference_batch:{preset_id:'c',image_ids:['b','a'],slot:0}
  });
});
test('empty then reselected group retains the character slot',async()=>{
  const {referenceRequest}=await subject();
  assert.deepEqual(referenceRequest(presets,{c:[],e:['room']},{preset_id:'c',image_ids:[]}).reference_ids,['room']);
  assert.deepEqual(referenceRequest(presets,{c:[],e:['room']},{preset_id:'c',image_ids:['b']}).reference_ids,['b','room']);
});
test('removed presets or images cannot survive a browser draft',async()=>{
  const {referenceRequest}=await subject();
  const result=referenceRequest(presets.slice(1),{c:['a'],e:['room','deleted']},{preset_id:'c',image_ids:['a']});
  assert.deepEqual(result,{reference_ids:['room']});
});
