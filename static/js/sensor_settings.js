let currentSensorId = null;
let sensors = [];
let groups = [];

async function fetchSensorData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();
    console.log(data);

    sensors = data.sensors;
    groups = data.groups;
    const sensorList = document.getElementById('sensor-list');
    sensorList.innerHTML = '';
    data.sensors.sort((a, b) => a.ip_address.localeCompare(b.ip_address)).forEach(sensor => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${sensor.name}</td>
            <td>${sensor.ip_address || 'N/A'}</td>
            <td>${sensor.occupancy || 0}</td>
            <td>${sensor.group_id}</td>
            <td>${sensor.type}</td>
            <td>${sensor.datapoint_id}</td>
            <td>
                ${sensor.type === 'VIRTUAL' ? `<button class="button button-danger" onclick="deleteVirtualSensor('${sensor.sensor_id}')">Löschen</button>` : ''}
                <button class="button button-secondary" onclick="openSensorModal('${sensor.sensor_id}')">Bearbeiten</button>
                <button class="button button-secondary" onclick="openWebInterface('${sensor.sensor_id}', '${sensor.ip_address}')">Webinterface</button>
                <button class="button button-warning" onclick="resetSensor('${sensor.sensor_id}')">Zählwerte zurücksetzen</button>
                <button class="button button-warning" onclick="rebootSensor('${sensor.sensor_id}')">Neustarten</button>
            </td>
        `;
        sensorList.appendChild(tr);
    });
}

function openSensorModal(sensorId) {
    currentSensorId = sensorId;
    const sensor = sensors.find(s => s.sensor_id === sensorId);
    const form = document.getElementById('sensorForm');
    form.innerHTML = '';
    document.getElementById('sensorModalTitle').innerText = `Sensor Einstellungen für Sensor ${sensor.ip_address || 'N/A'}`;
    for (const [key, value] of Object.entries(sensor)) {
        if (key === 'timestamp' || key === 'forward_value' || key === 'backward_value') {
            continue; // Skip these fields
        }
        const formGroup = document.createElement('div');
        formGroup.className = 'form-group';
        const label = document.createElement('label');
        label.innerText = key.charAt(0).toUpperCase() + key.slice(1).replace('_', ' ');
        if (key === 'group_id') {
            const select = document.createElement('select');
            select.name = key;
            groups.forEach(group => {
                const option = document.createElement('option');
                option.value = group.group_id;
                option.text = group.name;
                if (group.group_id === value) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
            formGroup.appendChild(label);
            formGroup.appendChild(select);
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.name = key;
            input.value = value;
            if (key === 'ip_address' || key === 'sensor_id' || key === 'occupancy' || key === 'type') {
                input.readOnly = true;
            }
            formGroup.appendChild(label);
            formGroup.appendChild(input);
        }
        form.appendChild(formGroup);
    }
    document.getElementById('sensorModal').style.display = 'block';
}

function openVirtualSensorModal() {
    document.getElementById('virtualSensorForm').reset();
    const groupSelect = document.getElementById('virtualSensorGroup');
    groupSelect.innerHTML = '';
    groups.forEach(group => {
        const option = document.createElement('option');
        option.value = group.group_id;
        option.text = group.name;
        groupSelect.appendChild(option);
    });
    document.getElementById('virtualSensorModalTitle').innerText = 'Virtuellen Sensor hinzufügen';
    document.getElementById('virtualSensorModal').style.display = 'block';
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

async function saveSensorSettings() {
    const form = document.getElementById('sensorForm');
    const formData = new FormData(form);
    const data = {};
    formData.forEach((value, key) => {
        data[key] = value;
    });
    const response = await fetch(`/api/sensors/${currentSensorId}/edit`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    });
    if (response.ok) {
        alert('Sensor updated successfully');
        fetchSensorData();
        closeModal('sensorModal');
    } else {
        alert('Failed to update sensor');
    }
}

async function saveVirtualSensor() {
    const form = document.getElementById('virtualSensorForm');
    const formData = new FormData(form);
    const data = {};
    formData.forEach((value, key) => {
        data[key] = value;
    });
    const response = await fetch('/api/sensors/virtual/add', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    });
    if (response.ok) {
        alert('Virtueller Sensor hinzugefügt');
        fetchSensorData();
        closeModal('virtualSensorModal');
    } else {
        alert('Fehler beim Hinzufügen des virtuellen Sensors');
    }
}

async function resetSensor(sensorId) {
    if (confirm('Sind Sie sicher, dass Sie die Zählerte zurücksetzen möchten?')) {
        const response = await fetch(`/api/sensors/${sensorId}/reset`, { method: 'POST' });
        if (response.ok) {
            alert('Zählwerte erfolgreich zurückgesetzt');
            fetchSensorData();
        } else {
            alert('Fehler beim Zurücksetzen der Zählwerte');
        }
    }
}

async function rebootSensor(sensorId) {
    if (confirm('Sind Sie sicher, dass Sie den Sensor neustarten möchten?')) {
        const response = await fetch(`/api/sensors/${sensorId}/reboot`, { method: 'POST' });
        if (response.ok) {
            alert('Sensor erfolgreich neugestartet');
            fetchSensorData();
        } else {
            alert('Fehler beim Neustarten des Sensors');
        }
    }
}

async function deleteVirtualSensor(sensorId) {
    if (confirm('Sind Sie sicher, dass Sie den virtuellen Sensor löschen möchten?')) {
        const response = await fetch(`/api/sensors/virtual/${sensorId}/delete`, {
            method: 'DELETE'
        });
        if (response.ok) {
            alert('Virtueller Sensor gelöscht');
            fetchSensorData();
        } else {
            alert('Fehler beim Löschen des virtuellen Sensors');
        }
    }
}


function openWebInterface(sensorId, ipAddress) {
    if (!ipAddress || ipAddress === 'N/A') {
        alert('Webinterface nicht verfügbar – keine IP-Adresse konfiguriert.');
        return;
    }
    const proxyUrl = `/api/sensors/${sensorId}/webinterface/`;
    const directUrl = `https://${ipAddress}/`;
    document.getElementById('webinterfaceModalTitle').innerText = `Webinterface – ${ipAddress}`;
    document.getElementById('webinterfaceFrame').src = proxyUrl;
    document.getElementById('webinterfaceExternalLink').href = directUrl;
    document.getElementById('webinterfaceModal').style.display = 'block';
}

function closeWebInterfaceModal() {
    document.getElementById('webinterfaceFrame').src = '';
    document.getElementById('webinterfaceModal').style.display = 'none';
}


fetchSensorData();
setInterval(fetchSensorData, 1000);  // Refresh data every second

// Close the modal when clicking outside of it
window.onclick = function(event) {
    ['sensorModal', 'virtualSensorModal'].forEach(id => {
        const modal = document.getElementById(id);
        if (event.target === modal) modal.style.display = 'none';
    });
    const webModal = document.getElementById('webinterfaceModal');
    if (event.target === webModal) closeWebInterfaceModal();
}
