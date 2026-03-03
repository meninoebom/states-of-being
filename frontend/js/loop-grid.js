/**
 * Loop grid — visual representation of sections × categories with play/mute toggles.
 *
 * Rows = categories (groove, bass, harmony, etc.)
 * Columns = song sections (intro, verse, chorus, etc.)
 * Each filled cell = a loop. Click to mute/unmute.
 * Lit (blue) = playing. Dim = muted.
 */

import { CATEGORY_ORDER, CATEGORY_LABELS } from './constants.js';

export class LoopGrid {
  constructor(container) {
    this.container = container;
    this.onTrackToggle = null; // callback(filename, muted)
  }

  render(metadata) {
    this.container.innerHTML = '';

    // Hint text
    const hint = document.createElement('p');
    hint.className = 'grid-hint';
    hint.textContent = 'Click cells to mute/unmute loops. Blue = playing, dim = muted.';
    this.container.appendChild(hint);

    // Deduplicate sections, preserving order
    const sectionLabels = [];
    const seen = new Set();
    for (const s of metadata.sections) {
      if (!seen.has(s.label)) {
        seen.add(s.label);
        sectionLabels.push(s.label);
      }
    }

    // Get categories present in this song
    const presentCategories = CATEGORY_ORDER.filter(cat =>
      metadata.tracks.some(t => t.category === cat)
    );

    // Build grid
    const grid = document.createElement('div');
    grid.className = 'loop-grid';
    grid.style.gridTemplateColumns = `120px repeat(${sectionLabels.length}, 1fr)`;

    // Header row
    grid.appendChild(this._cell('', 'grid-header grid-corner'));
    for (const label of sectionLabels) {
      grid.appendChild(this._cell(label, 'grid-header'));
    }

    // Category rows
    for (const cat of presentCategories) {
      const label = this._cell(CATEGORY_LABELS[cat] || cat, 'grid-label');
      label.dataset.category = cat;
      grid.appendChild(label);

      for (const sectionLabel of sectionLabels) {
        const tracks = metadata.tracks.filter(t =>
          t.category === cat && t.section === sectionLabel && t.selected
        );

        if (tracks.length === 0) {
          const emptyCell = this._cell('', 'grid-cell empty');
          emptyCell.dataset.category = cat;
          grid.appendChild(emptyCell);
        } else {
          const cell = document.createElement('div');
          cell.className = 'grid-cell has-track active';
          cell.dataset.category = cat;
          cell.title = `${CATEGORY_LABELS[cat] || cat} — ${sectionLabel}\n${tracks.map(t => t.file).join('\n')}\nClick to mute/unmute`;

          const dot = document.createElement('div');
          dot.className = 'track-dot';
          cell.appendChild(dot);

          let active = true;
          cell.addEventListener('click', () => {
            active = !active;
            cell.classList.toggle('active', active);
            cell.classList.toggle('muted', !active);
            for (const t of tracks) {
              if (this.onTrackToggle) this.onTrackToggle(t.file, !active);
            }
          });

          grid.appendChild(cell);
        }
      }
    }

    this.container.appendChild(grid);
  }

  /** Dim categories not in the allowed list (for arc mode phase gating). */
  setAvailableCategories(categories) {
    if (!this.container) return;
    this.container.querySelectorAll('[data-category]').forEach(el => {
      el.classList.toggle('phase-unavailable', !categories.includes(el.dataset.category));
    });
  }

  _cell(text, className) {
    const el = document.createElement('div');
    el.className = className;
    el.textContent = text;
    return el;
  }
}
