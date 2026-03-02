/**
 * Song Blender — main app orchestration.
 */

import { AudioEngine } from './audio-engine.js';
import { SongPicker } from './song-picker.js';
import { LoopGrid } from './loop-grid.js';

const API_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://song-blender-api-production.up.railway.app';

const engine = new AudioEngine();
const picker = new SongPicker(document.getElementById('song-picker'), API_URL);
const grid = new LoopGrid(document.getElementById('loop-grid'));

// Status display
const status = document.getElementById('status');
const playBtn = document.getElementById('play-btn');
let playing = false;
let songLoaded = false;

function setStatus(msg) { if (status) status.textContent = msg; }

function updatePlayButton() {
  playBtn.disabled = !songLoaded;
  playBtn.textContent = playing ? 'Stop' : 'Play';
}

// Wire up song selection
picker.onSongSelected = async (metadata) => {
  // Stop current playback before loading new song
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

  await engine.load(metadata, API_URL);

  grid.render(metadata);
  grid.onTrackToggle = (filename, muted) => {
    engine.setTrackMuted(filename, muted);
  };

  songLoaded = true;
  updatePlayButton();
  setStatus(`${metadata.name} — ${metadata.bpm} BPM — Click Play to start`);
};

// Single play/stop handler
playBtn.addEventListener('click', async () => {
  if (!songLoaded) return;

  if (playing) {
    engine.stop();
    playing = false;
    setStatus('Stopped');
  } else {
    await Tone.start();
    engine.start();
    // Set all categories to audible
    for (const cat of ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent']) {
      engine.setCategoryVolume(cat, -8);
    }
    playing = true;
    setStatus('Playing');
  }
  updatePlayButton();
});

// Load catalog on startup
picker.load();
