import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/chatTimeline.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { buildChatTimeline } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const message = (id, minute) => ({ id, created_at: `2026-10-13T12:${minute}:00Z`, role: 'user', content: id, status: 'completed' });
const report = (id, minute, status = 'completed') => ({ id, created_at: `2026-10-13T12:${minute}:00+00:00`, title: id, status });

test('a follow-up message appears after its earlier report, including after reload', () => {
  const timeline = buildChatTimeline([message('question', '00'), message('answer', '01'), message('follow-up', '03')], [report('excel', '02')]);
  assert.deepEqual(timeline.map(e => e.key), ['message-question', 'message-answer', 'report-excel', 'message-follow-up']);
});

test('multiple reports keep chronological positions even when the report API returns newest first', () => {
  const timeline = buildChatTimeline([message('first', '00'), message('second', '03'), message('third', '05')], [report('second-report', '04'), report('first-report', '02')]);
  assert.deepEqual(timeline.map(e => e.key), ['message-first', 'report-first-report', 'message-second', 'report-second-report', 'message-third']);
});

test('report completion updates its existing card without moving it below later messages', () => {
  const messages = [message('question', '00'), message('next', '03')];
  const before = buildChatTimeline(messages, [report('excel', '02', 'running')]);
  const after = buildChatTimeline(messages, [report('excel', '02')]);
  assert.deepEqual(after.map(e => e.key), before.map(e => e.key));
});

test('equal timestamps preserve user/assistant order and an empty conversation has no artifacts', () => {
  const timeline = buildChatTimeline([message('user', '00'), message('assistant', '00')], []);
  assert.deepEqual(timeline.map(e => e.key), ['message-user', 'message-assistant']);
  assert.deepEqual(buildChatTimeline([], []), []);
});
