import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import React from '../frontend/node_modules/react/index.js';
import { renderToStaticMarkup } from '../frontend/node_modules/react-dom/server.node.js';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const source = await readFile(new URL('../frontend/src/MarkdownContent.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
} }).outputText.replace(/from "([^"]+)"/g, (_, name) => `from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
const { MarkdownContent } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
export const renderMarkdown = content => renderToStaticMarkup(React.createElement(MarkdownContent, { children: content }));
export const example = `| Përshkrimi | Llogaritja ime (ALL) | Raporti i financës (ALL) | Diferenca (ALL) |
|---|---:|---:|---:|
| Klientë | 564.219.019,60 | 559.985.039,38 | **4.233.980,22** |
| Furnitorë | 764.495.598,89 | 763.181.106,26 | **1.314.492,63** |`;

test('chat and report Markdown produces semantic tables with aligned financial values', () => {
  const html = renderMarkdown(example);
  assert.match(html, /<table>/);
  assert.equal((html.match(/<th(?: |\>)/g) || []).length, 4);
  assert.equal((html.match(/<tr>/g) || []).length, 3);
  assert.equal((html.match(/class="numeric"/g) || []).length, 6);
  assert.match(html, /<strong>4\.233\.980,22<\/strong>/);
  assert.match(html, /<strong>1\.314\.492,63<\/strong>/);
  assert.match(html, /role="region" aria-label="Tabelë e përgjigjes" tabindex="0"/);
});

test('tables retain empty cells, escaped pipes, paragraphs and code', () => {
  const html = renderMarkdown('Before\n\n| Name | Value |\n|---|---:|\n| A \\| B | |\n\nAfter\n\n```text\n| literal | pipes |\n```');
  assert.match(html, /<p>Before<\/p>/);
  assert.match(html, /A \| B/);
  assert.match(html, /<td[^>]*><\/td>/);
  assert.match(html, /<p>After<\/p>/);
  assert.match(html, /<pre><code/);
  assert.equal((html.match(/<table>/g) || []).length, 1);
});

test('raw HTML and unsafe links remain untrusted inside tables', () => {
  const html = renderMarkdown('| Content |\n|---|\n| <script>alert(1)</script> |\n| [link](javascript:alert(1)) |');
  assert.doesNotMatch(html, /<script>|href="javascript:|onclick=/i);
  assert.match(html, /<table>/);
});
