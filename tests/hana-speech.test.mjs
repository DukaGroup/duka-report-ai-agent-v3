import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/hanaSpeech.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { syllables, planSpeech, mouthAt, PACE, stepSpring, transitionTiming } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const split = (word) => syllables(word).map(([a, b]) => word.slice(a, b)).join('-');

test('intro has 1.3-second moonrise and 1.2-second transformation without changing logout', () => {
  for (const mode of ['presentation','greeting','farewell']) {
    const timing=transitionTiming(mode);
    assert.equal(timing.rise,mode==='farewell'?0:1300);
    assert.equal(timing.transformation,mode==='farewell'?1000:1200);
    assert.equal(timing.speechEnd-timing.speechStart,1700);
    assert.equal(timing.speechStart,mode==='farewell'?0:2500);
    assert.equal(timing.total,mode==='farewell'?2700:4450);
    assert.deepEqual(transitionTiming(mode,true),{rise:0,transformation:0,speechStart:0,speechEnd:1700,total:1700});
  }
});

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
  // A brisk but still natural pace: roughly 6 to 10 syllables per second.
  const rate = plan.syllables.length / (plan.total / 1000);
  assert.ok(rate > 5 && rate < 11, `rate ${rate}`);
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

test('the mouth spring stays smooth at low frame rates and closes without bouncing', () => {
  for (const fps of [20,30,60,120]) {
    let position=0,velocity=0;
    for(let i=0;i<fps;i++) {
      const next=stepSpring(position,velocity,0.8,40,1/fps);
      assert.ok(next.position>=position-1e-10 && next.position<=0.8+1e-10);
      ({position,velocity}=next);
    }
    assert.ok(Math.abs(position-0.8)<1e-6);
    for(let i=0;i<fps;i++) {
      const next=stepSpring(position,velocity,0,40,1/fps);
      assert.ok(next.position<=position+1e-10 && next.position>=-1e-10);
      ({position,velocity}=next);
    }
    assert.ok(position<1e-6);
  }
});
