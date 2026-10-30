import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

async function load(file) {
  const source = await readFile(new URL(`../frontend/src/${file}`, import.meta.url), 'utf8');
  // Only the pure helpers are needed; drop the JSX components and CSS.
  const helpers = source.slice(0, source.indexOf('export function AnswerChart') > 0 ? source.indexOf('export function AnswerChart') : source.indexOf('// A state is shown'));
  const js = ts.transpileModule(helpers.replace(/^import .*$/gm, ''), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
}
const { parseFigure, chartFromTable } = await load('AnswerChart.tsx');

test('figures in Albanian and English formats are read correctly', () => {
  assert.equal(parseFigure('1.234.567'), 1234567);
  assert.equal(parseFigure('1.234.567,89 ALL'), 1234567.89);
  assert.equal(parseFigure('1,234,567.5'), 1234567.5);
  assert.equal(parseFigure('42,1%'), 42.1);
  assert.equal(parseFigure('−3 200'), -3200);
  assert.equal(parseFigure('Tirana'), null);
});

const cell = (tag, value) => ({ type: 'element', tagName: tag, children: [{ type: 'text', value }] });
const row = (tag, values) => ({ type: 'element', tagName: 'tr', children: values.map((v) => cell(tag, v)) });
const table = (head, rows) => ({ type: 'element', tagName: 'table', children: [
  { type: 'element', tagName: 'thead', children: [row('th', head)] },
  { type: 'element', tagName: 'tbody', children: rows.map((r) => row('td', r)) },
] });

test('a table of figures becomes a chart; the total row is left out', () => {
  const chart = chartFromTable(table(['Qyteti', 'Shitjet (ALL)'], [['Tirana', '520.000'], ['Durrësi', '310.000'], ['Totali', '830.000']]));
  assert.equal(chart.series, 'Shitjet (ALL)');
  assert.deepEqual(chart.points.map((p) => p.value), [520000, 310000]);
  assert.equal(chart.periods, false);
});

test('months are drawn as a trend; text-only tables get no chart', () => {
  const months = chartFromTable(table(['Muaji', 'Shitjet'], [['Janar', '10'], ['Shkurt', '12'], ['Mars', '15']]));
  assert.equal(months.periods, true);
  assert.equal(chartFromTable(table(['Emri', 'Roli'], [['A', 'x'], ['B', 'y']])), null);
});

test("Hana's pose follows what she is doing", async () => {
  const source = await readFile(new URL('../frontend/src/HanaStage.tsx', import.meta.url), 'utf8');
  const start = source.indexOf('export function stageFromActivity');
  const fn = source.slice(start, source.indexOf('\n}\n', start) + 2);
  const js = ts.transpileModule(fn, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
  const { stageFromActivity } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  assert.equal(stageFromActivity('Po kërkoj në internet…'), 'searching');
  assert.equal(stageFromActivity('Po kontrolloj të dhënat…'), 'analyzing');
  assert.equal(stageFromActivity('Po përgatis raportin…'), 'report');
  assert.equal(stageFromActivity('Po shkruaj…'), 'writing');
  assert.equal(stageFromActivity('Po mendoj…'), 'thinking');
});
