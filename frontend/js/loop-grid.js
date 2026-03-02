/**
 * Loop grid — visual representation of sections × categories with play/mute toggles.
 */

const CATEGORY_ORDER = ['groove', 'foundation', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent'];
const CATEGORY_LABELS = {
  groove: 'Groove', foundation: 'Foundation', bass: 'Bass',
  harmonic_bed: 'Harmony', hook: 'Hook', texture: 'Texture', accent: 'Accent',
};

export class LoopGrid {
  constructor(container) {
    this.container = container;
    this.onTrackToggle = null; // callback(filename, muted)
  }

  render(metadata) {
    this.container.innerHTML = '';

    // Get unique sections in order
    const sectionLabels = [];
    const seen = new Set();
    for (const s of metadata.sections) {
      const key = `${s.label}_${s.start}`;
      if (!seen.has(key)) {
        seen.add(key);
        sectionLabels.push({ label: s.label, start: s.start, end: s.end });
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
    for (const s of sectionLabels) {
      grid.appendChild(this._cell(s.label, 'grid-header'));
    }

    // Category rows
    for (const cat of presentCategories) {
      grid.appendChild(this._cell(CATEGORY_LABELS[cat] || cat, 'grid-label'));

      for (const section of sectionLabels) {
        const tracks = metadata.tracks.filter(t =>
          t.category === cat && t.section === section.label && t.selected
        );

        if (tracks.length === 0) {
          grid.appendChild(this._cell('', 'grid-cell empty'));
        } else {
          const cell = document.createElement('div');
          cell.className = 'grid-cell has-track';
          cell.dataset.active = 'true';
          cell.title = tracks.map(t => t.file).join(', ');

          const dot = document.createElement('div');
          dot.className = 'track-dot';
          cell.appendChild(dot);

          cell.addEventListener('click', () => {
            const active = cell.dataset.active === 'true';
            cell.dataset.active = String(!active);
            cell.classList.toggle('muted', active);
            for (const t of tracks) {
              if (this.onTrackToggle) this.onTrackToggle(t.file, active);
            }
          });

          grid.appendChild(cell);
        }
      }
    }

    this.container.appendChild(grid);
  }

  _cell(text, className) {
    const el = document.createElement('div');
    el.className = className;
    el.textContent = text;
    return el;
  }
}
