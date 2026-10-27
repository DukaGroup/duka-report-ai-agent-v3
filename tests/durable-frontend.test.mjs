import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

async function compile(name, replacement = s => s) {
  const source = replacement(await readFile(new URL(`../frontend/src/${name}.ts`, import.meta.url), 'utf8'));
  const compiled = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
}
const sessionSource=await readFile(new URL('../frontend/src/session.ts',import.meta.url),'utf8');
const sessionCompiled=ts.transpileModule(sessionSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const sessionUrl=`data:text/javascript;base64,${Buffer.from(sessionCompiled).toString('base64')}`;
const {onSessionEnded}=await import(sessionUrl);
const {api,streamChat} = await compile('api', s=>s
  .replace('import { errorMessage } from "./locale";', 'const errorMessage = value=>value;')
  .replace('"./session"',JSON.stringify(sessionUrl)));
const {loadDrafts,saveDrafts} = await compile('drafts');
const ndjson = events => new Response(events.map(e=>JSON.stringify(e)+'\n').join(''));

test('revoked API and chat sessions log out and never retry unauthorized work',async t=>{
  const previous=globalThis.window;
  globalThis.window=new EventTarget();
  let logouts=0,calls=0;
  const stop=onSessionEnded('dev',()=>logouts++);
  t.after(()=>{stop();if(previous===undefined)delete globalThis.window;else globalThis.window=previous;});
  t.mock.method(globalThis,'fetch',async()=>{calls++;return Response.json({detail:'Sign in first.'},{status:401});});
  await assert.rejects(api('/reports'),/Sign in first/);
  assert.equal(logouts,1);
  await assert.rejects(api('/auth/login'),/Sign in first/);
  assert.equal(logouts,1);
  await assert.rejects(streamChat('chat','Request','fixture',()=>{}),/Sign in first/);
  assert.equal(logouts,2);
  assert.equal(calls,3);
});

test('revocation during request recovery stops reconnecting after the unauthorized lookup',async t=>{
  const previous=globalThis.window;
  globalThis.window=new EventTarget();
  let calls=0,logouts=0;
  const stop=onSessionEnded('dev',()=>logouts++);
  t.after(()=>{stop();if(previous===undefined)delete globalThis.window;else globalThis.window=previous;});
  t.mock.method(globalThis,'fetch',async()=>{
    if(++calls===1)throw new TypeError('Connection lost');
    return Response.json({detail:'Sign in first.'},{status:401});
  });
  await assert.rejects(streamChat('chat','Request','fixture',()=>{}),/Sign in first/);
  assert.equal(calls,2);
  assert.equal(logouts,1);
});

test('subscription handoff resets an abandoned draft and reconnects without resubmitting', async t=>{
  const urls=[], events=[];let text='';
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    urls.push([url, options?.method]);
    if(urls.length===1)return ndjson([
      {type:'message',id:'run',seq:1},
      {type:'delta',text:'Unverified partial totals',seq:2},
      {type:'snapshot',text:'',activity:'switching',seq:3},
      {type:'route',provider:'claude',model:'claude:claude-opus-5-5',reasoning_effort:'max',seq:4},
    ]);
    assert.match(url,/events\?after=4$/);
    return ndjson([{type:'delta',text:'Verified result',seq:5},{type:'done',text:'Verified result',status:'completed',seq:6}]);
  });
  await streamChat('chat','Original request','fixture',event=>{
    events.push(event);
    if(event.type==='delta')text+=event.text;
    if(event.type==='snapshot')text=event.text||'';
  });
  assert.equal(text,'Verified result');
  assert.deepEqual(urls.map(x=>x[1]),['POST','GET']);
  assert.equal(events.find(e=>e.type==='route').model,'claude:claude-opus-5-5');
});

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

test('replacing a response cancels its obsolete listener without retrying its POST', async t=>{
  const controller=new AbortController(); const calls=[], events=[];
  t.mock.method(globalThis,'fetch', async (url,options)=>{
    calls.push(url);
    assert.equal(options.signal,controller.signal);
    const body=JSON.parse(options.body);
    assert.equal(body.interrupt_current,true);
    return new Response(new ReadableStream({
      start(stream){
        stream.enqueue(new TextEncoder().encode(JSON.stringify({type:'message',id:'old',seq:1})+'\n'));
        options.signal.addEventListener('abort',()=>stream.error(new DOMException('Stopped listener','AbortError')));
      }
    }));
  });
  await assert.rejects(streamChat('chat','Next request','fixture', e=>{
    events.push(e);
    controller.abort();
  }, [], {interrupt_current:true}, controller.signal), {name:'AbortError'});
  assert.equal(calls.length,1);
  assert.deepEqual(events.map(e=>e.type),['message']);
});

test('caller-provided submission key remains stable so Stop can cancel a POST before acceptance', async t=>{
  const bodies=[];
  t.mock.method(globalThis,'fetch', async (url,options)=>{
    if(url.includes('/requests/')) return Response.json({detail:'Not accepted'},{status:404});
    bodies.push(JSON.parse(options.body));
    if(bodies.length===1)return Response.json({detail:'Temporarily offline'},{status:503});
    return ndjson([{type:'message',id:'run',seq:1},{type:'done',text:'Done',status:'completed',seq:2}]);
  });
  await streamChat('chat','Request','fixture',()=>{},[],{request_id:'known-before-send'});
  assert.deepEqual(bodies.map(b=>b.request_id),['known-before-send','known-before-send']);
});
