/* Local export viewer. All network requests and external navigation are disabled. */
(() => {
  'use strict';
  window.open = () => null;
  document.addEventListener('click', e => {
    const anchor=e.target.closest?.('a[href]');
    if(anchor && /^(https?:|javascript:|data:|\\\\|\/\/)/i.test(anchor.getAttribute('href')||'')) {e.preventDefault();e.stopImmediatePropagation();}
  }, true);
  document.addEventListener('DOMContentLoaded', () => {
    const list=document.getElementById('wceMessageList');
    const metaElement=document.getElementById('wcePageMeta');
    let meta=null; try {meta=JSON.parse(metaElement?.textContent||'null');}catch{}
    let previous=Number(meta?.initialPage||1)-1;
    const loadPrevious = async () => {
      if(previous<1 || !list) return;
      const number=previous;
      const name=String(number).padStart(Number(meta.padWidth||4),'0');
      const file=String(meta.pageFilePrefix||'pages/page-')+name+'.js';
      if(!/^pages\/page-\d+\.js$/.test(file)) throw new Error('Invalid local page path');
      await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=file;s.onload=resolve;s.onerror=reject;document.head.appendChild(s);});
      const data=window.__OFFLINE_EXPORT_PAGES__?.[String(number)];
      if(!data || Number(data.page)!==number) throw new Error('Local export page missing');
      const template=document.createElement('template'); template.innerHTML=String(data.html||'');
      for(const node of template.content.querySelectorAll('script,iframe,object,embed')) node.remove();
      for(const node of template.content.querySelectorAll('*')) for(const a of [...node.attributes]) if(a.name.startsWith('on')) node.removeAttribute(a.name);
      list.prepend(template.content); previous--;
    };
    const pager=document.getElementById('wcePager');
    const button=document.getElementById('wceLoadPrevBtn');
    if(pager && previous>0) pager.style.display='';
    button?.addEventListener('click', async()=>{button.disabled=true;try{await loadPrevious();if(previous<1)pager.style.display='none';}finally{button.disabled=false;}});
    const filter=document.getElementById('messageTypeFilter');
    filter?.addEventListener('change',()=>{
      for(const item of list?.children||[]) {const kind=item.getAttribute('data-render-type')||'';item.hidden=!!filter.value && filter.value!=='all' && kind!==filter.value;}
    });
    const search=document.getElementById('wceMessageSearchInput');
    document.getElementById('wceMessageSearchBtn')?.addEventListener('click',async()=>{
      while(previous>0) await loadPrevious();
      const keyword=String(search?.value||'').toLocaleLowerCase();let count=0;
      for(const item of list?.children||[]) {item.hidden=!!keyword&&!item.textContent.toLocaleLowerCase().includes(keyword);if(!item.hidden)count++;}
      const status=document.getElementById('wceMessageSearchStatus');if(status)status.textContent=`匹配 ${count} 条`;
    });
    document.getElementById('wceDateJumpBtn')?.addEventListener('click',async()=>{
      while(previous>0) await loadPrevious();
      const day=document.getElementById('wceDateJumpInput')?.value;
      [...(list?.children||[])].find(item=>item.getAttribute('data-wce-date')===day)?.scrollIntoView();
    });
  });
})();
