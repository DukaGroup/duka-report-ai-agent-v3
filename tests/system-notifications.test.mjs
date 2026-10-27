import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {MessageChannel} from 'node:worker_threads';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const source=await readFile(new URL('../frontend/src/deviceNotifications.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/import \{ api \} from "\.\/api";/,'const api=(...args)=>globalThis.deviceTestApi(...args);');
const device=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
function environment() {
  const values=new Map(),calls=[],order=[];
  const subscription={endpoint:'https://fcm.googleapis.com/fcm/send/test',options:{},unsubscribed:0,toJSON(){return {endpoint:this.endpoint,keys:{p256dh:'fixture',auth:'fixture'}};},async unsubscribe(){this.unsubscribed++;}};
  const registration={pushManager:{async getSubscription(){return subscription;},async subscribe(){return subscription;}},async getNotifications(){return [{close(){order.push('closed');}}];}};
  globalThis.window={isSecureContext:true,Notification:{},PushManager:class{}};
  globalThis.Notification={permission:'default',async requestPermission(){order.push('permission');this.permission='granted';return this.permission;}};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{serviceWorker:{ready:Promise.resolve(registration),async register(){order.push('register');return registration;},async getRegistration(){return registration;}}}});
  globalThis.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  globalThis.deviceTestApi=async(path,options)=>{calls.push([path,options]);order.push(path);return path.endsWith('/config')?{public_key:btoa('a'.repeat(65)).replace(/=+$/,'')}:{enabled:true};};
  return {values,calls,order,subscription};
}
test('system notification permission is requested only from explicit enable, before asynchronous work',async()=>{
  const env=environment();
  assert.equal(await device.restoreDeviceNotifications('alice'),false);
  assert.deepEqual(env.order,[]);
  assert.equal(await device.enableDeviceNotifications('alice'),true);
  assert.equal(env.order[0],'permission');
  assert.equal(env.calls[1][0],'/notifications/subscriptions');
  assert.equal(JSON.parse(env.calls[1][1].body).endpoint,env.subscription.endpoint);
  assert.equal(env.values.get('duka.deviceNotifications.alice'),'true');
});
test('notification opt-in is per member; restoring never prompts or opts another account in',async()=>{
  const env=environment();await device.enableDeviceNotifications('alice');env.order.length=0;env.calls.length=0;
  assert.equal(await device.restoreDeviceNotifications('bob'),false);assert.deepEqual(env.calls,[]);
  assert.equal(await device.restoreDeviceNotifications('alice'),true);assert.ok(!env.order.includes('permission'));
});
test('denied permission and unsupported contexts never subscribe or prevent normal chat',async()=>{
  const env=environment();Notification.requestPermission=async()=> 'denied';
  await assert.rejects(device.enableDeviceNotifications('alice'),/nuk u lejuan/);assert.deepEqual(env.calls,[]);
  window.isSecureContext=false;
  assert.equal(device.supportsDeviceNotifications(),false);
  await assert.rejects(device.enableDeviceNotifications('alice'),/HTTPS/);
});
test('disabling removes server delivery, unsubscribes the browser and closes old system notices',async()=>{
  const env=environment();await device.enableDeviceNotifications('alice');
  assert.equal(await device.disableDeviceNotifications('alice'),false);
  assert.equal(env.calls.at(-1)[1].method,'DELETE');assert.equal(env.subscription.unsubscribed,1);
  assert.equal(env.values.get('duka.deviceNotifications.alice'),'false');assert.ok(env.order.includes('closed'));
});
const workerSource=await readFile(new URL('../frontend/public/notification-worker.js',import.meta.url),'utf8');
function worker({owner='alice',reading=false,existing=false,reportCount=0,ready=true,audio=false,tabCount=1,soundReply=true}={}) {
  const listeners={},shown=[],opened=[],sent=[],entries=new Map();let closes=0,focuses=0;
  const client={url:'https://duka.test/',focused:reading,visibilityState:reading?'visible':'hidden',
    async focus(){focuses++;return this;},async navigate(url){opened.push(url);},
    postMessage(message,ports){if(message.type==='duka-notification-state')ports[0].postMessage({userId:owner,page:'chat',conversationId:reading?'chat-a':'other'});else {sent.push(message);if(message.type==='duka-notification-sound'&&soundReply)ports[0].postMessage({played:audio});}}};
  const cache={async match(key){return entries.get(key);},async put(key,value){entries.set(key,value);},async keys(){return [...entries.keys()];},async delete(key){return entries.delete(key);}};
  const self={location:{origin:'https://duka.test'},addEventListener:(type,cb)=>listeners[type]=cb,
    clients:{async claim(){},async matchAll(){return existing||reading?Array.from({length:tabCount},()=>client):[];},async openWindow(url){opened.push(url);}},
    registration:{async showNotification(title,options){shown.push({title,options});}},async skipWaiting(){}};
  vm.runInNewContext(workerSource,{self,URL,MessageChannel,Response,setTimeout,clearTimeout,caches:{async open(){return cache;}},fetch:async()=>({ok:ready,async json(){return {userId:owner,conversationId:'chat-a',messageId:'reply-a',reportCount};}})});
  const payload={type:'reply-completed',userId:'alice',conversationId:'chat-a',messageId:'reply-a'};
  async function push(data=payload){let promise;listeners.push({data:{json:()=>data},waitUntil(p){promise=p;}});await promise;}
  async function click(data=payload){let promise;listeners.notificationclick({notification:{data,close(){closes++;}},waitUntil(p){promise=p;}});await promise;}
  return {listeners,shown,opened,sent,push,click,get focuses(){return focuses;},get closes(){return closes;}};
}
test('background push dispatches a system notification with generic Albanian text and OS sound enabled',async()=>{
  const w=worker();await w.push();
  assert.equal(w.shown.length,1);assert.equal(w.shown[0].title,'Hana');
  assert.equal(w.shown[0].options.icon,'/brand/hana-avatar.png');
  assert.match(w.shown[0].options.body,/Përgjigjja juaj është gati/);
  assert.equal(w.shown[0].options.silent,false);
  assert.equal(w.shown[0].options.tag,'duka-reply-reply-a');
  await w.push();assert.equal(w.shown.length,1);
  assert.equal(w.listeners.fetch,undefined); // Business pages and API responses never enter an offline cache.
});
test('system push is suppressed for a different member, a currently read reply or a malformed target',async()=>{
  const other=worker({owner:'bob'});await other.push();assert.equal(other.shown.length,0);
  const reading=worker({reading:true});await reading.push();assert.equal(reading.shown.length,0);
  const bad=worker();await bad.push({type:'reply-completed',userId:'alice',conversationId:'https://attacker.test',messageId:'r'});assert.equal(bad.shown.length,0);
});
test('clicking a system alert focuses an existing app and opens the owned conversation without discarding drafts',async()=>{
  const w=worker({existing:true});await w.click();
  assert.equal(w.focuses,1);assert.equal(w.closes,1);
  assert.equal(w.sent[0].type,'duka-open-conversation');assert.equal(w.sent[0].conversationId,'chat-a');
  assert.deepEqual(w.opened,[]);
});
test('a system alert can reopen the app; the destination stays on its origin and the app rechecks ownership',async()=>{
  const w=worker();await w.click();
  const url=new URL(w.opened[0]);assert.equal(url.origin,'https://duka.test');
  assert.equal(url.searchParams.get('conversation'),'chat-a');assert.equal(url.searchParams.get('notification_user'),'alice');
  const bad=worker();await bad.click({userId:'alice',conversationId:'../evil'});assert.equal(bad.opened.length,0);
});


test('system report alerts use report-ready wording and never show while exports remain unavailable',async()=>{
  const pending=worker({ready:false});await pending.push();assert.equal(pending.shown.length,0);
  const one=worker({reportCount:1});await one.push();assert.match(one.shown[0].options.body,/Raporti juaj është gati/);
  const several=worker({reportCount:2});await several.push();assert.match(several.shown[0].options.body,/Raportet tuaja janë gati/);
});


test('ready report push plays the app chime once across multiple background tabs and suppresses a second OS sound',async()=>{
  const w=worker({existing:true,audio:true,tabCount:3,reportCount:1});await w.push();
  assert.equal(w.sent.filter(m=>m.type==='duka-notification-sound').length,1);
  assert.equal(w.shown.length,1);assert.equal(w.shown[0].options.silent,true);
  assert.match(w.shown[0].options.body,/Raporti juaj është gati/);
  await w.push();assert.equal(w.sent.length,1);assert.equal(w.shown.length,1);
});
test('blocked, closed or suspended app audio uses the OS sound; a missing sound acknowledgement cannot block the alert',async()=>{
  for(const settings of [{},{existing:true},{existing:true,soundReply:false}]){
    const w=worker(settings);await w.push();assert.equal(w.shown.length,1);assert.equal(w.shown[0].options.silent,false);
  }
});
test('pending reports, another member and a conversation already being read never request a chime',async()=>{
  for(const settings of [{existing:true,ready:false},{existing:true,owner:'bob'},{reading:true}]){
    const w=worker({...settings,audio:true});await w.push();assert.equal(w.sent.length,0);assert.equal(w.shown.length,0);
  }
});
