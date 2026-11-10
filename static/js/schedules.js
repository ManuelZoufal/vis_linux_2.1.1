let schedules = [];
let sensors = [];

function renderSchedules(scheduleList){
    const schedulesList = document.getElementById('schedules-list');
    schedulesList.innerHTML = '';
    scheduleList.forEach(schedule => {
        const sensorNames = Array.isArray(schedule.sensors) ? schedule.sensors.join(', ') : schedule.sensors;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${schedule.action}</td>
            <td>${schedule.interval}</td>
            <td>${schedule.day || 'N/A'}</td>
            <td>${schedule.time}</td>
            <td>${sensorNames}</td>
            <td>
                <button class="button button-secondary" onclick="openEditScheduleModal(${schedule.id})">Bearbeiten</button>
                <button class="button button-danger" onclick="deleteSchedule(${schedule.id})">Löschen</button>
            </td>
        `;
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
    sensorSelect.innerHTML = '';
    sensors.forEach(sensor => {
        const option = document.createElement('option');
        option.value = sensor.sensor_id;
        option.text = sensor.name;
        sensorSelect.appendChild(option);
    });
}

function openScheduleModal() {
    document.getElementById('scheduleForm').reset();
    document.getElementById('scheduleModalTitle').innerText = 'Neue geplante Aktion hinzufügen';
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
        alert('Fehler beim Speichern der planmäßigen Aktion');
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
