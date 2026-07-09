/**
 * Song picker — fetches catalog and renders song cards.
 */

// Placeholder written by the backfill when a real value could not be verified
// (see scripts/backfill_catalog_metadata.py). We never surface it to users.
const NEEDS_REVIEW = 'UNKNOWN - NEEDS REVIEW';

function isReal(value) {
  return typeof value === 'string' && value.trim() && value !== NEEDS_REVIEW;
}

// Format a duration in seconds as m:ss (e.g. 189.75 -> "3:09").
function formatDuration(seconds) {
  if (typeof seconds !== 'number' || !isFinite(seconds)) return '';
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export class SongPicker {
  constructor(container, apiUrl) {
    this.container = container;
    this.apiUrl = apiUrl;
    this.onSongSelected = null; // callback(songMetadata), may be async and may throw
    this.onError = null;        // callback(message) — surface load failures to the user
  }

  async load() {
    this.container.innerHTML = '<p class="loading">Loading songs...</p>';

    try {
      const res = await fetch(`${this.apiUrl}/api/library`);
      if (!res.ok) throw new Error(`Library returned ${res.status}`);
      const catalog = await res.json();

      if (catalog.length === 0) {
        this.container.innerHTML = '<p class="empty">No songs in library yet.</p>';
        return;
      }

      this.container.innerHTML = '';
      for (const song of catalog) {
        const card = document.createElement('div');
        card.className = 'song-card';
        card.innerHTML = this._cardHtml(song);
        card.addEventListener('click', () => this._select(song.slug, card));
        this.container.appendChild(card);
      }
    } catch (err) {
      this.container.innerHTML = `<p class="error">Failed to load songs: ${err.message}</p>`;
    }
  }

  _cardHtml(song) {
    const duration = formatDuration(song.duration);
    const artistLine = isReal(song.artist)
      ? `<div class="song-artist">${escapeHtml(song.artist)}</div>`
      : '';
    // License is legally sensitive; only show a verified value, never the
    // "needs review" placeholder (see issues #11/#22).
    const licenseLine = isReal(song.license)
      ? `<div class="song-license">${escapeHtml(song.license)}</div>`
      : '';
    const meta = [`${song.bpm} BPM`, `${song.total_loops} loops`];
    if (duration) meta.push(duration);

    return `
      <h3>${escapeHtml(song.name)}</h3>
      ${artistLine}
      <div class="song-meta">
        ${meta.map((m) => `<span>${escapeHtml(m)}</span>`).join('')}
      </div>
      <div class="song-sections">${escapeHtml(song.sections.join(' · '))}</div>
      ${licenseLine}
    `;
  }

  async _select(slug, card) {
    // Highlight selected card
    this.container.querySelectorAll('.song-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');

    try {
      const res = await fetch(`${this.apiUrl}/api/library/${slug}`);
      if (!res.ok) throw new Error(`Song returned ${res.status}`);
      const metadata = await res.json();
      // Await the handler so a downstream load failure (dead/missing loops)
      // propagates here and the card gets deselected — no fake success. See #16.
      if (this.onSongSelected) await this.onSongSelected(metadata);
    } catch (err) {
      console.error('Failed to load song:', err);
      // Keep state honest: undo the selection so the UI never shows a song as
      // chosen when it could not actually load.
      card.classList.remove('selected');
      if (this.onError) this.onError(`Could not load that song: ${err.message}`);
    }
  }
}
