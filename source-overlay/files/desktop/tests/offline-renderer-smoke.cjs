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
let historyRows=[{id:'synthetic:2',account:'synthetic-account',conversation:'Synthetic Group',status:'downloaded',finished_at:1700000002,attempts:1},{id:'synthetic:1',account:'synthetic-account',conversation:'Synthetic Friend',status:'downloaded',finished_at:1700000001,attempts:1}];
let historyUnread=2;
let keyRequestModes=[];
const historySummary=()=>({downloaded:historyRows.length,local:0,failed:0,completed:0,cancelled:0,total:historyRows.length,unread:historyUnread});
const timeout=setTimeout(()=>{console.error('Renderer test timed out');app.exit(1);},45000);
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    if(req.headers['x-offline-token']!==token){res.writeHead(403);res.end();return;}
    authenticated++;
    const pathname=new URL(req.url,'http://127.0.0.1').pathname;
    if(pathname.startsWith('/api/')){
      res.setHeader('Content-Type','application/json');
      if(pathname==='/api/get_keys'){
        keyRequestModes.push(new URL(req.url,'http://127.0.0.1').searchParams.get('key_mode'));
        res.end(JSON.stringify({status:0,data:{db_key:'ab'.repeat(32),method:'local_source_memory_scan',verified:true}}));return;
      }
      if(pathname.startsWith('/api/offline/originals/history')){
        if(pathname.endsWith('/events')){res.setHeader('Content-Type','text/event-stream');res.end('data: {"revision":1}\n\n');return;}
        if(pathname.endsWith('/seen')){historyUnread=0;res.end(JSON.stringify(historySummary()));return;}
        if(pathname.endsWith('/summary')){res.end(JSON.stringify(historySummary()));return;}
        if(req.method==='DELETE'){historyRows=[];historyUnread=0;res.end(JSON.stringify(historySummary()));return;}
        res.end(JSON.stringify({items:historyRows,summary:historySummary(),through:{'synthetic-account':2},next_cursor:null}));return;
      }
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
  win=new BrowserWindow({show:false,width:1280,height:860,webPreferences:{offscreen:true,backgroundThrottling:false,session:ses,sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
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
  const historyDeadline=Date.now()+5000;
  while(Date.now()<historyDeadline){if(await win.webContents.executeJavaScript("!!document.querySelector('button[aria-label=\"原图下载记录，新获取 2 张\"]')"))break;await new Promise(resolve=>setTimeout(resolve,40));}
  const floatResult = await win.webContents.executeJavaScript(`(async () => {
    const wait = () => new Promise(resolve => setTimeout(resolve, 220));
    const button = () => document.querySelector('.history-trigger');
    const control = () => document.querySelector('.original-history');
    function drag(x, y) {
      const b = button(), r = b.getBoundingClientRect();
      const sx = Math.max(2, Math.min(innerWidth - 2, r.x + r.width / 2));
      const sy = Math.max(2, Math.min(innerHeight - 2, r.y + r.height / 2));
      b.dispatchEvent(new PointerEvent('pointerdown', {pointerId: 17, isPrimary: true, button: 0, clientX: sx, clientY: sy, bubbles: true}));
      window.dispatchEvent(new PointerEvent('pointermove', {pointerId: 17, clientX: x, clientY: y, cancelable: true}));
      window.dispatchEvent(new PointerEvent('pointerup', {pointerId: 17, clientX: x, clientY: y}));
      b.click();
    }
    for (const [edge, x, y] of [['left', 0, innerHeight / 2], ['right', innerWidth, innerHeight / 2], ['top', innerWidth / 2, 0], ['bottom', innerWidth / 2, innerHeight]]) {
      drag(x, y); await wait();
      if (control().dataset.dock !== edge || !control().classList.contains('collapsed') || document.querySelector('#original-history-panel')) throw Error('Dock or drag click failed: ' + edge);
      const rect = control().getBoundingClientRect();
      const visibleWidth = Math.min(innerWidth, rect.right) - Math.max(0, rect.left);
      const visibleHeight = Math.min(innerHeight, rect.bottom) - Math.max(0, rect.top);
      if (Math.round(edge === 'left' || edge === 'right' ? visibleWidth : visibleHeight) !== 24) throw Error('Dock is not a visible half-circle');
      button().click(); await wait();
      const panel = document.querySelector('#original-history-panel')?.getBoundingClientRect();
      if (!panel || panel.left < 0 || panel.top < 0 || panel.right > innerWidth || panel.bottom > innerHeight) throw Error('Expanded history leaves viewport');
      document.querySelector('button[aria-label="关闭原图下载历史"]').click(); await wait();
      drag(innerWidth / 2, innerHeight / 2); await wait();
      if (control().dataset.dock !== 'none' || control().classList.contains('collapsed')) throw Error('Drag did not undock');
    }
    return {edges: 4, visibleDockPixels: 24, dragDoesNotOpen: true};
  })()`);
  console.log('Floating history renderer: '+JSON.stringify(floatResult));
  await win.webContents.executeJavaScript("document.querySelector('button[aria-controls=\"original-history-panel\"]').click()");
  await new Promise(resolve=>setTimeout(resolve,200));
  if(!await win.webContents.executeJavaScript("document.querySelector('#original-history-panel')?.innerText.includes('Synthetic Group') && !!document.querySelector('button[aria-label=\"原图下载记录，新获取 0 张\"]')"))throw new Error('Built history did not display rows and reset the new count');
  await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  fs.writeFileSync(path.resolve(__dirname,'../../../validation-output/original-history-renderer.png'),(await win.webContents.capturePage()).toPNG());
  await win.webContents.executeJavaScript("[...document.querySelectorAll('#original-history-panel button')].find(b=>b.textContent==='清空历史').click()");
  await new Promise(resolve=>setTimeout(resolve,100));
  if(!await win.webContents.executeJavaScript("document.querySelector('#original-history-panel')?.innerText.includes('共 0 条历史')"))throw new Error('Built history clear failed');
  await win.webContents.executeJavaScript("document.querySelector('button[aria-label=\"关闭原图下载历史\"]').click()");
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
  await loadWithRedirect(win,origin+'/decrypt');
  await waitUI("!!document.querySelector('#dbPath') && [...document.querySelectorAll('button')].some(b=>b.textContent.includes('一键获取数据库密钥') && !b.disabled)");
  if(await win.webContents.executeJavaScript("!!document.querySelector('#key').value"))throw new Error('Fresh fixture unexpectedly has a saved database key');
  await win.webContents.executeJavaScript("{ const field=document.querySelector('#dbPath');field.value='D:/synthetic/account/db_storage';field.dispatchEvent(new Event('input',{bubbles:true}));[...document.querySelectorAll('button')].find(b=>b.textContent.includes('一键获取数据库密钥')).click(); }");
  await waitUI("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='开始只读获取')");
  await win.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='开始只读获取').click()");
  await waitUI("document.querySelector('#key')?.value==='ab'.repeat(32) && document.body.innerText.includes('数据库密钥已通过本机只读扫描获取')");
  if(JSON.stringify(keyRequestModes)!==JSON.stringify(['key_v4']))throw new Error('Fresh UI used an unexpected acquisition method');
  console.log('Fresh UI without a saved key filled the authenticated read-only acquisition result.');
  const denied=await win.webContents.executeJavaScript("fetch('https://example.invalid/synthetic-no-data').then(()=>false).catch(()=>true)");
  if(!denied||authenticated<2)throw new Error('Renderer network boundary/auth check failed');
  console.log('Built settings saved selected-group and all-conversation scopes and preserved choices. Original Nuxt chat and AI mounted; authenticated local access and external-fetch denial PASS. Synthetic-only hidden window.');
  clearTimeout(timeout);win.destroy();server.close(()=>app.exit(0));
}).catch(error=>{console.error(error.message);clearTimeout(timeout);if(server)server.close();app.exit(1);});
