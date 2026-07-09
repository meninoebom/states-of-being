/**
 * Song picker — fetches catalog and renders song cards.
 */

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
        card.innerHTML = `
          <h3>${song.name}</h3>
          <div class="song-meta">
            <span>${song.bpm} BPM</span>
            <span>${song.total_loops} loops</span>
          </div>
          <div class="song-sections">${song.sections.join(' · ')}</div>
        `;
        card.addEventListener('click', () => this._select(song.slug, card));
        this.container.appendChild(card);
      }
    } catch (err) {
      this.container.innerHTML = `<p class="error">Failed to load songs: ${err.message}</p>`;
    }
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
