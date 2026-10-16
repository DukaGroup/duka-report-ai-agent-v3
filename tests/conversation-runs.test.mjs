import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const source = await readFile(new URL('../frontend/src/conversationRuns.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { ConversationRuns, runningReports, pendingAssistantMessages } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const question = content => [{ id:'user', role:'user', content, status:'completed' }, {id:'streaming', role:'assistant',content:'',status:'streaming'}];
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
