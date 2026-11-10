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
