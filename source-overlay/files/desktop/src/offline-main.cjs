"use strict";
// Private offline desktop entry. It deliberately never imports upstream main.cjs.
const {app, BrowserWindow, ipcMain, dialog, session} = require("electron");
const {spawn} = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const {allowedUrl, secureSession, CSP} = require("./offline-session.cjs");
const {loadWithRedirect} = require("./renderer-startup.cjs");

const repo = path.resolve(__dirname, "../..");
const workspace = path.dirname(repo);
const python = path.join(workspace, ".upstream-runtime", "Scripts", "python.exe");
const port = 10392;
const origin = `http://127.0.0.1:${port}`;
const output = path.join(repo, "output");
const token = crypto.randomBytes(32).toString("hex");
let backend, window;
const batches = new Map();
app.commandLine.appendSwitch("disable-background-networking");
app.commandLine.appendSwitch("disable-component-update");
app.commandLine.appendSwitch("disable-sync");
app.commandLine.appendSwitch("dns-prefetch-disable");
app.commandLine.appendSwitch("disable-quic");
app.commandLine.appendSwitch("disable-features", "DnsOverHttps,MediaRouter,OptimizationHints");
app.commandLine.appendSwitch("force-webrtc-ip-handling-policy", "disable_non_proxied_udp");
app.commandLine.appendSwitch("host-resolver-rules", "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1");
app.setPath("userData", path.join(repo, "offline-profile"));
process.on("uncaughtException", () => { app.exit(1); });

function localPath(value) {
  const p = path.resolve(String(value || ""));
  if (p.startsWith("\\\\") || p.slice(2).includes(":")) throw new Error("Only local paths allowed");
  let current = p;
  while (true) {
    if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) throw new Error("Reparse paths disabled");
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return p;
}

function handle(channel, action) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!window || event.sender !== window.webContents || !allowedUrl(event.senderFrame?.url || "", origin)) throw new Error("Untrusted frame");
    return action(...args);
  });
}

function callLocalApi(route,method='GET',payload=null) {
  return new Promise((resolve,reject)=>{
    const body=payload===null?null:JSON.stringify(payload);
    const req=http.request(origin+route,{method,headers:{'X-Offline-Token':token,...(body?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}:{})}},res=>{
      let text='';res.setEncoding('utf8');res.on('data',chunk=>{text+=chunk;if(text.length>2_000_000)req.destroy();});
      res.on('end',()=>{try{const data=JSON.parse(text);if(res.statusCode>=400)reject(new Error('Local operation failed'));else resolve(data);}catch(error){reject(error);}});
    });
    req.setTimeout(30000,()=>req.destroy(new Error('Local operation timed out')));req.on('error',reject);if(body)req.write(body);req.end();
  });
}
function safeName(value) {return String(value||'page').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/^[. ]+|[. ]+$/g,'').slice(0,80)||'page';}
async function capturePng(options={}) {
  const viewport=window.getContentBounds();
  const x=Math.max(0,Math.round(Number(options.x)||0)),y=Math.max(0,Math.round(Number(options.y)||0));
  const width=Math.min(viewport.width-x,Math.round(Number(options.width)||0)),height=Math.min(viewport.height-y,Math.round(Number(options.height)||0));
  if(width<2||height<2)throw new Error('Invalid capture rectangle');
  let shot=await window.webContents.capturePage({x,y,width,height});
  const scale=Math.max(0.1,Math.min(4,Number(options.scale)||1));
  const outWidth=Math.min(8192,Math.max(1,Math.round(Number(options.outWidth)||width*scale)));
  const outHeight=Math.min(8192,Math.max(1,Math.round(Number(options.outHeight)||height*scale)));
  if(outWidth*outHeight>32_000_000)throw new Error('Capture dimensions too large');
  shot=shot.resize({width:outWidth,height:outHeight});return {buffer:shot.toPNG(),width:outWidth,height:outHeight};
}

function configureIpc() {
  handle("window:minimize", () => window.minimize());
  handle("window:toggleMaximize", () => { if(window.isMaximized()) window.unmaximize(); else window.maximize(); return window.isMaximized(); });
  handle("window:close", () => window.close());
  handle("window:isMaximized", () => window.isMaximized());
  handle("window:setTitleBarTheme", () => true);
  handle("app:isDebugEnabled", () => false);
  handle("app:getVersion", () => "2.10.0-local.1");
  handle("backend:getPort", () => ({port, source:"offline-policy"}));
  handle("backend:setPort", () => ({port, changed:false, offline:true}));
  handle("app:getAutoLaunch", () => false);
  handle("app:setAutoLaunch", () => false);
  handle("app:getCloseBehavior", () => "quit");
  handle("app:setCloseBehavior", () => "quit");
  handle("app:getOutputDir", () => output);
  handle("app:getOutputDirInfo", () => ({path:output, outputDir:output, defaultDir:output, isDefault:true}));
  handle("app:getOutputDirChangeProgress", () => ({running:false}));
  handle("app:setOutputDir", () => ({success:false, message:"当前离线版本固定使用项目内 output 目录"}));
  handle("app:openOutputDir", () => ({success:false, path:output, message:"请手动打开本机输出目录"}));
  handle("app:getAccountInfo", account => callLocalApi('/api/chat/account_info?account='+encodeURIComponent(String(account||''))));
  handle("app:deleteAccountData", account => callLocalApi('/api/chat/account?account='+encodeURIComponent(String(account||'')),'DELETE'));
  handle("app:captureRegion", async options => {
    const directory=localPath(path.join(output,'年度总结'));fs.mkdirSync(directory,{recursive:true});
    const shot=await capturePng(options);const destination=path.join(directory,Date.now()+'_'+safeName(options?.name)+'.png');
    fs.writeFileSync(destination,shot.buffer,{flag:'wx'});return {ok:true,path:destination,width:shot.width,height:shot.height};
  });
  handle("app:wrappedBatchBegin", () => {
    if(batches.size>=3)return {ok:false,error:'Too many local batches'};
    const batchId='wb_'+crypto.randomBytes(12).toString('hex');const directory=localPath(path.join(output,'年度总结',batchId));
    fs.mkdirSync(directory,{recursive:true});batches.set(batchId,{directory,count:0});return {ok:true,batchId};
  });
  handle("app:wrappedBatchCapture", async options => {
    const batch=batches.get(String(options?.batchId));if(!batch||batch.count>=100)return {ok:false,error:'Invalid local batch'};
    const shot=await capturePng(options);const index=Math.max(0,Math.min(999,Math.round(Number(options?.index)||0)));
    const destination=path.join(batch.directory,String(index).padStart(3,'0')+'_'+safeName(options?.name)+'.png');
    fs.writeFileSync(destination,shot.buffer,{flag:'wx'});batch.count++;return {ok:true,count:batch.count,width:shot.width,height:shot.height};
  });
  handle("app:wrappedBatchFinish", async options => {
    const batchId=String(options?.batchId),batch=batches.get(batchId);if(!batch)return {ok:false,error:'Invalid local batch'};
    const result=await callLocalApi('/api/offline/wrapped/zip','POST',{batch_id:batchId});
    if(path.dirname(path.resolve(batch.directory))!==path.resolve(output,'年度总结'))throw new Error('Invalid batch cleanup boundary');
    fs.rmSync(batch.directory,{recursive:true});batches.delete(batchId);return result;
  });
  handle("app:wrappedBatchAbort", options => {
    const batchId=String(options?.batchId),batch=batches.get(batchId);if(!batch)return {ok:true};
    if(path.dirname(path.resolve(batch.directory))!==path.resolve(output,'年度总结'))throw new Error('Invalid batch cleanup boundary');
    fs.rmSync(batch.directory,{recursive:true});batches.delete(batchId);return {ok:true};
  });
  handle("dialog:chooseDirectory", async options => {
    const result = await dialog.showOpenDialog(window, {title:String(options?.title || "选择本机目录"), properties:["openDirectory"]});
    return {canceled:result.canceled, filePaths:result.canceled ? [] : [localPath(result.filePaths[0])]};
  });
  handle("dialog:chooseArchive", async () => {
    const result = await dialog.showOpenDialog(window, {properties:["openFile"], filters:[{name:"Local archive", extensions:["zip"]}]});
    return {canceled:result.canceled, filePaths:result.canceled ? [] : [localPath(result.filePaths[0])]};
  });
  for (const channel of ["app:openExternalUrl", "app:checkForUpdates", "app:downloadAndInstall", "app:installUpdate", "app:ignoreUpdate"]) {
    handle(channel, () => ({enabled:false, hasUpdate:false, success:false, offline:true, message:"离线版本已关闭外部链接和在线更新"}));
  }
  // Renderer debug payloads may contain private text: intentionally discard them.
  ipcMain.on("debug:log", () => {});
}

async function health() {
  for(let i=0;i<150;i++) {
    if (backend.exitCode !== null) throw new Error("Backend stopped");
    const ready = await new Promise(resolve => {
      const req = http.get(origin+"/api/health", {headers:{"X-Offline-Token":token}}, res => {res.resume();resolve(res.statusCode===200);});
      req.setTimeout(500, () => {req.destroy();resolve(false);});
      req.on("error", () => resolve(false));
    });
    if(ready) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error("Backend startup timed out");
}

app.whenReady().then(async () => {
  if (process.env.WECHAT_OFFLINE_OS_POLICY !== "checked") throw new Error("Start using Start-Upstream-Offline.cmd after configuring OS isolation");
  if(!fs.existsSync(python) || !fs.existsSync(path.join(repo,"frontend/.output/public/index.html"))) throw new Error("Offline runtime or built UI missing");
  const privateSession = session.fromPartition("offline-private", {cache:false});
  await privateSession.setProxy({mode:"direct"});
  secureSession(privateSession, origin, token);
  fs.mkdirSync(output,{recursive:true});
  backend = spawn(python, ["-I", "-B", path.join(repo,"offline_backend.py")], {
    cwd:repo, windowsHide:true, stdio:"ignore",
    env:{...process.env, WECHAT_TOOL_OFFLINE_TOKEN:token, WECHAT_TOOL_PORT:String(port), WECHAT_TOOL_HOST:"127.0.0.1",
         WECHAT_TOOL_DATA_DIR:repo, WECHAT_TOOL_OUTPUT_DIR:output, HF_HUB_OFFLINE:"1", TRANSFORMERS_OFFLINE:"1"}
  });
  backend.on("error", () => app.exit(1));
  await health();
  window = new BrowserWindow({width:1280,height:860,minWidth:960,minHeight:640,title:"微信数据分析 · 本机离线版",
    webPreferences:{session:privateSession,preload:path.join(__dirname,"preload.cjs"),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true,webviewTag:false}});
  window.webContents.setWindowOpenHandler(() => ({action:"deny"}));
  window.webContents.on("will-navigate", (event,url) => {if(!allowedUrl(url,origin)) event.preventDefault();});
  window.webContents.on("will-attach-webview", event => event.preventDefault());
  configureIpc();
  await loadWithRedirect(window, origin);
  window.show();
  window.focus();
}).catch(() => {
  dialog.showErrorBox("离线版本未能启动", "请检查离线运行环境、前端构建和系统断网规则。不会自动降级为联网启动。");
  app.quit();
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => { if(backend && backend.exitCode===null) backend.kill(); });
