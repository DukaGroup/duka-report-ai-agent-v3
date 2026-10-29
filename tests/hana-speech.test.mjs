import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/hanaSpeech.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { syllables, planSpeech, mouthAt, PACE } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const split = (word) => syllables(word).map(([a, b]) => word.slice(a, b)).join('-');

test('Albanian words split into natural syllables', () => {
  assert.equal(split('Përshëndetje'), 'Për-shën-det-je');
  assert.equal(split('asistentja'), 'a-sis-ten-tja');
  assert.equal(split('Mirupafshim'), 'Mi-ru-paf-shim');
  assert.equal(split('jam'), 'jam');
});

test('letters appear in order and the whole sentence is shown by the end', () => {
  const text = 'Unë jam Hana, asistentja juaj.';
  const plan = planSpeech(text, PACE.presentation);
  assert.equal(plan.reveal.length, text.length);
  for (let i = 1; i < plan.reveal.length; i++) assert.ok(plan.reveal[i] >= plan.reveal[i - 1]);
  assert.ok(plan.reveal.at(-1) <= plan.total + PACE.presentation.stop);
  // A lively but natural pace: roughly 4 to 7 syllables per second.
  const rate = plan.syllables.length / (plan.total / 1000);
  assert.ok(rate > 3.5 && rate < 7.5, `rate ${rate}`);
});

test('the mouth closes during pauses and for m, b and p', () => {
  const plan = planSpeech('Mirë, mirë.', PACE.greeting);
  const comma = plan.reveal[4];
  // In the middle of the comma pause the mouth is shut.
  assert.equal(mouthAt(plan, comma + PACE.greeting.comma / 2).open, 0);
  // "Mi" starts with closed lips.
  assert.equal(mouthAt(plan, 0).open, 0);
  // and opens on its vowel.
  const first = plan.syllables[0];
  assert.ok(mouthAt(plan, (first.start + first.end) / 2).open > 0.2);
});

test('rounded vowels round the lips', () => {
  const plan = planSpeech('Ju', PACE.greeting);
  const s = plan.syllables[0];
  assert.ok(mouthAt(plan, (s.start + s.end) / 2).round > 0.5);
});
