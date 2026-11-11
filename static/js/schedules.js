let schedules = [];
let sensors = [];

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

function renderSchedules(scheduleList){
    const schedulesList = document.getElementById('schedules-list');
    schedulesList.replaceChildren();
    scheduleList.forEach(schedule => {
        const sensorNames = Array.isArray(schedule.sensors) ? schedule.sensors.join(', ') : schedule.sensors;
        const tr = document.createElement('tr');
        appendCells(tr, [schedule.action, schedule.interval, schedule.day || 'N/A', schedule.time, sensorNames]);
        const actions = document.createElement('td');
        actions.append(
            createButton('Bearbeiten', 'button-secondary', () => openEditScheduleModal(schedule.id)), ' ',
            createButton('Löschen', 'button-danger', () => deleteSchedule(schedule.id))
        );
        tr.appendChild(actions);
        schedulesList.appendChild(tr);
    });
}

async function fetchSchedules() {
    const response = await fetch('/api/schedules');
    const data = await response.json();
    schedules = data.schedules;
    renderSchedules(schedules);
}


async function fetchSensorData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();
    sensors = data.sensors;
    const sensorSelect = document.getElementById('scheduleSensors');
    sensorSelect.replaceChildren();
    sensors.forEach(sensor => {
        const option = document.createElement('option');
        option.value = sensor.sensor_id;
        // Devices without counting can be rebooted, but are skipped by reset and upload
        option.text = sensor.counting === false ? `${sensor.name} (keine Zählung)` : sensor.name;
        sensorSelect.appendChild(option);
    });
}

function openScheduleModal() {
    document.getElementById('scheduleForm').reset();
    document.getElementById('scheduleModalTitle').innerText = 'Neue geplante Aktion hinzufügen';
    document.getElementById('saveScheduleButton').onclick = () => saveSchedule();
    document.getElementById('scheduleModal').style.display = 'block';
}

function openEditScheduleModal(scheduleId) {
    const schedule = schedules.find(s => s.id === scheduleId);
    if (!schedule) return;

    document.getElementById('scheduleModalTitle').innerText = 'Geplante Aktion bearbeiten';
    document.getElementById('scheduleAction').value = schedule.action;
    document.getElementById('scheduleInterval').value = schedule.interval;
    document.getElementById('scheduleDay').value = schedule.day || '';
    document.getElementById('scheduleTime').value = schedule.time;
    const sensorSelect = document.getElementById('scheduleSensors');
    Array.from(sensorSelect.options).forEach(option => {
        option.selected = schedule.sensors.includes(option.value);
    });

    document.getElementById('scheduleModal').style.display = 'block';
    document.getElementById('saveScheduleButton').onclick = () => saveSchedule(scheduleId);
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

async function saveSchedule(scheduleId = null) {
    const form = document.getElementById('scheduleForm');
    const formData = new FormData(form);
    const data = {};
    formData.forEach((value, key) => {
        data[key] = value;
    });
    data.sensors = Array.from(document.getElementById('scheduleSensors').selectedOptions).map(option => option.value);

    const url = scheduleId ? `/api/schedules/${scheduleId}/edit` : '/api/schedules/add';
    const method = scheduleId ? 'POST' : 'PUT';
    const response = await fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    });
    if (response.ok) {
        alert('Planmäßige Aktion gespeichert');
        fetchSchedules();
        closeModal('scheduleModal');
    } else {
        let message = `HTTP ${response.status}`;
        try { message = (await response.json()).message || message; } catch (_) {}
        alert('Fehler beim Speichern der planmäßigen Aktion: ' + message);
    }
}

async function deleteSchedule(scheduleId) {
    if (confirm('Sind Sie sicher, dass Sie diese geplante Aktion löschen möchten?')) {
        const response = await fetch(`/api/schedules/${scheduleId}/delete`, {
            method: 'DELETE'
        });
        if (response.ok) {
            const data = await response.json();
            if (data.schedules !== undefined) {
                schedules = data.schedules;
                renderSchedules(schedules);
            } else {
                await fetchSchedules();
            }
            alert('Geplante Aktion gelöscht');
        } else {
            alert('Fehler beim Löschen der geplanten Aktion');
        }
    }
}

fetchSchedules();
fetchSensorData();
setInterval(fetchSchedules, 10000);  // Refresh schedules every 10 seconds

// Close the modal when clicking outside of it
window.onclick = function(event) {
    const scheduleModal = document.getElementById('scheduleModal');
    if (event.target === scheduleModal) {
        scheduleModal.style.display = 'none';
    }
}
