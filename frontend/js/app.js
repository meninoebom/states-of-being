/**
 * Song Blender — main app orchestration.
 * Supports 0, 1, or 2 bodies via auto-detection (no mode toggle needed).
 */

import { AudioEngine } from './audio-engine.js';
import { SongPicker } from './song-picker.js';
import { LoopGrid } from './loop-grid.js';
import { MovementDetector, computeRelational } from './movement.js';
import { ReadingsEngine, RELATIONAL_READINGS } from './readings.js';
import { applyMapping } from './mapping.js';

const API_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://song-blender-api-production.up.railway.app';

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
const debugPanel = document.getElementById('debug-panel');
let playing = false;
let songLoaded = false;
let mode = 'manual'; // 'manual' | 'webcam' | 'blend'

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
  playBtn.textContent = playing ? 'Stop' : 'Play';
}

// --- Song selection ---
picker.onSongSelected = async (metadata) => {
  if (playing) {
    engine.stop();
    playing = false;
  }

  songLoaded = false;
  updatePlayButton();
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
  setStatus(`${metadata.name} — ${metadata.bpm} BPM — Click Play to start`);
};

// --- Play/Stop ---
playBtn.addEventListener('click', async () => {
  if (!songLoaded) return;

  if (playing) {
    engine.stop();
    playing = false;
    setStatus('Stopped');
  } else {
    await Tone.start();
    engine.start();

    // In manual mode, set everything audible. In webcam/blend, let mapping drive it.
    if (mode === 'manual') {
      for (const cat of ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent']) {
        engine.setCategoryVolume(cat, -8);
      }
    }

    playing = true;
    setStatus('Playing');
  }
  updatePlayButton();
});

// --- Mode switching ---
if (modeSelect) {
  modeSelect.addEventListener('change', async (e) => {
    mode = e.target.value;

    if (mode === 'webcam' || mode === 'blend') {
      await ensureWebcam();
      if (!webcamRunning) {
        mode = 'manual';
        modeSelect.value = 'manual';
        return;
      }
    }

    if (mode === 'manual') {
      stopWebcam();
      if (debugPanel) debugPanel.style.display = 'none';
      if (skeletonCanvas) skeletonCanvas.style.display = 'none';
      // Restore manual volumes
      if (playing) {
        for (const cat of ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent']) {
          engine.setCategoryVolume(cat, -8);
        }
      }
    } else {
      if (debugPanel) debugPanel.style.display = 'block';
      if (skeletonCanvas) skeletonCanvas.style.display = 'block';
    }
  });
}

// --- Webcam / MediaPipe ---

async function ensureWebcam() {
  if (webcamRunning) return;

  try {
    setStatus('Starting webcam...');

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

    video = document.getElementById('webcam-video');
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: 'user' },
      audio: false,
    });
    video.srcObject = stream;
    await new Promise(r => { video.onloadedmetadata = r; });
    await video.play();

    webcamRunning = true;
    setStatus('Webcam active');
    detectLoop();
  } catch (err) {
    console.error('Webcam init failed:', err);
    setStatus(`Webcam failed: ${err.message}`);
  }
}

function stopWebcam() {
  webcamRunning = false;
  if (video && video.srcObject) {
    video.srcObject.getTracks().forEach(t => t.stop());
    video.srcObject = null;
  }
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
    if (playing && (mode === 'webcam' || mode === 'blend')) {
      applyMapping(finalReadings, engine);
    }

    // Draw skeletons + debug
    drawSkeletons(results.landmarks, bodyCount, finalReadings);
    updateDebug(allQualities, finalReadings, relQualities);
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

function bar(v) {
  const width = 16;
  const filled = Math.round(v * width);
  return '█'.repeat(filled) + '░'.repeat(width - filled);
}

// --- Init ---
picker.load();
