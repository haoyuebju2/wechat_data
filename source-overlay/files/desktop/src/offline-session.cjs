"use strict";
const CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
function allowedUrl(value, origin) {
  try {const url = new URL(value); return url.origin===origin && url.protocol==='http:' && !url.username && !url.password;}
  catch { return false; }
}
function secureSession(ses, origin, token) {
  ses.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  ses.setPermissionCheckHandler(()=>false);
  ses.webRequest.onBeforeRequest((details,callback)=>{
    const localResource = /^(data:|blob:)/.test(details.url);
    callback({cancel:!allowedUrl(details.url,origin) && !localResource});
  });
  ses.webRequest.onBeforeSendHeaders((details,callback)=>{
    const headers={...details.requestHeaders};
    for(const key of Object.keys(headers)) if(["referer","x-offline-token"].includes(key.toLowerCase())) delete headers[key];
    if(allowedUrl(details.url,origin)) headers['X-Offline-Token']=token;
    callback({requestHeaders:headers});
  });
  ses.webRequest.onHeadersReceived((details,callback)=>{
    const headers={...details.responseHeaders};
    for(const key of Object.keys(headers)) if(key.toLowerCase()==='content-security-policy') delete headers[key];
    headers['Content-Security-Policy']=[CSP];headers['Referrer-Policy']=['no-referrer'];
    callback({responseHeaders:headers});
  });
}
module.exports={allowedUrl,secureSession,CSP};
