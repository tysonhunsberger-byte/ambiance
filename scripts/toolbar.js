(function(){
  function ensureToolbar(){
    const tb=document.getElementById('toolbar'); if(!tb) return;
    if(!document.getElementById('toolbarInner')){
      const inn=document.createElement('div'); inn.id='toolbarInner';
      while(tb.firstChild){ inn.appendChild(tb.firstChild); }
      tb.appendChild(inn);
      const tbtn=document.createElement('div'); tbtn.id='taskButtons'; inn.appendChild(tbtn);
    }
    if(!document.getElementById('tray')){
      const tray=document.createElement('div'); tray.id='tray'; tray.innerHTML='<span id="clock"></span>';
      tb.appendChild(tray);
    }
  }

  function ensureStartButton(){
    const tb=document.getElementById('toolbar');
    if(!tb || document.getElementById('xpStart')) return;
    const inner=document.getElementById('toolbarInner');
    if(!inner) return;
    const start=document.createElement('div');
    start.id='xpStart';
    start.innerHTML='<span class="xpLogo"></span><span>Start</span>';
    tb.insertBefore(start, inner);
  }

  function ensureWinControls(){
    document.querySelectorAll('.mod-hdr').forEach(hdr=>{
      if(hdr.querySelector('.win-ctl')) return;
      const ctl=document.createElement('div'); ctl.className='win-ctl';
      const bMin=document.createElement('div'); bMin.className='btnctl min'; bMin.title='Minimize';
      const bMax=document.createElement('div'); bMax.className='btnctl max'; bMax.title='Maximize';
      const bCls=document.createElement('div'); bCls.className='btnctl cls'; bCls.title='Close';
      ctl.append(bMin,bMax,bCls);
      hdr.appendChild(ctl);
      const mod=hdr.closest('.mod');
      bMin.addEventListener('click', (e)=>{ e.stopPropagation(); mod?.classList.toggle('open'); });
      bMax.addEventListener('click', (e)=>{ e.stopPropagation(); mod?.classList.toggle('maximized'); });
      bCls.addEventListener('click', (e)=>{ e.stopPropagation(); if(mod) mod.style.display='none'; });
    });
  }

  function onTheme(){
    if(document.body.classList.contains('theme-xp')){
      ensureToolbar();
      ensureStartButton();
      ensureWinControls();
    }
  }

  function tick(){
    const el=document.getElementById('clock'); if(!el) return;
    const d=new Date(); const p=n=>String(n).padStart(2,'0');
    el.textContent=p(d.getHours())+':'+p(d.getMinutes());
  }

  function applyTheme(name){
    const b=document.body;
    b.classList.remove('theme-98','theme-xp');
    if(name==='win98') b.classList.add('theme-98'); else if(name==='winxp') b.classList.add('theme-xp');
    try{ localStorage.setItem('nt_theme', name); }catch(_){}
    const p=document.getElementById('themePicker'); if(p) p.value=name;
    onTheme();
  }
  window.__applyTheme=applyTheme;

  document.addEventListener('DOMContentLoaded', ()=>{
    ensureToolbar();
    tick();
    setInterval(tick, 30000);
    const picker=document.getElementById('themePicker');
    if(picker) picker.addEventListener('change', e=> applyTheme(e.target.value));
    const key='nt_theme_v';
    if(localStorage.getItem(key)!=='4'){
      localStorage.setItem('nt_theme','flat');
      localStorage.setItem(key,'4');
    }
    applyTheme(localStorage.getItem('nt_theme')||'flat');
  });

  window.addEventListener('load', onTheme);
  new MutationObserver(()=> onTheme()).observe(document.body,{childList:true,subtree:true});
})();
