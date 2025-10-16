(function(){
  const labRoot = document.getElementById('audioLab');
  if(!labRoot) return;

  /* ================= Virtual Instrument ================= */
  const instrumentCard = document.getElementById('labInstrument');
  const toggleBtn = instrumentCard ? instrumentCard.querySelector('[data-action="toggle-instrument"]') : null;
  const controlInputs = instrumentCard ? instrumentCard.querySelectorAll('[data-param]') : [];
  const readouts = instrumentCard ? instrumentCard.querySelectorAll('[data-readout]') : [];

  const KEY_TO_OFFSET = {
    KeyA:0, KeyW:1, KeyS:2, KeyE:3, KeyD:4, KeyF:5, KeyT:6, KeyG:7,
    KeyY:8, KeyH:9, KeyU:10, KeyJ:11, KeyK:12, KeyO:13, KeyL:14,
    KeyP:15, Semicolon:16, Quote:17
  };

  const instrumentState = {
    enabled:false,
    wave:'sine',
    octave:0,
    attack:0.02,
    release:0.4,
    cutoff:12000,
    resonance:1.2,
    reverb:0.25
  };

  let instrumentGraph = null;

  function ensureAudioGraph(){
    if(instrumentGraph) return instrumentGraph;
    let audioExports = null;
    if(typeof window.ensureNoisetownAudio === 'function'){
      audioExports = window.ensureNoisetownAudio();
    }
    const ctx = (audioExports && (audioExports.context || audioExports.actx)) || window.ACTX || new (window.AudioContext || window.webkitAudioContext)();
    if(!window.ACTX) window.ACTX = ctx;
    const master = (audioExports && (audioExports.master || audioExports.output)) || window._MASTER_OUT || ctx.destination;

    const voiceBus = ctx.createGain();
    voiceBus.gain.value = 1.0;

    const dryGain = ctx.createGain();
    const wetSend = ctx.createGain();
    const wetGain = ctx.createGain();
    const convolver = ctx.createConvolver();
    convolver.normalize = true;
    convolver.buffer = buildImpulse(ctx, 2.8, 3.6);

    voiceBus.connect(dryGain);
    voiceBus.connect(wetSend);
    dryGain.connect(master);
    wetSend.connect(convolver);
    convolver.connect(wetGain);
    wetGain.connect(master);

    updateReverbMix(dryGain, wetGain);

    instrumentGraph = {
      ctx,
      master,
      voiceBus,
      dryGain,
      wetGain,
      convolver,
      voices:new Map()
    };
    return instrumentGraph;
  }

  function buildImpulse(ctx, seconds=2.5, decay=3.5){
    const rate = ctx.sampleRate;
    const length = Math.max(1, Math.floor(rate * seconds));
    const impulse = ctx.createBuffer(2, length, rate);
    for(let channel=0; channel<impulse.numberOfChannels; channel++){
      const data = impulse.getChannelData(channel);
      for(let i=0;i<length;i++){
        data[i] = (Math.random()*2 - 1) * Math.pow(1 - i/length, decay);
      }
    }
    return impulse;
  }

  function offsetToFrequency(offset){
    const midi = 60 + (offset||0) + instrumentState.octave * 12;
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  function updateReadouts(){
    readouts.forEach(el=>{
      const key = el.getAttribute('data-readout');
      if(!key || !(key in instrumentState)) return;
      if(key === 'attack') el.textContent = Math.round(instrumentState.attack * 1000) + ' ms';
      else if(key === 'release') el.textContent = instrumentState.release.toFixed(2) + ' s';
      else if(key === 'cutoff') el.textContent = (instrumentState.cutoff/1000).toFixed(1) + ' kHz';
      else if(key === 'reverb') el.textContent = Math.round(instrumentState.reverb * 100) + '%';
      else if(key === 'resonance') el.textContent = 'Q ' + instrumentState.resonance.toFixed(1);
      else el.textContent = String(instrumentState[key]);
    });
  }

  function updateReverbMix(dry, wet){
    const dryMix = Math.max(0, 1 - instrumentState.reverb);
    dry.gain.setTargetAtTime(dryMix, dry.context.currentTime, 0.05);
    wet.gain.setTargetAtTime(instrumentState.reverb, wet.context.currentTime, 0.05);
  }

  function applyStateToVoices(){
    if(!instrumentGraph) return;
    const ctx = instrumentGraph.ctx;
    instrumentGraph.voices.forEach(voice=>{
      try{
        voice.osc.type = instrumentState.wave;
        voice.osc.frequency.setTargetAtTime(offsetToFrequency(voice.offset), ctx.currentTime, 0.05);
        voice.filter.frequency.setTargetAtTime(instrumentState.cutoff, ctx.currentTime, 0.05);
        voice.filter.Q.setTargetAtTime(instrumentState.resonance, ctx.currentTime, 0.05);
      }catch(e){ /* ignore */ }
    });
    updateReverbMix(instrumentGraph.dryGain, instrumentGraph.wetGain);
  }

  function startVoice(code, offset){
    const graph = ensureAudioGraph();
    const ctx = graph.ctx;
    const freq = offsetToFrequency(offset);
    if(graph.voices.has(code)) return;

    const osc = ctx.createOscillator();
    const filter = ctx.createBiquadFilter();
    const amp = ctx.createGain();

    osc.type = instrumentState.wave;
    osc.frequency.value = freq;

    filter.type = 'lowpass';
    filter.frequency.value = instrumentState.cutoff;
    filter.Q.value = instrumentState.resonance;

    amp.gain.value = 0;

    osc.connect(filter);
    filter.connect(amp);
    amp.connect(graph.voiceBus);

    const now = ctx.currentTime;
    osc.start(now);
    amp.gain.cancelScheduledValues(now);
    amp.gain.setValueAtTime(0, now);
    amp.gain.linearRampToValueAtTime(1, now + Math.max(0.005, instrumentState.attack));

    const voice = { osc, filter, amp, offset, released:false };
    graph.voices.set(code, voice);
  }

  function stopVoice(code){
    if(!instrumentGraph) return;
    const voice = instrumentGraph.voices.get(code);
    if(!voice || voice.released) return;
    const ctx = instrumentGraph.ctx;
    const now = ctx.currentTime;
    const releaseTime = Math.max(0.05, instrumentState.release);
    voice.released = true;
    try{
      voice.amp.gain.cancelScheduledValues(now);
      const current = voice.amp.gain.value;
      voice.amp.gain.setValueAtTime(current, now);
      voice.amp.gain.linearRampToValueAtTime(0, now + releaseTime);
      voice.osc.stop(now + releaseTime + 0.05);
      voice.osc.onended = ()=>{
        try{ voice.osc.disconnect(); }catch(e){}
        try{ voice.filter.disconnect(); }catch(e){}
        try{ voice.amp.disconnect(); }catch(e){}
      };
    }catch(e){ /* ignore */ }
    instrumentGraph.voices.delete(code);
  }

  function stopAllVoices(){
    if(!instrumentGraph) return;
    Array.from(instrumentGraph.voices.keys()).forEach(stopVoice);
  }

  function handleKeyDown(e){
    if(!instrumentState.enabled) return;
    if(e.repeat) return;
    const tag = e.target && e.target.tagName ? e.target.tagName.toLowerCase() : '';
    if(tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    const offset = KEY_TO_OFFSET[e.code];
    if(typeof offset === 'undefined') return;
    e.preventDefault();
    const graph = ensureAudioGraph();
    if(graph && graph.ctx.state === 'suspended'){
      graph.ctx.resume().catch(()=>{});
    }
    startVoice(e.code, offset);
  }

  function handleKeyUp(e){
    if(!instrumentState.enabled) return;
    const offset = KEY_TO_OFFSET[e.code];
    if(typeof offset === 'undefined') return;
    e.preventDefault();
    stopVoice(e.code);
  }

  if(toggleBtn){
    toggleBtn.addEventListener('click', ()=>{
      instrumentState.enabled = !instrumentState.enabled;
      toggleBtn.textContent = instrumentState.enabled ? 'Disable Instrument' : 'Enable Instrument';
      toggleBtn.setAttribute('aria-pressed', String(instrumentState.enabled));
      if(!instrumentState.enabled){
        stopAllVoices();
      }else{
        const graph = ensureAudioGraph();
        if(graph && graph.ctx.state === 'suspended'){
          graph.ctx.resume().catch(()=>{});
        }
      }
    });
  }

  controlInputs.forEach(input=>{
    const param = input.getAttribute('data-param');
    if(!param) return;
    input.addEventListener('input', ()=>{
      if(param === 'wave'){
        instrumentState.wave = input.value;
      }else if(param === 'octave'){
        instrumentState.octave = parseInt(input.value, 10) || 0;
      }else if(param === 'attack'){
        instrumentState.attack = parseFloat(input.value) || instrumentState.attack;
      }else if(param === 'release'){
        instrumentState.release = parseFloat(input.value) || instrumentState.release;
      }else if(param === 'cutoff'){
        instrumentState.cutoff = parseFloat(input.value) || instrumentState.cutoff;
      }else if(param === 'resonance'){
        instrumentState.resonance = parseFloat(input.value) || instrumentState.resonance;
      }else if(param === 'reverb'){
        instrumentState.reverb = Math.min(1, Math.max(0, parseFloat(input.value) || 0));
      }
      updateReadouts();
      applyStateToVoices();
    });
  });

  updateReadouts();
  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('keyup', handleKeyUp);
  window.addEventListener('blur', stopAllVoices);

  /* ================= External Tool Launchers ================= */
  labRoot.addEventListener('click', (ev)=>{
    const toolBtn = ev.target.closest('[data-tool-link]');
    if(toolBtn){
      const url = toolBtn.getAttribute('data-tool-link');
      if(url){
        window.open(url, '_blank', 'noopener');
      }
    }
  });

  /* ================= Workflow Notes ================= */
  const NOTES_KEY = 'noisetown.labNotes';
  const notesEl = document.getElementById('labNotes');
  const noteStatus = document.getElementById('labNoteStatus');

  if(notesEl){
    try{
      const saved = localStorage.getItem(NOTES_KEY);
      if(saved) notesEl.value = saved;
    }catch(e){ /* ignore */ }
  }

  function flashStatus(msg){
    if(!noteStatus) return;
    noteStatus.textContent = msg;
    setTimeout(()=>{ noteStatus.textContent=''; }, 1600);
  }

  labRoot.addEventListener('click', (ev)=>{
    const actionBtn = ev.target.closest('[data-action]');
    if(!actionBtn) return;
    const action = actionBtn.getAttribute('data-action');
    if(action === 'save-notes' && notesEl){
      try{
        localStorage.setItem(NOTES_KEY, notesEl.value || '');
        flashStatus('Notes saved to browser');
      }catch(e){ flashStatus('Unable to save notes'); }
    }else if(action === 'clear-notes' && notesEl){
      notesEl.value = '';
      try{ localStorage.removeItem(NOTES_KEY); }catch(e){}
      flashStatus('Notes cleared');
    }
  });
})();
