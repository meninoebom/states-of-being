/**
 * Song Blender — main app orchestration.
 */

import { AudioEngine } from './audio-engine.js';
import { SongPicker } from './song-picker.js';
import { LoopGrid } from './loop-grid.js';
import { MovementDetector } from './movement.js';
import { ReadingsEngine } from './readings.js';
import { applyMapping } from './mapping.js';

const API_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://song-blender-api-production.up.railway.app';

const engine = new AudioEngine();
const picker = new SongPicker(document.getElementById('song-picker'), API_URL);
const grid = new LoopGrid(document.getElementById('loop-grid'));
const detector = new MovementDetector();
const readings = new ReadingsEngine();

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

    // Dynamic import of MediaPipe
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
      numPoses: 1,
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
  const results = poseLandmarker.detectForVideo(video, now);

  if (results.landmarks && results.landmarks.length > 0) {
    const landmarks = results.landmarks[0];
    const qualities = detector.update(landmarks, now / 1000);
    const readingValues = readings.update(qualities);

    // Apply to audio (webcam or blend mode)
    if (playing && (mode === 'webcam' || mode === 'blend')) {
      applyMapping(readingValues, engine);
    }

    // Draw skeleton + update debug
    drawSkeleton(landmarks, readingValues);
    updateDebug(qualities, readingValues);
  }

  requestAnimationFrame(detectLoop);
}

// --- Skeleton drawing ---

// MediaPipe Pose connections (pairs of landmark indices)
const POSE_CONNECTIONS = [
  [11, 12], // shoulders
  [11, 13], [13, 15], // left arm
  [12, 14], [14, 16], // right arm
  [11, 23], [12, 24], // torso sides
  [23, 24], // hips
  [23, 25], [25, 27], // left leg
  [24, 26], [26, 28], // right leg
];

function drawSkeleton(landmarks, readingValues) {
  if (!skeletonCtx || !skeletonCanvas || skeletonCanvas.style.display === 'none') return;

  const W = skeletonCanvas.width = 200;
  const H = skeletonCanvas.height = 150;
  skeletonCtx.clearRect(0, 0, W, H);

  // Pick color from dominant active reading
  const READING_COLORS = { flowing: '#6ef', agitated: '#f66', stillness: '#668', reaching: '#fa4' };
  let color = '#8af';
  let maxVal = 0;
  for (const r of readingValues) {
    if (r.active && r.value > maxVal) {
      maxVal = r.value;
      color = READING_COLORS[r.id] || color;
    }
  }

  // Draw connections
  skeletonCtx.strokeStyle = color;
  skeletonCtx.lineWidth = 2;
  skeletonCtx.lineCap = 'round';

  for (const [a, b] of POSE_CONNECTIONS) {
    const la = landmarks[a], lb = landmarks[b];
    if (la.visibility > 0.3 && lb.visibility > 0.3) {
      skeletonCtx.beginPath();
      // Mirror x so it feels like a mirror (webcam is flipped)
      skeletonCtx.moveTo((1 - la.x) * W, la.y * H);
      skeletonCtx.lineTo((1 - lb.x) * W, lb.y * H);
      skeletonCtx.stroke();
    }
  }

  // Draw joints
  skeletonCtx.fillStyle = color;
  const joints = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
  for (const i of joints) {
    const lm = landmarks[i];
    if (lm.visibility > 0.3) {
      skeletonCtx.beginPath();
      skeletonCtx.arc((1 - lm.x) * W, lm.y * H, 3, 0, Math.PI * 2);
      skeletonCtx.fill();
    }
  }

  // Head (nose)
  const nose = landmarks[0];
  if (nose.visibility > 0.3) {
    skeletonCtx.beginPath();
    skeletonCtx.arc((1 - nose.x) * W, nose.y * H, 5, 0, Math.PI * 2);
    skeletonCtx.fill();
  }
}

// --- Debug overlay ---

function updateDebug(qualities, readingValues) {
  if (!debugPanel || debugPanel.style.display === 'none') return;

  const qLines = Object.entries(qualities)
    .filter(([k]) => !k.startsWith('_'))
    .map(([k, v]) => `${k.padEnd(14)} ${bar(v)} ${v.toFixed(2)}`)
    .join('\n');

  const rLines = readingValues
    .map(r => `${r.id.padEnd(14)} ${bar(r.value)} ${r.value.toFixed(2)} ${r.active ? '●' : '○'}`)
    .join('\n');

  debugPanel.textContent = `── qualities ──\n${qLines}\n\n── readings ──\n${rLines}`;
}

function bar(v) {
  const width = 16;
  const filled = Math.round(v * width);
  return '█'.repeat(filled) + '░'.repeat(width - filled);
}

// --- Init ---
picker.load();
