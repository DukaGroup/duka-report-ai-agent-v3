import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import React from '../frontend/node_modules/react/index.js';
import { renderToStaticMarkup } from '../frontend/node_modules/react-dom/server.node.js';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const require=createRequire(new URL('../frontend/package.json',import.meta.url));
async function moduleUrl(file) {
  const source=await readFile(new URL('../frontend/src/'+file,import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText
    .replace(/from "([^"]+)"/g,(_,name)=>`from ${JSON.stringify(pathToFileURL(require.resolve(name)).href)}`);
  return `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
}
const { ActivityTimeline }=await import(await moduleUrl('ActivityTimeline.tsx'));
const { visibleActivity }=await import(await moduleUrl('conversationRuns.ts'));
const labels=['Kalimi te abonimi tjetër','Përditësim i kontekstit të bisedës','Lexim i kontekstit të bisedës','Rifillim i punës','Lexim i të dhënave','Llogaritje e rezultateve'];
const steps=labels.map((label,i)=>({id:String(i),label,kind:'tool'}));

test('working steps are hidden completely from business users, including saved history',()=>{
  const html=renderToStaticMarkup(React.createElement(ActivityTimeline,{steps,active:false}));
  assert.equal(html, '');
  assert.equal(renderToStaticMarkup(React.createElement(ActivityTimeline,{steps:steps.slice(0,4),active:true})), '');
});

test('Devs retain all configuration steps and technical status labels',()=>{
  const html=renderToStaticMarkup(React.createElement(ActivityTimeline,{steps,active:true,technical:true}));
  for(const label of labels) assert.ok(html.includes(label));
  assert.match(html,/<span>6<\/span>/);
  for(const label of ['Po kaloj te abonimi tjetër…','Po përditësoj bisedën…','Po rifilloj hetimin…','Po rilidhem…','Po arsyetoj…']) {
    assert.equal(visibleActivity(label), 'Po mendoj…');
    assert.equal(visibleActivity(label,true),label);
  }
  assert.equal(visibleActivity('Po llogaris…'),'Po llogaris…');
});

test('consecutive repeated jobs collapse to one row and a later repeat remains visible',()=>{
  const repeated=['Kontroll i të dhënave','Kontroll i të dhënave','Kontroll i të dhënave','Llogaritje e rezultateve','Kontroll i të dhënave','Kontroll i të dhënave'];
  const history=repeated.map((label,i)=>({id:String(i),label,kind:'tool'}));
  const html=renderToStaticMarkup(React.createElement(ActivityTimeline,{steps:history,active:true,technical:true}));
  assert.match(html,/<span>3<\/span>/);
  assert.equal((html.match(/Kontroll i të dhënave/g)||[]).length,2);
  assert.equal((html.match(/Llogaritje e rezultateve/g)||[]).length,1);
  assert.equal((html.match(/class="[^"]*\bspin\b[^"]*"/g)||[]).length,1);
});
