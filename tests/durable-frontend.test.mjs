import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

async function compile(name, replacement = s => s) {
  const source = replacement(await readFile(new URL(`../frontend/src/${name}.ts`, import.meta.url), 'utf8'));
  const compiled = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
}
const {streamChat} = await compile('api', s=>s.replace('import { errorMessage } from "./locale";', 'const errorMessage = value=>value;'));
const {loadDrafts,saveDrafts} = await compile('drafts');
const ndjson = events => new Response(events.map(e=>JSON.stringify(e)+'\n').join(''));

test('frontend reconnect resumes after the last event without duplicating the POST or text', async t=>{
  const urls=[], events=[];
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    urls.push([url,options?.method]);
    if (urls.length===1) return ndjson([{type:'message',id:'run',seq:1},{type:'delta',text:'A',seq:2}]);
    assert.match(url,/runs\/run\/events\?after=2$/);
    return ndjson([{type:'delta',text:'B',seq:3},{type:'done',text:'AB',status:'completed',seq:4}]);
  });
  await streamChat('chat','Request','claude:default',e=>events.push(e));
  assert.deepEqual(urls.map(x=>x[1]),['POST','GET']);
  assert.equal(events.filter(e=>e.type==='delta').map(e=>e.text).join(''),'AB');
});

test('lost initial response discovers its exact accepted request before reconnecting',async t=>{
  const calls=[]; let request;
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    calls.push(url);
    if (calls.length===1) {request=JSON.parse(options.body).request_id;throw new TypeError('Offline');}
    if (url.includes('/requests/')) { assert.ok(url.endsWith(request));return Response.json({run_id:'accepted'}); }
    return ndjson([{type:'message',id:'accepted',seq:1},{type:'done',text:'Recovered',status:'completed',seq:2}]);
  });
  const events=[];
  await streamChat('chat','Request','fixture',e=>events.push(e));
  assert.equal(calls.length,3);
  assert.match(calls[2],/runs\/accepted\/events/);
  assert.equal(events.at(-1).text,'Recovered');
});

test('initial request not accepted is retried with the same persistent request key',async t=>{
  const keys=[];let calls=0;
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    calls++;
    if (url.includes('/requests/')) return Response.json({detail:'Response not found.'},{status:404});
    keys.push(JSON.parse(options.body).request_id);
    if(keys.length===1)throw new TypeError('Connection refused');
    return ndjson([{type:'message',id:'new',seq:1},{type:'done',text:'Only once',status:'completed',seq:2}]);
  });
  await streamChat('chat','Request','fixture',()=>{});
  assert.equal(calls,3);assert.equal(keys[0],keys[1]);
});

test('drafts preserve edit targets, attachments and model effort across refresh, isolated by member',t=>{
  const values=new Map();
  const previous=globalThis.localStorage;
  globalThis.localStorage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
  t.after(()=>{ if(previous===undefined)delete globalThis.localStorage;else globalThis.localStorage=previous; });
  const draft={draft:'Unsent request',attachments:[{id:'upload'}],model:'claude:default',reasoningEffort:'high',retryMessageId:'earlier'};
  saveDrafts('alice',new Map([['chat',draft],['__new__',{...draft,draft:'New conversation draft'}]]));
  assert.deepEqual(loadDrafts('alice').get('chat'),draft);
  assert.equal(loadDrafts('alice').get('__new__').draft,'New conversation draft');
  assert.equal(loadDrafts('bob').size,0);
  values.set('duka.drafts.alice','corrupt');assert.equal(loadDrafts('alice').size,0);
});
