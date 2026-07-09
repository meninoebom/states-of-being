/**
 * Song Blender — main app orchestration.
 * Supports 0, 1, or 2 bodies via auto-detection (no mode toggle needed).
 */

import { AudioEngine } from './audio-engine.js';
import { SongPicker } from './song-picker.js';
import { LoopGrid } from './loop-grid.js';
import { MovementDetector, computeRelational } from './movement.js';
import { ReadingsEngine, RELATIONAL_READINGS } from './readings.js';
import { applyMapping, QUIET_VOLUMES } from './mapping.js';
import { ArcEngine } from './arc.js';
import { CATEGORIES } from './constants.js';

const API_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://song-blender-api-production.up.railway.app';

// Debug gate: ?debug=1 exposes the developer surface (raw mode dropdown, loop
// grid, debug panel, ASCII phase indicator). Without it, /app is the guided
// movement product: pick a song, Start, move. See issue #14.
const DEBUG = new URLSearchParams(window.location.search).get('debug') === '1';

// Friendly phase names for the guided flow's phase indicator.
const PHASE_LABELS = {
  await: 'Move to begin',
  emerge: 'Emerging',
  build: 'Building',
  peak: 'Peak',
  breakdown: 'Drifting',
  resolve: 'Resolving',
};

const engine = new AudioEngine();
const picker = new SongPicker(document.getElementById('song-picker'), API_URL);
const grid = new LoopGrid(document.getElementById('loop-grid'));

// Two detectors + readings engines (always allocated, used when bodies present)
const detectors = [new MovementDetector(), new MovementDetector()];
const readingsEngines = [new ReadingsEngine(), new ReadingsEngine()];
const relationalReadings = new ReadingsEngine(RELATIONAL_READINGS);

// State
const status = document.getElementById('status');
const playBtn = document.getElementById('play-btn');
const modeSelect = document.getElementById('mode-select');
const modeToggle = document.getElementById('mode-toggle');
const loopGridEl = document.getElementById('loop-grid');
const cameraError = document.getElementById('camera-error');
const cameraRetryBtn = document.getElementById('camera-retry');
const debugPanel = document.getElementById('debug-panel');
let playing = false;
let songLoaded = false;
// Guided flow defaults to Arc ('Journey'); debug preserves the old Manual default.
let mode = DEBUG ? 'manual' : 'arc'; // 'manual' | 'webcam' | 'arc'
let arc = null;      // ArcEngine instance (created on arc mode play)
let arcFadeTimeout = null; // timeout ID for post-arc fade-to-silence
let lastFrameTime = null; // for dt calculation
const phaseIndicator = document.getElementById('phase-indicator');

// No-body prompt: nudge the user to step into frame in webcam mode
const NO_BODY_PROMPT_MS = 3000;
let lastBodySeen = 0;        // performance.now() of last frame with a body
let noBodyPromptShown = false;

// MediaPipe state
let poseLandmarker = null;
let video = null;
let webcamRunning = false;

// Skeleton canvas
const skeletonCanvas = document.getElementById('skeleton-canvas');
const skeletonCtx = skeletonCanvas ? skeletonCanvas.getContext('2d') : null;

function setStatus(msg) { if (status) status.textContent = msg; }

function updatePlayButton() {
  playBtn.disabled = !songLoaded;
  playBtn.textContent = playing ? 'Stop' : 'Start';
}

function showCameraError() { if (cameraError) cameraError.style.display = 'block'; }
function hideCameraError() { if (cameraError) cameraError.style.display = 'none'; }

/** Highlight the guided toggle button matching the current mode. */
function syncModeToggle() {
  if (!modeToggle) return;
  modeToggle.querySelectorAll('button').forEach((b) =>
    b.classList.toggle('active', b.dataset.mode === mode));
}

// --- Song selection ---
picker.onSongSelected = async (metadata) => {
  if (playing) {
    engine.stop();
    playing = false;
  }

  songLoaded = false;
  updatePlayButton();
  hideCameraError();
  setStatus(`Loading ${metadata.name}...`);

  engine.onLoadProgress = (loaded, total) => {
    setStatus(`Loading loops: ${loaded}/${total}`);
  };

  try {
    await engine.load(metadata, API_URL);
  } catch (err) {
    console.error('Failed to load song:', err);
    setStatus(`Failed to load ${metadata.name}: ${err.message}`);
    return;
  }

  grid.render(metadata);
  grid.onTrackToggle = (filename, muted) => {
    engine.setTrackMuted(filename, muted);
  };

  songLoaded = true;
  updatePlayButton();
  setStatus(`${metadata.name} · ${metadata.bpm} BPM · Click Start to begin`);
};

// --- Play/Stop ---
playBtn.addEventListener('click', async () => {
  if (!songLoaded) return;

  if (playing) {
    stopPlayback();
    setStatus('Stopped');
  } else {
    await attemptStart();
  }
  updatePlayButton();
});

// Camera denial retry: re-run the same start flow (acquires camera, then plays).
if (cameraRetryBtn) {
  cameraRetryBtn.addEventListener('click', async () => {
    await attemptStart();
    updatePlayButton();
  });
}

/**
 * Begin playback. Movement modes acquire the webcam first; on denial we surface
 * a clear retry message instead of silently dropping to a dead manual screen.
 */
async function attemptStart() {
  if (mode === 'webcam' || mode === 'arc') {
    hideCameraError();
    await ensureWebcam();
    if (!webcamRunning) {
      showCameraError();
      return;
    }
  }
  await Tone.start();
  engine.start();
  startPlayback();
}

/** Begin playback for the current mode, setting an audible baseline. */
function startPlayback() {
  playing = true;
  lastBodySeen = performance.now();
  noBodyPromptShown = false;

  if (mode === 'arc') {
    arc = new ArcEngine();
    lastFrameTime = null;
    arc.onPhaseChange = handlePhaseChange;
    arc.onComplete = handleArcComplete;
    // Start in AWAIT: only texture audible, quiet
    for (const cat of CATEGORIES) {
      engine.setCategoryVolume(cat, cat === 'texture' ? -12 : -60);
    }
    if (phaseIndicator) {
      phaseIndicator.style.display = 'block';
      phaseIndicator.textContent = DEBUG ? 'AWAIT — move to begin' : 'Move to begin';
    }
    grid.setAvailableCategories(['texture']);
    setStatus('Waiting for movement...');
  } else if (mode === 'webcam') {
    // Audible quiet baseline so the app is never silent while out of frame
    for (const cat of CATEGORIES) engine.setCategoryVolume(cat, QUIET_VOLUMES[cat]);
    setStatus('Playing');
  } else {
    // manual
    for (const cat of CATEGORIES) engine.setCategoryVolume(cat, -8);
    setStatus('Playing');
  }
}

/** Stop playback and tear down any mode-specific state (arc, indicators, grid dimming). */
function stopPlayback() {
  engine.stop();
  playing = false;
  arc = null;
  if (arcFadeTimeout) { clearTimeout(arcFadeTimeout); arcFadeTimeout = null; }
  if (phaseIndicator) phaseIndicator.style.display = 'none';
  noBodyPromptShown = false;
  grid.setAvailableCategories(CATEGORIES); // un-dim any arc phase gating
}

// --- Mode switching ---
// Debug users pick from the raw dropdown; guided users pick Journey / Free Play.
if (modeSelect) {
  modeSelect.addEventListener('change', (e) => setMode(e.target.value));
}
if (modeToggle) {
  modeToggle.querySelectorAll('button').forEach((btn) => {
    btn.addEventListener('click', () => {
      setMode(btn.dataset.mode);
      syncModeToggle();
    });
  });
}

/**
 * Single entry point for mode transitions. Tears down the previous mode by
 * stopping playback (an accepted simplification). The webcam is acquired at
 * Start (attemptStart), not here, so camera permission ties to an explicit
 * user gesture and denial surfaces at a clear moment.
 */
function setMode(newMode) {
  if (newMode === mode) return;

  // Always tear down: clears playback AND lingering UI (e.g. a completed arc's
  // phase indicator / grid dimming, where playing is already false).
  const wasPlaying = playing;
  stopPlayback();
  if (wasPlaying) {
    setStatus('Stopped');
    updatePlayButton();
  }
  hideCameraError();

  mode = newMode;
  if (mode === 'manual') stopWebcam();
}

// --- Webcam / MediaPipe ---

async function ensureWebcam() {
  if (webcamRunning) return;

  try {
    setStatus('Starting webcam...');

    // Build the landmarker once and reuse it; retries after a camera denial
    // should not leak a fresh GPU/WASM model each time.
    if (!poseLandmarker) {
      const { PoseLandmarker, FilesetResolver } = await import(
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs'
      );

      const vision = await FilesetResolver.forVisionTasks(
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
      );

      poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
          delegate: 'GPU',
        },
        runningMode: 'VIDEO',
        numPoses: 2,
        minPoseDetectionConfidence: 0.6,
        minPosePresenceConfidence: 0.6,
        minTrackingConfidence: 0.5,
      });
    }

    video = document.getElementById('webcam-video');
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: 'user' },
      audio: false,
    });
    video.srcObject = stream;
    await new Promise(r => { video.onloadedmetadata = r; });
    await video.play();

    webcamRunning = true;
    // Skeleton overlay is the "it sees me" feedback for everyone; the debug
    // panel is developer-only.
    if (skeletonCanvas) skeletonCanvas.style.display = 'block';
    if (DEBUG && debugPanel) debugPanel.style.display = 'block';
    setStatus('Webcam active');
    detectLoop();
  } catch (err) {
    console.error('Webcam init failed:', err);
    setStatus('Camera unavailable');
  }
}

function stopWebcam() {
  webcamRunning = false;
  if (video && video.srcObject) {
    video.srcObject.getTracks().forEach(t => t.stop());
    video.srcObject = null;
  }
  if (skeletonCanvas) skeletonCanvas.style.display = 'none';
  if (debugPanel) debugPanel.style.display = 'none';
}

function detectLoop() {
  if (!webcamRunning || !poseLandmarker || !video) return;
  if (video.readyState < 2) {
    requestAnimationFrame(detectLoop);
    return;
  }

  const now = performance.now();
  const ts = now / 1000;
  const results = poseLandmarker.detectForVideo(video, now);
  const bodyCount = results.landmarks ? results.landmarks.length : 0;

  if (bodyCount > 0) {
    lastBodySeen = now;
    if (noBodyPromptShown) {
      noBodyPromptShown = false;
      setStatus('Playing');
    }

    // Update each detected body
    const allQualities = [];
    const allReadings = [];

    for (let i = 0; i < bodyCount && i < 2; i++) {
      const qualities = detectors[i].update(results.landmarks[i], ts);
      const bodyReadings = readingsEngines[i].update(qualities);
      allQualities.push(qualities);
      allReadings.push(bodyReadings);
    }

    // Compute relational metrics when two bodies present
    let relReadings = [];
    let relQualities = null;
    if (bodyCount >= 2) {
      relQualities = computeRelational(allQualities[0], allQualities[1], detectors[0], detectors[1]);
      relReadings = relationalReadings.update(relQualities);
    }

    // Merge readings for mapping:
    // Average individual readings (so two "agitated" bodies don't double-weight),
    // then append relational readings
    const mergedReadings = averageReadings(allReadings);
    const finalReadings = [...mergedReadings, ...relReadings];

    // Apply to audio
    if (playing && mode === 'webcam') {
      applyMapping(finalReadings, engine);
    } else if (playing && mode === 'arc' && arc) {
      // Feed arc engine
      const now2 = performance.now() / 1000;
      const dt = lastFrameTime ? now2 - lastFrameTime : 1 / 30;
      lastFrameTime = now2;
      const avgVelocity = allQualities.length > 0
        ? allQualities.reduce((s, q) => s + (q.velocity || 0), 0) / allQualities.length
        : 0;
      arc.update(dt, avgVelocity);

      const phase = arc.getCurrentPhase();
      if (phase) {
        applyMapping(finalReadings, engine, phase.categories);
        updatePhaseIndicator(phase);
      }
    }

    // Draw skeletons + debug
    drawSkeletons(results.landmarks, bodyCount, finalReadings);
    updateDebug(allQualities, finalReadings, relQualities);
  } else if (playing && mode === 'webcam') {
    // No body detected. The quiet baseline keeps playing (never silent); nudge
    // the user to step into frame once they've been absent for a moment.
    if (!noBodyPromptShown && now - lastBodySeen > NO_BODY_PROMPT_MS) {
      noBodyPromptShown = true;
      setStatus('Step into frame to shape the music');
    }
  } else if (playing && mode === 'arc' && arc) {
    // No body detected — still tick arc so timed phases advance. Arc starts with
    // audible texture and shows its own AWAIT prompt, so it never hits the trap.
    const now2 = performance.now() / 1000;
    const dt = lastFrameTime ? now2 - lastFrameTime : 1 / 30;
    lastFrameTime = now2;
    arc.update(dt, 0);
    const phase = arc.getCurrentPhase();
    if (phase) updatePhaseIndicator(phase);
  }

  requestAnimationFrame(detectLoop);
}

/**
 * Average readings across bodies. For each reading ID, average the values
 * and consider active if ANY body has it active.
 */
function averageReadings(bodyReadingsArrays) {
  if (bodyReadingsArrays.length === 1) return bodyReadingsArrays[0];

  // Build map of id → { totalValue, active, count }
  const map = {};
  for (const bodyReadings of bodyReadingsArrays) {
    for (const r of bodyReadings) {
      if (!map[r.id]) map[r.id] = { totalValue: 0, active: false, count: 0 };
      map[r.id].totalValue += r.value;
      map[r.id].active = map[r.id].active || r.active;
      map[r.id].count++;
    }
  }

  return Object.entries(map).map(([id, { totalValue, active, count }]) => ({
    id,
    value: totalValue / count,
    active,
  }));
}

// --- Skeleton drawing ---

const POSE_CONNECTIONS = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [24, 26], [26, 28],
];

const BODY_COLORS = ['#8af', '#fa8']; // body 0 = blue, body 1 = orange
const READING_COLORS = { flowing: '#6ef', agitated: '#f66', stillness: '#668', reaching: '#fa4', unison: '#af6', opposition: '#f6a' };

function drawSkeletons(allLandmarks, bodyCount, readingValues) {
  if (!skeletonCtx || !skeletonCanvas || skeletonCanvas.style.display === 'none') return;

  const W = skeletonCanvas.width = 200;
  const H = skeletonCanvas.height = 150;
  skeletonCtx.clearRect(0, 0, W, H);

  // If relational readings are active, tint the background
  for (const r of readingValues) {
    if ((r.id === 'unison' || r.id === 'opposition') && r.active && r.value > 0.1) {
      skeletonCtx.fillStyle = r.id === 'unison'
        ? `rgba(170, 255, 100, ${r.value * 0.15})`
        : `rgba(255, 100, 170, ${r.value * 0.15})`;
      skeletonCtx.fillRect(0, 0, W, H);
    }
  }

  for (let b = 0; b < bodyCount && b < 2; b++) {
    const landmarks = allLandmarks[b];
    const color = BODY_COLORS[b];

    // Connections
    skeletonCtx.strokeStyle = color;
    skeletonCtx.lineWidth = 2;
    skeletonCtx.lineCap = 'round';

    for (const [a, i] of POSE_CONNECTIONS) {
      const la = landmarks[a], lb = landmarks[i];
      if (la.visibility > 0.3 && lb.visibility > 0.3) {
        skeletonCtx.beginPath();
        skeletonCtx.moveTo((1 - la.x) * W, la.y * H);
        skeletonCtx.lineTo((1 - lb.x) * W, lb.y * H);
        skeletonCtx.stroke();
      }
    }

    // Joints
    skeletonCtx.fillStyle = color;
    for (const i of [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) {
      const lm = landmarks[i];
      if (lm.visibility > 0.3) {
        skeletonCtx.beginPath();
        skeletonCtx.arc((1 - lm.x) * W, lm.y * H, 3, 0, Math.PI * 2);
        skeletonCtx.fill();
      }
    }

    // Head
    const nose = landmarks[0];
    if (nose.visibility > 0.3) {
      skeletonCtx.beginPath();
      skeletonCtx.arc((1 - nose.x) * W, nose.y * H, 5, 0, Math.PI * 2);
      skeletonCtx.fill();
    }
  }
}

// --- Debug overlay ---

function updateDebug(allQualities, readingValues, relQualities) {
  if (!debugPanel || debugPanel.style.display === 'none') return;

  let text = '';

  for (let i = 0; i < allQualities.length; i++) {
    const label = allQualities.length > 1 ? ` (body ${i + 1})` : '';
    const qLines = Object.entries(allQualities[i])
      .filter(([k]) => !k.startsWith('_'))
      .map(([k, v]) => `${k.padEnd(14)} ${bar(v)} ${v.toFixed(2)}`)
      .join('\n');
    text += `── qualities${label} ──\n${qLines}\n\n`;
  }

  if (relQualities) {
    const relLines = Object.entries(relQualities)
      .map(([k, v]) => `${k.padEnd(16)} ${bar(v)} ${v.toFixed(2)}`)
      .join('\n');
    text += `── relational ──\n${relLines}\n\n`;
  }

  const rLines = readingValues
    .map(r => `${r.id.padEnd(14)} ${bar(r.value)} ${r.value.toFixed(2)} ${r.active ? '●' : '○'}`)
    .join('\n');
  text += `── readings ──\n${rLines}`;

  debugPanel.textContent = text;
}

function bar(v, width = 16) {
  const filled = Math.round(v * width);
  return '█'.repeat(filled) + '░'.repeat(width - filled);
}

// --- Arc mode handlers ---

function handlePhaseChange(phase) {
  const section = arc.config.sectionMap[phase.id];
  if (section) {
    swapLoopsToSection(section);
  }
  setStatus(DEBUG ? `Arc: ${phase.id.toUpperCase()}` : (PHASE_LABELS[phase.id] || ''));
  if (phaseIndicator) updatePhaseIndicator(arc.getCurrentPhase());
  grid.setAvailableCategories(phase.categories);
}

function swapLoopsToSection(targetSection) {
  for (const cat of CATEGORIES) {
    const loops = engine.getLoopsForCategory(cat);
    if (loops.length === 0) continue;
    // Find a loop matching the target section
    const match = loops.find(l => l.section === targetSection && !l.active);
    if (match) {
      engine.setActiveLoop(cat, match.index);
    } else {
      console.log(`swapLoopsToSection: no "${targetSection}" loop for ${cat}, keeping current`);
    }
  }
}

function handleArcComplete() {
  setStatus(DEBUG ? 'Arc complete' : 'Journey complete');
  if (phaseIndicator) phaseIndicator.textContent = DEBUG ? 'COMPLETE' : 'Journey complete';
  // Fade all to silence over ~8 bars
  const fadeDur = engine.getBarDuration() * 8;
  engine.fadeOutAll(fadeDur);
  // Stop after fade (store ID so manual stop can cancel)
  arcFadeTimeout = setTimeout(() => {
    arcFadeTimeout = null;
    engine.stop();
    playing = false;
    arc = null;
    updatePlayButton();
    setStatus(DEBUG ? 'Arc complete — click Play to go again' : 'Click Start to go again');
  }, fadeDur * 1000 + 500);
}

let _lastPhaseIndicatorPct = -1;
function updatePhaseIndicator(phase) {
  if (!phaseIndicator) return;
  const pct = Math.round(phase.progress * 100);
  // Only update DOM when visible progress changes
  if (pct === _lastPhaseIndicatorPct) return;
  _lastPhaseIndicatorPct = pct;
  phaseIndicator.textContent = DEBUG
    ? `${phase.id.toUpperCase()} ${bar(phase.progress, 20)} ${pct}%  (${phase.index + 1}/${phase.totalPhases})`
    : (PHASE_LABELS[phase.id] || phase.id);
}

// --- Init: apply the debug vs guided surface ---
if (DEBUG) {
  document.body.classList.add('debug');
  if (modeToggle) modeToggle.style.display = 'none';
  if (modeSelect) { modeSelect.style.display = ''; modeSelect.value = mode; }
} else {
  document.body.classList.add('guided');
  if (modeSelect) modeSelect.style.display = 'none';
  if (loopGridEl) loopGridEl.style.display = 'none';
  syncModeToggle();
}

picker.load();
