let currentGroupId = null;
let groups = [];
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

async function fetchGroupData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();

    groups = data.groups;
    sensors = data.sensors;
    const groupList = document.getElementById('group-list');
    groupList.replaceChildren();
    data.groups.sort((a, b) => String(a.group_id).localeCompare(String(b.group_id))).forEach(group => {
        const currentOccupancy = calculateCurrentOccupancy(group.group_id, data.sensors);
        const occupancyPercentage = calculateOccupancyPercentage(currentOccupancy, group.max_occupancy);
        const tr = document.createElement('tr');
        appendCells(tr, [group.group_id, group.name, group.max_occupancy, currentOccupancy,
            `${occupancyPercentage}%`, group.welcome_text || '']);

        const toggle = document.createElement('label');
        toggle.className = 'switch';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = Boolean(group.maintenance_mode);
        checkbox.addEventListener('click', () => toggleMaintenanceMode(group.group_id, checkbox.checked));
        const slider = document.createElement('span');
        slider.className = 'slider round';
        toggle.append(checkbox, slider);
        tr.appendChild(createCell(toggle));

        const actions = document.createElement('td');
        actions.append(
            createButton('Bearbeiten', 'button-secondary', () => openGroupModal(group.group_id)), ' ',
            createButton('Bilder', 'button-warning', () => openImagesModal(group.group_id)), ' ',
            createButton('Löschen', 'button-danger', () => confirmDeleteGroup(group.group_id))
        );
        tr.appendChild(actions);
        groupList.appendChild(tr);
    });
}

function calculateCurrentOccupancy(groupId, sensors) {
    return sensors.filter(sensor => sensor.group_id === groupId).reduce((sum, sensor) => sum + sensor.occupancy, 0);
}

function calculateOccupancyPercentage(currentOccupancy, maxOccupancy) {
    return maxOccupancy > 0 ? ((currentOccupancy / maxOccupancy) * 100).toFixed(2) : 0;
}

function openGroupModal(groupId = null) {
    currentGroupId = groupId;
    const form = document.getElementById('groupForm');
    form.reset();
    if (groupId) {
        const group = groups.find(g => String(g.group_id) === String(groupId));
        document.getElementById('groupModalTitle').innerText = `Gruppen Einstellungen für Gruppe ${group.name}`;
        document.getElementById('groupId').value = group.group_id;
        document.getElementById('groupName').value = group.name;
        document.getElementById('groupMaxOccupancy').value = group.max_occupancy;
        document.getElementById('groupWelcomeText').value = group.welcome_text || '';
        document.getElementById('groupMaintenanceMode').checked = group.maintenance_mode;
    } else {
        document.getElementById('groupModalTitle').innerText = 'Neue Gruppe hinzufügen';
    }
    document.getElementById('groupModal').style.display = 'block';
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

async function saveGroupSettings() {
    const form = document.getElementById('groupForm');
    const formData = new FormData(form);
    const data = {};
    formData.forEach((value, key) => {
        data[key] = value;
    });
    data.maintenance_mode = document.getElementById('groupMaintenanceMode').checked;
    const url = currentGroupId ? `/api/groups/${currentGroupId}/edit` : '/api/groups/add';
    const method = currentGroupId ? 'POST' : 'PUT';
    const response = await fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    });
    if (response.ok) {
        alert('Gruppe erfolgreich gespeichert');
        fetchGroupData();
        closeModal('groupModal');
    } else {
        alert('Fehler beim Speichern der Gruppe');
    }
}

async function deleteGroup(groupId) {
    const response = await fetch(`/api/groups/${groupId}/delete`, {
        method: 'DELETE'
    });
    if (response.ok) {
        alert('Gruppe erfolgreich gelöscht');
        fetchGroupData();
    } else {
        alert('Fehler beim Löschen der Gruppe');
    }
}

async function confirmDeleteGroup(groupId) {
    const associatedSensors = sensors.filter(sensor => sensor.group_id === groupId);
    if (associatedSensors.length > 0) {
        if (confirm('Dieser Gruppe sind noch Sensoren zugeordnet. Sind Sie sicher, dass Sie die Gruppe löschen möchten?')) {
            deleteGroup(groupId);
        }
    } else {
        if (confirm('Sind Sie sicher, dass Sie die Gruppe löschen möchten?')) {
            deleteGroup(groupId);
        }
    }
}

async function toggleMaintenanceMode(groupId, isChecked) {
    const response = await fetch(`/api/groups/${groupId}/toggle_maintenance_mode`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ maintenance_mode: isChecked })
    });
    if (response.ok) {
        alert('Wartungsmodus erfolgreich geändert');
        fetchGroupData();
    } else {
        alert('Fehler beim Ändern des Wartungsmodus');
    }
}

// ── Image management ──

let imagesGroupId = null;

async function openImagesModal(groupId) {
    imagesGroupId = groupId;
    const group = groups.find(g => String(g.group_id) === String(groupId));
    document.getElementById('imagesModalTitle').innerText = `Anzeigebilder – Gruppe ${group ? group.name : groupId}`;
    await renderImageSlots(groupId);
    document.getElementById('imagesModal').style.display = 'block';
}

async function renderImageSlots(groupId) {
    const response = await fetch(`/api/groups/${groupId}/display_images`);
    const data = await response.json();
    const images = data.display_images || [null, null, null];
    const container = document.getElementById('image-slots-container');
    container.replaceChildren();
    const smallButton = 'padding:6px 12px;font-size:0.9em;';
    for (let slot = 0; slot < 3; slot++) {
        const filename = images[slot] || null;
        const div = document.createElement('div');
        div.style.cssText = 'border:1px solid #ddd;border-radius:8px;padding:12px;margin-bottom:12px;';

        const title = document.createElement('strong');
        title.textContent = `Bild ${slot + 1}`;
        div.append(title, document.createElement('br'));

        if (filename) {
            const img = document.createElement('img');
            img.src = `/static/uploads/${encodeURIComponent(filename)}`;
            img.alt = `Bild ${slot + 1}`;
            img.style.cssText = 'max-width:200px;max-height:120px;margin:8px 0;display:block;border-radius:4px;';
            const deleteButton = createButton('Löschen', 'button-danger', () => deleteImage(slot));
            deleteButton.style.cssText = smallButton;
            div.append(img, deleteButton);
        } else {
            const empty = document.createElement('span');
            empty.style.cssText = 'color:#999;font-size:0.9em;';
            empty.textContent = 'Kein Bild';
            div.appendChild(empty);
        }

        const uploadRow = document.createElement('div');
        uploadRow.style.marginTop = '8px';
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.id = `file-input-${slot}`;
        fileInput.accept = '.png,.jpg,.jpeg,.gif,.webp';
        fileInput.style.display = 'none';
        fileInput.addEventListener('change', () => uploadImage(slot));
        const uploadButton = createButton(filename ? 'Ersetzen' : 'Hochladen', 'button-secondary', () => fileInput.click());
        uploadButton.style.cssText = smallButton;
        uploadRow.append(fileInput, uploadButton);
        div.appendChild(uploadRow);

        container.appendChild(div);
    }
}

async function uploadImage(slot) {
    const fileInput = document.getElementById(`file-input-${slot}`);
    const file = fileInput.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('slot', String(slot));
    try {
        const response = await fetch(`/api/groups/${imagesGroupId}/display_images`, {
            method: 'POST',
            body: formData,
            redirect: 'error'
        });
        if (response.ok) {
            await renderImageSlots(imagesGroupId);
        } else {
            let msg = `HTTP ${response.status}`;
            try { const err = await response.json(); msg = err.message || msg; } catch (_) {}
            alert('Fehler beim Hochladen: ' + msg);
        }
    } catch (e) {
        alert('Fehler beim Hochladen: ' + e.message);
    }
}

async function deleteImage(slot) {
    if (!confirm(`Bild ${slot + 1} wirklich löschen?`)) return;
    const response = await fetch(`/api/groups/${imagesGroupId}/display_images/${slot}`, {
        method: 'DELETE'
    });
    if (response.ok) {
        await renderImageSlots(imagesGroupId);
    } else {
        alert('Fehler beim Löschen des Bildes');
    }
}

fetchGroupData();
setInterval(fetchGroupData, 1000);

window.onclick = function(event) {
    ['groupModal', 'imagesModal'].forEach(id => {
        const modal = document.getElementById(id);
        if (event.target === modal) modal.style.display = 'none';
    });
};
