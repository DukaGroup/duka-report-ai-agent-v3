import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

let version = 0;
async function compile(name) {
  const source = await readFile(new URL(`../frontend/src/${name}.ts`, import.meta.url), 'utf8');
  const result = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(result).toString('base64')}#${version++}`);
}

function environment(t, {dark = false, stored = null, blocked = false} = {}) {
  const previous = Object.fromEntries(['window','document','localStorage'].map(key=>[key,globalThis[key]]));
  const cleanups = [];
  const events = new EventTarget();
  const query = Object.assign(new EventTarget(), {matches:dark});
  const values = new Map(stored === null ? [] : [['duka.theme',stored]]);
  globalThis.window = {matchMedia:()=>query,addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events)};
  globalThis.document = {documentElement:{dataset:{},style:{}}};
  globalThis.localStorage = {
    getItem:key=>{if(blocked)throw new Error('Storage disabled');return values.get(key)??null;},
    setItem:(key,value)=>{if(blocked)throw new Error('Storage disabled');values.set(key,value);},
  };
  t.after(()=>{for(const cleanup of cleanups)cleanup();for(const key of Object.keys(previous)) {if(previous[key]===undefined)delete globalThis[key];else globalThis[key]=previous[key];}});
  return {query,values,events,root:document.documentElement,onCleanup:cleanup=>cleanups.unshift(cleanup)};
}

test('System follows live device changes, while an explicit theme overrides them',async t=>{
  const {query,root,values,onCleanup}=environment(t);
  const theme=await compile('theme');
  onCleanup(theme.initializeTheme());
  assert.equal(root.dataset.theme,'light');
  query.matches=true;query.dispatchEvent(new Event('change'));
  assert.equal(root.dataset.theme,'dark');
  assert.equal(root.style.colorScheme,'dark');
  theme.setThemePreference('light');
  assert.equal(values.get('duka.theme'),'light');
  query.dispatchEvent(new Event('change'));
  assert.equal(root.dataset.theme,'light');
  theme.setThemePreference('system');
  assert.equal(root.dataset.theme,'dark');
  assert.equal(theme.themeSnapshot(),'system:dark');
});

test('Saved choices apply before rendering and survive a fresh initialization',async t=>{
  const {root,values,onCleanup}=environment(t,{stored:'dark'});
  const first=await compile('theme');
  const stop=first.initializeTheme();
  assert.equal(root.dataset.theme,'dark');
  first.setThemePreference('light');
  stop();
  const fresh=await compile('theme');
  onCleanup(fresh.initializeTheme());
  assert.equal(values.get('duka.theme'),'light');
  assert.equal(fresh.themeSnapshot(),'light:light');
});

test('Theme changes work when browser storage is unavailable',async t=>{
  const {root,onCleanup}=environment(t,{blocked:true,dark:true});
  const theme=await compile('theme');
  onCleanup(theme.initializeTheme());
  theme.setThemePreference('light');
  assert.equal(root.dataset.theme,'light');
  theme.setThemePreference('dark');
  assert.equal(root.dataset.theme,'dark');
});

test('Invalid preferences fall back to System and changes synchronize between tabs',async t=>{
  const {root,events,onCleanup}=environment(t,{stored:'corrupt',dark:true});
  const theme=await compile('theme');
  onCleanup(theme.initializeTheme());
  assert.equal(theme.themeSnapshot(),'system:dark');
  let notifications=0;
  const stop=theme.subscribeTheme(()=>notifications++);
  events.dispatchEvent(Object.assign(new Event('storage'),{key:'unrelated',newValue:'light'}));
  assert.equal(notifications,0);
  events.dispatchEvent(Object.assign(new Event('storage'),{key:'duka.theme',newValue:'light'}));
  assert.equal(root.dataset.theme,'light');
  assert.equal(notifications,1);
  events.dispatchEvent(Object.assign(new Event('storage'),{key:null,newValue:null}));
  assert.equal(theme.themeSnapshot(),'system:dark');
  stop();
});

test('Settings keeps system configuration Devs-only and member management President-accessible',async()=>{
  const {settingsSections}=await compile('settings');
  assert.deepEqual(settingsSections('manager').map(s=>s.id),['appearance']);
  assert.deepEqual(settingsSections('president').map(s=>s.id),['appearance','members']);
  assert.deepEqual(settingsSections('devs').map(s=>s.id),['appearance','account','models','sources','members','overview','traffic','logs','activity']);
  assert.deepEqual(settingsSections('unknown').map(s=>s.id),['appearance']);
});
