async function fetchLogs() {
    const response = await fetch('/api/logs');
    const data = await response.json();
    const logsTable = document.getElementById('logs-table').getElementsByTagName('tbody')[0];
    logsTable.innerHTML = '';
    data.logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${log.timestamp}</td>
            <td>${log.message}</td>
        `;
        logsTable.appendChild(tr);
    });
}

async function fetchDebugInfo() {
    const response = await fetch('/api/debug_info');
    const data = await response.json();
    const debugTable = document.getElementById('debug-table').getElementsByTagName('tbody')[0];
    debugTable.innerHTML = '';
    data.debug_info.forEach(info => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${info.timestamp}</td>
            <td>${info.message}</td>
        `;
        debugTable.appendChild(tr);
    });
}

const THREAD_STATE_LABELS = {
    ok: 'OK',
    error: 'Fehler',
    stale: 'Keine Rückmeldung',
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
    setThreadSummary(`${okCount} von ${data.threads.length} Threads OK – Stand ${data.server_time}`, false);
}

function exportLogs() {
    window.location.href = '/api/logs/export';
}

function exportDebugInfo() {
    window.location.href = '/api/debug_info/export';
}

fetchLogs();
setInterval(fetchLogs, 10000);  // Refresh logs every 10 seconds

// Fetch debug info if the debug table exists
if (document.getElementById('debug-table')) {
    fetchDebugInfo();
    setInterval(fetchDebugInfo, 10000);  // Refresh debug info every 10 seconds
}

// Live thread status, only rendered for administrators
if (document.getElementById('thread-table')) {
    fetchThreadStatus();
    setInterval(fetchThreadStatus, 2000);  // Refresh thread status every 2 seconds
}
