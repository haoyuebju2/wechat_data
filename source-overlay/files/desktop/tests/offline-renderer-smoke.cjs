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
let originals={enabled:true,auto_mode:'off',conversations:{},queue:{pending:0,done:0,failed:0}};
const timeout=setTimeout(()=>{console.error('Renderer test timed out');app.exit(1);},45000);
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    if(req.headers['x-offline-token']!==token){res.writeHead(403);res.end();return;}
    authenticated++;
    const pathname=new URL(req.url,'http://127.0.0.1').pathname;
    if(pathname.startsWith('/api/')){
      res.setHeader('Content-Type','application/json');
      if(pathname==='/api/offline/originals/settings'){
        if(req.method==='PUT'){
          let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{originals={...originals,...JSON.parse(body)};res.end(JSON.stringify(originals));});return;
        }
        res.end(JSON.stringify(originals));return;
      }
      res.end(JSON.stringify({status:'success',accounts:['synthetic-account'],sessions:[],contacts:[
        {username:'synthetic_friend',displayName:'Synthetic Friend'},
        {username:'synthetic_group@chatroom',displayName:'Synthetic Group'}
      ],offline:true,enabled:false,capabilities:{}}));return;
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
    const ready=await win.webContents.executeJavaScript("document.body.innerText.includes('本机工具')");
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!await win.webContents.executeJavaScript("document.body.innerText.includes('本机工具')")) throw new Error('Original offline UI did not mount');
  // Accept the fixture agreement in this synthetic-only session, then exercise
  // the built chat route as well as the initial shell.
  await win.webContents.executeJavaScript("localStorage.setItem('ui.first_use_agreement',JSON.stringify({version:'2026-08-12.3',acceptedAt:new Date().toISOString()}))");
  await loadWithRedirect(win,origin+'/chat');
  const chatDeadline=Date.now()+15000;
  while(Date.now()<chatDeadline){
    if(await win.webContents.executeJavaScript("!!document.querySelector('.chat-page-shell')"))break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!await win.webContents.executeJavaScript("!!document.querySelector('.chat-page-shell')"))throw new Error('Built chat did not mount');
  if(await win.webContents.executeJavaScript("/正在本地更新|校验完成后更新记录|更新最新记录/.test(document.body.innerText)"))throw new Error('Background update status remains visible');
  await win.webContents.executeJavaScript("document.querySelector('[title=\"设置\"]').click()");
  const scopeSelector='select[aria-label="自动下载范围"]';
  async function waitUI(expression){
    const until=Date.now()+5000;
    while(Date.now()<until){if(await win.webContents.executeJavaScript(expression))return;await new Promise(resolve=>setTimeout(resolve,40));}
    throw new Error('Original-image scope UI did not settle');
  }
  await waitUI(`!!document.querySelector('${scopeSelector}') && !document.querySelector('${scopeSelector}').disabled`);
  async function chooseMode(value){
    await win.webContents.executeJavaScript(`{const select=document.querySelector('${scopeSelector}');select.value='${value}';select.dispatchEvent(new Event('change',{bubbles:true}));}`);
    await waitUI(`document.querySelector('${scopeSelector}').value==='${value}' && !document.querySelector('${scopeSelector}').disabled`);
  }
  await chooseMode('selected');
  await waitUI("[...document.querySelectorAll('label')].some(el=>el.textContent.includes('Synthetic Group') && el.querySelector('input[type=checkbox]'))");
  await win.webContents.executeJavaScript("[...document.querySelectorAll('label')].find(el=>el.textContent.includes('Synthetic Group') && el.querySelector('input[type=checkbox]')).querySelector('input').click()");
  await waitUI(`!document.querySelector('${scopeSelector}').disabled`);
  if(JSON.stringify(originals.conversations)!==JSON.stringify({'synthetic-account':['synthetic_group@chatroom']}))throw new Error('Selected group scope was not saved by the built UI');
  await chooseMode('all');
  if(originals.auto_mode!=='all')throw new Error('All-conversations scope was not saved');
  await chooseMode('selected');
  if(originals.conversations['synthetic-account'][0]!=='synthetic_group@chatroom')throw new Error('Scope change lost per-account selection');
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
  console.log('Built settings saved selected-group and all-conversation scopes and preserved choices. Original Nuxt chat and AI mounted; authenticated local access and external-fetch denial PASS. Synthetic-only hidden window.');
  clearTimeout(timeout);win.destroy();server.close(()=>app.exit(0));
}).catch(error=>{console.error(error.message);clearTimeout(timeout);if(server)server.close();app.exit(1);});
