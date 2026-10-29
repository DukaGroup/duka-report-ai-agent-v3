import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/chatScroll.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { ChatScrollFollower } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function scroll() {
  return {
    scrollTop: 0, clientHeight: 300, scrollHeight: 1000, calls: 0,
    scrollTo({ top }) { this.scrollTop = top - this.clientHeight; this.calls++; },
  };
}

test('manual upward scrolling stops following streaming updates until the jump action', () => {
  const follower = new ChatScrollFollower();
  const viewport = scroll();
  follower.update(viewport, true);
  assert.equal(viewport.scrollTop, 700);
  follower.pause();
  viewport.scrollTop = 680;
  assert.equal(follower.observe(viewport), false);
  viewport.scrollHeight += 200;
  follower.update(viewport);
  assert.equal(viewport.scrollTop, 680);
  assert.equal(viewport.calls, 1);
  viewport.scrollTop = 850;
  assert.equal(follower.observe(viewport), false);
  viewport.scrollHeight += 100;
  follower.update(viewport);
  assert.equal(viewport.scrollTop, 850);
  follower.resume(viewport);
  assert.equal(viewport.scrollTop, 1000);
});

test('scrolling back down to the end resumes following and hides the jump button', () => {
  const follower = new ChatScrollFollower();
  const viewport = scroll();
  follower.update(viewport, true);
  viewport.scrollTop = 400;
  assert.equal(follower.observe(viewport), false);
  viewport.scrollTop = 698;
  assert.equal(follower.observe(viewport), true);
  viewport.scrollHeight += 100;
  follower.update(viewport);
  assert.equal(viewport.scrollTop, 800);
});

test('a conversation that fits on screen never keeps the jump button', () => {
  const follower = new ChatScrollFollower();
  const viewport = { ...scroll(), scrollHeight: 280 };
  follower.pause();
  follower.update(viewport);
  assert.equal(follower.following, true);
});

test('upward gesture near bottom stays paused; jump to latest and chat switch resume', () => {
  const follower = new ChatScrollFollower();
  const viewport = scroll();
  follower.update(viewport, true);
  follower.pause();
  viewport.scrollTop = 690;
  assert.equal(follower.observe(viewport), false);
  viewport.scrollHeight += 100;
  follower.update(viewport);
  assert.equal(viewport.scrollTop, 690);
  follower.resume(viewport);
  assert.equal(viewport.scrollTop, 800);
  follower.pause();
  follower.update(viewport, true);
  assert.equal(follower.following, true);
});

test('the jump button stays hidden while the last message is already in view', () => {
  const follower = new ChatScrollFollower();
  const viewport = scroll();
  follower.update(viewport, true);
  // Scrolling up at the very end (or a touch) pauses following...
  follower.pause();
  assert.equal(follower.showsJump(viewport), false);
  // ...and a few pixels above the end still counts as "at the last message".
  viewport.scrollTop = 650;
  follower.observe(viewport);
  assert.equal(follower.showsJump(viewport), false);
  // Only real content below brings the button back.
  viewport.scrollTop = 300;
  follower.observe(viewport);
  assert.equal(follower.showsJump(viewport), true);
});
