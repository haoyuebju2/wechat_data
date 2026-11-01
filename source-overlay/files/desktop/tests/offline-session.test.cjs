const {test}=require('node:test');
const assert=require('node:assert/strict');
const {allowedUrl,secureSession,CSP}=require('../src/offline-session.cjs');
const origin='http://127.0.0.1:10392';
test('only exact same origin; deny credentials, rebinding names and external URLs',()=>{
  assert.equal(allowedUrl(origin+'/api/health',origin),true);
  for(const value of ['https://evil.invalid/','http://127.0.0.1.evil.invalid:10392/','http://127.0.0.1:18888/','http://user:secret@127.0.0.1:10392/','file:///C:/private.db','javascript:alert(1)']) assert.equal(allowedUrl(value,origin),false);
});
test('session prevents remote requests and never attaches token to them',()=>{
  const handlers={};
  const ses={setPermissionRequestHandler:f=>handlers.permission=f,setPermissionCheckHandler:f=>handlers.check=f,
    webRequest:{onBeforeRequest:f=>handlers.request=f,onBeforeSendHeaders:f=>handlers.headers=f,onHeadersReceived:f=>handlers.response=f}};
  secureSession(ses,origin,'synthetic-secret');
  let result;
  handlers.request({url:'https://evil.invalid/media'},r=>result=r);assert.equal(result.cancel,true);
  handlers.request({url:origin+'/image'},r=>result=r);assert.equal(result.cancel,false);
  handlers.headers({url:origin+'/api',requestHeaders:{Referer:'private'}},r=>result=r);
  assert.equal(result.requestHeaders['X-Offline-Token'],'synthetic-secret');assert.equal(result.requestHeaders.Referer,undefined);
  handlers.headers({url:'https://evil.invalid',requestHeaders:{'X-Offline-Token':'synthetic-secret'}},r=>result=r);
  assert.equal(result.requestHeaders['X-Offline-Token'],undefined);
  handlers.response({responseHeaders:{}},r=>result=r);assert.equal(result.responseHeaders['Content-Security-Policy'][0],CSP);
  assert.equal(handlers.check(),false);
});
