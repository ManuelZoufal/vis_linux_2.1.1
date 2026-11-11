async function fetchLogs() {
    const response = await fetch('/api/logs');
    const data = await response.json();
    const logsTable = document.getElementById('logs-table').getElementsByTagName('tbody')[0];
    logsTable.replaceChildren();
    data.logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.appendChild(createCell(log.timestamp));
        tr.appendChild(createCell(log.message));
        logsTable.appendChild(tr);
    });
}

const THREAD_STATE_LABELS = {
    ok: 'OK',
    error: 'Fehler',
    stale: 'Keine Rückmeldung',
    idle: 'Keine Zählung',
    starting: 'Startet',
    stopped: 'Beendet',
    not_started: 'Nicht gestartet'
};

function createCell(text) {
    const td = document.createElement('td');
    td.textContent = text;
    return td;
}

function setThreadSummary(text, offline) {
    const summary = document.getElementById('thread-summary');
    summary.textContent = text;
    summary.classList.toggle('thread-summary-offline', offline);
}

async function fetchThreadStatus() {
    let data;
    try {
        const response = await fetch('/api/thread_status');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
    } catch (error) {
        setThreadSummary(`Keine Verbindung zum Server (${error.message}) – Anzeige ist nicht aktuell`, true);
        return;
    }

    const tbody = document.getElementById('thread-table').getElementsByTagName('tbody')[0];
    tbody.replaceChildren();
    data.threads.forEach(thread => {
        const tr = document.createElement('tr');
        tr.appendChild(createCell(thread.label));

        const stateCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = `thread-badge state-${thread.state}`;
        badge.textContent = THREAD_STATE_LABELS[thread.state] || thread.state;
        stateCell.appendChild(badge);
        tr.appendChild(stateCell);

        tr.appendChild(createCell(thread.last_success || '–'));
        tr.appendChild(createCell(thread.run_count));
        tr.appendChild(createCell(thread.error_count));

        const errorCell = document.createElement('td');
        if (thread.last_error) {
            const time = document.createElement('span');
            time.className = 'thread-error-time';
            time.textContent = thread.last_error_time;
            errorCell.appendChild(time);
            errorCell.appendChild(document.createTextNode(thread.last_error));
        } else {
            errorCell.textContent = '–';
        }
        tr.appendChild(errorCell);
        tbody.appendChild(tr);
    });

    const okCount = data.threads.filter(thread => thread.state === 'ok').length;
    // Sensors without counting are neither OK nor faulty, so they are counted separately
    const idleCount = data.threads.filter(thread => thread.state === 'idle').length;
    setThreadSummary(`${okCount} von ${data.threads.length - idleCount} Threads OK`
        + (idleCount ? `, ${idleCount} ohne Zählung` : '') + ` – Stand ${data.server_time}`, false);

    const certificate = document.getElementById('certificate-status');
    if (certificate && data.certificate) {
        certificate.textContent = data.certificate.message;
        certificate.classList.toggle('thread-summary-offline', data.certificate.state !== 'ok');
    }
}

function exportLogs() {
    window.location.href = '/api/logs/export';
}

function exportThreadStatus() {
    window.location.href = '/api/thread_status/export';
}

fetchLogs();
setInterval(fetchLogs, 10000);  // Refresh logs every 10 seconds

// ── Event log ──

function eventQuery() {
    const params = new URLSearchParams({ hours: document.getElementById('event-hours').value });
    const source = document.getElementById('event-source').value;
    if (source) params.set('source', source);
    return params.toString();
}

async function fetchEvents() {
    const summary = document.getElementById('event-summary');
    let data;
    try {
        const response = await fetch('/api/events?' + eventQuery());
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
    } catch (error) {
        summary.textContent = `Ereignisse konnten nicht geladen werden (${error.message})`;
        summary.classList.add('thread-summary-offline');
        return;
    }
    summary.classList.remove('thread-summary-offline');

    // Fill the source filter once, keeping the current selection
    const sourceSelect = document.getElementById('event-source');
    if (sourceSelect.options.length <= 1) {
        data.sources.forEach(source => {
            const option = document.createElement('option');
            option.value = source.name;
            option.textContent = source.label;
            sourceSelect.appendChild(option);
        });
        // The detail log offers the same sensors as scope
        const scopeSelect = document.getElementById('detail-scope');
        data.sources.filter(source => source.name.startsWith('SensorThread-')).forEach(source => {
            const option = document.createElement('option');
            option.value = 'sensor:' + source.name.slice('SensorThread-'.length);
            option.textContent = 'nur ' + source.label;
            scopeSelect.appendChild(option);
        });
    }

    const tbody = document.getElementById('event-table').getElementsByTagName('tbody')[0];
    tbody.replaceChildren();
    data.events.forEach(entry => {
        const tr = document.createElement('tr');
        tr.appendChild(createCell(entry.ts));
        const kindCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = `event-kind kind-${entry.kind}`;
        badge.textContent = entry.kind_label;
        kindCell.appendChild(badge);
        tr.appendChild(kindCell);
        tr.appendChild(createCell(entry.label));
        tr.appendChild(createCell(entry.message));
        tbody.appendChild(tr);
    });
    summary.textContent = data.events.length
        ? `${data.events.length} Ereignisse${data.truncated ? ' (nur die neuesten werden angezeigt, der Export enthält alle)' : ''}`
        : 'Keine Ereignisse im gewählten Zeitraum.';
}

function exportEvents() {
    window.location.href = '/api/events/export?' + eventQuery();
}

// ── Detail log ──

function formatBytes(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' kB';
    return bytes + ' B';
}

async function fetchDetailLog() {
    const status = document.getElementById('detail-status');
    let data;
    try {
        const response = await fetch('/api/detail_log');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
    } catch (error) {
        status.textContent = `Status konnte nicht geladen werden (${error.message})`;
        return;
    }
    const limit = formatBytes(data.max_bytes);
    if (!data.available) {
        status.textContent = 'Nicht verfügbar: Das Protokollverzeichnis ist nicht beschreibbar.';
    } else if (data.active) {
        status.textContent = `Läuft seit ${data.started} bis ${data.until} – Umfang ${data.scope}, bisher ${formatBytes(data.bytes)} von höchstens ${limit}.`;
    } else {
        status.textContent = `Nicht aktiv${data.last_stop_reason ? ' (zuletzt beendet: ' + data.last_stop_reason + ')' : ''}. `
            + `Größengrenze ${limit} je Datei, die letzten ${data.keep_files} Dateien bleiben erhalten.`;
    }
    status.classList.toggle('thread-summary-offline', data.active);
    document.getElementById('detail-stop').style.display = data.active ? '' : 'none';

    const tbody = document.getElementById('detail-table').getElementsByTagName('tbody')[0];
    tbody.replaceChildren();
    data.files.forEach(file => {
        const tr = document.createElement('tr');
        tr.appendChild(createCell(file.name + (file.name === data.file ? ' (läuft)' : '')));
        tr.appendChild(createCell(formatBytes(file.bytes)));
        tr.appendChild(createCell(file.modified));
        const actions = document.createElement('td');
        const download = document.createElement('button');
        download.className = 'button button-small';
        download.textContent = 'Herunterladen';
        download.addEventListener('click', () => { window.location.href = '/api/detail_log/files/' + encodeURIComponent(file.name); });
        actions.appendChild(download);
        if (file.name !== data.file) {
            const remove = document.createElement('button');
            remove.className = 'button button-small button-danger';
            remove.textContent = 'Löschen';
            remove.addEventListener('click', () => deleteDetailFile(file.name));
            actions.appendChild(remove);
        }
        tr.appendChild(actions);
        tbody.appendChild(tr);
    });
}

async function startDetailLog() {
    const response = await fetch('/api/detail_log/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            minutes: Number(document.getElementById('detail-minutes').value),
            scope: document.getElementById('detail-scope').value
        })
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try { message = (await response.json()).message || message; } catch (_) {}
        alert('Detail-Protokoll konnte nicht gestartet werden: ' + message);
    }
    fetchDetailLog();
    fetchEvents();
}

async function stopDetailLog() {
    await fetch('/api/detail_log/stop', { method: 'POST' });
    fetchDetailLog();
    fetchEvents();
}

async function deleteDetailFile(name) {
    if (!confirm(`Datei ${name} wirklich löschen?`)) return;
    const response = await fetch('/api/detail_log/files/' + encodeURIComponent(name), { method: 'DELETE' });
    if (!response.ok) alert('Die Datei konnte nicht gelöscht werden.');
    fetchDetailLog();
}

// Live thread status, only rendered for administrators
if (document.getElementById('thread-table')) {
    fetchThreadStatus();
    setInterval(fetchThreadStatus, 2000);  // Refresh thread status every 2 seconds
}

if (document.getElementById('event-table')) {
    fetchEvents();
    setInterval(fetchEvents, 30000);  // Refresh the event log every 30 seconds
    fetchDetailLog();
    setInterval(fetchDetailLog, 10000);  // Refresh the detail log status every 10 seconds
}
