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
function setStatus(msg) { if (status) status.textContent = msg; }

// Wire up song selection
picker.onSongSelected = async (metadata) => {
  setStatus(`Loading ${metadata.name}...`);

  engine.onLoadProgress = (loaded, total) => {
    setStatus(`Loading loops: ${loaded}/${total}`);
  };

  await engine.load(metadata, API_URL);

  grid.render(metadata);
  grid.onTrackToggle = (filename, muted) => {
    engine.setTrackMuted(filename, muted);
  };

  setStatus(`${metadata.name} — ${metadata.bpm} BPM — Click play to start`);
  document.getElementById('play-btn').disabled = false;
};

// Play button (Tone.js requires user gesture to start AudioContext)
document.getElementById('play-btn').addEventListener('click', async () => {
  await Tone.start();
  engine.start();

  // Set all categories to audible
  for (const cat of ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent']) {
    engine.setCategoryVolume(cat, -8);
  }

  setStatus('Playing');
  document.getElementById('play-btn').textContent = 'Stop';
  document.getElementById('play-btn').onclick = () => {
    engine.stop();
    setStatus('Stopped');
    document.getElementById('play-btn').textContent = 'Play';
    document.getElementById('play-btn').onclick = async () => {
      await Tone.start();
      engine.start();
      for (const cat of ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent']) {
        engine.setCategoryVolume(cat, -8);
      }
      setStatus('Playing');
    };
  };
});

// Load catalog on startup
picker.load();
