let currentSensorId = null;
let sensors = [];
let groups = [];

// Server data is always inserted as text, never as HTML
function createCell(content) {
    const td = document.createElement('td');
    if (content instanceof Node) {
        td.appendChild(content);
    } else {
        td.textContent = content;
    }
    return td;
}

function appendCells(tr, values) {
    values.forEach(value => tr.appendChild(createCell(value)));
}

function createButton(label, className, onClick) {
    const button = document.createElement('button');
    button.className = `button ${className}`;
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
}

async function fetchSensorData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();

    sensors = data.sensors;
    groups = data.groups;
    const sensorList = document.getElementById('sensor-list');
    sensorList.replaceChildren();
    data.sensors.sort((a, b) => a.ip_address.localeCompare(b.ip_address)).forEach(sensor => {
        const tr = document.createElement('tr');
        appendCells(tr, [sensor.name, sensor.ip_address || 'N/A', sensor.occupancy || 0, sensor.group_id,
            sensor.type, sensor.datapoint_id]);

        const actions = document.createElement('td');
        if (sensor.type === 'VIRTUAL') {
            actions.append(createButton('Löschen', 'button-danger', () => deleteVirtualSensor(sensor.sensor_id)), ' ');
        }
        actions.append(createButton('Bearbeiten', 'button-secondary', () => openSensorModal(sensor.sensor_id)));
        if (sensor.type !== 'VIRTUAL') {
            // A virtual sensor has no device that could be opened, reset or rebooted
            actions.append(' ',
                createButton('Webinterface', 'button-secondary', () => openWebInterface(sensor.ip_address)), ' ',
                createButton('Zählwerte zurücksetzen', 'button-warning', () => resetSensor(sensor.sensor_id)), ' ',
                createButton('Neustarten', 'button-warning', () => rebootSensor(sensor.sensor_id))
            );
        }
        tr.appendChild(actions);
        sensorList.appendChild(tr);
    });
}

function openSensorModal(sensorId) {
    currentSensorId = sensorId;
    const sensor = sensors.find(s => s.sensor_id === sensorId);
    const form = document.getElementById('sensorForm');
    form.replaceChildren();
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
            // The occupancy of a virtual sensor is entered by hand, all other sensors count themselves
            const occupancyEditable = key === 'occupancy' && sensor.type === 'VIRTUAL';
            if (key === 'ip_address' || key === 'sensor_id' || key === 'type' || (key === 'occupancy' && !occupancyEditable)) {
                input.readOnly = true;
            }
            if (occupancyEditable) {
                input.type = 'number';
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
    groupSelect.replaceChildren();
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
    const sensor = sensors.find(s => s.sensor_id === currentSensorId);
    const url = sensor && sensor.type === 'VIRTUAL'
        ? `/api/sensors/virtual/${currentSensorId}/edit`
        : `/api/sensors/${currentSensorId}/edit`;
    const response = await fetch(url, {
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


// Opens the web interface of the sensor directly in a new browser tab
function openWebInterface(ipAddress) {
    if (!ipAddress || ipAddress === 'N/A') {
        alert('Webinterface nicht verfügbar – keine IP-Adresse konfiguriert.');
        return;
    }
    window.open(`https://${ipAddress}/`, '_blank', 'noopener');
}


fetchSensorData();
setInterval(fetchSensorData, 1000);  // Refresh data every second

// Close the modal when clicking outside of it
window.onclick = function(event) {
    ['sensorModal', 'virtualSensorModal'].forEach(id => {
        const modal = document.getElementById(id);
        if (event.target === modal) modal.style.display = 'none';
    });
}
