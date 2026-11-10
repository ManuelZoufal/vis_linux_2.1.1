async function fetchAdminData() {
    try {
        const response = await fetch('/api/get_data');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        document.getElementById('local-ip').innerText = data.local_ip;
        document.getElementById('server-hostname').innerText = data.server_hostname;
        document.getElementById('system-time').innerText = data.system_time;

        const dbDataTable = document.getElementById('db-data-table').getElementsByTagName('tbody')[0];
        dbDataTable.innerHTML = '';
        (data.sensors || []).sort((a, b) => a.sensor_id.localeCompare(b.sensor_id)).forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${row.sensor_id}</td>
                <td>${row.name}</td>
                <td>${row.ip_address}</td>
                <td>${row.group_id}</td>
                <td>${row.occupancy}</td>
                <td>${row.forward_value}</td>
                <td>${row.backward_value}</td>
                <td>${row.timestamp || 'N/A'}</td>
            `;
            dbDataTable.appendChild(tr);
        });

        const groupDataTable = document.getElementById('group-data-table').getElementsByTagName('tbody')[0];
        groupDataTable.innerHTML = '';
        (data.groups || []).forEach(group => {
            try {
                const currentOccupancy = calculateCurrentOccupancy(group.group_id, data.sensors);
                const occupancyPercentage = calculateOccupancyPercentage(currentOccupancy, group.max_occupancy);
                const tr = document.createElement('tr');
                if (group.maintenance_mode) {
                    tr.style.backgroundColor = '#ffd6d6';
                }
                tr.innerHTML = `
                    <td>${group.group_id}</td>
                    <td>${group.name}</td>
                    <td>${group.max_occupancy}</td>
                    <td>${currentOccupancy}</td>
                    <td>${occupancyPercentage}%</td>
                    <td>${group.welcome_text || ''}</td>
                    <td>${group.maintenance_mode ? 'Aktiv' : 'Inaktiv'}</td>
                `;
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
