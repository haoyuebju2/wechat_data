// Full built Nuxt + real backend + filesystem/WAL notifications + SSE + DOM.
// All account data and message text are synthetic and live in a temporary folder.
const {app,BrowserWindow,session}=require('electron');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const http=require('node:http');
const {secureSession}=require('../src/offline-session.cjs');
const {loadWithRedirect}=require('../src/renderer-startup.cjs');
const root=path.resolve(__dirname,'../../..');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'wechat-live-synthetic-'));
const token='synthetic-live-token-only'.padEnd(64,'0');
const origin='http://127.0.0.1:10392';
let backend,win;
let stage='startup';
let fixtureError='';
app.setPath('userData',path.join(temporary,'profile'));
app.commandLine.appendSwitch('disable-background-networking');
app.commandLine.appendSwitch('host-resolver-rules','MAP * ~NOTFOUND, EXCLUDE 127.0.0.1');
const timeout=setTimeout(()=>finish(1,'Synthetic live chat test timed out'),45000);
function api(url,method='GET'){
  return new Promise((resolve,reject)=>{
    const request=http.request(origin+url,{method,headers:{'X-Offline-Token':token}},response=>{
      let text='';response.on('data',chunk=>text+=chunk);response.on('end',()=>{
        if(response.statusCode!==200)return reject(new Error('Synthetic API HTTP '+response.statusCode));
        try{resolve(JSON.parse(text));}catch{reject(new Error('Invalid synthetic response'));}
      });
    });
    request.on('error',reject);request.setTimeout(3000,()=>request.destroy(new Error('Synthetic HTTP timeout')));request.end();
  });
}
async function waitFor(test,milliseconds=10000){
  const deadline=Date.now()+milliseconds;
  while(Date.now()<deadline){if(await test())return;await new Promise(resolve=>setTimeout(resolve,20));}
  throw new Error('Synthetic condition not reached at '+stage);
}
let finishing=false;
async function finish(code,message){
  if(finishing)return;finishing=true;clearTimeout(timeout);
  if(message)console.log(message);
  if(code&&fixtureError)console.log('Synthetic backend diagnostic: '+fixtureError.slice(-2500));
  if(code&&win&&!win.isDestroyed()){
    try{console.log('Synthetic fixture UI: '+(await win.webContents.executeJavaScript('document.body.innerText')).slice(-2500));}catch{}
  }
  if(win&&!win.isDestroyed())win.destroy();
  if(backend&&backend.exitCode===null){backend.kill();await new Promise(resolve=>{backend.once('exit',resolve);setTimeout(resolve,3000);});}
  // Only this freshly created, verified temporary folder is cleaned up.
  if(temporary.startsWith(os.tmpdir()+path.sep)&&path.basename(temporary).startsWith('wechat-live-synthetic-')){
    try{fs.rmSync(temporary,{recursive:true,force:true});}catch{}
  }
  app.exit(code);
}
app.whenReady().then(async()=>{
  backend=spawn(path.join(root,'.runtime/python.exe'),['-I','-B',path.join(__dirname,'live-chat-fixture.py')],{
    cwd:path.join(root,'upstream_local'),windowsHide:true,stdio:['ignore','ignore','pipe'],
    env:{...process.env,WECHAT_SYNTHETIC_DATA_DIR:temporary,WECHAT_TOOL_OFFLINE_TOKEN:token,WECHAT_TOOL_PORT:'10392'}
  });
  backend.stderr.on('data',chunk=>{fixtureError+=chunk.toString();});
  await waitFor(async()=>{try{return(await api('/api/health')).status==='healthy';}catch{return false;}},15000);
  const ses=session.fromPartition('synthetic-live-only',{cache:false});secureSession(ses,origin,token);
  win=new BrowserWindow({show:false,webPreferences:{session:ses,sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
  await loadWithRedirect(win,origin);
  await win.webContents.executeJavaScript("localStorage.setItem('ui.first_use_agreement',JSON.stringify({version:'2026-08-12.3',acceptedAt:new Date().toISOString()}));localStorage.setItem('ui.selected_account','wxid_live_test')");
  await loadWithRedirect(win,origin+'/chat/wxid_live_friend');
  stage='initial synthetic messages';
  await waitFor(()=>win.webContents.executeJavaScript("document.body.innerText.includes('普通文本消息')"));
  const committed=await api('/api/offline-test/commit','POST');
  stage='automatic DOM append';
  if(committed.event_stream_requests<1)throw new Error('No authenticated local event stream');
  await waitFor(()=>win.webContents.executeJavaScript("document.body.innerText.includes('SYNTHETIC_LIVE_MESSAGE_20261101')"),8000);
  const elapsed=Date.now()-committed.commit_epoch_ms;
  if(elapsed>2500)throw new Error('Synthetic commit-to-DOM latency exceeded 2.5s');
  await finish(0,JSON.stringify({passed:true,commit_to_dom_ms:Math.round(elapsed),event_stream_requests:committed.event_stream_requests,
    scope:'synthetic committed WAL to built chat DOM via real file watcher, backend and SSE; no manual refresh'}));
}).catch(error=>finish(1,error.message));
