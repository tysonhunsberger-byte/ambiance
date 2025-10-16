(function(){
  function installAB(root){
    (root||document).querySelectorAll('.mod').forEach(m=>{
      if(m.classList.contains('fxMod') || m.classList.contains('spaceMod')){ 
        const old=m.querySelector('.abPick'); if(old) old.remove(); 
        return; 
      }
      if(m.querySelector('.abPick')) return;
      const hdr=m.querySelector('.mod-hdr'); if(!hdr) return;
      const sel=document.createElement('select'); sel.className='abPick'; sel.title='Apply to';
      sel.innerHTML='<option value="both">A+B</option><option value="A">A only</option><option value="B">B only</option>';
      sel.value = m.dataset.ab || 'both';
      sel.addEventListener('change', ()=>{ m.dataset.ab = sel.value; });
      hdr.insertBefore(sel, hdr.querySelector('.carat'));
    });
  }
  document.addEventListener('DOMContentLoaded', ()=> installAB(document));
  new MutationObserver(m=> m.forEach(r=> r.addedNodes && r.addedNodes.forEach(n=> n.nodeType===1 && installAB(n)))).observe(document.body,{childList:true,subtree:true});
})();
