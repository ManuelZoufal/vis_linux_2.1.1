// Page "Einstellungen": certificate and verbose server log

async function fetchCertificate() {
    const status = document.getElementById('certificate-status');
    try {
        const response = await fetch('/api/thread_status');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const certificate = (await response.json()).certificate;
        status.textContent = certificate.message;
        status.classList.toggle('thread-summary-offline', certificate.state !== 'ok');
        document.getElementById('certificate-renewal').textContent = certificate.renew_message || '';
    } catch (error) {
        status.textContent = `Status konnte nicht geladen werden (${error.message})`;
        status.classList.add('thread-summary-offline');
    }
}

async function renewCertificate() {
    const method = document.getElementById('certificate-renewal').textContent.includes('selbstsigniert')
        ? 'Das neue Zertifikat ist selbstsigniert: Browser und Anzeigegeräte zeigen eine Warnung, bis es dort als vertrauenswürdig hinterlegt ist.'
        : 'Das neue Zertifikat wird von der eigenen CA ausgestellt.';
    if (!confirm('Jetzt einen neuen Schlüssel und ein neues Zertifikat erstellen und sofort verwenden?\n\n'
        + method + '\nDie bisherigen Dateien bleiben als *.alt erhalten.')) {
        return;
    }
    const button = document.getElementById('certificate-renew-button');
    button.disabled = true;
    try {
        const response = await fetch('/api/certificate/renew', { method: 'POST' });
        const data = await response.json();
        alert(response.ok ? 'Zertifikat erneuert. ' + data.certificate.message : (data.error || 'Fehler ' + response.status));
    } catch (error) {
        // The connection of this very request can be affected by the change of the certificate
        alert('Keine Antwort erhalten. Bitte die Seite neu laden und den Zertifikatsstatus prüfen.');
    }
    button.disabled = false;
    fetchCertificate();
}

// ── Verbose server log ──

async function fetchServerLog() {
    const status = document.getElementById('server-log-status');
    let data;
    try {
        const response = await fetch('/api/server_log');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
    } catch (error) {
        status.textContent = `Status konnte nicht geladen werden (${error.message})`;
        return;
    }
    if (data.always) {
        status.textContent = 'Dauerhaft eingeschaltet, weil APP_DEBUG in der .env gesetzt ist.';
    } else if (data.active) {
        status.textContent = `Eingeschaltet seit ${data.started}, schaltet sich um ${data.until} selbst ab.`;
    } else {
        status.textContent = `Ausgeschaltet${data.last_stop_reason ? ' (zuletzt beendet: ' + data.last_stop_reason + ')' : ''}.`;
    }
    status.classList.toggle('thread-summary-offline', data.active || data.always);
    document.getElementById('server-log-controls').style.display = data.always ? 'none' : '';
    document.getElementById('server-log-stop').style.display = data.active ? '' : 'none';
}

async function startServerLog() {
    const response = await fetch('/api/server_log/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes: Number(document.getElementById('server-log-minutes').value) })
    });
    if (!response.ok) alert('Das ausführliche Server-Log konnte nicht eingeschaltet werden.');
    fetchServerLog();
}

async function stopServerLog() {
    await fetch('/api/server_log/stop', { method: 'POST' });
    fetchServerLog();
}

fetchCertificate();
setInterval(fetchCertificate, 10000);
fetchServerLog();
setInterval(fetchServerLog, 10000);
