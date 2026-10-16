import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/subscriptionRecovery.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { recoverSubscription } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function environment(t) {
  const timers = new Map();
  let id = 0;
  t.mock.method(globalThis, 'setTimeout', (callback) => { timers.set(++id, callback); return id; });
  t.mock.method(globalThis, 'clearTimeout', (identifier) => timers.delete(identifier));
  const windowTarget = new EventTarget(), documentTarget = new EventTarget();
  documentTarget.visibilityState = 'visible';
  const previousWindow = globalThis.window, previousDocument = globalThis.document;
  globalThis.window = windowTarget;
  globalThis.document = documentTarget;
  t.after(() => { globalThis.window = previousWindow; globalThis.document = previousDocument; });
  return {
    timers, windowTarget, documentTarget,
    async tick() {
      assert.ok(timers.size, 'a retry must be scheduled');
      const [identifier, callback] = timers.entries().next().value;
      timers.delete(identifier);
      callback();
      await new Promise(setImmediate);
    },
  };
}

test('initial page startup checks immediately and retries when the backend becomes ready', async t => {
  const env = environment(t);
  let attempts = 0;
  const stop = recoverSubscription(async () => ++attempts === 2, 5000, true);
  assert.equal(attempts, 1);
  await new Promise(setImmediate);
  await env.tick();
  assert.equal(attempts, 2);
  assert.equal(env.timers.size, 0);
  stop();
});

test('an offline startup retries failed requests and routing until the saved account recovers', async t => {
  const env = environment(t);
  let attempts = 0;
  const stop = recoverSubscription(async () => {
    attempts++;
    if (attempts === 1) throw new Error('backend offline');
    return attempts === 3;
  });
  await env.tick();
  await env.tick();
  await env.tick();
  assert.equal(attempts, 3);
  assert.equal(env.timers.size, 0);
  env.windowTarget.dispatchEvent(new Event('online'));
  assert.equal(attempts, 3, 'stop retrying once connected');
  stop();
});

test('online and visible events retry promptly without overlapping an existing request', async t => {
  const env = environment(t);
  let attempts = 0, resolve;
  const stop = recoverSubscription(() => { attempts++; return new Promise(r => { resolve = r; }); });
  env.windowTarget.dispatchEvent(new Event('online'));
  env.documentTarget.dispatchEvent(new Event('visibilitychange'));
  env.windowTarget.dispatchEvent(new Event('online'));
  assert.equal(attempts, 1);
  assert.equal(env.timers.size, 0);
  resolve(false);
  await new Promise(setImmediate);
  assert.equal(env.timers.size, 1);
  stop();
  assert.equal(env.timers.size, 0);
});

test('closing the page cancels recovery even if an offline request is still pending', async t => {
  const env = environment(t);
  let resolve, attempts = 0;
  const stop = recoverSubscription(() => { attempts++; return new Promise(r => { resolve = r; }); });
  env.windowTarget.dispatchEvent(new Event('online'));
  stop();
  resolve(false);
  await new Promise(setImmediate);
  env.windowTarget.dispatchEvent(new Event('online'));
  env.documentTarget.dispatchEvent(new Event('visibilitychange'));
  assert.equal(attempts, 1);
  assert.equal(env.timers.size, 0);
});
