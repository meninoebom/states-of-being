/**
 * Live tuning panel — developer-only (rendered behind the ?debug=1 gate).
 *
 * Exposes the taste-layer constants as sliders that can be adjusted while a
 * dancer moves, so movement-to-music mappings get tuned in a live session
 * instead of an edit-reload loop.
 *
 * Why in-place mutation works: ReadingsEngine keeps `this.configs = configs` by
 * reference, and every engine shares the module-level DEFAULT_READINGS /
 * RELATIONAL_READINGS arrays. applyMapping reads VOLUME_MAP every frame. So
 * mutating the same objects the per-frame loop already reads is all that's
 * needed — no engine reconstruction, no config snapshotting to defeat.
 *
 * The "Copy config JSON" button captures a good mid-session configuration so
 * the values can be pasted back into the code constants and committed.
 */

import { DEFAULT_READINGS, RELATIONAL_READINGS } from './readings.js';
import { VOLUME_MAP, QUIET_VOLUMES } from './mapping.js';

/** Format a numeric value compactly: integers plain, weights to 2 decimals. */
function fmt(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/**
 * Build one slider row that mutates a target object's key in place.
 * @param {{label:string,min:number,max:number,step:number,value:number,onInput:(v:number)=>void}} opts
 */
function sliderRow({ label, min, max, step, value, onInput }) {
  const row = document.createElement('label');
  row.className = 'tune-row';

  const name = document.createElement('span');
  name.className = 'tune-label';
  name.textContent = label;

  const input = document.createElement('input');
  input.type = 'range';
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);

  const out = document.createElement('span');
  out.className = 'tune-val';
  out.textContent = fmt(value);

  input.addEventListener('input', () => {
    const v = parseFloat(input.value);
    out.textContent = fmt(v);
    onInput(v);
  });

  row.append(name, input, out);
  return row;
}

/** Collapsible group of rows under a titled <details>. */
function group(title) {
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = title;
  details.appendChild(summary);
  return details;
}

/** A labelled sub-block within a group (one reading id, one volume set). */
function subGroup(parent, title) {
  const block = document.createElement('div');
  block.className = 'tune-block';
  const h = document.createElement('div');
  h.className = 'tune-block-title';
  h.textContent = title;
  block.appendChild(h);
  parent.appendChild(block);
  return block;
}

/** Sliders for reading configs: mix weights, inverted mix weights, gate thresholds. */
function buildReadingsSection(title, configs) {
  const details = group(title);
  for (const config of configs) {
    const block = subGroup(details, config.id);

    for (const q of Object.keys(config.mix)) {
      block.appendChild(sliderRow({
        label: `mix ${q}`, min: 0, max: 1, step: 0.05, value: config.mix[q],
        onInput: (v) => { config.mix[q] = v; },
      }));
    }

    if (config._invertInMix) {
      for (const q of Object.keys(config._invertInMix)) {
        block.appendChild(sliderRow({
          label: `inv ${q}`, min: 0, max: 1, step: 0.05, value: config._invertInMix[q],
          onInput: (v) => { config._invertInMix[q] = v; },
        }));
      }
    }

    if (config.gate) {
      for (const q of Object.keys(config.gate)) {
        const cond = config.gate[q];
        for (const dir of Object.keys(cond)) { // 'above' and/or 'below'
          block.appendChild(sliderRow({
            label: `gate ${q} ${dir}`, min: 0, max: 1, step: 0.01, value: cond[dir],
            onInput: (v) => { cond[dir] = v; },
          }));
        }
      }
    }
  }
  return details;
}

/** Sliders for per-reading volume targets (dB). */
function buildVolumeSection(title, volumeMap) {
  const details = group(title);
  for (const id of Object.keys(volumeMap)) {
    const block = subGroup(details, id);
    const map = volumeMap[id];
    for (const cat of Object.keys(map)) {
      block.appendChild(sliderRow({
        label: cat, min: -60, max: 0, step: 1, value: map[cat],
        onInput: (v) => { map[cat] = v; },
      }));
    }
  }
  return details;
}

/** "Copy config JSON" — capture the current live config for pasting back to code. */
function buildCopyButton() {
  const btn = document.createElement('button');
  btn.className = 'tune-copy';
  btn.type = 'button';
  const defaultLabel = 'Copy config JSON';
  btn.textContent = defaultLabel;

  btn.addEventListener('click', async () => {
    const json = JSON.stringify(
      { DEFAULT_READINGS, RELATIONAL_READINGS, VOLUME_MAP, QUIET_VOLUMES },
      null,
      2,
    );
    try {
      await navigator.clipboard.writeText(json);
      btn.textContent = 'Copied!';
    } catch {
      // Clipboard can be blocked (no user gesture, insecure context). Log so the
      // config is still recoverable rather than lost.
      console.log(json);
      btn.textContent = 'Copied to console';
    }
    setTimeout(() => { btn.textContent = defaultLabel; }, 1500);
  });

  return btn;
}

/**
 * Render the tuning panel into `panel`. Idempotent: clears any prior render.
 * @param {HTMLElement} panel
 */
export function initTuningPanel(panel) {
  if (!panel) return;
  panel.innerHTML = '';

  const heading = document.createElement('div');
  heading.className = 'tune-heading';
  heading.textContent = 'Live tuning';
  panel.appendChild(heading);

  panel.appendChild(buildReadingsSection('Readings (mix / gate)', DEFAULT_READINGS));
  panel.appendChild(buildReadingsSection('Relational readings', RELATIONAL_READINGS));
  panel.appendChild(buildVolumeSection('Volume targets (dB)', VOLUME_MAP));
  // Quiet baseline is one more volume set; reuse the volume section builder.
  panel.appendChild(buildVolumeSection('Quiet baseline (dB)', { baseline: QUIET_VOLUMES }));
  panel.appendChild(buildCopyButton());
}
