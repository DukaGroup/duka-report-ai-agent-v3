import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source=await readFile(new URL('../frontend/src/session.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {endSession,onSessionEnded}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function environment(t,blocked=false){
  const previous={window:globalThis.window,localStorage:globalThis.localStorage};
  const events=new EventTarget(),values=new Map();
  globalThis.window=events;
  globalThis.localStorage={setItem:(key,value)=>{if(blocked)throw new Error('Storage blocked');values.set(key,value);}};
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  return {events,values};
}

test('self deletion logs out immediately and publishes a unique cross-tab notification',t=>{
  const {values}=environment(t);let calls=0;
  const stop=onSessionEnded('dev',()=>calls++);t.after(stop);
  endSession('other');assert.equal(calls,0);
  endSession('dev');assert.equal(calls,1);
  const first=JSON.parse(values.get('duka.sessionEnded'));
  assert.equal(first.userId,'dev');
  endSession('dev');assert.equal(calls,2);
  assert.notEqual(JSON.parse(values.get('duka.sessionEnded')).nonce,first.nonce);
  stop();endSession('dev');assert.equal(calls,2);
});

test('other tabs only close the matching account and ignore malformed notifications',t=>{
  const {events}=environment(t);let calls=0;
  t.after(onSessionEnded('dev',()=>calls++));
  const notify=(key,newValue)=>events.dispatchEvent(Object.assign(new Event('storage'),{key,newValue}));
  notify('unrelated','{}');notify('duka.sessionEnded','invalid');notify('duka.sessionEnded',null);
  notify('duka.sessionEnded',JSON.stringify({userId:'other'}));assert.equal(calls,0);
  notify('duka.sessionEnded',JSON.stringify({userId:'dev'}));assert.equal(calls,1);
});

test('a revoked session closes locally even when browser storage is blocked',t=>{
  environment(t,true);let calls=0;
  t.after(onSessionEnded('dev',()=>calls++));
  endSession();assert.equal(calls,1);
});
