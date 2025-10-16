(function(){
  const labRoot = document.getElementById('audioLab');
  if(!labRoot) return;

  /* ================= Virtual Instrument ================= */
  const instrumentCard = document.getElementById('labInstrument');
  const toggleBtn = instrumentCard ? instrumentCard.querySelector('[data-action="toggle-instrument"]') : null;
  const controlInputs = instrumentCard ? instrumentCard.querySelectorAll('[data-param]') : [];
  const readouts = instrumentCard ? instrumentCard.querySelectorAll('[data-readout]') : [];
  const waveSelect = instrumentCard ? instrumentCard.querySelector('select[data-param="wave"]') : null;
  const sampleFileInput = instrumentCard ? instrumentCard.querySelector('[data-sample-file]') : null;
  const sampleStatusEl = instrumentCard ? instrumentCard.querySelector('[data-status="sample"]') : null;
  const samplePlayBtn = instrumentCard ? instrumentCard.querySelector('[data-action="play-sample"]') : null;
  const sampleStopBtn = instrumentCard ? instrumentCard.querySelector('[data-action="stop-sample"]') : null;
  const loopCheckbox = instrumentCard ? instrumentCard.querySelector('input[data-param="sample-loop"]') : null;

  const KEY_TO_OFFSET = {
    KeyA:0, KeyW:1, KeyS:2, KeyE:3, KeyD:4, KeyF:5, KeyT:6, KeyG:7,
    KeyY:8, KeyH:9, KeyU:10, KeyJ:11, KeyK:12, KeyO:13, KeyL:14,
    KeyP:15, Semicolon:16, Quote:17
  };

  const instrumentState = {
    enabled:false,
    voice:'classic',
    wave:'sine',
    master:1,
    volume:0.9,
    octave:0,
    attack:0.02,
    release:0.4,
    cutoff:12000,
    resonance:1.2,
    reverb:0.25,
    sampleLoop:false
  };

  let instrumentGraph = null;
  let sampleBuffer = null;
  let samplePlayback = null;
  const periodicWaves = new Map();
  let noiseBuffer = null;

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
    voiceBus.gain.value = instrumentState.volume;

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

    if(master && master.gain){
      try{
        master.gain.setValueAtTime(instrumentState.master, ctx.currentTime);
      }catch(e){
        master.gain.value = instrumentState.master;
      }
    }

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

  function getPulseWave(ctx){
    if(periodicWaves.has('pulse')) return periodicWaves.get('pulse');
    const size = 4096;
    const real = new Float32Array(size);
    const imag = new Float32Array(size);
    const duty = 0.35;
    for(let n=1;n<size;n++){
      const theta = n * Math.PI * duty;
      real[n] = (2 / (n * Math.PI)) * Math.sin(theta);
      imag[n] = 0;
    }
    const wave = ctx.createPeriodicWave(real, imag, {disableNormalization:true});
    periodicWaves.set('pulse', wave);
    return wave;
  }

  function getNoiseBuffer(ctx){
    if(noiseBuffer && noiseBuffer.sampleRate === ctx.sampleRate) return noiseBuffer;
    const length = ctx.sampleRate * 2;
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for(let i=0;i<length;i++){
      data[i] = Math.random()*2 - 1;
    }
    noiseBuffer = buffer;
    return buffer;
  }

  function offsetToFrequency(offset){
    const midi = 60 + (offset||0) + instrumentState.octave * 12;
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  function updateReadouts(){
    readouts.forEach(el=>{
      const key = el.getAttribute('data-readout');
      if(!key) return;
      if(key === 'attack') el.textContent = Math.round(instrumentState.attack * 1000) + ' ms';
      else if(key === 'release') el.textContent = instrumentState.release.toFixed(2) + ' s';
      else if(key === 'cutoff') el.textContent = (instrumentState.cutoff/1000).toFixed(1) + ' kHz';
      else if(key === 'reverb') el.textContent = Math.round(instrumentState.reverb * 100) + '%';
      else if(key === 'resonance') el.textContent = 'Q ' + instrumentState.resonance.toFixed(1);
      else if(key === 'master' || key === 'volume') el.textContent = Math.round(instrumentState[key] * 100) + '%';
      else el.textContent = String(instrumentState[key]);
    });
  }

  function updateWaveAvailability(){
    if(!waveSelect) return;
    const disableWave = instrumentState.voice !== 'classic';
    waveSelect.disabled = disableWave;
    if(disableWave){
      if(waveSelect.parentElement){ waveSelect.parentElement.classList.add('lab-control--disabled'); }
    }else{
      if(waveSelect.parentElement){ waveSelect.parentElement.classList.remove('lab-control--disabled'); }
    }
  }

  function updateMasterVolume(){
    const graph = ensureAudioGraph();
    if(graph && graph.master && graph.master.gain){
      try{
        graph.master.gain.setTargetAtTime(instrumentState.master, graph.ctx.currentTime, 0.05);
      }catch(e){
        graph.master.gain.value = instrumentState.master;
      }
    }
  }

  function updateInstrumentVolume(){
    if(!instrumentGraph) return;
    const ctx = instrumentGraph.ctx;
    try{
      instrumentGraph.voiceBus.gain.setTargetAtTime(instrumentState.volume, ctx.currentTime, 0.05);
    }catch(e){
      instrumentGraph.voiceBus.gain.value = instrumentState.volume;
    }
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
      const freq = offsetToFrequency(voice.offset);
      try{
        voice.filter.frequency.setTargetAtTime(instrumentState.cutoff, ctx.currentTime, 0.05);
        voice.filter.Q.setTargetAtTime(instrumentState.resonance, ctx.currentTime, 0.05);
      }catch(e){ /* ignore */ }
      if(voice.type === 'classic'){
        voice.sources.forEach(src=>{
          try{
            src.type = instrumentState.wave;
            src.frequency.setTargetAtTime(freq, ctx.currentTime, 0.05);
          }catch(e){ /* ignore */ }
        });
      }else if(voice.type === 'supersaw'){
        voice.sources.forEach((src, idx)=>{
          try{
            src.frequency.setTargetAtTime(freq, ctx.currentTime, 0.05);
            if(voice.detunes && typeof voice.detunes[idx] === 'number'){
              src.detune.setTargetAtTime(voice.detunes[idx], ctx.currentTime, 0.05);
            }
          }catch(e){ /* ignore */ }
        });
      }else if(voice.type === 'pulse'){
        voice.sources.forEach(src=>{
          try{ src.frequency.setTargetAtTime(freq, ctx.currentTime, 0.05); }catch(e){ /* ignore */ }
        });
      }else if(voice.type === 'organ'){
        voice.sources.forEach((src, idx)=>{
          const ratio = idx === 0 ? 1 : (idx === 1 ? 2 : 3);
          try{ src.frequency.setTargetAtTime(freq * ratio, ctx.currentTime, 0.05); }catch(e){ /* ignore */ }
        });
      }
    });
    updateReverbMix(instrumentGraph.dryGain, instrumentGraph.wetGain);
    updateInstrumentVolume();
  }

  function cleanupVoice(voice){
    voice.sources.forEach(src=>{
      try{ src.disconnect(); }catch(e){}
      if(src.stop && !voice.released){
        try{ src.stop(); }catch(e){}
      }
    });
    try{ voice.filter.disconnect(); }catch(e){}
    try{ voice.amp.disconnect(); }catch(e){}
    voice.sources.length = 0;
  }

  function startVoice(code, offset){
    const graph = ensureAudioGraph();
    const ctx = graph.ctx;
    const freq = offsetToFrequency(offset);
    if(graph.voices.has(code)) return;

    const filter = ctx.createBiquadFilter();
    const amp = ctx.createGain();
    filter.type = 'lowpass';
    filter.frequency.value = instrumentState.cutoff;
    filter.Q.value = instrumentState.resonance;
    amp.gain.value = 0;
    filter.connect(amp);
    amp.connect(graph.voiceBus);

    const voice = { offset, type: instrumentState.voice, filter, amp, sources: [], released:false };

    const now = ctx.currentTime;
    const attackTime = Math.max(0.005, instrumentState.attack);

    if(voice.type === 'classic'){
      const osc = ctx.createOscillator();
      osc.type = instrumentState.wave;
      osc.frequency.value = freq;
      osc.connect(filter);
      osc.start(now);
      voice.sources.push(osc);
    }else if(voice.type === 'supersaw'){
      const detunes = [-18, -8, 0, 8, 18];
      voice.detunes = detunes;
      detunes.forEach(det=>{
        const osc = ctx.createOscillator();
        osc.type = 'sawtooth';
        osc.frequency.value = freq;
        osc.detune.value = det;
        osc.connect(filter);
        osc.start(now);
        voice.sources.push(osc);
      });
    }else if(voice.type === 'pulse'){
      const osc = ctx.createOscillator();
      osc.setPeriodicWave(getPulseWave(ctx));
      osc.frequency.value = freq;
      osc.connect(filter);
      osc.start(now);
      voice.sources.push(osc);
    }else if(voice.type === 'organ'){
      const harmonics = [1, 2, 3];
      harmonics.forEach(ratio=>{
        const osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.value = freq * ratio;
        osc.connect(filter);
        osc.start(now);
        voice.sources.push(osc);
      });
    }else if(voice.type === 'noise'){
      const src = ctx.createBufferSource();
      src.buffer = getNoiseBuffer(ctx);
      src.loop = true;
      src.connect(filter);
      src.start(now);
      voice.sources.push(src);
    }

    amp.gain.cancelScheduledValues(now);
    amp.gain.setValueAtTime(0, now);
    amp.gain.linearRampToValueAtTime(1, now + attackTime);

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
    }catch(e){ /* ignore */ }
    voice.sources.forEach(src=>{
      if(typeof src.stop === 'function'){
        try{ src.stop(now + releaseTime + 0.05); }catch(e){ try{ src.stop(); }catch(_e){} }
      }
    });
    setTimeout(()=>{
      cleanupVoice(voice);
    }, (releaseTime + 0.1) * 1000);
    instrumentGraph.voices.delete(code);
  }

  function stopAllVoices(){
    if(!instrumentGraph) return;
    Array.from(instrumentGraph.voices.keys()).forEach(stopVoice);
  }

  function updateSampleButtons(){
    if(samplePlayBtn){
      samplePlayBtn.disabled = !sampleBuffer || (samplePlayback && samplePlayback.playing);
    }
    if(sampleStopBtn){
      sampleStopBtn.disabled = !samplePlayback || !samplePlayback.playing;
    }
  }

  function updateSampleStatus(text){
    if(sampleStatusEl) sampleStatusEl.textContent = text;
  }

  function stopSamplePlayback(immediate=false){
    if(!samplePlayback || !samplePlayback.playing) return;
    const graph = instrumentGraph || ensureAudioGraph();
    const ctx = graph ? graph.ctx : null;
    const releaseTime = immediate ? 0.05 : Math.max(0.05, instrumentState.release);
    if(ctx){
      const now = ctx.currentTime;
      if(samplePlayback.gain){
        try{
          samplePlayback.gain.gain.cancelScheduledValues(now);
          const current = samplePlayback.gain.gain.value;
          samplePlayback.gain.gain.setValueAtTime(current, now);
          samplePlayback.gain.gain.linearRampToValueAtTime(0, now + releaseTime);
        }catch(e){ /* ignore */ }
      }
      if(samplePlayback.source){
        try{ samplePlayback.source.stop(now + releaseTime + 0.05); }
        catch(e){ try{ samplePlayback.source.stop(); }catch(_e){} }
      }
    }else if(samplePlayback.source){
      try{ samplePlayback.source.stop(); }catch(e){}
    }
    samplePlayback.playing = false;
    updateSampleButtons();
  }

  function playSample(){
    if(!sampleBuffer) return;
    const graph = ensureAudioGraph();
    const ctx = graph.ctx;
    stopSamplePlayback(true);
    const source = ctx.createBufferSource();
    source.buffer = sampleBuffer;
    source.loop = instrumentState.sampleLoop;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    source.connect(gain);
    gain.connect(graph.voiceBus);
    const now = ctx.currentTime;
    const attackTime = Math.max(0.005, instrumentState.attack);
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(1, now + attackTime);
    source.start(now);
    samplePlayback = { source, gain, playing:true };
    source.onended = ()=>{
      try{ source.disconnect(); }catch(e){}
      try{ gain.disconnect(); }catch(e){}
      if(samplePlayback && samplePlayback.source === source){
        samplePlayback = null;
      }
      updateSampleButtons();
    };
    updateSampleButtons();
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
        stopSamplePlayback(true);
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
    const handler = ()=>{
      if(param === 'wave'){
        instrumentState.wave = input.value;
      }else if(param === 'voice'){
        instrumentState.voice = input.value;
        updateWaveAvailability();
      }else if(param === 'master'){
        instrumentState.master = parseFloat(input.value) || 0;
        updateMasterVolume();
      }else if(param === 'volume'){
        instrumentState.volume = parseFloat(input.value) || instrumentState.volume;
        updateInstrumentVolume();
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
      }else if(param === 'sample-loop'){
        instrumentState.sampleLoop = !!(input.checked);
        if(samplePlayback && samplePlayback.source){
          samplePlayback.source.loop = instrumentState.sampleLoop;
        }
      }
      updateReadouts();
      applyStateToVoices();
    };
    input.addEventListener('input', handler);
    if(input.tagName === 'SELECT' || input.type === 'checkbox'){
      input.addEventListener('change', handler);
    }
  });

  updateWaveAvailability();
  updateReadouts();
  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('keyup', handleKeyUp);
  window.addEventListener('blur', ()=>{
    stopAllVoices();
    stopSamplePlayback(true);
  });

  if(instrumentCard){
    instrumentCard.addEventListener('click', (ev)=>{
      const actionBtn = ev.target.closest('[data-action]');
      if(!actionBtn) return;
      const action = actionBtn.getAttribute('data-action');
      if(action === 'load-sample' && sampleFileInput){
        sampleFileInput.value = '';
        sampleFileInput.click();
      }else if(action === 'play-sample'){
        playSample();
      }else if(action === 'stop-sample'){
        stopSamplePlayback();
      }
    });
  }

  if(sampleFileInput){
    sampleFileInput.addEventListener('change', async ()=>{
      const file = sampleFileInput.files && sampleFileInput.files[0];
      if(!file) return;
      const graph = ensureAudioGraph();
      updateSampleStatus('Loading sample…');
      try{
        const arrayBuf = await file.arrayBuffer();
        const decoded = await graph.ctx.decodeAudioData(arrayBuf);
        sampleBuffer = decoded;
        const seconds = decoded.duration;
        updateSampleStatus(`Loaded ${file.name} (${seconds.toFixed(2)} s)`);
        updateSampleButtons();
      }catch(e){
        console.warn('Sample decode failed', e);
        updateSampleStatus('Unable to load sample');
        sampleBuffer = null;
        updateSampleButtons();
      }
    });
  }

  if(loopCheckbox){
    loopCheckbox.checked = instrumentState.sampleLoop;
  }

  updateSampleButtons();
})();
