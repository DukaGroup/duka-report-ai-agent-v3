import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const source = await readFile(new URL('../frontend/src/uiScale.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replace(/from "([^"]+)"/g, (_, name) => `from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
const { zoomFor } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('laptops keep the normal size; larger screens grow the interface', () => {
  assert.equal(zoomFor(1366, 768), 1);
  assert.equal(zoomFor(1440, 900), 1);
  assert.equal(zoomFor(1920, 1080), 1.25);
  assert.equal(zoomFor(2560, 1440), 1.6);
  assert.equal(zoomFor(3840, 2160), 1.6);
});

test('a short, wide window is limited by its height so nothing gets cut off', () => {
  assert.equal(zoomFor(2560, 900), 1.0);
  assert.equal(zoomFor(1920, 1000), 1.15);
});
