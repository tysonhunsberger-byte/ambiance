(function(){
  if (window.__NT_MODS_ADV__) return; window.__NT_MODS_ADV__ = true;

  const CLAMP01 = v => Math.max(0, Math.min(1, v));
  const now = () => (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  const TICKERS = [];

  (function loop(t){
    for (let i=0;i<TICKERS.length;i++){ try{ TICKERS[i](t); }catch(e){} }
    requestAnimationFrame(loop);
  })(0);

  function applyTo(target, value, ctx){
    // Allow user hook first
    if (typeof window.applyMod === 'function'){
      try { window.applyMod(target, value, ctx); return; } catch(e){}
    }
    try {
      if (target === 'vol'  && ctx && ctx.out) {
        ctx.out.gain.value = Math.max(0, Math.min(1, 0.5 + value));
      } else if (target === 'pan'  && ctx && ctx.pan) {
        ctx.pan.pan.value = Math.max(-1, Math.min(1, value));
      } else if (target === 'lpf'  && ctx && (ctx.lpf || ctx.lpfA || ctx.lpfB)) {
        const f = 500 + (1+value)*9750;
        if (ctx.lpf)  ctx.lpf.frequency.value  = f;
        if (ctx.lpfA) ctx.lpfA.frequency.value = f;
        if (ctx.lpfB) ctx.lpfB.frequency.value = f;
      } else if (target === 'ab'   && ctx && ctx.ab) {
        const v = Math.max(0, Math.min(1, 0.5 + value*0.5));
        ctx.ab.gain.value = v;
      } else if (target === 'tempo' && ctx && ctx.setTempo) {
        ctx.setTempo(ctx.tempoBase * Math.max(0.25, Math.min(4, 1+value)));
      } else if (target === 'pitch'){
        const semi = value;
        if (ctx && ctx.detune) ctx.detune.value = (ctx.detuneBase||0) + semi*100;
        else if (ctx && ctx.playbackRate) ctx.playbackRate.value = (ctx.pbBase||1) * Math.pow(2, semi/12);
      } else if (target === 'toneLevel' || target === 'toneFreq'){
        const host = ctx && ctx.el ? ctx.el : document;
        const mods = host.querySelectorAll('.mod');
        let tone = null;
        mods.forEach(m => {
          const hdr = m.querySelector('.mod-hdr .name, .mod-hdr .mod-name, .mod-hdr .title, .mod .hdr .name');
          if (hdr && /tone/i.test(hdr.textContent)) tone = tone || m;
        });
        if (tone){
          const ranges = tone.querySelectorAll('input[type="range"]');
          let targetRange = (target === 'toneLevel') ? (ranges[ranges.length-1] || null) : (ranges[0] || null);
          if (targetRange){
            const min = parseFloat(targetRange.min || "0"), max = parseFloat(targetRange.max || "1");
            const v = Math.max(min, Math.min(max, (min + max)/2 + value * (max - min)/2));
            targetRange.value = String(v);
            targetRange.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
      }
    } catch(e) {}
  }



  function ctxFor(modEl){
    const host = modEl.closest('.stream, .block, [data-stream]') || document;
    if (host.__modCtx) return host.__modCtx;
    const actx = window.ACTX || window.audioCtx || (window.AudioContext ? new AudioContext() : null) || null;
    return (host.__modCtx = {
      el: host, actx,
      out: window._MASTER_OUT || null,
      pan: null, lpf: null, ab: null,
      tempoBase: window._GLOBAL_TEMPO || 120,
      playbackRate: null, pbBase: 1,
      detune: null, detuneBase: 0
    });
  }

  function ensureSubtabs(mod){
    if (mod.__hasSubtabs) return;
    const body = mod.querySelector('.mod-body') || mod;
    const keep = Array.from(body.children);
    const bar = document.createElement('div');
    bar.className = 'subtabs';
    bar.style.cssText = 'display:flex;gap:8px;margin:6px 0 10px';
    const b1 = Object.assign(document.createElement('button'),{textContent:'LFO',className:'btn btn-xs active'});
    const b2 = Object.assign(document.createElement('button'),{textContent:'Advanced',className:'btn btn-xs'});
    bar.append(b1,b2);
    const paneLFO = document.createElement('div'); paneLFO.className='tab-pane lfo-pane';
    keep.forEach(ch=>paneLFO.appendChild(ch));
    const lfoExtras = document.createElement('div');
    lfoExtras.className='row'; lfoExtras.innerHTML =
      '<label style="margin-left:8px">Phase</label><input class="lfoPhase" type="range" min="0" max="1" step="0.01" value="0">'+
      '<label>Jitter</label><input class="lfoJitter" type="range" min="0" max="1" step="0.01" value="0">'+
      '<label>Offset</label><input class="lfoOffset" type="range" min="-1" max="1" step="0.01" value="0">'+
      '<label><input class="lfoSync" type="checkbox"> Sync</label>';
    paneLFO.appendChild(lfoExtras);

    const paneADV = document.createElement('div'); paneADV.className='tab-pane adv-pane'; paneADV.style.display='none';
    paneADV.innerHTML = [
      '<div class="row euclid">',
      '<button class="btn euOn">Euclid: OFF</button>',
      '<label>Target</label>',
      '<select class="euTarget" title="Destination parameter"><option value="vol">Volume</option><option value="pan">Pan</option><option value="lpf">LPF</option><option value="ab">A↔B</option><option value="tempo">Tempo</option><option value="pitch">Pitch</option></select>',
      '<label>Steps</label><input class="euSteps" title="Total steps in the pattern" type="number" min="1" max="32" value="16" style="width:56px">',
      '<label>Pulses</label><input class="euPulses" title="Number of hits per cycle" type="number" min="0" max="32" value="8" style="width:56px">',
      '<label>Rotate</label><input class="euRotate" title="Rotate pattern start" type="number" min="0" max="31" value="0" style="width:56px">',
      '<label>Depth</label><input class="euDepth" title="Modulation depth" type="range" min="0" max="1" step="0.01" value="1">',
      '<label>Rate</label><select class="euRate" title="Step rate"><option>1/4</option><option selected>1/8</option><option>1/16</option></select>',
      '</div>',
      '<div class="row xy" style="align-items:center;gap:10px;">',
      '<button class="btn xyOn">XY: OFF</button>',
      '<div class="xyPad" title="Drag to modulate assigned targets" style="width:140px;height:100px;border:1px solid var(--select-border,#888);background:rgba(0,0,0,0.12);position:relative;touch-action:none"><div class="xyDot" style="position:absolute;width:10px;height:10px;border-radius:50%;background:var(--accent,#09f);transform:translate(-50%,-50%);left:50%;top:50%"></div></div>',
      '<div>',
      '<label>X→</label><select class="xyX" title="X-axis target"><option value="pan">Pan</option><option value="vol">Volume</option><option value="lpf">LPF</option><option value="ab">A↔B</option></select>',
      '<label>Depth</label><input class="xyXDepth" title="X-axis depth" type="range" min="0" max="1" step="0.01" value="1"><br>',
      '<label>Y→</label><select class="xyY" title="Y-axis target"><option value="vol">Volume</option><option value="pan">Pan</option><option value="lpf">LPF</option><option value="ab">A↔B</option></select>',
      '<label>Depth</label><input class="xyYDepth" title="Y-axis depth" type="range" min="0" max="1" step="0.01" value="1">',
      '</div>',
      '<label style="margin-left:10px"><input class="xyRec" title="Record XY movement (if supported)" type="checkbox"> Record</label>',
      '</div>',
      '<div class="row macros" style="flex-wrap:wrap;gap:8px;">',
      '<button class="btn mcOn">Macros: ON</button>',
      '<div class="macWrap"></div>',
      '<button class="btn mcSnap">Snapshot</button>',
      '<button class="btn mcMorph">Morph</button>',
      '</div>',
      '<div class="row chord">',
      '<button class="btn chOn">Chord: OFF</button>',
      '<label>Key</label>',
      '<select class="chKey" title="Key center"><option>C</option><option>C#</option><option>D</option><option>Eb</option><option>E</option><option>F</option><option>F#</option><option>G</option><option>Ab</option><option>A</option><option>Bb</option><option>B</option></select>',
      '<label>Scale</label>',
      '<select class="chScale" title="Scale / mode"><option>Major</option><option>Minor</option><option>Dorian</option><option>Mixolydian</option><option>Pentatonic</option><option>Chromatic</option></select>',
      '<label>Pattern</label><input class="chPat" title="Comma-separated semitone offsets, e.g. 0,4,7" type="text" value="0,4,7,12" style="width:120px" title="Comma-separated semitone offsets, e.g. 0,4,7">',
      '<label>Rate</label><select class="chRate" title="Arp rate"><option>1/4</option><option selected>1/8</option><option>1/16</option></select>',
      '<label>Depth</label><input class="chDepth" title="Pitch depth in semitones" type="range" min="0" max="1" step="0.01" value="1">',
      '<label>Swing</label><input class="chSwing" title="Swing amount" type="range" min="0" max="0.5" step="0.01" value="0">',
      '<label>Quantize</label><input class="chQuant" title="Quantize to scale" type="checkbox" checked>',
      '</div>'
    ].join('');
    body.innerHTML=''; body.append(bar,paneLFO,paneADV);
    function show(which){ if(which==='lfo'){ paneLFO.style.display=''; paneADV.style.display='none'; b1.classList.add('active'); b2.classList.remove('active'); } else { paneLFO.style.display='none'; paneADV.style.display=''; b2.classList.add('active'); b1.classList.remove('active'); } }
    b1.addEventListener('click',()=>show('lfo')); b2.addEventListener('click',()=>show('adv')); show('lfo');
    mod.__hasSubtabs = true;
  }

  /* Euclidean pattern */
  function bjorklund(steps,pulses,rot){
    steps=Math.max(1,Math.min(32,Math.floor(+steps||1)));
    pulses=Math.max(0,Math.min(steps,Math.floor(+pulses||0)));
    let pattern = Array(pulses).fill([1]), rests = Array(steps-pulses).fill([0]);
    while(rests.length>1){
      const r=Math.min(pattern.length, rests.length), next=[];
      for(let i=0;i<r;i++) next.push(pattern[i].concat(rests[i]));
      pattern = next.concat(pattern.slice(r)); rests = rests.slice(r);
    }
    let flat = pattern.flat();
    const k = (Math.floor(+rot||0))%steps; if(k) flat = flat.slice(k).concat(flat.slice(0,k));
    return flat;
  }

  function wireEuclid(scope, ctx){
    const on = scope.querySelector('.euOn'); if(!on || on.__wired) return; on.__wired = true;
    const tgt=scope.querySelector('.euTarget'), stp=scope.querySelector('.euSteps'),
          pul=scope.querySelector('.euPulses'), rot=scope.querySelector('.euRotate'),
          dep=scope.querySelector('.euDepth'), rate=scope.querySelector('.euRate');
    const st = { on:false, pat:[], idx:0, t0:now(), tPrev:0, depth:+dep.value||1, rate:rate.value, target:tgt.value };
    function rebuild(){ st.pat = bjorklund(stp.value, pul.value, rot.value); st.idx = 0; }
    on.addEventListener('click',()=>{ st.on=!st.on; on.textContent='Euclid: '+(st.on?'ON':'OFF'); st.t0=now(); st.tPrev=0; });
    [stp,pul,rot].forEach(x=> x.addEventListener('change',rebuild));
    dep.addEventListener('input',()=> st.depth = +dep.value || 1);
    rate.addEventListener('change',()=> st.rate = rate.value);
    tgt.addEventListener('change',()=> st.target = tgt.value);
    rebuild();
    TICKERS.push(function(ts){
      if(!st.on) return;
      const tempo=window._GLOBAL_TEMPO||ctx.tempoBase||120, spb=60/Math.max(20,tempo);
      const div=st.rate==='1/16'?4:(st.rate==='1/4'?1:2), dur=spb/div;
      const t=(ts-st.t0)/1000;
      if(t-(st.tPrev||0)>=dur){ st.tPrev+=dur; const hit=st.pat[st.idx%st.pat.length]; const v=hit?(st.depth||1):0; applyTo(st.target, hit?v:-v, ctx); st.idx++; }
    });
  }

  function wireXY(scope,ctx){
    const on=scope.querySelector('.xyOn'); if(!on||on.__wired) return; on.__wired=true;
    const pad=scope.querySelector('.xyPad'), dot=scope.querySelector('.xyDot');
    const X=scope.querySelector('.xyX'), Y=scope.querySelector('.xyY');
    const Xd=scope.querySelector('.xyXDepth'), Yd=scope.querySelector('.xyYDepth');
    const st={on:false,x:0,y:0};
    on.addEventListener('click',()=>{ st.on=!st.on; on.textContent='XY: '+(st.on?'ON':'OFF'); });
    function set(ev){
      if(!st.on) return;
      const r=pad.getBoundingClientRect(), x=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)), y=Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height));
      st.x=x*2-1; st.y=(1-y)*2-1; dot.style.left=(x*100)+'%'; dot.style.top=(y*100)+'%';
      applyTo(X.value, st.x*(+Xd.value||0), ctx); applyTo(Y.value, st.y*(+Yd.value||0), ctx);
    }
    ['pointerdown','pointermove'].forEach(t=>pad.addEventListener(t,set));
  }

  function wireMacros(scope, ctx){
    const on=scope.querySelector('.mcOn'); if(!on||on.__wired) return; on.__wired=true;
    const wrap=scope.querySelector('.macWrap'), snap=scope.querySelector('.mcSnap'), morph=scope.querySelector('.mcMorph');
    const M=8, S={vals:Array(M).fill(0), routes:Array(M).fill([]), A:null, B:null};
    if(!wrap.childElementCount){
      for(let i=0;i<M;i++){
        const c=document.createElement('div'); c.style.cssText='display:inline-flex;flex-direction:column;align-items:center';
        c.innerHTML='<div style="font-size:10px">M'+(i+1)+'</div><input class="mVal" title="Macro value" type="range" min="-1" max="1" step="0.01" value="0" style="width:100px"><button class="btn btn-xs mRoute">Route</button>';
        const s=c.querySelector('.mVal');
        s.addEventListener('input',()=>{ S.vals[i]=+s.value; for(const r of S.routes[i]) applyTo(r.target, S.vals[i]*r.depth, ctx); });
        c.querySelector('.mRoute').addEventListener('click',()=>{
          const t=(prompt('Target (vol|pan|lpf|ab|tempo|pitch):','pan')||'pan').trim();
          const d=+prompt('Depth (-1..1):','0.5')||0.5; S.routes[i].push({target:t,depth:d});
        });
        wrap.appendChild(c);
      }
    }
    snap.addEventListener('click',()=>{ if(!S.A) S.A=S.vals.slice(0); else S.B=S.vals.slice(0); });
    morph.addEventListener('click',()=>{
      if(!S.A||!S.B) return; let k=0; const dur=0.5;
      const step=()=>{ k=Math.min(1,k+1/60/dur);
        wrap.querySelectorAll('.mVal').forEach((el,i)=>{ const v=S.A[i]+(S.B[i]-S.A[i])*k; S.vals[i]=v; el.value=v; for(const r of S.routes[i]) applyTo(r.target, v*r.depth, ctx); });
        if(k<1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  const SCALES={Major:[0,2,4,5,7,9,11],Minor:[0,2,3,5,7,8,10],Dorian:[0,2,3,5,7,9,10],Mixolydian:[0,2,4,5,7,9,10],Pentatonic:[0,3,5,7,10],Chromatic:[0,1,2,3,4,5,6,7,8,9,10,11]};
  const KEYS={C:0,'C#':1,D:2,Eb:3,E:4,F:5,'F#':6,G:7,Ab:8,A:9,Bb:10,B:11};
  function nearest(semi,key,scale){
    const off=((semi%12)+12)%12, allow=SCALES[scale]||SCALES.Major;
    if(allow.includes(off)) return semi;
    let best=semi, d=99;
    for(let s=semi-6;s<=semi+6;s++){
      const o=((s%12)+12)%12;
      if(allow.includes(o)){ const dd=Math.abs(s-semi); if(dd<d){ d=dd; best=s; } }
    }
    return best;
  }
  const parsePat=t=>String(t||'').split(/[, ]+/).map(s=>+s).filter(Number.isFinite);

  function wireChord(scope,ctx){
    const on=scope.querySelector('.chOn'); if(!on||on.__wired) return; on.__wired=true;
    const key=scope.querySelector('.chKey'), scale=scope.querySelector('.chScale'), pat=scope.querySelector('.chPat'),
          rate=scope.querySelector('.chRate'), depth=scope.querySelector('.chDepth'), swing=scope.querySelector('.chSwing'),
          quant=scope.querySelector('.chQuant');
    const st={on:false, idx:0, t0:now(), tPrev:0, arr:parsePat(pat.value)};
    on.addEventListener('click',()=>{ st.on=!st.on; on.textContent='Chord: '+(st.on?'ON':'OFF'); st.t0=now(); st.tPrev=0; st.idx=0; });
    pat.addEventListener('change',()=> st.arr=parsePat(pat.value));
    TICKERS.push(function(ts){
      if(!st.on || !st.arr.length) return;
      const tempo=window._GLOBAL_TEMPO||ctx.tempoBase||120, spb=60/Math.max(20,tempo);
      const div=rate.value==='1/16'?4:(rate.value==='1/4'?1:2), dur=spb/div, sw=+swing.value||0;
      const k=KEYS[key.value]||0, sc=scale.value, t=(ts-st.t0)/1000, adj=(st.idx%2? sw*dur:0);
      if(t-(st.tPrev||0)>=dur+adj){
        st.tPrev += dur+adj;
        let semi = st.arr[st.idx % st.arr.length];
        if(quant.checked) semi = nearest(semi+k, k, sc) - k;
        applyTo('pitch', (+depth.value||1) * semi, ctx);
        st.idx++;
      }
    });
  }

  function wire(mod){
    ensureSubtabs(mod);
    const adv=mod.querySelector('.adv-pane'), ctx=ctxFor(mod);
    wireEuclid(adv,ctx); wireXY(adv,ctx); wireMacros(adv,ctx); wireChord(adv,ctx);
  }
  function boot(root){
    (root||document)
      .querySelectorAll(".mod.modMatrix, .mod.modulation, .mod.mod-modulation")
      .forEach(m=>{ try { wire(m); } catch(e){} });
  }

  document.addEventListener('DOMContentLoaded',()=>boot(document));
  new MutationObserver((mutations)=>{
    mutations.forEach(m=>{
      if (m.addedNodes) m.addedNodes.forEach(n=>{ if (n.nodeType===1) boot(n); });
    });
  }).observe(document.body,{childList:true,subtree:true});
})();
