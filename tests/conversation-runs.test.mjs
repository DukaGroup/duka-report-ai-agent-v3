import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import React from '../frontend/node_modules/react/index.js';
import { renderToStaticMarkup } from '../frontend/node_modules/react-dom/server.node.js';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const source = await readFile(new URL('../frontend/src/conversationRuns.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { ConversationRuns, runningReports, pendingAssistantMessages } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const { streamActivity, reportActivity } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const question = content => [{ id:'user', role:'user', content, status:'completed' }, {id:'streaming', role:'assistant',content:'',status:'streaming'}];
test('public work steps persist in the stream, deduplicate replay and reject stale runs',()=>{
  const runs=new ConversationRuns();
  const first=runs.start('chat',question('First'));
  runs.step('chat',{type:'tool',step_id:'one',step_label:'Kërkim në internet',step_kind:'tool'},first);
  runs.step('chat',{type:'tool',step_id:'one',step_label:'Kërkim në internet',step_kind:'tool'},first);
  assert.deepEqual(runs.snapshot('chat')[1].steps,[{id:'one',label:'Kërkim në internet',kind:'tool'}]);
  const second=runs.start('chat',question('Next'),true);
  runs.step('chat',{type:'tool',step_id:'late',step_label:'Late',step_kind:'tool'},first);
  assert.equal(runs.snapshot('chat')[1].steps,undefined);
  runs.step('chat',{type:'activity',step_id:'two',step_label:'Arsyetim',step_kind:'activity'},second);
  assert.equal(runs.snapshot('chat')[1].steps[0].label,'Arsyetim');
});
test('pending activity shows visible text without repeating the avatar thought dots',async()=>{
  const require=createRequire(new URL('../frontend/package.json',import.meta.url));
  const source=await readFile(new URL('../frontend/src/ThinkingStatus.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText
    .replace(/from "([^"]+)"/g,(_,name)=>`from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
  const {ThinkingStatus}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const html=renderToStaticMarkup(React.createElement(ThinkingStatus,{description:'Po arsyetoj…'}));
  assert.match(html,/role="status"/);
  assert.match(html,/<span class="thinking-label">Po arsyetoj…<\/span>/);
  // Hana's avatar already shows animated thought dots; they appear only once.
  assert.doesNotMatch(html,/thinking-dots/);
});
test('visible activity follows each chat phase and ignores quiet or private events',()=>{
  const runs=new ConversationRuns();
  const token=runs.start('a',question('First'));
  runs.start('b',question('Second'));
  assert.equal(runs.activity('a'),'Po mendoj…');
  for(const [event,expected] of [
    [{type:'activity',activity:'reasoning',text:'PRIVATE'},'Po arsyetoj…'],
    [{type:'tool',name:'query_database'},'Po kontrolloj të dhënat…'],
    [{type:'tool',name:'calculate_data'},'Po llogaris…'],
    [{type:'tool',name:'create_calculation_report'},'Po përgatis raportin…'],
    [{type:'tool',name:'WebSearch'},'Po kërkoj në internet…'],
    [{type:'tool',name:'WebFetch'},'Po lexoj faqen…'],
    [{type:'snapshot',activity:'refreshing'},'Po përditësoj bisedën…'],
    [{type:'delta',text:'Public answer'},'Po shkruaj…'],
    [{type:'reconnecting'},'Po rilidhem…'],
    [{type:'snapshot',activity:'switching'},'Po kaloj te abonimi tjetër…'],
  ]) {
    runs.update('a','','streaming',streamActivity(event),token);
    assert.equal(runs.activity('a'),expected);
    assert.equal(runs.activity('b'),'Po mendoj…');
  }
  for(const event of [{type:'heartbeat'},{type:'activity',activity:'PRIVATE'},{type:'activity',activity:'__proto__'}]){
    assert.equal(streamActivity(event),undefined);
    runs.update('a','','streaming',streamActivity(event),token);
    assert.equal(runs.activity('a'),'Po kaloj te abonimi tjetër…');
  }
  assert.equal(reportActivity('validating'),'Po kontrolloj raportin…');
  assert.equal(reportActivity('unknown-provider-text'),'Po përgatis raportin…');
});
test('two simultaneous streams retain independent messages and activity when switching chats', () => {
  const runs = new ConversationRuns();
  runs.start('a', question('A confidential question'));
  runs.start('b', question('B independent question'));
  runs.update('a', 'A response', 'streaming', 'A data');
  runs.update('b', 'B response', 'streaming', 'B data');
  assert.equal(runs.snapshot('a')[1].content, 'A response');
  assert.equal(runs.snapshot('b')[1].content, 'B response');
  assert.equal(runs.activity('b'), 'B data');
  runs.update('a', 'A result', 'completed');
  runs.finish('a');
  assert.equal(runs.has('a'), false);
  assert.equal(runs.has('b'), true);
  assert.equal(runs.snapshot('b')[0].content, 'B independent question');
  assert.equal(runs.snapshot('b')[1].status, 'streaming');
});
test('a report locks only its originating conversation until a terminal result', () => {
  const reports = [{id:'r1', conversation_id:'a',status:'running'},{id:'r2', conversation_id:'b',status:'queued'},{id:'r3',conversation_id:'a',status:'completed'},{id:'r4',conversation_id:null,status:'running'}];
  assert.deepEqual(runningReports(reports,'a').map(r=>r.id), ['r1']);
  assert.deepEqual(runningReports(reports,'b').map(r=>r.id), ['r2']);
  assert.deepEqual(runningReports(reports,'c'), []);
  assert.deepEqual(runningReports(reports,null), []);
  reports[0].status='failed';
  assert.deepEqual(runningReports(reports,'a'), []);
  assert.equal(runningReports(reports,'b').length, 1);
});

test('assistant dots persist through partial text and Excel generation, then stop at completion or interruption', () => {
  const messages = [
    { id: 'old-answer', role: 'assistant', content: 'Previous answer', status: 'completed' },
    ...question('Create a report'),
  ];
  messages.at(-1).content = 'The report is being prepared.';
  const reports = [{ id: 'excel', conversation_id: 'a', status: 'queued' }];
  assert.deepEqual([...pendingAssistantMessages(messages, reports, 'a')], ['streaming']);
  messages.at(-1).status = 'completed';
  assert.deepEqual([...pendingAssistantMessages(messages, reports, 'a')], ['streaming']);
  reports[0].status = 'running';
  assert.deepEqual([...pendingAssistantMessages(messages, reports, 'a')], ['streaming']);
  assert.deepEqual([...pendingAssistantMessages(messages, reports, 'b')], []);
  for (const status of ['completed', 'failed', 'interrupted']) {
    reports[0].status = status;
    assert.deepEqual([...pendingAssistantMessages(messages, reports, 'a')], []);
  }
  messages.at(-1).status = 'interrupted';
  assert.deepEqual([...pendingAssistantMessages(messages, reports, 'a')], []);
});

test('restart keeps only the prefix before any selected user message', async () => {
  const { messagesBeforeRestart } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const messages = [
    {id:'u1', role:'user', content:'First', status:'completed'},
    {id:'a1', role:'assistant', content:'First answer', status:'completed'},
    {id:'u2', role:'user', content:'Second', status:'completed'},
    {id:'a2', role:'assistant', content:'Second answer', status:'completed'},
    {id:'u3', role:'user', content:'Third', status:'completed'},
    {id:'a3', role:'assistant', content:'Third answer', status:'interrupted'},
  ];
  assert.deepEqual(messagesBeforeRestart(messages,'u1'), []);
  assert.deepEqual(messagesBeforeRestart(messages,'u2'), messages.slice(0,2));
  assert.deepEqual(messagesBeforeRestart(messages,'u3'), messages.slice(0,4));
  assert.equal(messages.length,6);
  assert.throws(() => messagesBeforeRestart(messages,'a1'));
  assert.throws(() => messagesBeforeRestart(messages,'other-chat'));
});

test('late output and cleanup from a replaced or deleted run cannot change its successor', () => {
  const runs = new ConversationRuns();
  const old = runs.start('a', question('Original'));
  const next = runs.start('a', question('Replacement'), true);
  assert.equal(runs.isCurrent('a', old), false);
  assert.equal(runs.update('a', 'Old late error', 'failed', undefined, old), undefined);
  runs.finish('a', old);
  assert.equal(runs.isCurrent('a', next), true);
  assert.equal(runs.snapshot('a')[0].content, 'Replacement');
  runs.update('a', 'New answer', 'completed', undefined, next);
  assert.equal(runs.snapshot('a')[1].content, 'New answer');
  runs.finish('a');
  assert.equal(runs.update('a', 'Late text after delete', 'streaming', undefined, next), undefined);
  assert.equal(runs.has('a'), false);
});

test('replacement keeps the interrupted partial answer separate from the next assistant placeholder', async () => {
  const {messagesBeforeNextTurn} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const previous = question('Original'); previous[1].content='Partial original';
  const messages=[...messagesBeforeNextTurn(previous), ...question('Next')];
  const runs=new ConversationRuns(); const token=runs.start('chat',messages);
  runs.update('chat','New answer','streaming',undefined,token);
  assert.equal(runs.snapshot('chat')[1].content,'Partial original');
  assert.equal(runs.snapshot('chat')[1].status,'interrupted');
  assert.notEqual(runs.snapshot('chat')[1].id,'streaming');
  assert.equal(runs.snapshot('chat')[3].content,'New answer');
});

test('acceptance assigns the real user message ID before Stop so edit and resend remain valid', () => {
  const runs=new ConversationRuns();
  const old=runs.start('chat',question('Original'));
  runs.identifyUser('chat','saved-user-id',old);
  assert.equal(runs.snapshot('chat')[0].id,'saved-user-id');
  const next=runs.start('chat',question('Next'),true);
  runs.identifyUser('chat','late-old-id',old);
  assert.equal(runs.snapshot('chat')[0].id,'user');
  runs.identifyUser('chat','next-saved-id',next);
  assert.equal(runs.snapshot('chat')[0].id,'next-saved-id');
});

const notificationSource = await readFile(new URL('../frontend/src/replyNotifications.ts', import.meta.url), 'utf8');
const notificationJs = ts.transpileModule(notificationSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { ReplyCompletions } = await import(`data:text/javascript;base64,${Buffer.from(notificationJs).toString('base64')}`);
const away = {page:'chat',conversationId:'other',hidden:false};
test('background completion notifies once, even when stream replay and polling both deliver it',()=>{
  const notices=new ReplyCompletions();
  notices.observe([{id:'a',running:true}]);
  assert.equal(notices.finish('a','reply-1','completed',away),true);
  assert.deepEqual(notices.observe([{id:'a',running:false}]),['a']);
  assert.equal(notices.finish('a','reply-1','completed',away),false);
  assert.equal(notices.finish('a','reply-2','completed',away),true);
});
test('watching the reply suppresses a toast; another page and a hidden browser tab qualify',()=>{
  const notices=new ReplyCompletions();
  assert.equal(notices.finish('a','r1','completed',{page:'chat',conversationId:'a',hidden:false}),false);
  // A seen reply must not become a new notification simply by navigating away.
  assert.equal(notices.finish('a','r1','completed',away),false);
  assert.equal(notices.finish('a','r2','completed',{page:'settings',conversationId:'a',hidden:false}),true);
  assert.equal(notices.finish('a','r3','completed',{page:'chat',conversationId:'a',hidden:true}),true);
});
test('interrupted, failed, deleted and superseded replies never announce success',()=>{
  const notices=new ReplyCompletions();
  assert.equal(notices.finish('a','r1','interrupted',away),false);
  assert.equal(notices.finish('a','r2','failed',away),false);
  // Polling an unfinished reply cannot swallow its eventual completion.
  assert.equal(notices.finish('a','r3','streaming',away),false);
  assert.equal(notices.finish('a','r3','completed',away),true);
  notices.observe([{id:'deleted',running:true}]);
  notices.forget('deleted');
  assert.equal(notices.finish('deleted','r4','completed',away),false);
  assert.deepEqual(notices.observe([{id:'deleted',running:false}]),[]);
});
test('reloaded runs are watched without notifying for old history; failed checks can retry',()=>{
  const notices=new ReplyCompletions();
  assert.deepEqual(notices.observe([{id:'old',running:false},{id:'a',running:true},{id:'b',running:true}]),[]);
  assert.deepEqual(notices.observe([{id:'old',running:false},{id:'a',running:false},{id:'b',running:true}]),['a']);
  notices.retry('a');
  assert.deepEqual(notices.observe([{id:'a',running:false},{id:'b',running:false}]),['a','b']);
  assert.deepEqual(notices.observe([{id:'a',running:false},{id:'b',running:false}]),[]);
});
test('completion tracking is isolated to each signed-in workspace',()=>{
  const first=new ReplyCompletions(),second=new ReplyCompletions();
  first.observe([{id:'a',running:true}]);
  assert.deepEqual(second.observe([{id:'a',running:false}]),[]);
  assert.equal(first.finish('a','same','completed',away),true);
  assert.equal(second.finish('a','same','completed',away),true);
});
test('custom completion notices have Albanian open/dismiss actions and escape conversation titles',async()=>{
  const require=createRequire(new URL('../frontend/package.json',import.meta.url));
  const source=await readFile(new URL('../frontend/src/ReplyNotifications.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText
    .replace(/from "([^"]+)"/g,(_,name)=>`from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
  const {ReplyNotifications}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const html=renderToStaticMarkup(React.createElement(ReplyNotifications,{items:[{id:'r1',conversationId:'a',title:'<script>private</script>'}],disabled:false,onOpen(){},onDismiss(){}}));
  assert.match(html,/aria-live="polite"/);
  assert.match(html,/Përgjigjja përfundoi/);
  assert.match(html,/Hap përgjigjen:/);
  assert.match(html,/Mbyll njoftimin:/);
  assert.doesNotMatch(html,/<script>/);
  assert.match(html,/&lt;script&gt;private&lt;\/script&gt;/);
});

test('a completion buffered while minimized still alerts after returning to that same conversation',()=>{
  const notices=new ReplyCompletions();
  const view={page:'chat',conversationId:'a',hidden:false};
  const start=Date.parse('2026-10-20T10:00:00Z');
  notices.visibility(true,start);
  notices.visibility(true,start+1000); // Repeated events do not reset the interval.
  notices.visibility(false,start+10000);
  assert.equal(notices.finish('a','buffered','completed',view,new Date(start+5000).toISOString()),true);
  assert.equal(notices.finish('a','buffered','completed',view,new Date(start+5000).toISOString()),false);
  assert.equal(notices.finish('a','after-return','completed',view,new Date(start+11000).toISOString()),false);
  assert.equal(notices.finish('a','before-minimize','completed',view,new Date(start-1000).toISOString()),false);
  assert.equal(notices.finish('a','no-timestamp','completed',view),false);
});

const soundSource=await readFile(new URL('../frontend/src/replySound.ts',import.meta.url),'utf8');
const soundJs=ts.transpileModule(soundSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {ReplySound,playNotificationSound}=await import(`data:text/javascript;base64,${Buffer.from(soundJs).toString('base64')}`);
function audioFixture(state='suspended') {
  const tones=[],gains=[];
  const context={state,currentTime:1,destination:{},resumes:0,closes:0,
    async resume(){this.resumes++;this.state='running';},
    async close(){this.closes++;this.state='closed';},
    createOscillator(){const tone={frequency:{},connect(){},disconnect(){},start(at){this.startTime=at;},stop(at){this.stopTime=at;}};tones.push(tone);return tone;},
    createGain(){const gain={gain:{setValueAtTime(){},linearRampToValueAtTime(value){gain.volume=value;},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}};gains.push(gain);return gain;}
  };
  return {context,tones,gains};
}
test('completion sound unlocks on interaction and plays a short chime while backgrounded',async()=>{
  const {context,tones,gains}=audioFixture();
  const sound=new ReplySound(()=>context);
  sound.unlock(); await Promise.resolve();
  assert.equal(tones.length,0); // Unlocking itself is silent.
  sound.play();
  assert.equal(tones.length,2);
  assert.deepEqual(tones.map(t=>t.frequency.value),[660,880]);
  assert.ok(tones.every(t=>t.stopTime-t.startTime<.5));
  assert.ok(gains.every(g=>g.volume<=.12));
  sound.play();assert.equal(tones.length,2); // Simultaneous replies cannot become a loud burst.
  context.currentTime+=2;sound.play();assert.equal(tones.length,4);
  sound.dispose();assert.equal(context.closes,1);
});
test('blocked or suspended audio keeps one pending chime for resumption, without losing visual notifications',async()=>{
  const {context,tones}=audioFixture();
  let resume;
  context.resume=()=>new Promise(resolve=>{resume=()=>{context.state='running';resolve();};});
  const sound=new ReplySound(()=>context);
  sound.play(); // A recovered response may finish before the first user gesture.
  sound.unlock();sound.play();sound.resume();
  assert.equal(tones.length,0);
  resume();await Promise.resolve();assert.equal(tones.length,2);
  sound.resume();assert.equal(tones.length,2);
  sound.dispose();
  assert.doesNotThrow(()=>new ReplySound(()=>{throw Error('Audio unavailable');}).unlock());
});
test('pending sounds are cancelled when notices are cleared or a member signs out',async()=>{
  const {context,tones}=audioFixture();
  const sound=new ReplySound(()=>context);
  sound.play();sound.cancelPending();sound.unlock();await Promise.resolve();
  assert.equal(tones.length,0);
  sound.dispose();sound.play();sound.unlock();assert.equal(tones.length,0);
});

test('completion tracking waits for report export jobs even after the assistant message finishes',()=>{
  const notices=new ReplyCompletions();
  assert.deepEqual(notices.observe([{id:'a',running:true,notification_pending:true}]),[]);
  assert.deepEqual(notices.observe([{id:'a',running:false,notification_pending:true}]),[]);
  // A refreshed page observes pending reports without a local chat stream as well.
  const refreshed=new ReplyCompletions();
  assert.deepEqual(refreshed.observe([{id:'a',running:false,notification_pending:true}]),[]);
  assert.deepEqual(notices.observe([{id:'a',running:false,notification_pending:false}]),['a']);
  assert.deepEqual(refreshed.observe([{id:'a',running:false,notification_pending:false}]),['a']);
  assert.deepEqual(notices.observe([{id:'a',running:false,notification_pending:false}]),[]);
});


test('native notification chime acknowledges unlocked audio and leaves blocked audio to the OS without a delayed duplicate',async()=>{
  const {context,tones}=audioFixture('running');const sound=new ReplySound(()=>context);
  assert.equal(sound.playIfReady(),false);sound.unlock();assert.equal(sound.playIfReady(),true);
  assert.equal(tones.length,2);assert.equal(sound.playIfReady(),true);assert.equal(tones.length,2);
  context.state='suspended';assert.equal(sound.playIfReady(),false);
  context.currentTime+=2;sound.resume();await Promise.resolve();assert.equal(tones.length,2);
  sound.dispose();assert.equal(sound.playIfReady(),false);
  const broken=audioFixture('running');broken.context.createOscillator=()=>{throw Error('Device disconnected');};
  const unavailable=new ReplySound(()=>broken.context);unavailable.unlock();assert.equal(unavailable.playIfReady(),false);
});
test('sound requests require current member opt-in and an unexpired deadline',()=>{
  let plays=0;const sound={playIfReady(){plays++;return true;}};
  const request={type:'duka-notification-sound',userId:'alice',messageId:'reply-a',expiresAt:Date.now()+450};
  assert.equal(playNotificationSound(request,'alice',sound,true),true);assert.equal(plays,1);
  for(const data of [null,{}, {...request,userId:'bob'}, {...request,messageId:'../bad'}, {...request,expiresAt:Date.now()-1}, {...request,expiresAt:Infinity}, {...request,expiresAt:Date.now()+5000}])
    assert.equal(playNotificationSound(data,'alice',sound,true),false);
  assert.equal(playNotificationSound(request,'alice',sound,false),false);
  assert.equal(playNotificationSound(request,'alice',null,true),false);assert.equal(plays,1);
});
