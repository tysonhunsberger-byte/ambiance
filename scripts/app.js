/* --- Granular Worklet Source --- */
  ;(function ensureGranularWorklet(){
    if(self._granularWorkletReady) return;
    const code = `
      class GranularProcessor extends AudioWorkletProcessor {
        static get parameterDescriptors(){
          return [
            { name:'rate', defaultValue:1, minValue:0.25, maxValue:4 },
            { name:'transpose', defaultValue:0, minValue:-12, maxValue:12 },
            { name:'grainSize', defaultValue:0.08, minValue:0.02, maxValue:0.2 },
            { name:'overlap', defaultValue:0.6, minValue:0.1, maxValue:0.95 },
            { name:'gate', defaultValue:0, minValue:0, maxValue:1 }
          ];
        }
        constructor(){
          super();
          this.bufL = null; this.bufR = null;
          this.len = 0; this.pos = 0; this.loop = true; this.reverse = false;
          this.sr = sampleRate;
          this._win = {}; // Hann cache
          this.port.onmessage = (e)=>{
            const d = e.data||{};
            if(d.type==='setBuffer'){
              this.bufL = d.L || null; this.bufR = d.R || null;
              this.len = (this.bufL && this.bufL.length)|0; this.pos = Math.max(0, Math.min(this.pos, this.len-1));
            }else if(d.type==='seek'){
              const t = d.time||0; this.pos = Math.max(0, Math.min(Math.floor(t*this.sr), this.len-1));
            }else if(d.type==='params'){
              if(typeof d.loop==='boolean') this.loop = d.loop;
              if(typeof d.reverse==='boolean') this.reverse = d.reverse;
            }
          };
        }
        hann(n){
          if(this._win[n]) return this._win[n];
          const w = new Float32Array(n); for(let i=0;i<n;i++) w[i]=0.5*(1-Math.cos(2*Math.PI*i/(n-1)));
          return (this._win[n]=w);
        }
        process(inputs, outputs, params){
          const outL = outputs[0][0]; const outR = outputs[0][1] || outputs[0][0];
          outL.fill(0); outR.fill(0);
          if(!this.bufL || this.len<=1) return true;

          const gate = (params.gate.length>1?params.gate[0]:params.gate[0])|0;
          if(!gate){ return true; } // silent when gate=0 (not playing)

          const rate = params.rate.length>1 ? params.rate[0] : params.rate[0];
          const semi = params.transpose.length>1 ? params.transpose[0] : params.transpose[0];
          const grainSec = params.grainSize[0];
          const ov = params.overlap[0];

          const pitch = Math.pow(2, semi/12);
          const grainLen = Math.max(32, Math.floor(grainSec * this.sr));
          const hop = Math.max(1, Math.floor(grainLen * (1-ov)));
          const win = this.hann(grainLen);

          // Simple 1-grain OLA per block (cheap & stable)
          for(let i=0; i<outL.length; i++){
            // compute source index for this output sample
            // time-stretch: advance read head by 'rate' every 'hop' samples
            if(i % hop === 0){
              const step = (this.reverse ? -1 : 1) * Math.max(0.0001, rate) * hop;
              this.pos += step;
              if(this.loop){
                while(this.pos < 0) this.pos += this.len;
                while(this.pos >= this.len) this.pos -= this.len;
              }else{
                if(this.pos < 0 || this.pos >= this.len){ this.pos = Math.max(0, Math.min(this.pos, this.len-1)); }
              }
            }

            // pitch: resample within the grain
            const gphase = (i % grainLen) / grainLen;
            const srcIndex = this.pos + (gphase * grainLen) * (this.reverse ? -pitch : pitch);
            let j = Math.floor(srcIndex);
            let a = srcIndex - j;

            if(this.loop){
              while(j < 0) j += this.len;
              while(j >= this.len) j -= this.len;
            }else{
              if(j < 0){ j = 0; a = 0; }
              if(j >= this.len-1){ j = this.len-2; a = 1; }
            }

            const l0 = this.bufL[j] || 0, l1 = this.bufL[(j+1) % this.len] || 0;
            const r0 = (this.bufR?this.bufR[j]:l0), r1 = (this.bufR?this.bufR[(j+1)%this.len]:l1);
            const w = win[Math.floor(gphase*(win.length-1))];
            const sL = (l0 + (l1-l0)*a) * w;
            const sR = (r0 + (r1-r0)*a) * w;

            outL[i] += sL;
            outR[i] += sR;
          }
          return true;
        }
      }
      registerProcessor('granular-processor', GranularProcessor);
    `;
    const blob = new Blob([code], {type:'application/javascript'});
    self._granularWorkletURL = URL.createObjectURL(blob);
    self._granularWorkletReady = true;
  })();

(function(){
  // ===== Utilities =====

  function applyIndepRouting(sample, gA, gB){
    try{
      if(sample.indepTP){
        if(!sample.A.proc) sample.A.proc = createGranularNodeFor(sample.A);
        if(!sample.B.proc) sample.B.proc = createGranularNodeFor(sample.B);
        if(sample.A.proc){ try{ sample.A.proc.disconnect(); }catch(e){} sample.A.proc.connect(gA); }
        if(sample.B.proc){ try{ sample.B.proc.disconnect(); }catch(e){} sample.B.proc.connect(gB); }
      }else{
        try{ if(sample.A.proc) sample.A.proc.disconnect(); }catch(e){}
        try{ if(sample.B.proc) sample.B.proc.disconnect(); }catch(e){}
      }
    }catch(e){ console.warn('applyIndepRouting', e); }
  }

  function createGranularNodeFor(side){
    if(!ACTX || !ACTX.audioWorklet) return null;
    try{
      const node = new AudioWorkletNode(ACTX, 'granular-processor', { numberOfInputs:0, numberOfOutputs:1, outputChannelCount:[2] });
      node.parameters.get('rate').value = 1;
      node.parameters.get('transpose').value = 0;
      node.parameters.get('grainSize').value = 0.08;
      node.parameters.get('overlap').value = 0.6;
      node.parameters.get('gate').value = 0;
      // send buffer if available
      if(side && side.buf){
        const L = side.buf.getChannelData(0).slice();
        const R = (side.buf.numberOfChannels>1) ? side.buf.getChannelData(1).slice() : null;
        node.port.postMessage({type:'setBuffer', L, R});
      }
      return node;
    }catch(e){ console.warn('Granular node create failed', e); return null; }
  }
  function clamp01(x){ return x<0?0:(x>1?1:x); }
  function makeReversedBuffer(buf){
    if(!buf) return null;
    const out = new AudioBuffer({length: buf.length, numberOfChannels: buf.numberOfChannels, sampleRate: buf.sampleRate});
    for(let ch=0; ch<buf.numberOfChannels; ch++){
      const src = buf.getChannelData(ch);
      const dst = out.getChannelData(ch);
      for(let i=0, n=src.length; i<n; i++) dst[i] = src[n-1-i];
    }
    return out;
  }

  const GRID = 16; // snap size (px)
  const LFO_TICKS = [];
  const MODULE_TEMPLATES = new Map();
  const MODULE_LABELS = {
    timepitch: 'Time & Pitch',
    muffle: 'Muffle',
    tone: 'Tone',
    noise: 'Noise',
    eq: 'EQ',
    fx: 'FX Chain',
    modulation: 'Modulation',
    space: 'Spaces',
    spectrum: 'Spectrogram'
  };
  let LFO_LOOP_STARTED = false;
  function ensureLfoLoop(){
    if(LFO_LOOP_STARTED) return;
    LFO_LOOP_STARTED = true;
    const loop = (ts)=>{ for(const fn of LFO_TICKS){ try{ fn(ts); }catch(e){} } requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  const qs = (sel, root=document)=>root.querySelector(sel);
  const qsa = (sel, root=document)=>Array.from(root.querySelectorAll(sel));
  const ce = (tag, cls)=>{ const el=document.createElement(tag); if(cls) el.className=cls; return el; };
  const fmtPan = v => (Math.abs(v)<0.01 ? 'C' : (v<0?`L ${Math.round(-v*100)}%`:`R ${Math.round(v*100)}%`));
  const valueToFreq = x => 300 * Math.pow(20000/300, x); // 0..1 -> 300..20000 Hz
  const clamp = (v,min,max)=>Math.min(max,Math.max(min,v));
  const tip = (el, text)=>{ el.setAttribute('title', text); el.classList.add('hasTip'); };

  // ===== Audio Master Graph =====
  let ACTX = null;
  const MASTER = { pre:null, limiter:null };

  
  async function loadGranularWorklet(){
    try{
      ensureGranularWorklet();
      await ACTX.audioWorklet.addModule(self._granularWorkletURL);
    }catch(e){ console.warn('Granular worklet failed to load', e); }
  }
function bootAudio(){
    if(ACTX) return;
    ACTX = new (window.AudioContext || window.webkitAudioContext)({ latencyHint:'interactive' });

    // expose for legacy helpers that look up the global context
    window.ACTX = ACTX;

    MASTER.pre = ACTX.createGain(); MASTER.pre.gain.value = 1.0;
    MASTER.limiter = ACTX.createDynamicsCompressor();
    MASTER.limiter.threshold.value = -6; MASTER.limiter.knee.value = 6; MASTER.limiter.ratio.value = 6;
    MASTER.limiter.attack.value = 0.003; MASTER.limiter.release.value = 0.25;

    MASTER.pre.connect(MASTER.limiter);
    MASTER.limiter.connect(ACTX.destination);

    // allow external modulation helpers to reuse the master output
    window._MASTER_OUT = MASTER.pre;

    if(typeof window._GLOBAL_TEMPO !== 'number'){ window._GLOBAL_TEMPO = 120; }
  }

  window.ensureNoisetownAudio = function ensureNoisetownAudio(){
    bootAudio();
    if(ACTX && typeof ACTX.resume === 'function' && ACTX.state === 'suspended'){
      ACTX.resume().catch(()=>{});
    }
    return { context: ACTX, master: MASTER.pre };
  };

  // ===== Blocks & Streams =====
  const main = qs('#main');
  const blocks = [];        // { el, bus, analyser, cvs, ctx, streams:[] }
  const streamSpectros = []; // for spectrogram draw loop

  let blockCount = 0;

  function addBlock(){
    if(!ACTX){ bootAudio(); /* resume only on Start Audio click */ }
    const blockEl = ce('div','block');
    const id = ++blockCount;
    blockEl.dataset.id = id;
    blockEl.innerHTML = `
      <h2><span class="dragHandle" style="cursor:move">Move</span> Block ${id}</h2>
      <div class="row">
        <label>Block Vol</label><input type="range" class="blockVol" min="0" max="1" step="0.001" value="1.0"><span class="small bVolVal">100%</span>
        <button class="btn addStream">Add Stream</button>
        <canvas class="scope" aria-label="Oscilloscope for Block ${id}"></canvas>
      </div>
      <div class="streams"></div>
    `;
    
    // Add reset buttons to block-level sliders (excluding volume)
    ;(function addBlockSliderResets(){
      const ranges = blockEl.querySelectorAll('input[type="range"]');
      ranges.forEach(r=>{
        if(r.classList.contains('no-reset') || r.classList.contains('vol') || /vol/i.test(r.className) || /vol/i.test(r.id||'')) return;
        if(r.nextElementSibling && r.nextElementSibling.classList && r.nextElementSibling.classList.contains('reset')) return;
        const btn = document.createElement('button');
        btn.className = 'btn btn-xs reset';
        btn.textContent = 'Reset';
        btn.title = 'Reset to default';
        btn.style.marginLeft = '4px';
        r.setAttribute('data-default', r.defaultValue);
        r.insertAdjacentElement('afterend', btn);
        btn.addEventListener('click', ()=>{
          const def = r.getAttribute('data-default');
          if(def!=null){ r.value = def; r.dispatchEvent(new Event('input', {bubbles:true})); }
        });
      });
    })();
const bus = ACTX.createGain(); bus.gain.value = 1.0; bus.connect(MASTER.pre);
    // Per-block analyser for oscilloscope
    const analyser = ACTX.createAnalyser(); analyser.fftSize = 1024;
    bus.connect(analyser);

    const bVol = qs('.blockVol', blockEl);
    const bVolVal = qs('.bVolVal', blockEl);
    bVol.addEventListener('input', ()=>{
      bus.gain.setTargetAtTime(parseFloat(bVol.value)||0, ACTX.currentTime, 0.02);
      bVolVal.textContent = Math.round(parseFloat(bVol.value)*100) + '%';
    });

    qs('.addStream', blockEl).addEventListener('click', ()=>{
      const sIdx = qs('.streams', blockEl).children.length + 1;
      const s = createStream(sIdx, bus);
      qs('.streams', blockEl).appendChild(s.el);
      renumberStreams(blockEl);
      enableEditReorder(editMode);
    });

    // Init canvas size for block scope
    const cvs = qs('.scope', blockEl);
    const ctx = cvs.getContext('2d', { willReadFrequently: true });
    const resizeScope = ()=>{ const bb = cvs.getBoundingClientRect(); cvs.width = Math.max(220, Math.floor(bb.width)); cvs.height = 60; };
    resizeScope(); window.addEventListener('resize', resizeScope);

    const blockModel = { el:blockEl, bus, analyser, cvs, ctx, streams:[] };
    blocks.push(blockModel);

    // Drag (Edit mode)
    const handle = blockEl.querySelector('.dragHandle');
    let drag = null;
    
    handle.addEventListener('mousedown', (e)=>{
      if(!editMode) return;
      const r = blockEl.getBoundingClientRect();
      const parentR = main.getBoundingClientRect();
      drag = {dx:e.clientX - r.left, dy:e.clientY - r.top, parentR, w:r.width, h:r.height};
      blockEl.classList.add('dragging');
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e)=>{
      if(!drag) return;
      let x = e.clientX - drag.parentR.left - drag.dx + main.scrollLeft;
      let y = e.clientY - drag.parentR.top - drag.dy + main.scrollTop;
      // grid snap
      x = Math.round(x / GRID) * GRID;
      y = Math.round(y / GRID) * GRID;
      blockEl.style.left = x + 'px';
      blockEl.style.top = y + 'px';
      blockEl.style.position = 'absolute';
      // fixed width based on initial down
      blockEl.style.width = Math.max(520, Math.floor(drag.w)) + 'px';
    });
    window.addEventListener('mouseup', ()=>{
      if(!drag) return;
      drag=null;
      blockEl.classList.remove('dragging');
    });
main.appendChild(blockEl);

return blockModel;
  }

  function createStream(idx, blockBus){
    const el = ce('div','stream');
    el.innerHTML = `

      <h3>Stream ${idx}</h3>
      <div class="row aRow">
        <label>A</label><input class="fileA" type="file" accept="audio/*"><span class="small aName">none</span>
        <div class="spacer"></div>
        <div class="small">A&nbsp;Pos</div>
        <input class="scrubA" type="range" min="0" max="1" step="0.001" value="0" style="width:220px">
        <span class="small curTimeA">0:00</span>
      </div>
      <div class="row bRow">
        <label>B</label><input class="fileB" type="file" accept="audio/*"><span class="small bName">none</span>
        <div class="spacer"></div>
        <div class="small">B&nbsp;Pos</div>
        <input class="scrubB" type="range" min="0" max="1" step="0.001" value="0" style="width:220px">
        <span class="small curTimeB">0:00</span>
      </div>
      <div class="row">
        <button class="btn play">Play</button>
        <button class="btn stop">Stop</button>
        <label>Loop</label><input type="checkbox" class="loop" checked>
        <div class="spacer"></div>






      </div>
      <div class="row">
        <label>A↔B</label>
        <input class="ab midiable" type="range" min="0" max="1" step="0.001" value="0.5">
        <span class="small abVal">A=B</span>
      </div>
      <div class="row">
        <label>Vol</label>
        <input class="vol midiable" type="range" min="0" max="1" step="0.001" value="1"><span class="small volVal">100%</span>
        <label style="margin-left:10px;">Pan</label>
        <input class="pan midiable" type="range" min="-1" max="1" step="0.001" value="0"><span class="small panVal">C</span>
        <button class="btn mute" title="Mute">Mute</button>
      </div>
<!-- Vertical dropdown modules -->
      <div class="mods">\n
      <div class="mod mod-timepitch" data-mod="timepitch">
        <div class="mod-hdr"><span class="name">Time &amp; Pitch</span><span class="carat">▸</span></div>
        <div class="mod-body">
<div class="row">
        <label>Tempo</label>
        <input class="tempo midiable" type="range" min="0.25" max="4" step="0.01" value="1"><span class="small tempoVal">1.00×</span>
        <label style="margin-left:10px;">Pitch</label>
        <input class="pitch midiable" type="range" min="-12" max="12" step="1" value="0"><span class="small pitchVal">0 st</span>
        <label style="margin-left:10px;">Advanced (independent)</label>
        <input class="indepTP" type="checkbox">
      </div>
      <div class="row">
        <label>Reverse A</label><input class="revA" type="checkbox">
        <label style="margin-left:10px;">Reverse B</label><input class="revB" type="checkbox">
      </div>
        </div>
      </div>
    

        <div class="mod muffleMod" data-mod="muffle">
          <div class="mod-hdr"><span class="name">Muffle</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <button class="btn muffle">Muffle: OFF</button>
              <label>Amt</label><input class="mAmt midiable" type="range" min="0" max="1" step="0.001" value="1">
              <span class="small hz">Cutoff: 20,000 Hz</span>
            </div>
          </div>
        </div>

        <div class="mod toneMod" data-mod="tone">
          <div class="mod-hdr"><span class="name">Tone</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <button class="btn tone">Tone: OFF</button>
              <label>Wave</label>
              <select class="tWave"><option>sine</option><option>square</option><option>triangle</option><option>sawtooth</option></select>
              <label>Preset</label>
              <select class="tPreset">
                <option value="custom">Custom</option>
                <option value="schumann">Schumann (7.83 Hz)</option>
                <option value="delta">Delta (0.5–4)</option>
                <option value="theta">Theta (4–8)</option>
                <option value="alpha">Alpha (8–12)</option>
                <option value="beta">Beta (12–30)</option>
                <option value="gamma">Gamma (30–45)</option>
              </select>
            </div>
            <div class="row">
              <label>Base</label><input class="tBase midiable" type="number" min="20" max="2000" value="200" style="width:70px" title="Carrier base frequency in Hz">
              <label>Δ</label><input class="tBeat midiable" type="number" min="0" max="45" value="10" style="width:60px" title="Binaural beat delta between left and right oscillators (Hz)">
              <label>Level</label><input class="tLevel midiable" type="range" min="0" max="1" step="0.001" value="0.2" style="width:120px" title="Output level of the tone generator">
              <span class="small tSum">L 195.0 Hz / R 205.0 Hz</span>
            </div>
          </div>
        </div>

        <div class="mod noiseMod" data-mod="noise">
          <div class="mod-hdr"><span class="name">Noise</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <button class="btn noise">Noise: OFF</button>
              <label>Type</label><select class="nType"><option>white</option><option>pink</option><option>brown</option></select>
              <label>Level</label><input class="nLevel midiable" type="range" min="0" max="1" step="0.001" value="0.2" style="width:140px" title="Output level of the noise generator">
              <label>Tilt</label><input class="nTilt midiable" type="range" min="-1" max="1" step="0.01" value="0" style="width:140px" title="Spectral tilt: negative = darker (low boost), positive = brighter (high boost)">
            </div>
          </div>
        </div>

        <div class="mod eqMod" data-mod="eq">
          <div class="mod-hdr"><span class="name">EQ</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <label class="hasTip" title="Low shelf: boosts/attenuates low frequencies around 120 Hz">Low</label>
              <input class="eqLow midiable" type="range" min="-12" max="12" step="0.1" value="0" style="width:140px"><span class="small eqLowVal">0.0 dB</span>
              <label class="hasTip" title="Mid peaking filter near 1 kHz">Mid</label>
              <input class="eqMid midiable" type="range" min="-12" max="12" step="0.1" value="0" style="width:140px"><span class="small eqMidVal">0.0 dB</span>
              <label class="hasTip" title="High shelf: boosts/attenuates high frequencies above ~8 kHz">High</label>
              <input class="eqHigh midiable" type="range" min="-12" max="12" step="0.1" value="0" style="width:140px"><span class="small eqHighVal">0.0 dB</span>
            </div>
          </div>
        </div>

        <div class="mod fxMod" data-mod="fx">
          <div class="mod-hdr"><span class="name">FX Chain</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <label class="hasTip" title="Wet/dry balance for the FX return">FX Mix</label>
              <input class="fxMix midiable" type="range" min="0" max="1" step="0.001" value="0" style="width:140px"><span class="small fxMixVal">0%</span>
              <label class="hasTip" title="Delay time in seconds">Delay</label>
              <input class="fxDelay midiable" type="range" min="0" max="1" step="0.001" value="0.25" style="width:140px"><span class="small fxDelayVal">0.25s</span>
              <label class="hasTip" title="Feedback amount (how much of the delay output is fed back)">Feedback</label>
              <input class="fxFb midiable" type="range" min="0" max="0.95" step="0.001" value="0.3" style="width:140px"><span class="small fxFbVal">30%</span>
              <label class="hasTip" title="Waveshaper distortion amount">Dist</label>
              <input class="fxDist midiable" type="range" min="0" max="1" step="0.001" value="0" style="width:140px"><span class="small fxDistVal">0%</span>
            </div>
          </div>
        </div>

        <div class="mod modMatrix" data-mod="modulation">
          <div class="mod-hdr"><span class="name">Modulation</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <button class="btn lfoOn" title="Toggle low-frequency oscillator modulation">LFO: OFF</button>
              <label class="hasTip" title="Which parameter the LFO modulates">Target</label>
              <select class="lfoTarget"><option value="pan">Pan</option><option value="vol">Volume</option><option value="lpf">LPF Cutoff</option><option value="tempo">Tempo</option><option value="pitch">Pitch</option><option value="ab">A↔B Mix</option><option value="apos">A Position</option><option value="bpos">B Position</option></select>
              <label class="hasTip" title="Oscillation speed of LFO">Rate</label>
              <input class="lfoRate midiable" type="range" min="0.05" max="10" step="0.01" value="0.5"><span class="small lfoRateVal">0.50 Hz</span>
              <label class="hasTip" title="Modulation amount of LFO">Depth</label>
              <input class="lfoDepth midiable" type="range" min="0" max="1" step="0.001" value="0.4"><span class="small lfoDepthVal">40%</span>
            </div>
            <div class="row">
              <label class="hasTip" title="Attack: time to rise from 0 to peak">Env A</label>
              <input class="envA midiable" type="range" min="0.001" max="2" step="0.001" value="0.01"><span class="small envAVal">10 ms</span>
              <label class="hasTip" title="Decay: time to drop from peak to sustain level">D</label>
              <input class="envD midiable" type="range" min="0.001" max="2" step="0.001" value="0.2"><span class="small envDVal">0.20 s</span>
              <label class="hasTip" title="Sustain: level held while note is on">S</label>
              <input class="envS midiable" type="range" min="0" max="1" step="0.001" value="0.7"><span class="small envSVal">70%</span>
              <label class="hasTip" title="Release: time to fall back to 0 after stop">R</label>
              <input class="envR midiable" type="range" min="0.001" max="3" step="0.001" value="0.4"><span class="small envRVal">0.40 s</span>
            </div>
          </div>
        </div>

        <div class="mod spaceMod" data-mod="space">
          <div class="mod-hdr"><span class="name">Spaces</span><span class="carat">▸</span></div>
          <div class="mod-body">
            <div class="row">
              <label>Preset</label>
              <select class="spPreset">
                <option value="none">None</option>
                <option value="hall">Hall</option>
                <option value="studio">Studio</option>
                <option value="cabin">Cabin</option>
              </select>
              <label>Mix</label><input class="spMix midiable" type="range" min="0" max="1" step="0.001" value="0"><span class="small spMixVal">0%</span>
              <label>Decay</label><input class="spDecay midiable" type="range" min="0.2" max="6" step="0.01" value="1.2"><span class="small spDecayVal">1.20 s</span>
              <label>Pre-Delay</label><input class="spPre midiable" type="range" min="0" max="0.25" step="0.001" value="0.0"><span class="small spPreVal">0.00 s</span>
            </div>
          </div>
        </div>

        <div class="mod spectrumMod" data-mod="spectrum">
        <div class="mod-hdr"><span class="name">Spectrogram</span><span class="carat">▸</span></div>
        <div class="mod-body">
          <canvas class="spectro" aria-label="Spectrogram"></canvas>
        </div>
      </div>
    </div>


      </div><div class="mod-body">
<div class="row">
      <label>Tempo</label>
      <input class="tempo midiable" type="range" min="0.25" max="4" step="0.01" value="1"><span class="small tempoVal">1.00×</span>
      <label style="margin-left:10px;">Pitch</label>
      <input class="pitch midiable" type="range" min="-12" max="12" step="1" value="0"><span class="small pitchVal">0 st</span>
      <label style="margin-left:10px;">Advanced (independent)</label>
      <input class="indepTP" type="checkbox">
    </div>
    <div class="row">
      <label>Reverse A</label><input class="revA" type="checkbox">
      <label style="margin-left:10px;">Reverse B</label><input class="revB" type="checkbox">
    </div>
    </div>
  </div>`;

    const modsContainer = el.querySelector('.mods');
    let refreshModChoices = ()=>{};
    const rawHeader = el.querySelector('h3');
    if(rawHeader){
      const headerWrap = document.createElement('div');
      headerWrap.className = 'stream-header';
      const actions = document.createElement('div');
      actions.className = 'stream-actions';
      const removeStreamBtn = document.createElement('button');
      removeStreamBtn.type = 'button';
      removeStreamBtn.className = 'btn btn-xs removeStream';
      removeStreamBtn.textContent = 'Remove Stream';
      const addSelect = document.createElement('select');
      addSelect.className = 'mod-add-select';
      const addButton = document.createElement('button');
      addButton.type = 'button';
      addButton.className = 'btn btn-xs addModBtn';
      addButton.textContent = 'Add Module';
      const dragHint = document.createElement('span');
      dragHint.className = 'stream-hint';
      dragHint.textContent = 'Drag to reorder';
      actions.append(removeStreamBtn, addSelect, addButton, dragHint);
      headerWrap.append(rawHeader, actions);
      el.insertBefore(headerWrap, el.firstChild);
      refreshModChoices = ()=>{
        if(!modsContainer){ addSelect.disabled = true; addButton.disabled = true; return; }
        const present = new Set(Array.from(modsContainer.querySelectorAll('.mod')).map(mod=>mod.dataset.mod).filter(Boolean));
        const available = Array.from(MODULE_TEMPLATES.keys()).filter(key=>!present.has(key));
        addSelect.innerHTML = '';
        if(!available.length){
          const opt = document.createElement('option');
          opt.value='';
          opt.textContent='All modules added';
          addSelect.appendChild(opt);
          addSelect.disabled = true;
          addButton.disabled = true;
        }else{
          available.forEach(key=>{
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = moduleLabel(key);
            addSelect.appendChild(opt);
          });
          addSelect.disabled = false;
          addButton.disabled = false;
        }
      };
      addButton.addEventListener('click', ()=>{
        const key = addSelect.value;
        if(!key || !MODULE_TEMPLATES.has(key) || !modsContainer) return;
        const tmp = document.createElement('div');
        tmp.innerHTML = MODULE_TEMPLATES.get(key).trim();
        const newMod = tmp.firstElementChild;
        if(!newMod) return;
        modsContainer.appendChild(newMod);
        attachModuleClose(newMod);
        const closeBtn = newMod.querySelector('.mod-close');
        if(closeBtn && !closeBtn._refreshBound){
          closeBtn._refreshBound = true;
          closeBtn.addEventListener('click', ()=> setTimeout(refreshModChoices, 0));
        }
        makeModsDraggable(modsContainer);
        enableEditReorder(editMode);
        refreshModChoices();
      });
      removeStreamBtn.addEventListener('click', ()=>{
        stopPlayback();
        el.remove();
        const blockEl = el.closest('.block');
        if(blockEl){
          renumberStreams(blockEl);
        }
        enableEditReorder(editMode);
      });
    }

    el.querySelectorAll('.mod').forEach(mod=>{
      attachModuleClose(mod);
      const closeBtn = mod.querySelector('.mod-close');
      if(closeBtn && !closeBtn._refreshBound){
        closeBtn._refreshBound = true;
        closeBtn.addEventListener('click', ()=> setTimeout(refreshModChoices, 0));
      }
    });
    captureModuleTemplates(el);
    refreshModChoices();

    
    // Dropdown toggles (supports <div class="mod"><div class="mod-hdr">...</div></div>
    // and <details class="mod"><summary>...</summary> ... </details>)
    el.querySelectorAll('.mod').forEach(mod=>{
      const isDetails = mod.tagName && mod.tagName.toLowerCase()==='details';
      const hdr = mod.querySelector('.mod-hdr') || mod.querySelector('summary');
      let carat = mod.querySelector('.carat');
      if(isDetails){
        // Ensure a carat exists in summary for visual consistency
        if(hdr && !carat){
          carat = document.createElement('span');
          carat.className = 'carat';
          carat.textContent = mod.open ? '▾' : '▸';
          hdr.appendChild(carat);
        }
        mod.classList.toggle('open', !!mod.open);
        mod.addEventListener('toggle', ()=>{
          mod.classList.toggle('open', !!mod.open);
          if(carat) carat.textContent = mod.open ? '▾' : '▸';
        });
      }else if(hdr && carat){
        hdr.addEventListener('click', ()=>{
          const open = !mod.classList.contains('open');
          mod.classList.toggle('open', open);
          carat.textContent = open ? '▾' : '▸';
        });
      }
    });

    // --- Nodes per stream ---

    const gA = ACTX.createGain(); gA.gain.value = 1.0;
    const gB = ACTX.createGain(); gB.gain.value = 1.0; // will set by AB
    const sampleVCA = ACTX.createGain(); sampleVCA.gain.value = 1.0; // ADSR applies here (samples only)
    const genSum = ACTX.createGain(); genSum.gain.value = 1.0; // tone/noise path (always audible)
    const preEQ = ACTX.createGain(); // mix of sampleVCA + generators
    const lpf = ACTX.createBiquadFilter(); lpf.type='lowpass'; lpf.frequency.value=20000; lpf.Q.value=0.707;

    // EQ
    const eqLow = ACTX.createBiquadFilter(); eqLow.type='lowshelf'; eqLow.frequency.value=120; eqLow.gain.value=0;
    const eqMid = ACTX.createBiquadFilter(); eqMid.type='peaking'; eqMid.frequency.value=1000; eqMid.Q.value=1; eqMid.gain.value=0;
    const eqHigh = ACTX.createBiquadFilter(); eqHigh.type='highshelf'; eqHigh.frequency.value=8000; eqHigh.gain.value=0;

    // FX chain (distortion -> delay)
    const dryGain = ACTX.createGain(); dryGain.gain.value = 1.0;
    const fxIn = ACTX.createGain(); const fxOut = ACTX.createGain(); fxOut.gain.value = 0;
    const shaper = ACTX.createWaveShaper();
    const delay = ACTX.createDelay(1.0); delay.delayTime.value = 0.25;
    const fb = ACTX.createGain(); fb.gain.value = 0.3;

    // Spaces (per-stream convolver path)
    const spPre = ACTX.createDelay(1.0); spPre.delayTime.value = 0.0;
    const convolver = ACTX.createConvolver(); convolver.normalize = true;
    const spWet = ACTX.createGain(); spWet.gain.value = 0;

    // Sum -> Pan -> Out
    const sum = ACTX.createGain(); const pan = ACTX.createStereoPanner(); pan.pan.value = 0;
    const out = ACTX.createGain(); out.gain.value = 0.5; // default 50%

    // Routing
    gA.connect(sampleVCA); gB.connect(sampleVCA);
    sampleVCA.connect(preEQ);
    genSum.connect(preEQ);
    preEQ.connect(lpf);
    lpf.connect(eqLow); eqLow.connect(eqMid); eqMid.connect(eqHigh);
    // Split to dry/fx/spaces
    eqHigh.connect(dryGain);
    eqHigh.connect(fxIn);
    eqHigh.connect(spPre);
    // FX path
    fxIn.connect(shaper); shaper.connect(delay); delay.connect(fxOut); delay.connect(fb); fb.connect(delay);
    // Spaces path
    spPre.connect(convolver); convolver.connect(spWet);
    // Sum to pan/out
    dryGain.connect(sum); fxOut.connect(sum); spWet.connect(sum); sum.connect(pan); pan.connect(out); out.connect(blockBus);

    // Visuals: per-block oscilloscope is connected at block bus.
    // Per-stream spectrogram analyser:
    const specAnalyser = ACTX.createAnalyser(); specAnalyser.fftSize = 512; out.connect(specAnalyser);

    // Sampler state
    const sample = { indepTP:false, A:{buf:null,revBuf:null,src:null,name:'',dur:0,offset:0,startTime:0, reverse:false}, B:{buf:null,revBuf:null,src:null,name:'',dur:0,offset:0,startTime:0, reverse:false}, loop:true, playing:false, tempo:1.0, pitch:0 };
    // expose for preset save / modulation helpers
    el._streamState = sample;

    // LFO state (JS-driven for general targets)
    const lfo = { enabled:false, rate:0.5, depth:0.4, target:'pan', t0:performance.now(), wave:'sine' };
    const sh = { enabled:false, target:'pan', rate:2, depth:0.25, t0:performance.now(), tPrev:0, val:0 };

    // Envelope (ADSR) applied to sampleVCA only
    const env = { a:0.01, d:0.2, s:0.7, r:0.4 };

    // share modulation context with external helpers (mods-advanced.js, etc.)
    const modCtx = { el, actx: ACTX, out, pan, lpf, sample, lfo, sh, env, gA, gB };
    el.__modCtx = modCtx;

    // Helpers
    const decodeFile = (file)=> new Promise((res,rej)=>{
      const fr = new FileReader();
      fr.onload = async ev => {
        try{ const buf = await ACTX.decodeAudioData(ev.target.result); res(buf); }
        catch(err){ rej(err); }
      };
      fr.readAsArrayBuffer(file);
    });

    const startSide = (side, gainNode, when=ACTX.currentTime, offset=0, rate=1)=>{
      if(!side.buf) return null;
      try{ if(side.src){ try{ side.src.stop(); }catch(e){} } }catch(e){}
      const src = ACTX.createBufferSource();
      const useBuf = (side.reverse ? (side.revBuf||side.buf) : side.buf);
    src.buffer = useBuf; src.loop = sample.loop;
      src.playbackRate.value = (rate||1);
    src.connect(gainNode);
      src.start(when, (useBuf && useBuf.duration ? (offset % useBuf.duration) : 0));
      side.src = src;
      return src;
    };

    function trigEnvAttack(){
      const now = ACTX.currentTime;
      sampleVCA.gain.cancelScheduledValues(now);
      sampleVCA.gain.setValueAtTime(0, now);
      const base = 1;
      sampleVCA.gain.linearRampToValueAtTime(base, now + env.a);
      sampleVCA.gain.linearRampToValueAtTime(base * env.s, now + env.a + env.d);
    }
    function trigEnvRelease(){
      const now = ACTX.currentTime;
      const cur = sampleVCA.gain.value;
      sampleVCA.gain.cancelScheduledValues(now);
      sampleVCA.gain.setValueAtTime(cur, now);
      sampleVCA.gain.linearRampToValueAtTime(0, now + env.r);
    }

    function startPlayback(){
    const when = ACTX.currentTime + 0.01;
    if(sample.indepTP && sample.A.proc && sample.B.proc){
      // Independent: drive granular processors
      const rate = sample.tempo||1, semi = sample.pitch||0;
      // gate on, set params, seek
      [ ['A', sample.A, gA], ['B', sample.B, gB] ].forEach(([key, side, g])=>{
        const node = side.proc;
        node.parameters.get('rate').value = rate;
        node.parameters.get('transpose').value = semi;
        node.parameters.get('gate').value = 1;
        node.port.postMessage({type:'params', loop: sample.loop, reverse: !!side.reverse});
        const off = side.offset || 0;
        node.port.postMessage({type:'seek', time: off});
      });
      sample.A.startTime = when - (sample.A.offset / rate);
      sample.B.startTime = when - (sample.B.offset / rate);
      sample.playing = true;
      qs('.play', el).classList.add('on');
      try{ trigEnvAttack(); }catch(e){}
    }else{
      // Classic path (tempo & pitch are coupled)
      const rate = (sample.tempo||1) * Math.pow(2, (sample.pitch||0)/12);
      startSide(sample.A, gA, when, sample.A.offset, rate);
      startSide(sample.B, gB, when, sample.B.offset, rate);
      sample.A.startTime = when - (sample.A.offset / rate);
      sample.B.startTime = when - (sample.B.offset / rate);
      sample.playing = true;
      qs('.play', el).classList.add('on');
      try{ trigEnvAttack(); }catch(e){}
    }
  }
    function stopPlayback(){
    try{ if(sample.A.src){ sample.A.src.stop(); sample.A.src.disconnect(); sample.A.src=null; } }catch(e){}
    try{ if(sample.B.src){ sample.B.src.stop(); sample.B.src.disconnect(); sample.B.src=null; } }catch(e){}
    try{ if(sample.indepTP && sample.A.proc){ sample.A.proc.parameters.get('gate').value = 0; } }catch(e){}
    try{ if(sample.indepTP && sample.B.proc){ sample.B.proc.parameters.get('gate').value = 0; } }catch(e){}
    sample.playing = false;
    qs('.play', el).classList.remove('on');
    try{ trigEnvRelease(); }catch(e){}
  }

  // Files
    qs('.fileA', el).addEventListener('change', async (e)=>{
      const f = e.target.files[0]; if(!f) return;
      try{ sample.A.buf = await decodeFile(f); sample.A.revBuf = makeReversedBuffer(sample.A.buf);
        
        if(sample.A.proc){
          const L = sample.A.buf.getChannelData(0).slice();
          const R = (sample.A.buf.numberOfChannels>1)?sample.A.buf.getChannelData(1).slice():null;
          sample.A.proc.port.postMessage({type:'setBuffer', L, R});
          if(sample.playing){ sample.A.proc.port.postMessage({type:'seek', time: sample.A.offset||0}); }
        }
        if(sample.A.proc){ const L = sample.A.buf.getChannelData(0).slice(); const R = (sample.A.buf.numberOfChannels>1)?sample.A.buf.getChannelData(1).slice():null; sample.A.proc.port.postMessage({type:'setBuffer', L, R}); }
        sample.A.name=f.name; sample.A.dur = sample.A.buf.duration; updateDurations(); qs('.aName', el).textContent = f.name; updateDurations(); if(sample.playing) startPlayback(); }catch{ alert('Failed to load A'); }
    });
    qs('.fileB', el).addEventListener('change', async (e)=>{
      const f = e.target.files[0]; if(!f) return;
      try{ sample.B.buf = await decodeFile(f); sample.B.revBuf = makeReversedBuffer(sample.B.buf);
        
        if(sample.B.proc){
          const L = sample.B.buf.getChannelData(0).slice();
          const R = (sample.B.buf.numberOfChannels>1)?sample.B.buf.getChannelData(1).slice():null;
          sample.B.proc.port.postMessage({type:'setBuffer', L, R});
          if(sample.playing){ sample.B.proc.port.postMessage({type:'seek', time: sample.B.offset||0}); }
        }
        if(sample.B.proc){ const L = sample.B.buf.getChannelData(0).slice(); const R = (sample.B.buf.numberOfChannels>1)?sample.B.buf.getChannelData(1).slice():null; sample.B.proc.port.postMessage({type:'setBuffer', L, R}); }
        sample.B.name=f.name; sample.B.dur = sample.B.buf.duration; updateDurations(); qs('.bName', el).textContent = f.name; updateDurations(); if(sample.playing) startPlayback(); }catch{ alert('Failed to load B'); }
    });

    
    const fmtTime = s=>{ if(!isFinite(s)) return '0:00'; const m=Math.floor(s/60); const ss=Math.floor(s%60).toString().padStart(2,'0'); return `${m}:${ss}`; };

    const scrubA = qs('.scrubA', el), curTA = qs('.curTimeA', el), durTA = qs('.durTimeA', el);
    const scrubB = qs('.scrubB', el), curTB = qs('.curTimeB', el), durTB = qs('.durTimeB', el);

    function updateDurations(){
      durTA.textContent = fmtTime(sample.A.dur||0);
      durTB.textContent = fmtTime(sample.B.dur||0);
    }

    function updateScrubA(){
      const dur = sample.A.dur||0;
      if(dur<=0){ curTA.textContent = '0:00'; scrubA.value=0; requestAnimationFrame(updateScrubA); return; }
      const rate = sample.indepTP ? (sample.tempo||1) : ((sample.tempo||1) * Math.pow(2,(sample.pitch||0)/12)); const t = sample.playing && (sample.indepTP || sample.A.src) ? ((ACTX.currentTime - sample.A.startTime) * rate) % dur : (sample.A.offset % dur);
      curTA.textContent = fmtTime(t);
      scrubA.value = (t/dur).toFixed(3);
      requestAnimationFrame(updateScrubA);
    }
    function updateScrubB(){
      const dur = sample.B.dur||0;
      if(dur<=0){ curTB.textContent = '0:00'; scrubB.value=0; requestAnimationFrame(updateScrubB); return; }
      const rate = sample.indepTP ? (sample.tempo||1) : ((sample.tempo||1) * Math.pow(2,(sample.pitch||0)/12)); const t = sample.playing && (sample.indepTP || sample.B.src) ? ((ACTX.currentTime - sample.B.startTime) * rate) % dur : (sample.B.offset % dur);
      curTB.textContent = fmtTime(t);
      scrubB.value = (t/dur).toFixed(3);
      requestAnimationFrame(updateScrubB);
    }
    requestAnimationFrame(updateScrubA);
    requestAnimationFrame(updateScrubB);

    scrubA.addEventListener('input', ()=>{
      const dur = sample.A.dur||0; if(dur<=0) return;
      sample.A.offset = parseFloat(scrubA.value) * dur;
      if(sample.playing) startPlayback();
    });
    scrubB.addEventListener('input', ()=>{
      const dur = sample.B.dur||0; if(dur<=0) return;
      sample.B.offset = parseFloat(scrubB.value) * dur;
      if(sample.playing) startPlayback();
    });

    // Playback controls
    // Add reset buttons for range sliders (except any *vol* sliders)
    (function addSliderResets(){
      const ranges = el.querySelectorAll('input[type="range"]');
      ranges.forEach(r=>{
        if(r.classList.contains('no-reset') || r.classList.contains('vol') || /vol/i.test(r.className) || /vol/i.test(r.id||'')) return;
        if(r.nextElementSibling && r.nextElementSibling.classList && r.nextElementSibling.classList.contains('reset')) return;
        const btn = document.createElement('button');
        btn.className = 'btn btn-xs reset';
        btn.textContent = 'Reset';
        btn.title = 'Reset to default';
        btn.style.marginLeft = '4px';
        r.setAttribute('data-default', r.defaultValue);
        r.insertAdjacentElement('afterend', btn);
        btn.addEventListener('click', ()=>{
          const def = r.getAttribute('data-default');
          if(def!=null){ r.value = def; r.dispatchEvent(new Event('input', {bubbles:true})); }
        });
      });
    })();

    qs('.play', el).addEventListener('click', ()=>{ if(!sample.playing) startPlayback(); else stopPlayback(); });
    qs('.stop', el).addEventListener('click', ()=> stopPlayback());
    qs('.loop', el).addEventListener('change', (e)=>{ sample.loop = e.target.checked; if(sample.playing) startPlayback(); });

    
    // Time & Pitch controls (listeners + init)
    const tempo = qs('.tempo', el), tempoVal = qs('.tempoVal', el);
    const pitch = qs('.pitch', el), pitchVal = qs('.pitchVal', el);
    const indep = qs('.indepTP', el);
    const revA = qs('.revA', el), revB = qs('.revB', el);

    function setScrubValue(slider, ratio){
      if(!slider) return;
      const next = clamp(ratio, 0, 1);
      slider.value = next;
      slider.dispatchEvent(new Event('input', { bubbles:true }));
    }

    sample.seekA = (ratio)=>{
      if(!sample.A || !sample.A.dur) return;
      setScrubValue(scrubA, ratio);
    };
    sample.seekB = (ratio)=>{
      if(!sample.B || !sample.B.dur) return;
      setScrubValue(scrubB, ratio);
    };
    modCtx.seekA = sample.seekA;
    modCtx.seekB = sample.seekB;

    function _updateTPReadouts(){
      if(tempo && tempoVal){ tempoVal.textContent = (parseFloat(tempo.value)||1).toFixed(2)+'×'; }
      if(pitch && pitchVal){ pitchVal.textContent = (parseInt(pitch.value,10)||0) + ' st'; }
    }

    if(tempo){ tempo.addEventListener('input', ()=>{
      sample.tempo = parseFloat(tempo.value)||1;
      _updateTPReadouts();
      modCtx.tempoBase = sample.tempo || 1;
      if(sample.indepTP){
        try{ if(sample.A.proc) sample.A.proc.parameters.get('rate').value = sample.tempo; if(sample.B.proc) sample.B.proc.parameters.get('rate').value = sample.tempo; }catch(e){}
      }else if(sample.playing){ startPlayback(); }
    }); }
    sample.setTempo = (ratio)=>{
      if(!tempo){ sample.tempo = ratio; return; }
      const min = parseFloat(tempo.min)||0.25;
      const max = parseFloat(tempo.max)||4;
      const next = clamp(ratio, min, max);
      modCtx.tempoBase = next;
      tempo.value = next;
      tempo.dispatchEvent(new Event('input', { bubbles:true }));
    };
    modCtx.setTempo = sample.setTempo;
    modCtx.tempoBase = sample.tempo || 1;
    if(pitch){ pitch.addEventListener('input', ()=>{
      sample.pitch = parseInt(pitch.value,10)||0;
      _updateTPReadouts();
      if(sample.indepTP){
        try{ if(sample.A.proc) sample.A.proc.parameters.get('transpose').value = sample.pitch; if(sample.B.proc) sample.B.proc.parameters.get('transpose').value = sample.pitch; }catch(e){}
      }else if(sample.playing){ startPlayback(); }
    }); }
    sample.setPitch = (semi)=>{
      if(!pitch){ sample.pitch = semi; return; }
      const min = parseFloat(pitch.min)||-12;
      const max = parseFloat(pitch.max)||12;
      const next = clamp(semi, min, max);
      pitch.value = next;
      pitch.dispatchEvent(new Event('input', { bubbles:true }));
    };
    modCtx.setPitch = sample.setPitch;
    if(revA){ revA.addEventListener('change', ()=>{
      sample.A.reverse = !!revA.checked;
      if(sample.indepTP && sample.A.proc){ try{ sample.A.proc.port.postMessage({type:'params', reverse: sample.A.reverse}); }catch(e){} }
      else if(sample.playing){ startPlayback(); }
    }); }
    if(revB){ revB.addEventListener('change', ()=>{
      sample.B.reverse = !!revB.checked;
      if(sample.indepTP && sample.B.proc){ try{ sample.B.proc.port.postMessage({type:'params', reverse: sample.B.reverse}); }catch(e){} }
      else if(sample.playing){ startPlayback(); }
    }); }
    if(indep){ indep.addEventListener('change', ()=>{
      sample.indepTP = !!indep.checked;
      applyIndepRouting(sample, gA, gB);
      if(sample.indepTP){
        try{
          if(sample.A.proc){ sample.A.proc.parameters.get('rate').value = sample.tempo||1; sample.A.proc.parameters.get('transpose').value = sample.pitch||0; sample.A.proc.port.postMessage({type:'params', loop: sample.loop, reverse: !!sample.A.reverse}); }
          if(sample.B.proc){ sample.B.proc.parameters.get('rate').value = sample.tempo||1; sample.B.proc.parameters.get('transpose').value = sample.pitch||0; sample.B.proc.port.postMessage({type:'params', loop: sample.loop, reverse: !!sample.B.reverse}); }
        }catch(e){}
      }
      if(sample.playing) startPlayback();
    }); }

    // Initialize values + routing
    if(tempo){ sample.tempo = parseFloat(tempo.value)||1; }
    if(pitch){ sample.pitch = parseInt(pitch.value,10)||0; }
    if(revA){ sample.A.reverse = !!revA.checked; }
    if(revB){ sample.B.reverse = !!revB.checked; }
    if(indep){ sample.indepTP = !!indep.checked; applyIndepRouting(sample, gA, gB); }
    _updateTPReadouts();
// AB mix
    const ab = qs('.ab', el), abVal = qs('.abVal', el);
    const setABMix = (mix)=>{
      if(!ab) return;
      const next = clamp(mix, 0, 1);
      ab.value = next;
      ab.dispatchEvent(new Event('input', { bubbles:true }));
    };
    modCtx.setAB = setABMix;
    modCtx.ab = { set: setABMix };
    if(ab && abVal){ ab.addEventListener('input', ()=>{
      const mix = parseFloat(ab.value)||0.5;
      gA.gain.setTargetAtTime(1 - mix, ACTX.currentTime, 0.02);
      gB.gain.setTargetAtTime(mix, ACTX.currentTime, 0.02);
      abVal.textContent = mix<0.01?'A':(mix>0.99?'B':(Math.abs(mix-0.5)<0.01?'A=B':mix.toFixed(2)));
    });
    ab.dispatchEvent(new Event('input')); }

    // Volume / Pan / Mute
    const vol = qs('.vol', el), volVal = qs('.volVal', el);
    const mute = qs('.mute', el), panEl = qs('.pan', el), panVal = qs('.panVal', el);
    if(vol && volVal){
      vol.addEventListener('input', ()=>{
        const v = parseFloat(vol.value)||0;
        sum.gain.setTargetAtTime(v, ACTX.currentTime, 0.02);
        volVal.textContent = Math.round(v*100)+'%';
      });
    }
    if(panEl && panVal){
      panEl.addEventListener('input', ()=>{
        const v = parseFloat(panEl.value)||0;
        pan.pan.setTargetAtTime(v, ACTX.currentTime, 0.02);
        panVal.textContent = fmtPan(v);
      });
    }
    let isMuted = false;
    if(mute){
      mute.addEventListener('click', ()=>{
        isMuted = !isMuted;
        out.gain.setTargetAtTime(isMuted?0:1, ACTX.currentTime, 0.02);
        mute.classList.toggle('on', isMuted);
      });
    }

    // Muffle (LPF)
    const mBtn = qs('.mBtn', el), mAmt = qs('.mAmt', el), hz = qs('.hz', el);
    let mOn = false;
    const applyMuffle = ()=>{
      if(!mAmt) return;
      const f = valueToFreq(parseFloat(mAmt.value)||1);
      if(hz) hz.textContent = 'Cutoff: ' + Math.round(f).toLocaleString() + ' Hz';
      if(mOn){ lpf.frequency.setTargetAtTime(f, ACTX.currentTime, 0.02); }
      else { lpf.frequency.setTargetAtTime(20000, ACTX.currentTime, 0.02); }
      if(mBtn) mBtn.textContent = 'Muffle: ' + (mOn?'ON':'OFF');
    };
    if(mBtn){ mBtn.addEventListener('click', ()=>{ mOn=!mOn; applyMuffle(); }); }
    if(mAmt){ mAmt.addEventListener('input', applyMuffle); applyMuffle(); }

    // Tone (binaural)
    // Tone (binaural)
    const tBtn = qs('.tone', el), tWave = qs('.tWave', el), tPreset = qs('.tPreset', el),
          tBase = qs('.tBase', el), tBeat = qs('.tBeat', el), tLevel = qs('.tLevel', el), tSum = qs('.tSum', el);
    const tone = { enabled:false, nodes:null, wave:'sine', base:200, beat:10, level:0.2 };
    function ensureTone(){
      if(tone.nodes) return;
      const lPan = ACTX.createStereoPanner(); lPan.pan.value = -1;
      const rPan = ACTX.createStereoPanner(); rPan.pan.value = 1;
      const lGain = ACTX.createGain(); const rGain = ACTX.createGain();
      lGain.gain.value = rGain.gain.value = tone.level;
      lPan.connect(lGain); rPan.connect(rGain);
      // Connect tone into generators sum (so it's always audible even if samples stop)
      lGain.connect(genSum); rGain.connect(genSum);
      tone.nodes = { lPan, rPan, lGain, rGain, lOsc:null, rOsc:null };
    }
    function stopTone(){ if(!tone.nodes) return; try{ if(tone.nodes.lOsc){ try{ tone.nodes.lOsc.stop(); }catch(e){} }; if(tone.nodes.rOsc){ try{ tone.nodes.rOsc.stop(); }catch(e){} }; }catch(e){} tone.nodes.lOsc=tone.nodes.rOsc=null; }
    function startTone(){ ensureTone(); stopTone(); const n=tone.nodes;
      n.lOsc = ACTX.createOscillator(); n.rOsc = ACTX.createOscillator();
      n.lOsc.type = n.rOsc.type = tone.wave;
      n.lOsc.frequency.value = tone.base - tone.beat/2;
      n.rOsc.frequency.value = tone.base + tone.beat/2;
      n.lOsc.connect(n.lPan); n.rOsc.connect(n.rPan);
      n.lOsc.start(); n.rOsc.start();
      updateToneSummary();
    }
    function applyTone(){ if(!tone.nodes) return; tone.nodes.lGain.gain.setTargetAtTime(tone.level, ACTX.currentTime, 0.02); tone.nodes.rGain.gain.setTargetAtTime(tone.level, ACTX.currentTime, 0.02);
      if(tone.nodes.lOsc) tone.nodes.lOsc.frequency.setTargetAtTime(tone.base - tone.beat/2, ACTX.currentTime, 0.02);
      if(tone.nodes.rOsc) tone.nodes.rOsc.frequency.setTargetAtTime(tone.base + tone.beat/2, ACTX.currentTime, 0.02); updateToneSummary(); }
    function updateToneSummary(){ const L = tone.base - tone.beat/2, R = tone.base + tone.beat/2; tSum.textContent = 'L ' + L.toFixed(1) + ' Hz / R ' + R.toFixed(1) + ' Hz'; }
    tBtn.addEventListener('click', ()=>{ tone.enabled=!tone.enabled; tBtn.textContent = 'Tone: ' + (tone.enabled?'ON':'OFF'); tBtn.classList.toggle('on', tone.enabled); if(tone.enabled){ startTone(); applyTone(); } else { stopTone(); } });
    tWave.addEventListener('change', ()=>{ tone.wave = tWave.value; if(tone.enabled){ startTone(); applyTone(); } });
    tBase.addEventListener('input', ()=>{ tone.base = clamp(parseFloat(tBase.value)||200, 20, 2000); applyTone(); });
    tBeat.addEventListener('input', ()=>{ tone.beat = clamp(parseFloat(tBeat.value)||0, 0, 45); applyTone(); });
    tLevel.addEventListener('input', ()=>{ tone.level = parseFloat(tLevel.value)||0; applyTone(); });
    tPreset.addEventListener('change', ()=>{
      const v = tPreset.value;
      const map = { schumann:7.83, delta:2.0, theta:6.0, alpha:10.0, beta:20.0, gamma:40.0 };
      if(map[v]){ tBeat.value = map[v]; tone.beat = map[v]; applyTone(); }
    });
    updateToneSummary();

    // Noise (with spectral tilt)
    const nBtn = qs('.noise', el), nType = qs('.nType', el), nLevel = qs('.nLevel', el), nTilt = qs('.nTilt', el);
    const noise = { enabled:false, type:'white', level:0.2, src:null, gain:null, tilt:0, loShelf:null, hiShelf:null };
    function buildNoiseBuffer(type){
      const len = ACTX.sampleRate * 2;
      const buf = ACTX.createBuffer(1, len, ACTX.sampleRate);
      const data = buf.getChannelData(0);
      if(type==='white'){
        for(let i=0;i<len;i++) data[i] = Math.random()*2-1;
      }else if(type==='pink'){
        let b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0;
        for(let i=0;i<len;i++){
          const white = Math.random()*2-1;
          b0 = 0.99886*b0 + white*0.0555179;
          b1 = 0.99332*b1 + white*0.0750759;
          b2 = 0.96900*b2 + white*0.1538520;
          b3 = 0.86650*b3 + white*0.3104856;
          b4 = 0.55000*b4 + white*0.5329522;
          b5 = -0.7616*b5 - white*0.0168980;
          data[i] = b0+b1+b2+b3+b4+b5+b6+white*0.5362;
          data[i] *= 0.11;
          b6 = white*0.115926;
        }
      }else{ // brown
        let last=0;
        for(let i=0;i<len;i++){
          const white = Math.random()*2-1;
          last = (last + 0.02 * white) / 1.02;
          data[i] = last * 3.5;
        }
      }
      return buf;
    }
    function startNoise(){
      stopNoise();
      noise.gain = ACTX.createGain(); noise.gain.gain.value = noise.level;
      noise.src = ACTX.createBufferSource(); noise.src.buffer = buildNoiseBuffer(noise.type); noise.src.loop = true;
      // Tilt filters
      noise.loShelf = ACTX.createBiquadFilter(); noise.loShelf.type='lowshelf'; noise.loShelf.frequency.value=300;
      noise.hiShelf = ACTX.createBiquadFilter(); noise.hiShelf.type='highshelf'; noise.hiShelf.frequency.value=4000;
      noise.src.connect(noise.loShelf); noise.loShelf.connect(noise.hiShelf); noise.hiShelf.connect(noise.gain);
      noise.gain.connect(genSum); // into generator path so always audible
      noise.src.start();
    }
    function stopNoise(){ try{ if(noise.src){ try{ noise.src.stop(); }catch(e){} }; }catch(e){} noise.src=null; if(noise.gain){ noise.gain.disconnect(); noise.gain=null; } }
    function applyNoise(){
      if(noise.gain) noise.gain.gain.setTargetAtTime(noise.level, ACTX.currentTime, 0.02);
      const t = parseFloat(nTilt.value)||0;
      if(noise.loShelf && noise.hiShelf){
        noise.loShelf.gain.value = clamp(t<0 ? Math.abs(t)*12 : -t*6, -12, 12); // darken/brighten balance
        noise.hiShelf.gain.value = clamp(t>0 ? t*12 : -Math.abs(t)*6, -12, 12);
      }
    }
    nBtn.addEventListener('click', ()=>{ noise.enabled=!noise.enabled; nBtn.textContent='Noise: '+(noise.enabled?'ON':'OFF'); nBtn.classList.toggle('on', noise.enabled); if(noise.enabled){ startNoise(); applyNoise(); } else { stopNoise(); } });
    nType.addEventListener('change', ()=>{ noise.type = nType.value; if(noise.enabled){ startNoise(); applyNoise(); } });
    nLevel.addEventListener('input', ()=>{ noise.level = parseFloat(nLevel.value)||0; applyNoise(); });
    nTilt.addEventListener('input', applyNoise);

    // EQ binds
    const bEq = (cls,valCls,node)=>{
      const r=qs(cls,el), outLbl=qs(valCls,el);
      r.addEventListener('input', ()=>{ const dB=parseFloat(r.value)||0; node.gain.setTargetAtTime(dB, ACTX.currentTime, 0.02); outLbl.textContent = dB.toFixed(1)+' dB'; });
      r.dispatchEvent(new Event('input'));
    };
    bEq('.eqLow','.eqLowVal',eqLow);
    bEq('.eqMid','.eqMidVal',eqMid);
    bEq('.eqHigh','.eqHighVal',eqHigh);

    // FX binds (with tooltips already)
    const fxMix = qs('.fxMix',el), fxMixVal = qs('.fxMixVal',el);
    const fxDelay = qs('.fxDelay',el), fxDelayVal = qs('.fxDelayVal',el);
    const fxFb = qs('.fxFb',el), fxFbVal = qs('.fxFbVal',el);
    const fxDist = qs('.fxDist',el), fxDistVal = qs('.fxDistVal',el);
    fxMix.addEventListener('input', ()=>{ fxOut.gain.setTargetAtTime(parseFloat(fxMix.value)||0, ACTX.currentTime, 0.02); fxMixVal.textContent = Math.round(parseFloat(fxMix.value)*100)+'%'; });
    fxDelay.addEventListener('input', ()=>{ delay.delayTime.setTargetAtTime(parseFloat(fxDelay.value)||0, ACTX.currentTime, 0.02); fxDelayVal.textContent = (parseFloat(fxDelay.value)||0).toFixed(2)+'s'; });
    fxFb.addEventListener('input', ()=>{ fb.gain.setTargetAtTime(parseFloat(fxFb.value)||0, ACTX.currentTime, 0.02); fxFbVal.textContent = Math.round(parseFloat(fxFb.value)*100)+'%'; });
    fxDist.addEventListener('input', ()=>{ shaper.curve = makeDistCurve(parseFloat(fxDist.value)||0); fxDistVal.textContent = Math.round(parseFloat(fxDist.value)*100)+'%'; });
    function makeDistCurve(amount){ const k = amount*1000+1; const n=44100; const curve=new Float32Array(n); const deg=Math.PI/180; for(let i=0;i<n;i++){ const x=i*2/n-1; curve[i]=(3+k)*x*20*deg/(Math.PI+k*Math.abs(x)); } return curve; }
    fxMix.dispatchEvent(new Event('input')); fxDelay.dispatchEvent(new Event('input')); fxFb.dispatchEvent(new Event('input')); fxDist.dispatchEvent(new Event('input'));

    // Spaces (per stream)
    function makeImpulse(duration=1.2, decay=2.5){
      const rate = ACTX.sampleRate;
      const len = Math.max(1, Math.floor(rate * duration));
      const impulse = ACTX.createBuffer(2, len, rate);
      for(let ch=0; ch<2; ch++){
        const data = impulse.getChannelData(ch);
        for(let i=0; i<len; i++){
          data[i] = (Math.random()*2-1) * Math.pow(1 - i/len, decay);
        }
      }
      return impulse;
    }
    const spPreset = qs('.spPreset', el), spMix = qs('.spMix', el), spMixVal = qs('.spMixVal', el), spDecay = qs('.spDecay', el), spDecayVal = qs('.spDecayVal', el), spPreEl = qs('.spPre', el), spPreVal = qs('.spPreVal', el);
    function updSpacePreset(){
      let dur=1.2, dec=2.5;
      if(spPreset.value==='hall'){ dur=3.2; dec=3.5; }
      if(spPreset.value==='studio'){ dur=1.4; dec=2.0; }
      if(spPreset.value==='cabin'){ dur=0.9; dec=1.8; }
      convolver.buffer = makeImpulse(parseFloat(spDecay.value)||dur, dec);
    }
    spPreset.addEventListener('change', updSpacePreset);
    spDecay.addEventListener('input', ()=>{ spDecayVal.textContent = (parseFloat(spDecay.value)||1.2).toFixed(2)+' s'; updSpacePreset(); });
    spMix.addEventListener('input', ()=>{ spWet.gain.setTargetAtTime(parseFloat(spMix.value)||0, ACTX.currentTime, 0.02); spMixVal.textContent = Math.round(parseFloat(spMix.value)*100)+'%'; });
    spPreEl.addEventListener('input', ()=>{ spPre.delayTime.setTargetAtTime(parseFloat(spPreEl.value)||0, ACTX.currentTime, 0.02); spPreVal.textContent = (parseFloat(spPreEl.value)||0).toFixed(2)+' s'; });
    updSpacePreset(); spMix.dispatchEvent(new Event('input')); spPreEl.dispatchEvent(new Event('input'));

    // LFO loop
    const lfoOn = qs('.lfoOn', el), lfoTarget = qs('.lfoTarget', el), lfoRate = qs('.lfoRate', el), lfoDepth = qs('.lfoDepth', el);
    lfoOn.addEventListener('click', ()=>{ lfo.enabled=!lfo.enabled; lfoOn.textContent='LFO: '+(lfo.enabled?'ON':'OFF'); lfoOn.classList.toggle('on', lfo.enabled); lfo.t0=performance.now(); });
    lfoTarget.addEventListener('change', ()=>{ lfo.target = lfoTarget.value; });
    lfoRate.addEventListener('input', ()=>{ lfo.rate = parseFloat(lfoRate.value)||0.5; qs('.lfoRateVal', el).textContent = lfo.rate.toFixed(2)+' Hz'; });
    lfoDepth.addEventListener('input', ()=>{ lfo.depth = parseFloat(lfoDepth.value)||0.4; qs('.lfoDepthVal', el).textContent = Math.round(lfo.depth*100)+'%'; });
    lfoRate.dispatchEvent(new Event('input')); lfoDepth.dispatchEvent(new Event('input'));

    function lfoTick(ts){
      if(lfo.enabled){
        const t = (ts - lfo.t0)/1000;
        const phase = Math.sin(2*Math.PI*lfo.rate * t);
        const d = lfo.depth;
        if(lfo.target==='pan'){
          const base = parseFloat(panEl.value)||0;
          pan.pan.setValueAtTime(clamp(base + phase*d, -1, 1), ACTX.currentTime);
        }else if(lfo.target==='vol'){
          const base = parseFloat(vol.value)||0.5;
          out.gain.setValueAtTime(clamp(base * (1 - d/2 + (phase+1)/2*d), 0, 1), ACTX.currentTime);
        }else if(lfo.target==='lpf'){
          const x = clamp((phase+1)/2, 0, 1);
          const f = valueToFreq(x);
          if(mOn){ lpf.frequency.setValueAtTime(f, ACTX.currentTime); } // respect muffle on/off
        }
      }
    }
    LFO_TICKS.push(lfoTick); ensureLfoLoop();
// Envelope binds
    const envA = qs('.envA', el), envD = qs('.envD', el), envS = qs('.envS', el), envR = qs('.envR', el);
    envA.addEventListener('input', ()=>{ env.a = parseFloat(envA.value)||0.01; qs('.envAVal', el).textContent = Math.round(env.a*1000)+' ms'; });
    envD.addEventListener('input', ()=>{ env.d = parseFloat(envD.value)||0.2; qs('.envDVal', el).textContent = env.d.toFixed(2)+' s'; });
    envS.addEventListener('input', ()=>{ env.s = parseFloat(envS.value)||0.7; qs('.envSVal', el).textContent = Math.round(env.s*100)+'%'; });
    envR.addEventListener('input', ()=>{ env.r = parseFloat(envR.value)||0.4; qs('.envRVal', el).textContent = env.r.toFixed(2)+' s'; });
    envA.dispatchEvent(new Event('input')); envD.dispatchEvent(new Event('input')); envS.dispatchEvent(new Event('input')); envR.dispatchEvent(new Event('input'));

    // Spectrogram registration
    const spectro = el.querySelector('.spectro');
    const sctx = spectro.getContext('2d', { willReadFrequently: true });
    const specBuf = new Uint8Array(specAnalyser.frequencyBinCount);
    function resizeSpectro(){ const bb = spectro.getBoundingClientRect(); spectro.width = Math.max(320, Math.floor(bb.width)); spectro.height = 90; }
    resizeSpectro(); window.addEventListener('resize', resizeSpectro);
    streamSpectros.push({ analyser:specAnalyser, canvas:spectro, ctx:sctx, buf:specBuf, x:0 });

    // enable drag-reorder if currently in edit mode
    try{ makeStreamDraggable(el, editMode); makeModsDraggable(el.querySelector('.mods'), editMode); }catch(e){}
    return { el };
  }

  // ===== Render loops =====
  function drawBlockScopes(){
    requestAnimationFrame(drawBlockScopes);
    for(const b of blocks){
      const analyser = b.analyser, ctx = b.ctx, cvs = b.cvs;
      const N = analyser.fftSize;
      const buf = new Uint8Array(N);
      analyser.getByteTimeDomainData(buf);
      ctx.clearRect(0,0,cvs.width,cvs.height);
      ctx.strokeStyle = '#59ff85';
      ctx.beginPath();
      for(let i=0;i<buf.length;i++){
        const x = i * (cvs.width / buf.length);
        const scopeGAIN = 2.0; const y = cvs.height/2 + ((buf[i]-128)/128) * (cvs.height/2) * scopeGAIN;
        i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
  }
  function drawStreamSpectros(){
    requestAnimationFrame(drawStreamSpectros);
    for(const s of streamSpectros){
      const { analyser, ctx, canvas, buf } = s;
      analyser.getByteFrequencyData(buf);
      // scroll left by 1 px
      const w = canvas.width, h = canvas.height;
      const img = ctx.getImageData(1, 0, w-1, h);
      ctx.putImageData(img, 0, 0);
      // draw new column at right
      for(let i=0;i<buf.length;i++){
        const mag = buf[i]/255; // 0..1
        const y = Math.floor(h - (i/buf.length)*h);
        ctx.fillStyle = spectroColor(mag);
        ctx.fillRect(w-1, y, 1, Math.ceil(h/buf.length)+1);
      }
    }
  }
  function spectroColor(t){ t = clamp01(t); const r = clamp01(4*t - 1.5)*t; const g = clamp01(4*t - 0.5)*t; const b = clamp01(2 - 4*t)*t; return `rgb(${Math.floor(r*255)},${Math.floor(g*255)},${Math.floor(b*255)})`; }
  drawBlockScopes();
  drawStreamSpectros();

  // ===== Toolbar wiring =====
  qs('#startAudio').addEventListener('click', ()=>{
    bootAudio();
    ACTX.resume();
  });

  qs('#addBlock').addEventListener('click', ()=> addBlock() );

  // Edit mode: drag blocks
  let editMode = false;
  
  qs('#editToggle').addEventListener('click', (e)=>{
    editMode = !editMode;
    e.target.textContent = editMode ? 'Edit Mode: ON' : 'Edit Mode: OFF';
    e.target.setAttribute('aria-pressed', String(editMode));
    document.body.classList.toggle('edit-on', editMode);
    const toast = qs('#modeToast');
    toast.textContent = editMode ? 'Edit Mode ON — drag blocks with the Move handle.' : 'Edit Mode OFF';
    toast.style.display = 'block';
    setTimeout(()=> toast.style.display='none', 1500);
  });

  
  
  // ---- Error Reporter (for Opera diagnostics) ----
  (function(){
    const box = document.createElement('div');
    box.id = 'errBox';
    box.style.cssText = 'position:fixed;right:8px;bottom:8px;max-width:60ch;background:#300b;border:1px solid #a44;color:#faa;padding:8px 10px;border-radius:6px;font:12px/1.3 system-ui, sans-serif;z-index:9999;display:none';
    document.body.appendChild(box);
    let shown=false;
    window.addEventListener('error', function(e){
      if(shown) return;
      shown=true;
      box.textContent = 'JS error: ' + (e && e.message ? e.message : 'unknown');
      box.style.display = 'block';
      setTimeout(()=> box.style.display='none', 8000);
    });
    window.addEventListener('unhandledrejection', function(e){
      if(shown) return;
      shown=true;
      try{
        box.textContent = 'Promise rejection: ' + (e && (e.reason && (e.reason.message||e.reason)) || 'unknown');
      }catch(_) { box.textContent = 'Promise rejection (unknown)'; }
      box.style.display = 'block';
      setTimeout(()=> box.style.display='none', 8000);
    });
  })();

  // ===== Session Save / Load =====
  function gatherSession(){
    const data = { blocks:[] };
    qsa('.block', main).forEach(blk=>{
      const b = {
        pos: { left: blk.style.left, top: blk.style.top, width: blk.style.width, position: blk.style.position },
        vol: parseFloat(qs('.blockVol', blk).value)||1,
        streams: []
      };
      qsa('.stream', blk).forEach(st=>{
        const s = {
          ab: parseFloat(qs('.ab', st).value)||0.5,
          vol: parseFloat(qs('.vol', st).value)||0.5,
          pan: parseFloat(qs('.pan', st).value)||0,
          muffleOn: qs('.muffle', st).classList.contains('on'),
          mAmt: parseFloat(qs('.mAmt', st).value)||1,
          tone:{ on: qs('.tone',st).classList.contains('on'), wave: qs('.tWave',st).value, base: parseFloat(qs('.tBase',st).value)||200, beat: parseFloat(qs('.tBeat',st).value)||10, level: parseFloat(qs('.tLevel',st).value)||0.2, preset: qs('.tPreset',st).value },
          noise:{ on: qs('.noise',st).classList.contains('on'), type: qs('.nType',st).value, level: parseFloat(qs('.nLevel',st).value)||0.2, tilt: parseFloat(qs('.nTilt',st).value)||0 },
          eq:{ low: parseFloat(qs('.eqLow',st).value)||0, mid: parseFloat(qs('.eqMid',st).value)||0, high: parseFloat(qs('.eqHigh',st).value)||0 },
          fx:{ mix: parseFloat(qs('.fxMix',st).value)||0, delay: parseFloat(qs('.fxDelay',st).value)||0.25, fb: parseFloat(qs('.fxFb',st).value)||0.3, dist: parseFloat(qs('.fxDist',st).value)||0 },
          lfo:{ on: qs('.lfoOn',st).classList.contains('on'), target: qs('.lfoTarget',st).value, rate: parseFloat(qs('.lfoRate',st).value)||0.5, depth: parseFloat(qs('.lfoDepth',st).value)||0.4 },
          env:{ a: parseFloat(qs('.envA',st).value)||0.01, d: parseFloat(qs('.envD',st).value)||0.2, s: parseFloat(qs('.envS',st).value)||0.7, r: parseFloat(qs('.envR',st).value)||0.4 },
          space:{ preset: qs('.spPreset',st).value, mix: parseFloat(qs('.spMix',st).value)||0, decay: parseFloat(qs('.spDecay',st).value)||1.2, pre: parseFloat(qs('.spPre',st).value)||0 }
        };
        s.files = { A: qs('.aName', st).textContent || '', B: qs('.bName', st).textContent || '' };
        b.streams.push(s);
      });
      data.blocks.push(b);
    });
    return data;
  }
  function applySession(data){
    qsa('.block', main).forEach(b=>b.remove());
    if(!ACTX){ bootAudio(); ACTX.resume(); }
    (data.blocks||[]).forEach(b=>{
      const blk = addBlock();
      const dom = blocks[blocks.length-1].el;
      if(b.pos){ dom.style.position=b.pos.position||''; dom.style.left=b.pos.left||''; dom.style.top=b.pos.top||''; dom.style.width=b.pos.width||''; }
      const volEl = qs('.blockVol', dom); if(volEl){ volEl.value = b.vol; volEl.dispatchEvent(new Event('input')); }
      const streamsWrap = qs('.streams', dom);
      (b.streams||[]).forEach(s=>{
        const st = createStream(streamsWrap.children.length+1, blocks[blocks.length-1].bus);
        streamsWrap.appendChild(st.el);
        qs('.ab', st.el).value = s.ab; qs('.ab', st.el).dispatchEvent(new Event('input'));
        qs('.vol', st.el).value = s.vol; qs('.vol', st.el).dispatchEvent(new Event('input'));
        qs('.pan', st.el).value = s.pan; qs('.pan', st.el).dispatchEvent(new Event('input'));
        if(s.muffleOn) qs('.muffle', st.el).click();
        qs('.mAmt', st.el).value = s.mAmt; qs('.mAmt', st.el).dispatchEvent(new Event('input'));
        if((s.tone && s.tone.on)) qs('.tone', st.el).click();
        qs('.tWave', st.el).value = (s.tone && s.tone.wave) || 'sine';
        qs('.tPreset', st.el).value = (s.tone && s.tone.preset) || 'custom';
        qs('.tBase', st.el).value = (s.tone && s.tone.base) || 200; qs('.tBase', st.el).dispatchEvent(new Event('input'));
        qs('.tBeat', st.el).value = (s.tone && s.tone.beat) || 10; qs('.tBeat', st.el).dispatchEvent(new Event('input'));
        qs('.tLevel', st.el).value = (s.tone && s.tone.level) || 0.2; qs('.tLevel', st.el).dispatchEvent(new Event('input'));
        if((s.noise && s.noise.on)) qs('.noise', st.el).click();
        qs('.nType', st.el).value = (s.noise && s.noise.type) || 'white';
        qs('.nLevel', st.el).value = (s.noise && s.noise.level) || 0.2; qs('.nLevel', st.el).dispatchEvent(new Event('input'));
        qs('.nTilt', st.el).value = (s.noise && s.noise.tilt) || 0; qs('.nTilt', st.el).dispatchEvent(new Event('input'));
        qs('.eqLow', st.el).value = (s.eq && s.eq.low) || 0; qs('.eqLow', st.el).dispatchEvent(new Event('input'));
        qs('.eqMid', st.el).value = (s.eq && s.eq.mid) || 0; qs('.eqMid', st.el).dispatchEvent(new Event('input'));
        qs('.eqHigh', st.el).value = (s.eq && s.eq.high) || 0; qs('.eqHigh', st.el).dispatchEvent(new Event('input'));
        qs('.fxMix', st.el).value = (s.fx && s.fx.mix) || 0; qs('.fxMix', st.el).dispatchEvent(new Event('input'));
        qs('.fxDelay', st.el).value = (s.fx && s.fx.delay) || 0.25; qs('.fxDelay', st.el).dispatchEvent(new Event('input'));
        qs('.fxFb', st.el).value = (s.fx && s.fx.fb) || 0.3; qs('.fxFb', st.el).dispatchEvent(new Event('input'));
        qs('.fxDist', st.el).value = (s.fx && s.fx.dist) || 0; qs('.fxDist', st.el).dispatchEvent(new Event('input'));
        if((s.lfo && s.lfo.on)) qs('.lfoOn', st.el).click();
        qs('.lfoTarget', st.el).value = (s.lfo && s.lfo.target) || 'pan';
        qs('.lfoRate', st.el).value = (s.lfo && s.lfo.rate) || 0.5; qs('.lfoRate', st.el).dispatchEvent(new Event('input'));
        qs('.lfoDepth', st.el).value = (s.lfo && s.lfo.depth) || 0.4; qs('.lfoDepth', st.el).dispatchEvent(new Event('input'));
        qs('.envA', st.el).value = (s.env && s.env.a) || 0.01; qs('.envA', st.el).dispatchEvent(new Event('input'));
        qs('.envD', st.el).value = (s.env && s.env.d) || 0.2; qs('.envD', st.el).dispatchEvent(new Event('input'));
        qs('.envS', st.el).value = (s.env && s.env.s) || 0.7; qs('.envS', st.el).dispatchEvent(new Event('input'));
        qs('.envR', st.el).value = (s.env && s.env.r) || 0.4; qs('.envR', st.el).dispatchEvent(new Event('input'));
        qs('.spPreset', st.el).value = (s.space && s.space.preset) || 'none'; qs('.spPreset', st.el).dispatchEvent(new Event('change'));
        qs('.spMix', st.el).value = (s.space && s.space.mix) || 0; qs('.spMix', st.el).dispatchEvent(new Event('input'));
        qs('.spDecay', st.el).value = (s.space && s.space.decay) || 1.2; qs('.spDecay', st.el).dispatchEvent(new Event('input'));
        qs('.spPre', st.el).value = (s.space && s.space.pre) || 0; qs('.spPre', st.el).dispatchEvent(new Event('input'));
      });
    });
    enableEditReorder(editMode);
  }

  qs('#saveSession').addEventListener('click', ()=>{
    const blob = new Blob([JSON.stringify(gatherSession(), null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'noisetown_session.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  qs('#loadSession').addEventListener('click', ()=> qs('#loadFile').click());
  qs('#loadFile').addEventListener('change', async (e)=>{
    const file = e.target.files[0]; if(!file) return;
    const txt = await file.text();
    try{ const data = JSON.parse(txt); applySession(data); }catch(err){ alert('Invalid session file'); }
  });

  // ===== Preset with embedded audio (JSON) =====
  function audioBufferToWav(buffer){
    const numCh = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const numFrames = buffer.length;
    const bytesPerSample = 2;
    const blockAlign = numCh * bytesPerSample;
    const dataSize = numFrames * blockAlign;
    const bufferSize = 44 + dataSize;
    const ab = new ArrayBuffer(bufferSize);
    const view = new DataView(ab);
    function writeString(off, str){ for(let i=0;i<str.length;i++) view.setUint8(off+i, str.charCodeAt(i)); }
    let off = 0;
    writeString(off, 'RIFF'); off+=4;
    view.setUint32(off, 36 + dataSize, true); off+=4;
    writeString(off, 'WAVE'); off+=4;
    writeString(off, 'fmt '); off+=4;
    view.setUint32(off, 16, true); off+=4;
    view.setUint16(off, 1, true); off+=2;
    view.setUint16(off, numCh, true); off+=2;
    view.setUint32(off, sampleRate, true); off+=4;
    view.setUint32(off, sampleRate * blockAlign, true); off+=4;
    view.setUint16(off, blockAlign, true); off+=2;
    view.setUint16(off, 16, true); off+=2;
    writeString(off, 'data'); off+=4;
    view.setUint32(off, dataSize, true); off+=4;
    const interleaved = new Float32Array(numFrames * numCh);
    for(let ch=0; ch<numCh; ch++){
      const data = buffer.getChannelData(ch);
      for(let i=0;i<numFrames;i++){ interleaved[i*numCh+ch] = data[i]; }
    }
    let idx = 0;
    for(let i=0;i<numFrames;i++){
      for(let ch=0; ch<numCh; ch++){
        let s = Math.max(-1, Math.min(1, interleaved[idx++]));
        view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        off += 2;
      }
    }
    return new Blob([ab], {type:'audio/wav'});
  }
  function blobToBase64(blob){
    return new Promise(res=>{ const fr=new FileReader(); fr.onload=()=>res(fr.result.split(',')[1]); fr.readAsDataURL(blob); });
  }
  function base64ToArrayBuffer(b64){
    const bin = atob(b64); const len = bin.length; const buf = new ArrayBuffer(len); const view = new Uint8Array(buf);
    for(let i=0;i<len;i++) view[i] = bin.charCodeAt(i);
    return buf;
  }

  async function gatherPresetWithAudio(){
    const session = gatherSession();
    let blockIdx = 0;
    const blockEls = qsa('.block', main);
    for (const blk of blockEls){
      const streams = qsa('.stream', blk);
      let sidx = 0;
      for (const st of streams){
        const scope = session.blocks[blockIdx].streams[sidx];
        scope.audio = scope.audio || {};
        const streamState = st._streamState;
        if(streamState){
          if(streamState.A && streamState.A.buf){
            const blob = audioBufferToWav(streamState.A.buf);
            scope.audio.A = { mime:'audio/wav', base64: await blobToBase64(blob) };
          }
          if(streamState.B && streamState.B.buf){
            const blob = audioBufferToWav(streamState.B.buf);
            scope.audio.B = { mime:'audio/wav', base64: await blobToBase64(blob) };
          }
        }
        sidx++;
      }
      blockIdx++;
    }
    return session;
  }

  qs('#savePreset').addEventListener('click', async ()=>{
    try{
      const preset = await gatherPresetWithAudio();
      const blob = new Blob([JSON.stringify(preset, null, 2)], {type:'application/json'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'noisetown_preset.json';
      document.body.appendChild(a);
      a.click();
      setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 0);
    }catch(err){ alert('Failed to save preset'); }
  });

  qs('#loadPreset').addEventListener('click', ()=> qs('#loadPresetFile').click());
  qs('#loadPresetFile').addEventListener('change', async (e)=>{
    const file = e.target.files[0]; if(!file) return;
    try{
      const txt = await file.text(); const data = JSON.parse(txt);
      applySession(data);
      let bidx = 0;
      for(const blk of data.blocks||[]){
        const domBlock = blocks[bidx];
        const streamsWrap = qs('.streams', domBlock.el);
        let sidx = 0;
        for(const s of blk.streams||[]){
          const stEl = streamsWrap.children[sidx];
          if(s.audio){
            if((s.audio && s.audio.A && s.audio.A.base64)){
              const buf = await ACTX.decodeAudioData(base64ToArrayBuffer(s.audio.A.base64));
              stEl._streamState.A = stEl._streamState.A || {};
              stEl._streamState.A.buf = buf; stEl._streamState.A.dur = buf.duration; qs('.aName', stEl).textContent = (s.files && s.files.A) || 'embedded A';
            }
            if((s.audio && s.audio.B && s.audio.B.base64)){
              const buf = await ACTX.decodeAudioData(base64ToArrayBuffer(s.audio.B.base64));
              stEl._streamState.B = stEl._streamState.B || {};
              stEl._streamState.B.buf = buf; stEl._streamState.B.dur = buf.duration; qs('.bName', stEl).textContent = (s.files && s.files.B) || 'embedded B';
            }
          }
          sidx++;
        }
        bidx++;
      }
    }catch(err){ console.error(err); alert('Invalid preset file'); }
  });

  // ===== Style Mode (hover + apply styles + save theme) =====
  let styleMode = false;
  let styleTarget = null;
  const stylePanel = qs('#stylePanel');
  
  
qs('#styleMode').addEventListener('click', (e)=>{
  styleMode = !styleMode;
  e.target.textContent = 'Style Mode: ' + (styleMode?'ON':'OFF');
  e.target.setAttribute('aria-pressed', String(styleMode));
  stylePanel.style.display = styleMode ? 'block' : 'none';
  document.body.classList.toggle('style-on', styleMode);

  // Toggle contenteditable on visible text elements
  const textSel = 'h1,h2,h3,h4,.mod-hdr .name,label,button,.small,span,.block h2';
  if(styleMode){
    qsa(textSel).forEach(el=>{
      if(el.closest('#toolbar') || el.closest('#stylePanel')) return;
      el.setAttribute('contenteditable','true');
      el.setAttribute('data-text-edit','1');
      el.spellcheck = false;
    });
  }else{
    qsa('[contenteditable="true"]').forEach(el=> el.removeAttribute('contenteditable'));
  }

  // toast
  const toast = qs('#modeToast');
  toast.textContent = styleMode ? 'Style Mode ON — hover to pick, click to select, then use the panel.' : 'Style Mode OFF';
  toast.style.display = 'block';
  setTimeout(()=> toast.style.display='none', 1800);
  if(!styleMode){ qsa('.style-hover').forEach(x=>x.classList.remove('style-hover')); styleTarget=null; }
});


  
  
  let hoverEl = null;
  document.addEventListener('mouseover', (ev)=>{
    if(!styleMode) return;
    if(ev.target.closest('#stylePanel') || ev.target.closest('#toolbar')) return;
    if(hoverEl) hoverEl.classList.remove('style-hover');
    hoverEl = ev.target;
    hoverEl.classList.add('style-hover');
  }, true);


  
  
  
document.addEventListener('click', (ev)=>{
  if(!styleMode) return;
  if(ev.target.closest('#stylePanel') || ev.target.closest('#toolbar')) return;
  if(ev.target.closest('[contenteditable="true"]')) return; // allow text editing
  // Lock selection to the last hovered element
  if(hoverEl){ styleTarget = hoverEl; }
  ev.preventDefault();
  ev.stopPropagation();
}, true);

  // ESC clears selection
  document.addEventListener('keydown', (ev)=>{
    if(!styleMode) return;
    if(ev.key === 'Escape'){ styleTarget=null; }
  });


  qs('#styApply').addEventListener('click', ()=>{
    if(!styleTarget) return alert('Hover and click an element first to select it.');
    const preset = qs('#stylePreset').value;
    const radius = parseInt(qs('#styRadius').value, 10);
    const shadow = parseInt(qs('#styShadow').value, 10);
    const scope = qs('#styScope').value;

    const css = {};
    if(preset==='bevel'){ css.borderRadius = radius+'px'; css.boxShadow = `inset 1px 1px 0 #fff1, inset -1px -1px 0 #0008`; }
    else if(preset==='shadow'){ css.borderRadius = radius+'px'; css.boxShadow = `${shadow}px ${shadow}px ${Math.max(10,shadow)}px #0008`; }
    else if(preset==='soft'){ css.borderRadius = radius+'px'; css.boxShadow = `0 2px 10px #000a`; }
    else if(preset==='glow'){ css.borderRadius = radius+'px'; css.boxShadow = `0 0 ${Math.max(8,shadow)}px #59a7ff88`; }
    else if(preset==='flat'){ css.borderRadius = radius+'px'; css.boxShadow = 'none'; }
    else { css.borderRadius = radius+'px'; css.boxShadow = `${shadow}px ${shadow}px ${Math.max(10,shadow)}px #0006`; }

    const applyTo = (el)=>{ for(const k in css){ el.style[k] = css[k]; } };
    if(scope==='element'){ applyTo(styleTarget); }
    else if(scope==='stream'){ let p=styleTarget; while(p && !(p.classList && p.classList.contains('stream'))) p=p.parentElement; if(p) applyTo(p); }
    else if(scope==='block'){ let p=styleTarget; while(p && !(p.classList && p.classList.contains('block'))) p=p.parentElement; if(p) applyTo(p); }
    else if(scope==='global'){ qsa('body *').forEach(el=>applyTo(el)); }
  });

  
qs('#stySaveTheme').addEventListener('click', ()=>{
  // Collect inline styles as theme JSON
  const themed = [];
  qsa('body *').forEach(el=>{
    const s = el.getAttribute('style');
    if(s) themed.push({ selector: getDomPath(el), style: s });
  });
  // Collect CSS vars and user CSS
  const varNames = ['--bg','--panel','--card','--text','--muted','--accent','--select','--select-border'];
  const varsOut = {}; varNames.forEach(n=> varsOut[n] = getComputedStyle(document.documentElement).getPropertyValue(n).trim());
  const userCSS = (document.getElementById('userThemeCSS')?.textContent || '');

  // Collect edited texts
  const texts = [];
  qsa('[data-text-edit="1"]').forEach(el=>{
    texts.push({ selector: getDomPath(el), html: el.innerHTML });
  });

  const blob = new Blob([JSON.stringify({ vars: varsOut, userCSS, theme: themed, texts }, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'noisetown_theme.json';
  document.body.appendChild(a);
  a.click();
  setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 0);
});
  // ===== Theme Editor (CSS variables, custom CSS, save/load) =====
  const root = document.documentElement;
  const userCssTag = document.getElementById('userThemeCSS') || (()=>{ const t=document.createElement('style'); t.id='userThemeCSS'; document.head.appendChild(t); return t; })();

  // Baselines to support Reset
  let THEME_BASELINE = null;
  let INLINE_BASELINE = null;

  function getDomPath(el){
    if(!el || el===document.body) return 'body';
    const ix = Array.from(el.parentNode.children).indexOf(el)+1;
    return getDomPath(el.parentNode) + ' > ' + el.tagName.toLowerCase() + `:nth-child(${ix})`;
  }
  function snapshotInline(){
    const arr = [];
    qsa('body *').forEach(el=>{
      const s = el.getAttribute('style');
      if(s) arr.push({ selector: getDomPath(el), style: s });
    });
    return arr;
  }
  function captureBaseline(){
    const varNames = ['--bg','--panel','--card','--text','--muted','--accent','--select','--select-border'];
    const varsOut = {};
    varNames.forEach(n=> varsOut[n] = getComputedStyle(root).getPropertyValue(n).trim());
    THEME_BASELINE = { vars: varsOut, userCSS: userCssTag.textContent || '' };
    INLINE_BASELINE = snapshotInline();
  }
  captureBaseline();

  function addThemeControls(){
    const vars = ['--bg','--panel','--card','--text','--muted','--accent','--select','--select-border'];
    const sectionHdr = ce('div'); sectionHdr.className='subhdr'; sectionHdr.textContent='Theme Colors (CSS Variables)';
    stylePanel.insertBefore(sectionHdr, qs('#styApply').parentElement);

    const grid = ce('div'); grid.className='grid';
    vars.forEach(v=>{
      const lab = ce('label'); lab.textContent = v;
      const inp = ce('input'); inp.type='color';
      const cur = getComputedStyle(root).getPropertyValue(v).trim() || '#000000';
      inp.value = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(cur) ? cur : '#000000';
      inp.dataset.var = v;
      inp.addEventListener('input', e=> root.style.setProperty(v, e.target.value));
      grid.appendChild(lab); grid.appendChild(inp);
    });
    stylePanel.insertBefore(grid, qs('#styApply').parentElement);

    const cssHdr = ce('div'); cssHdr.className='subhdr'; cssHdr.textContent='Custom CSS (live)';
    const cssRow = ce('div'); cssRow.className='row wrap';
    const cssTa = ce('textarea'); cssTa.id='userCssText'; cssTa.placeholder='/* Example */\n.stream{ background: #2a2a2a; }';
    cssRow.appendChild(cssTa);
    const cssBtns = ce('div'); cssBtns.className='row';
    const applyCssBtn = ce('button'); applyCssBtn.className='btn'; applyCssBtn.textContent='Apply CSS';
    applyCssBtn.addEventListener('click', ()=>{ userCssTag.textContent = cssTa.value || ''; });
    const loadThemeBtn = ce('button'); loadThemeBtn.className='btn'; loadThemeBtn.textContent='Load Theme JSON';
    loadThemeBtn.style.marginLeft = 'auto';
    const themeFile = ce('input'); themeFile.type='file'; themeFile.accept='application/json'; themeFile.style.display='none';
    loadThemeBtn.addEventListener('click', ()=> themeFile.click());
    
themeFile.addEventListener('change', async (e)=>{
  const f = e.target.files[0]; if(!f) return;
  try{
    const txt = await f.text(); const data = JSON.parse(txt);
    if(data.vars){ Object.entries(data.vars).forEach(([k,v])=> document.documentElement.style.setProperty(k, v)); }
    if(typeof data.userCSS === 'string'){ userCssTag.textContent = data.userCSS; cssTa.value = data.userCSS; }
    // clear inline then apply
    qsa('body *').forEach(el=> el.removeAttribute('style'));
    if(Array.isArray(data.theme)){
      data.theme.forEach(t=>{ try{ const el = document.querySelector(t.selector); if(el && t.style) el.setAttribute('style', t.style); }catch(e){} });
    }
    if(Array.isArray(data.texts)){
      data.texts.forEach(t=>{ try{ const el = document.querySelector(t.selector); if(el && typeof t.html==='string') el.innerHTML = t.html; }catch(e){} });
  }
  }catch(err){ alert('Invalid theme JSON'); }
});
    cssBtns.appendChild(applyCssBtn); cssBtns.appendChild(loadThemeBtn); cssRow.appendChild(cssBtns);
    cssRow.appendChild(themeFile);
    stylePanel.insertBefore(cssHdr, qs('#styApply').parentElement);
    stylePanel.insertBefore(cssRow, qs('#styApply').parentElement);
  }
  addThemeControls();

  // Reset to last baseline
  qs('#styResetTheme').addEventListener('click', ()=>{
    if(!THEME_BASELINE){ alert('No baseline to reset to.'); return; }
    Object.entries(THEME_BASELINE.vars).forEach(([k,v])=> root.style.setProperty(k, v));
    userCssTag.textContent = THEME_BASELINE.userCSS || '';
    const ta = qs('#userCssText'); if(ta) ta.value = THEME_BASELINE.userCSS || '';
    qsa('body *').forEach(el=> el.removeAttribute('style'));
    (INLINE_BASELINE||[]).forEach(t=>{ try{ const el = document.querySelector(t.selector); if(el) el.setAttribute('style', t.style); }catch(e){} });
  });

  // Extend Save Theme JSON -> include CSS variables + custom CSS + inline paint
  const origSave = qs('#stySaveTheme');
  origSave.addEventListener('click', (ev)=>{
    ev.preventDefault();
    const themed = [];
    qsa('body *').forEach(el=>{
      const s = el.getAttribute('style');
      if(s) themed.push({ selector: getDomPath(el), style: s });
    });
    const varNames = ['--bg','--panel','--card','--text','--muted','--accent','--select','--select-border'];
    const varsOut = {};
    varNames.forEach(n=> varsOut[n] = getComputedStyle(root).getPropertyValue(n).trim());
    const payload = {
      vars: varsOut,
      userCSS: (qs('#userCssText') ? qs('#userCssText').value : '')||userCssTag.textContent||'',
      theme: themed
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'noisetown_theme.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  const selInfo = ce('div'); selInfo.className='small'; selInfo.id='stySelInfo'; stylePanel.appendChild(selInfo);
  const updateSelInfo = ()=>{ selInfo.textContent = styleTarget ? ('Target: ' + getDomPath(styleTarget)) : 'Target: (none)'; };
  setInterval(updateSelInfo, 250);

  // ===== Edit-mode reordering for Streams and Mods =====
  function renumberStreams(blockEl){
    const headers = blockEl.querySelectorAll('.stream-header h3');
    headers.forEach((hdr, i)=>{ hdr.textContent = `Stream ${i+1}`; });
  }

  function attachModuleClose(modEl){
    if(!modEl) return;
    const hdr = modEl.querySelector('.mod-hdr');
    if(!hdr) return;
    let closeBtn = modEl.querySelector('.mod-close');
    if(!closeBtn){
      closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'mod-close';
      closeBtn.textContent = 'Remove';
      closeBtn.title = 'Remove module';
      hdr.appendChild(closeBtn);
    }
    if(closeBtn._modRemoveBound) return;
    closeBtn.addEventListener('click', (ev)=>{
      ev.stopPropagation();
      const parent = modEl.parentElement;
      modEl.remove();
      if(parent){
        enableEditReorder(editMode);
      }
    });
    closeBtn._modRemoveBound = true;
  }

  function captureModuleTemplates(streamEl){
    streamEl.querySelectorAll('.mod').forEach(mod=>{
      const key = mod.dataset.mod;
      if(key && !MODULE_TEMPLATES.has(key)){
        MODULE_TEMPLATES.set(key, mod.outerHTML);
      }
    });
  }

  function moduleLabel(key){
    return MODULE_LABELS[key] || key.replace(/^[a-z]/, m=>m.toUpperCase());
  }

  function enableEditReorder(enabled){
    qsa('.stream').forEach(stream=>{
      makeStreamDraggable(stream);
      stream.draggable = !!enabled;
      const header = stream.querySelector('.stream-header');
      if(header){
        header.classList.toggle('reorder-on', !!enabled);
        header.style.cursor = enabled ? 'move' : '';
      }
    });
    qsa('.mods').forEach(mods=>{
      makeModsDraggable(mods);
      mods.querySelectorAll('.mod').forEach(mod=>{
        mod.draggable = !!enabled;
        const hdr = mod.querySelector('.mod-hdr');
        if(hdr) hdr.style.cursor = enabled ? 'move' : '';
      });
    });
  }

  function makeStreamDraggable(streamEl){
    if(streamEl._dndSetup) return;
    const header = streamEl.querySelector('.stream-header');
    if(header){
      header.style.cursor = editMode ? 'move' : '';
    }
    streamEl.addEventListener('dragstart', (e)=>{
      if(!editMode){ e.preventDefault(); return; }
      streamEl.classList.add('draggingItem');
      e.dataTransfer.effectAllowed='move';
      e.dataTransfer.setData('text/plain', 'stream');
      const ph = document.createElement('div');
      ph.className='placeholder';
      ph.style.height = streamEl.getBoundingClientRect().height+'px';
      const parent = streamEl.parentElement;
      if(parent){ parent.insertBefore(ph, streamEl.nextSibling); }
    });
    streamEl.addEventListener('dragend', ()=>{
      streamEl.classList.remove('draggingItem');
      const parent = streamEl.parentElement;
      if(parent){ parent.querySelectorAll('.placeholder').forEach(x=>x.remove()); }
      const blockEl = streamEl.closest('.block');
      if(blockEl){ renumberStreams(blockEl); }
    });
    const container = streamEl.parentElement;
    if(container && !container._dndBound){
      container._dndBound = true;
      container.addEventListener('dragover', (e)=>{
        if(!editMode) return;
        e.preventDefault();
        const dragging = container.querySelector('.draggingItem');
        if(!dragging) return;
        const after = getDragAfterElement(container, e.clientY);
        const ph = container.querySelector('.placeholder');
        if(ph){
          if(after==null) container.appendChild(ph);
          else container.insertBefore(ph, after);
        }
      });
      container.addEventListener('drop', (e)=>{
        if(!editMode) return;
        e.preventDefault();
        const ph = container.querySelector('.placeholder');
        const dragging = container.querySelector('.draggingItem');
        if(ph && dragging){
          container.insertBefore(dragging, ph);
          ph.remove();
        }
        const blockEl = container.closest('.block');
        if(blockEl){ renumberStreams(blockEl); }
      });
    }
    streamEl._dndSetup = true;
  }

  function makeModsDraggable(modsContainer){
    if(!modsContainer) return;
    modsContainer.querySelectorAll('.mod').forEach(mod=>{
      const hdr = mod.querySelector('.mod-hdr');
      if(hdr) hdr.style.cursor = editMode ? 'move' : '';
      attachModuleClose(mod);
      if(mod._dndSetup) return;
      mod.addEventListener('dragstart', (e)=>{
        if(!editMode){ e.preventDefault(); return; }
        mod.classList.add('draggingItem');
        e.dataTransfer.effectAllowed='move';
        try{ e.dataTransfer.setData('text/plain', mod.dataset.mod || 'module'); }
        catch(err){ /* Firefox requires setData but others may throw */ }
        const ph = document.createElement('div');
        ph.className='placeholder';
        ph.style.height = mod.getBoundingClientRect().height+'px';
        const parent = mod.parentElement;
        if(parent){ parent.insertBefore(ph, mod.nextSibling); }
      });
      mod.addEventListener('dragend', ()=>{
        mod.classList.remove('draggingItem');
        const parent = mod.parentElement;
        if(parent){ parent.querySelectorAll('.placeholder').forEach(x=>x.remove()); }
      });
      mod._dndSetup = true;
    });
    if(!modsContainer._dndBound){
      modsContainer._dndBound = true;
      modsContainer.addEventListener('dragover', (e)=>{
        if(!editMode) return;
        e.preventDefault();
        const dragging = modsContainer.querySelector('.draggingItem');
        if(!dragging) return;
        const after = getDragAfterElement(modsContainer, e.clientY);
        const ph = modsContainer.querySelector('.placeholder');
        if(ph){
          if(after==null) modsContainer.appendChild(ph);
          else modsContainer.insertBefore(ph, after);
        }
      });
      modsContainer.addEventListener('drop', (e)=>{
        if(!editMode) return;
        e.preventDefault();
        const ph = modsContainer.querySelector('.placeholder');
        const dragging = modsContainer.querySelector('.draggingItem');
        if(ph && dragging){
          modsContainer.insertBefore(dragging, ph);
          ph.remove();
        }
      });
    }
  }

  function getDragAfterElement(container, y){
    const els = [...container.querySelectorAll(':scope > :not(.placeholder):not(.draggingItem)')];
    let closest = {offset: Number.NEGATIVE_INFINITY, element: null};
    for(const child of els){
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height/2;
      if(offset < 0 && offset > closest.offset) closest = {offset, element: child};
    }
    return closest.element;
  }

  // When Edit toggles, (re)enable drag
  const _editBtn = qs('#editToggle');
  _editBtn.addEventListener('click', ()=> enableEditReorder(editMode));

  // Also enable on newly created streams
  // Start with one block for convenience
  addBlock();
})();

function applyMod(target, value, ctx){
  if(!ctx) return;
  const host = ctx.el || (ctx.modEl && ctx.modEl.closest ? ctx.modEl.closest('.stream') : null) || null;
  const el = host || ctx.el || null;
  const modCtx = (el && el.__modCtx) ? el.__modCtx : ctx;
  const actx = modCtx.actx || ctx.actx || ACTX || null;
  const sample = ctx.sample || modCtx.sample || (el && el._streamState) || null;
  const clamp01 = v=> Math.min(1, Math.max(0, v));
  const lfoState = ctx.lfo || modCtx.lfo || null;
  const depthOr = (fallback)=> (lfoState && typeof lfoState.depth === 'number') ? lfoState.depth : fallback;
  try{
    switch(target){
      case 'pan':{
        const panNode = ctx.pan || modCtx.pan;
        if(!panNode || !panNode.pan) break;
        const amt = Math.max(-1, Math.min(1, value * depthOr(1)));
        try{ panNode.pan.value = amt; }
        catch(e){ try{ panNode.pan.setValueAtTime(amt, actx ? actx.currentTime : 0); }catch(_){} }
        if(el){
          const control = el.querySelector('.pan');
          if(control){ control.value = amt; control.dispatchEvent(new Event('input', { bubbles:true })); }
        }
        break; }
      case 'vol':{
        const outNode = ctx.out || modCtx.out;
        const mix = clamp01(0.5 + value * depthOr(0.5));
        if(outNode){
          try{ outNode.gain.value = mix; }
          catch(e){ try{ outNode.gain.setValueAtTime(mix, actx ? actx.currentTime : 0); }catch(_){} }
        }
        if(el){
          const control = el.querySelector('.vol');
          if(control){ control.value = mix; control.dispatchEvent(new Event('input', { bubbles:true })); }
        }
        break; }
      case 'lpf':{
        const lpfNode = ctx.lpf || modCtx.lpf;
        if(!lpfNode) break;
        const hz = 500 + (1+value)*9750;
        try{ lpfNode.frequency.value = hz; }
        catch(e){ try{ lpfNode.frequency.setValueAtTime(hz, actx ? actx.currentTime : 0); }catch(_){} }
        break; }
      case 'tempo':{
        const setTempo = ctx.setTempo || modCtx.setTempo;
        const ratio = clamp01(0.5 + value * depthOr(0.5)) * 2;
        if(typeof setTempo === 'function'){ setTempo(ratio); }
        else if(sample){ sample.tempo = ratio; }
        break; }
      case 'pitch':{
        const setPitch = ctx.setPitch || modCtx.setPitch;
        const semi = Math.round(value * depthOr(0.5) * 12);
        if(typeof setPitch === 'function'){ setPitch(semi); }
        else if(sample){ sample.pitch = semi; }
        break; }
      case 'ab':{
        const mix = clamp01(0.5 + value*0.5);
        const setAB = ctx.setAB || modCtx.setAB;
        if(typeof setAB === 'function'){ setAB(mix); }
        else if(el){
          const control = el.querySelector('.ab');
          if(control){ control.value = mix; control.dispatchEvent(new Event('input', { bubbles:true })); }
        }
        break; }
      case 'apos':{
        if(sample && sample.A){
          const ratio = clamp01(((sample.A.dur||0)>0 ? sample.A.offset/(sample.A.dur||1) : 0) + value*0.001);
          if(typeof (ctx.seekA||modCtx.seekA) === 'function'){ (ctx.seekA||modCtx.seekA)(ratio); }
          else { sample.A.offset = ratio * (sample.A.dur||1); }
        }
        break; }
      case 'bpos':{
        if(sample && sample.B){
          const ratio = clamp01(((sample.B.dur||0)>0 ? sample.B.offset/(sample.B.dur||1) : 0) + value*0.001);
          if(typeof (ctx.seekB||modCtx.seekB) === 'function'){ (ctx.seekB||modCtx.seekB)(ratio); }
          else { sample.B.offset = ratio * (sample.B.dur||1); }
        }
        break; }
      default:
        break;
    }
  }catch(e){ /* ignore */ }
}
window.applyMod = applyMod;

(function(){
  const presetSelect = document.getElementById('stylePreset');
  if(!presetSelect) return;
  const applyTheme = window.__applyTheme || ((name)=>{
    document.body.classList.remove('theme-98','theme-xp');
    if(name==='win98'){ document.body.classList.add('theme-98'); }
    else if(name==='winxp'){ document.body.classList.add('theme-xp'); }
  });
  function maybeApply(value){
    if(value==='win98' || value==='winxp' || value==='flat'){
      applyTheme(value);
    }
  }
  presetSelect.addEventListener('change', ()=> maybeApply(presetSelect.value));
  maybeApply(presetSelect.value);
})();

(function(){
  const stylePanel = document.getElementById('stylePanel');
  if(!stylePanel) return;
  const mk = (html)=>{ const d=document.createElement('div'); d.innerHTML=html.trim(); return d.firstChild; };
  const grp = mk(`
    <div class="group">
      <div class="h">Assets (images)</div>
      <div class="row wrap" style="gap:8px">
        <label>Slider Track</label>
        <input id="imgTrackFile" type="file" accept="image/*">
        <input id="imgTrackUrl" type="text" placeholder="or paste image URL" style="width:220px">
        <label>Scale</label><input id="imgTrackScale" type="number" step="0.1" value="1" style="width:70px">
        <label>Rotate</label><input id="imgTrackRotate" type="number" step="1" value="0" style="width:70px">
      </div>
      <div class="row wrap" style="gap:8px">
        <label>Slider Thumb</label>
        <input id="imgThumbFile" type="file" accept="image/*">
        <input id="imgThumbUrl" type="text" placeholder="or paste image URL" style="width:220px">
        <label>Scale</label><input id="imgThumbScale" type="number" step="0.1" value="1" style="width:70px">
        <label>Rotate</label><input id="imgThumbRotate" type="number" step="1" value="0" style="width:70px">
      </div>
      <div class="row wrap" style="gap:8px">
        <label>Background image</label>
        <input id="imgBgFile" type="file" accept="image/*">
        <input id="imgBgUrl" type="text" placeholder="or paste image URL" style="width:220px">
        <button class="btn" id="imgBgApply">Apply BG</button>
        <button class="btn" id="imgBgClear">Clear BG</button>
      </div>
    </div>`);
  stylePanel.appendChild(grp);

  const fileToDataURL = (file)=> new Promise((res, rej)=>{ const r=new FileReader(); r.onload=()=>res(r.result); r.onerror=rej; r.readAsDataURL(file); });
  async function applyImgVar(fromFileEl, fromUrlEl, varName){
    try{
      let url = (fromUrlEl && fromUrlEl.value.trim()) || '';
      if(fromFileEl && fromFileEl.files && fromFileEl.files[0]) url = await fileToDataURL(fromFileEl.files[0]);
      if(!url) return;
      document.documentElement.style.setProperty(varName, `url("${url}")`);
    }catch(e){ console.warn('img var apply failed', varName, e); }
  }
  const setNumVar = (id, cssVar, unit='')=>{
    const el=document.getElementById(id);
    if(!el) return;
    const v=parseFloat(el.value)||0;
    document.documentElement.style.setProperty(cssVar, v + unit);
  };

  const trackFile=document.getElementById('imgTrackFile');
  const trackUrl=document.getElementById('imgTrackUrl');
  const thumbFile=document.getElementById('imgThumbFile');
  const thumbUrl=document.getElementById('imgThumbUrl');
  const bgFile=document.getElementById('imgBgFile');
  const bgUrl=document.getElementById('imgBgUrl');
  const bgApply=document.getElementById('imgBgApply');
  const bgClear=document.getElementById('imgBgClear');

  [trackFile, trackUrl].forEach(el=> el && el.addEventListener('change', ()=> applyImgVar(trackFile, trackUrl, '--slider-track-img')));
  [thumbFile, thumbUrl].forEach(el=> el && el.addEventListener('change', ()=> applyImgVar(thumbFile, thumbUrl, '--slider-thumb-img')));
  document.getElementById('imgTrackScale')?.addEventListener('change', ()=> setNumVar('imgTrackScale','--slider-track-scale'));
  document.getElementById('imgTrackRotate')?.addEventListener('change', ()=> setNumVar('imgTrackRotate','--slider-track-rotate','deg'));
  document.getElementById('imgThumbScale')?.addEventListener('change', ()=> setNumVar('imgThumbScale','--slider-thumb-scale'));
  document.getElementById('imgThumbRotate')?.addEventListener('change', ()=> setNumVar('imgThumbRotate','--slider-thumb-rotate','deg'));

  bgApply?.addEventListener('click', async ()=>{
    await applyImgVar(bgFile, bgUrl, '--_tmp');
    const val = getComputedStyle(document.documentElement).getPropertyValue('--_tmp').trim();
    if(val) document.body.style.backgroundImage = val;
  });
  bgClear?.addEventListener('click', ()=>{ document.body.style.backgroundImage=''; });
})();

(function(){
  const emojiRE = /[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}\u{2600}-\u{26FF}]/gu;
  function strip(node){
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
    const targets = [];
    while(walker.nextNode()){
      const n = walker.currentNode;
      if(emojiRE.test(n.nodeValue)) targets.push(n);
    }
    targets.forEach(n=>{ n.nodeValue = n.nodeValue.replace(emojiRE, ''); });
  }
  const body = document.body;
  if(!body) return;
  strip(body);
  new MutationObserver(()=> strip(body)).observe(body, {childList:true, subtree:true, characterData:true});
})();
