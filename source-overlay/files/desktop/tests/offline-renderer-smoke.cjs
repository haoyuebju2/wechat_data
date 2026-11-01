// Development test only. Renders public UI + synthetic HTTP responses, no account files.
const {app,BrowserWindow,session}=require('electron');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {secureSession}=require('../src/offline-session.cjs');
const {loadWithRedirect}=require('../src/renderer-startup.cjs');
app.commandLine.appendSwitch('disable-background-networking');
app.commandLine.appendSwitch('host-resolver-rules','MAP * ~NOTFOUND, EXCLUDE 127.0.0.1');
app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'wechat-render-synthetic-')));
const publicDir=path.resolve(__dirname,'../../frontend/.output/public');
let server,win;
const token='synthetic-renderer-only-token';
let authenticated=0;
const timeout=setTimeout(()=>{console.error('Renderer test timed out');app.exit(1);},30000);
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    if(req.headers['x-offline-token']!==token){res.writeHead(403);res.end();return;}
    authenticated++;
    const pathname=new URL(req.url,'http://127.0.0.1').pathname;
    if(pathname.startsWith('/api/')){
      res.setHeader('Content-Type','application/json');
      res.end(JSON.stringify({status:'success',accounts:[],sessions:[],contacts:[],offline:true,enabled:false,capabilities:{}}));return;
    }
    const file=path.resolve(publicDir,'.'+decodeURIComponent(pathname));
    if(!file.startsWith(publicDir+path.sep)&&file!==publicDir){res.writeHead(403);res.end();return;}
    const target=fs.existsSync(file)&&fs.statSync(file).isFile()?file:path.join(publicDir,'index.html');
    const mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.png':'image/png','.woff2':'font/woff2'};
    res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');fs.createReadStream(target).pipe(res);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const ses=session.fromPartition('offline-renderer-test',{cache:false});
  secureSession(ses,origin,token);
  win=new BrowserWindow({show:false,webPreferences:{session:ses,sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  await loadWithRedirect(win,origin);
  const readyDeadline=Date.now()+15000;
  while(Date.now()<readyDeadline){
    const ready=await win.webContents.executeJavaScript("document.body.innerText.includes('本机离线版')");
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!await win.webContents.executeJavaScript("document.body.innerText.includes('本机离线版')")) throw new Error('Original offline UI did not mount');
  // Accept the fixture agreement in this synthetic-only session, then exercise
  // the built chat route as well as the initial shell.
  await win.webContents.executeJavaScript("localStorage.setItem('ui.first_use_agreement',JSON.stringify({version:'2026-08-12.3',acceptedAt:new Date().toISOString()}))");
  await loadWithRedirect(win,origin+'/chat');
  const chatDeadline=Date.now()+15000;
  while(Date.now()<chatDeadline){
    if(await win.webContents.executeJavaScript("document.body.innerText.includes('更新最新记录')"))break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!await win.webContents.executeJavaScript("document.body.innerText.includes('更新最新记录')"))throw new Error('Built chat refresh control did not mount');
  await loadWithRedirect(win,origin+'/ai');
  const aiDeadline=Date.now()+10000;
  while(Date.now()<aiDeadline){
    if(await win.webContents.executeJavaScript("document.body.innerText.includes('授权这份资料给 ChatGPT（一次）')"))break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!await win.webContents.executeJavaScript("document.body.innerText.includes('授权这份资料给 ChatGPT（一次）')"))throw new Error('Built private AI control did not mount');
  if(await win.webContents.executeJavaScript("[...document.querySelectorAll('button')].some(b=>/高级版|打开套餐|^Pro$/.test(b.textContent.trim())||b.title.includes('Pro ·'))"))throw new Error('Promotion UI remains');
  const denied=await win.webContents.executeJavaScript("fetch('https://example.invalid/synthetic-no-data').then(()=>false).catch(()=>true)");
  if(!denied||authenticated<2)throw new Error('Renderer network boundary/auth check failed');
  console.log('Original Nuxt UI, live chat and private AI controls mounted; Pro promotion absent; same-origin token injected; renderer external fetch rejected. Synthetic-only hidden window PASS.');
  clearTimeout(timeout);win.destroy();server.close(()=>app.exit(0));
}).catch(error=>{console.error(error.message);clearTimeout(timeout);if(server)server.close();app.exit(1);});
