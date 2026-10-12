// Heartbeat + ambient drone, pilotés par le scroll. Web Audio API, aucun fichier.
// Le son ne démarre qu'au clic sur le bouton (politique autoplay des navigateurs).

let ctx, running = false, bpm = 0, targetBpm = 0, beatId = null;
let gainBeat, gainDrone, osc1, osc2, noiseGain;

function createCtx() {
  ctx = new (window.AudioContext || window.webkitAudioContext)();

  // Master gain
  const master = ctx.createGain();
  master.gain.value = 0.35;
  master.connect(ctx.destination);

  // Beat channel
  gainBeat = ctx.createGain();
  gainBeat.gain.value = 0.7;
  gainBeat.connect(master);

  // Drone channel
  gainDrone = ctx.createGain();
  gainDrone.gain.value = 0;
  gainDrone.connect(master);

  // Ambient drone: two detuned low oscillators
  osc1 = ctx.createOscillator();
  osc1.type = 'sine';
  osc1.frequency.value = 55;
  const f1 = ctx.createBiquadFilter();
  f1.type = 'lowpass';
  f1.frequency.value = 120;
  osc1.connect(f1).connect(gainDrone);
  osc1.start();

  osc2 = ctx.createOscillator();
  osc2.type = 'sine';
  osc2.frequency.value = 82.5;
  const f2 = ctx.createBiquadFilter();
  f2.type = 'lowpass';
  f2.frequency.value = 100;
  const g2 = ctx.createGain();
  g2.gain.value = 0.4;
  osc2.connect(f2).connect(g2).connect(gainDrone);
  osc2.start();
}

// Lub-dub: two short low-freq pulses
function beat() {
  if (!running || !ctx || bpm < 40) return;

  const now = ctx.currentTime;

  // Lub (S1)
  const lub = ctx.createOscillator();
  lub.type = 'sine';
  lub.frequency.setValueAtTime(65, now);
  lub.frequency.exponentialRampToValueAtTime(45, now + 0.08);
  const lubG = ctx.createGain();
  lubG.gain.setValueAtTime(0, now);
  lubG.gain.linearRampToValueAtTime(1, now + 0.01);
  lubG.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
  lub.connect(lubG).connect(gainBeat);
  lub.start(now);
  lub.stop(now + 0.12);

  // Dub (S2) — slightly higher, quieter, 120ms later
  const dub = ctx.createOscillator();
  dub.type = 'sine';
  dub.frequency.setValueAtTime(55, now + 0.12);
  dub.frequency.exponentialRampToValueAtTime(35, now + 0.2);
  const dubG = ctx.createGain();
  dubG.gain.setValueAtTime(0, now + 0.12);
  dubG.gain.linearRampToValueAtTime(0.6, now + 0.13);
  dubG.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
  dub.connect(dubG).connect(gainBeat);
  dub.start(now + 0.12);
  dub.stop(now + 0.24);

  // Smooth BPM transition
  bpm += (targetBpm - bpm) * 0.15;
  const interval = 60000 / Math.max(40, bpm);
  beatId = setTimeout(beat, interval);
}

// Footstep — short noise burst, like a soft impact
function footstep() {
  if (!running || !ctx) return;
  const now = ctx.currentTime;
  const bufLen = ctx.sampleRate * 0.06;
  const buf = ctx.createBuffer(1, bufLen, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < bufLen; i++) data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (bufLen * 0.15));

  const src = ctx.createBufferSource();
  src.buffer = buf;
  const filt = ctx.createBiquadFilter();
  filt.type = 'lowpass';
  filt.frequency.value = 300;
  const g = ctx.createGain();
  g.gain.value = 0.12;
  src.connect(filt).connect(g).connect(gainBeat);
  src.start(now);
}

let stepAccum = 0, lastProgress = 0;

export function setProgress(progress, fc) {
  targetBpm = fc || 0;

  // Drone: fade in during the race, louder in the middle
  if (gainDrone && ctx) {
    const intensity = Math.sin(Math.PI * Math.min(1, progress / 0.95)) * 0.15;
    gainDrone.gain.linearRampToValueAtTime(intensity, ctx.currentTime + 0.1);
  }

  // Footsteps at a pace that follows scroll speed
  const delta = Math.abs(progress - lastProgress);
  if (delta > 0) {
    stepAccum += delta;
    if (stepAccum > 0.008) {
      footstep();
      stepAccum = 0;
    }
  }
  lastProgress = progress;
}

export function start() {
  if (!ctx) createCtx();
  if (ctx.state === 'suspended') ctx.resume();
  running = true;
  bpm = targetBpm || 70;
  beat();
}

export function stop() {
  running = false;
  if (beatId) { clearTimeout(beatId); beatId = null; }
  if (gainDrone && ctx) gainDrone.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3);
}

export function isRunning() { return running; }
