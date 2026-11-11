// Tile view of all groups. Every tile shows the real display page of its group,
// scaled down, so the preview always looks like the screen at the entrance.

// The display is laid out for a full HD screen; the preview renders it at this
// size and shrinks it to the width of the tile
const PREVIEW_WIDTH = 1920;
const PREVIEW_HEIGHT = 1080;
const REFRESH_MS = 5000;

const tiles = new Map();  // group_id -> { tile, name, info, badge }

function displayUrl(groupId) {
    return `/visualize/display?group_id=${encodeURIComponent(groupId)}`;
}

function createTile(group) {
    const tile = document.createElement('a');
    tile.className = 'group-tile';
    tile.href = displayUrl(group.group_id);

    const header = document.createElement('div');
    header.className = 'group-tile-header';
    const name = document.createElement('span');
    name.className = 'group-tile-name';
    const badge = document.createElement('span');
    badge.className = 'group-tile-badge';
    badge.textContent = 'Wartungsmodus';
    header.append(name, badge);

    // The preview is an inline frame that cannot be clicked or focused: the whole
    // tile is the link. It is only loaded when the tile comes into view.
    const preview = document.createElement('div');
    preview.className = 'group-tile-preview';
    const frame = document.createElement('iframe');
    frame.src = displayUrl(group.group_id);
    frame.width = PREVIEW_WIDTH;
    frame.height = PREVIEW_HEIGHT;
    frame.loading = 'lazy';
    frame.tabIndex = -1;
    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('scrolling', 'no');
    preview.appendChild(frame);

    const info = document.createElement('div');
    info.className = 'group-tile-info';

    tile.append(header, preview, info);
    scaleObserver.observe(preview);
    return { tile, name, info, badge };
}

function updateTile(entry, group) {
    // Names and texts are set as text, never as HTML
    entry.name.textContent = group.name;
    entry.info.textContent = `Maximale Belegung: ${group.max_occupancy}`;
    entry.badge.style.display = group.maintenance_mode ? '' : 'none';
    entry.tile.title = `Belegungsanzeige „${group.name}“ öffnen`;
}

// Shrink the full size frame to the width the tile currently has
const scaleObserver = new ResizeObserver(entries => {
    entries.forEach(entry => {
        const frame = entry.target.querySelector('iframe');
        if (frame) {
            frame.style.transform = `scale(${entry.contentRect.width / PREVIEW_WIDTH})`;
        }
    });
});

async function fetchGroupData() {
    const hint = document.getElementById('group-hint');
    let data;
    try {
        const response = await fetch('/api/get_data');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
    } catch (error) {
        hint.textContent = `Gruppen konnten nicht geladen werden (${error.message}).`;
        hint.style.display = '';
        return;
    }

    const container = document.getElementById('group-tiles');
    const groups = (data.groups || []).slice().sort(
        (a, b) => String(a.group_id).localeCompare(String(b.group_id), undefined, { numeric: true }));
    const seen = new Set();

    groups.forEach((group, index) => {
        const id = String(group.group_id);
        seen.add(id);
        // A tile is created once and then only updated: rebuilding it would reload its preview
        if (!tiles.has(id)) {
            tiles.set(id, createTile(group));
        }
        const entry = tiles.get(id);
        updateTile(entry, group);
        if (container.children[index] !== entry.tile) {
            container.insertBefore(entry.tile, container.children[index] || null);
        }
    });

    tiles.forEach((entry, id) => {
        if (!seen.has(id)) {
            scaleObserver.unobserve(entry.tile.querySelector('.group-tile-preview'));
            entry.tile.remove();
            tiles.delete(id);
        }
    });

    hint.textContent = 'Keine Gruppen vorhanden.';
    hint.style.display = groups.length ? 'none' : '';
}

fetchGroupData();
setInterval(fetchGroupData, REFRESH_MS);  // names, limits and the list of groups; the previews update themselves
