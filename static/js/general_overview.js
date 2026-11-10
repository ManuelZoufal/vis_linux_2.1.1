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

async function fetchAdminData() {
    try {
        const response = await fetch('/api/get_data');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        document.getElementById('local-ip').innerText = data.local_ip;
        document.getElementById('server-hostname').innerText = data.server_hostname;
        document.getElementById('system-time').innerText = data.system_time;

        const dbDataTable = document.getElementById('db-data-table').getElementsByTagName('tbody')[0];
        dbDataTable.replaceChildren();
        (data.sensors || []).sort((a, b) => a.sensor_id.localeCompare(b.sensor_id)).forEach(row => {
            const tr = document.createElement('tr');
            appendCells(tr, [row.sensor_id, row.name, row.ip_address, row.group_id, row.occupancy,
                row.forward_value, row.backward_value, row.timestamp || 'N/A']);
            dbDataTable.appendChild(tr);
        });

        const groupDataTable = document.getElementById('group-data-table').getElementsByTagName('tbody')[0];
        groupDataTable.replaceChildren();
        (data.groups || []).forEach(group => {
            try {
                const currentOccupancy = calculateCurrentOccupancy(group.group_id, data.sensors);
                const occupancyPercentage = calculateOccupancyPercentage(currentOccupancy, group.max_occupancy);
                const tr = document.createElement('tr');
                if (group.maintenance_mode) {
                    tr.style.backgroundColor = '#ffd6d6';
                }
                appendCells(tr, [group.group_id, group.name, group.max_occupancy, currentOccupancy,
                    `${occupancyPercentage}%`, group.welcome_text || '', group.maintenance_mode ? 'Aktiv' : 'Inaktiv']);
                groupDataTable.appendChild(tr);
            } catch (groupErr) {
                console.error('Fehler beim Rendern von Gruppe', group, groupErr);
            }
        });
    } catch (err) {
        console.error('fetchAdminData Fehler:', err);
    }
}

function calculateCurrentOccupancy(groupId, sensors) {
    return sensors.filter(sensor => sensor.group_id === groupId).reduce((sum, sensor) => sum + sensor.occupancy, 0);
}

function calculateOccupancyPercentage(currentOccupancy, maxOccupancy) {
    return maxOccupancy > 0 ? ((currentOccupancy / maxOccupancy) * 100).toFixed(2) : 0;
}

fetchAdminData();
setInterval(fetchAdminData, 1000);  // Refresh data every second
