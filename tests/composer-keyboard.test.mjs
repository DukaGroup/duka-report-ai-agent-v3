import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const source = await readFile(new URL('../frontend/src/composerKeyboard.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {shouldCaptureTyping} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
globalThis.Element = class { constructor(selector=''){this.selector=selector;} closest(selectors){return selectors.includes(this.selector) && this.selector ? this : null;} };
const key = (overrides={}) => ({key:'a',target:new Element(),...overrides});
test('ordinary typing routes into composer, with accented text and Shift supported', () => {
  for(const letter of ['a','ë','Ç','1',' ']) assert.equal(shouldCaptureTyping(key({key:letter}), '', false),true);
  assert.equal(shouldCaptureTyping(key({key:'A',shiftKey:true}), '', false),true);
});
test('typing never steals other editors, modal input, selected text, IME, or shortcuts', () => {
  for(const selector of ['input','textarea','select','[role="textbox"]','[role="combobox"]','[role="menu"]','[contenteditable]'])
    assert.equal(shouldCaptureTyping(key({target:new Element(selector)}), '', false),false);
  for(const override of [{ctrlKey:true},{altKey:true},{metaKey:true},{isComposing:true},{defaultPrevented:true},{key:'Enter'},{key:'ArrowDown'},{key:'Tab'}])
    assert.equal(shouldCaptureTyping(key(override), '', false),false);
  assert.equal(shouldCaptureTyping(key(), '', true),false);
  assert.equal(shouldCaptureTyping(key(), 'selected text', false),false);
  assert.equal(shouldCaptureTyping(key({key:' ',target:new Element('button')}), '', false),false);
});
