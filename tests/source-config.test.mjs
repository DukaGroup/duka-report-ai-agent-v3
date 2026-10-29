import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import React from '../frontend/node_modules/react/index.js';
import {renderToStaticMarkup} from '../frontend/node_modules/react-dom/server.node.js';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
async function moduleUrl(file,imports={}){
 const source=await readFile(new URL('../frontend/src/'+file,import.meta.url),'utf8');
 const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}}).outputText.replace(/from "([^"]+)"/g,(_,name)=>`from ${JSON.stringify(imports[name]||pathToFileURL(require.resolve(name)).href)}`);
 return `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
}
const {SourceConnectionForm}=await import(await moduleUrl('SourceConnectionForm.tsx',{'./Select':await moduleUrl('Select.tsx',{'./uiScale':await moduleUrl('uiScale.ts')})}));
const {errorMessage}=await import(await moduleUrl('locale.ts'));
test('old HANA policy errors identify an outdated backend',()=>{
 const message=errorMessage('Production HANA connections require encryption and certificate validation.');
 assert.match(message,/Përditësoni backend/);
 assert.match(message,/Kriptimin TLS/);
 assert.match(message,/Verifikimin e certifikatës/);
 assert.doesNotMatch(message,/Production HANA/);
});
const noop=()=>{};
function source(kind,origin='saved'){
 const prefix=kind==='saphana'?'HANA':'SQLSERVER';
 return {id:'fixture',name:'Connection fixture',kind,status:'connected',description:'',configuration_origin:origin,env_prefix:'PRIVATE_PROFILE_',connection_fields:Object.fromEntries(['HOST','PORT','USER','PASSWORD','DATABASE'].map(k=>[prefix+'_'+k,true])),tls:{encrypt:true,validate_certificate:true,custom_ca:true,server_name_configured:true}};
}
function render(props={}){return renderToStaticMarkup(React.createElement(SourceConnectionForm,{source:null,kind:'sqlserver',summary:false,discovery:true,saving:false,onKindChange:noop,onEdit:noop,onCancelEdit:noop,onDiscoveryChange:noop,onClose:noop,onSubmit:noop,...props}));}
const input=(html,name)=>html.match(new RegExp(`<input[^>]*name="${name}"[^>]*>`))?.[0];
test('existing environment and saved connections show status without posting credential or TLS fields',()=>{
 for(const kind of ['sqlserver','saphana'])for(const origin of ['environment','saved']){
  const html=render({source:source(kind,origin),kind,summary:true});
  assert.match(html,/Ndrysho konfigurimin/);assert.match(html,/E konfiguruar/);
  for(const name of ['SQLSERVER_HOST','SQLSERVER_PORT','SQLSERVER_USER','SQLSERVER_PASSWORD','SQLSERVER_DATABASE','HANA_HOST','HANA_PORT','HANA_USER','HANA_PASSWORD','HANA_DATABASE','HANA_ENCRYPT','HANA_VALIDATE_CERTIFICATE','HANA_TLS_CA_CERTIFICATE','HANA_TLS_SERVER_NAME'])assert.equal(input(html,name),undefined);
  assert.doesNotMatch(html,/<textarea[^>]*name="HANA_/);
  assert.match(html,/role="combobox"[^>]*disabled=""/);
 }
});
test('editing a saved HANA connection leaves credentials blank, retains TLS choices and keeps optional certificate inputs collapsed',()=>{
 const saved=source('saphana');saved.tls.encrypt=false;saved.tls.validate_certificate=false;
 const html=render({source:saved,kind:'saphana',discovery:false});
 for(const name of ['HANA_HOST','HANA_USER','HANA_PASSWORD','HANA_PORT','HANA_DATABASE']){
  assert.ok(input(html,name));assert.doesNotMatch(input(html,name),/required=|value="[^\"]+"/);
 }
 assert.match(input(html,'HANA_ENCRYPT'),/value="false"/);assert.match(input(html,'HANA_VALIDATE_CERTIFICATE'),/value="false"/);
 assert.match(html,/<details class="source-certificate-options">/);assert.doesNotMatch(html,/<details[^>]*open/);
 assert.match(html,/Anulo ndryshimet e lidhjes/);assert.match(html,/Certifikata është ruajtur/);
});
test('new connections require credentials, default to their correct port and use custom dropdowns',()=>{
 for(const [kind,prefix,port] of [['sqlserver','SQLSERVER','1433'],['saphana','HANA','30015']]){
  const html=render({kind});
  for(const key of ['HOST','USER','PASSWORD','PORT'])assert.match(input(html,prefix+'_'+key),/required=""/);
  assert.match(input(html,prefix+'_PORT'),new RegExp(`value="${port}"`));
  assert.equal(input(html,prefix+'_DATABASE'),undefined);assert.doesNotMatch(html,/<select\b/);
 }
});
test('both database forms offer optional certificates and unverified TLS by default',()=>{
 for(const [kind,prefix] of [['sqlserver','SQLSERVER'],['saphana','HANA']]){
  const html=render({kind});
  assert.match(input(html,prefix+'_VALIDATE_CERTIFICATE'),/value="false"/);
  assert.match(html,new RegExp(`<textarea[^>]*name="${prefix}_TLS_CA_CERTIFICATE"`));
  assert.ok(input(html,prefix+'_TLS_SERVER_NAME'));
  assert.match(html,/Certifikata është opsionale/);
  assert.match(html,/identiteti i serverit nuk kontrollohet/);
  assert.match(html,/aktivizon gjithmonë TLS dhe verifikimin/);
 }
 const sql=render({kind:'sqlserver'});
 assert.match(input(sql,'SQLSERVER_ENCRYPTION'),/value="require"/);
});

test('changing database type requires its new port and never exposes fields for the old engine',()=>{
 const html=render({source:source('sqlserver'),kind:'saphana'});
 assert.match(input(html,'HANA_PORT'),/required=""/);assert.doesNotMatch(input(html,'HANA_HOST'),/required=""/);
 assert.equal(input(html,'SQLSERVER_HOST'),undefined);
});

test('an existing environment connection supports a single-field edit for either driver',()=>{
 for(const kind of ['sqlserver','saphana']){
  const prefix=kind==='saphana'?'HANA':'SQLSERVER';const html=render({source:source(kind,'environment'),kind});
  for(const field of ['HOST','PORT','USER','PASSWORD'])assert.doesNotMatch(input(html,prefix+'_'+field),/required=""/);
  assert.match(html,/Plotësoni vetëm vlerat/);
 }
});
const {SelectionToolbar}=await import(await moduleUrl('SelectionToolbar.tsx',{'./IconButton':await moduleUrl('IconButton.tsx')}));
test('report and trash selection toolbars require a selection and distinguish permanent deletion',()=>{
 for(const permanent of [false,true])for(const selected of [0,1,3]){
  const html=renderToStaticMarkup(React.createElement(SelectionToolbar,{available:3,selected,busy:false,permanent,onToggleAll:noop,onClear:noop,onDelete:noop}));
  assert.match(html,/type="checkbox"/);assert.match(html,new RegExp(`${selected} të zgjedhura`));
  const action=html.match(/<button[^>]*class="button danger small"[^>]*>/)[0];
  assert.equal(action.includes('disabled=""'),selected===0);
  assert.match(action,permanent?/Fshi përgjithmonë raportet e zgjedhura/:/Fshi raportet e zgjedhura/);
  assert.equal(/<input[^>]*checked=""/.test(html),selected===3);
 }
});

test('conversation selection shares report controls with conversation-specific labels',()=>{
  for(const busy of [false,true]){
    const html=renderToStaticMarkup(React.createElement(SelectionToolbar,{kind:'conversations',available:3,selected:2,busy,onToggleAll:noop,onClear:noop,onDelete:noop}));
    assert.match(html,/Përzgjedhja e bisedave/);
    assert.match(html,/Fshi bisedat e zgjedhura/);
    assert.match(html,/2 të zgjedhura/);
    assert.equal((html.match(/disabled=""/g)||[]).length,busy?3:0);
  }
});

test('conversation selection clearly labels irreversible deletion without a trash view',()=>{
  const html=renderToStaticMarkup(React.createElement(SelectionToolbar,{kind:'conversations',permanent:true,available:2,selected:1,busy:false,onToggleAll:noop,onClear:noop,onDelete:noop}));
  assert.match(html,/Përzgjedhja e bisedave/);assert.doesNotMatch(html,/bisedave në kosh/);
  assert.match(html,/Fshi përgjithmonë bisedat e zgjedhura/);
});

test('bulk restore appears only in Trash and requires a nonbusy selection',()=>{
  for(const permanent of [false,true])for(const selected of [0,2])for(const busy of [false,true]){
    const html=renderToStaticMarkup(React.createElement(SelectionToolbar,{kind:'conversations',permanent,available:3,selected,busy,onToggleAll:noop,onClear:noop,onDelete:noop,onRestore:noop,restoring:busy}));
    const button=html.match(/<button[^>]*aria-label="Rikthe bisedat e zgjedhura"[^>]*>/)?.[0];
    assert.equal(!!button,permanent);
    if(button)assert.equal(button.includes('disabled=""'),!selected||busy);
  }
});
