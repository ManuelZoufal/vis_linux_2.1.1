async function fetchGroupData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();
    const groupList = document.getElementById('group-list');
    groupList.innerHTML = '';
    data.groups.forEach(group => {
        const li = document.createElement('li');
        li.innerHTML = `
            <span>${group.name} (Max: ${group.max_occupancy})</span>
        `;
        li.onclick = () => window.location.href = `/visualize/display?group_id=${group.group_id}`;
        groupList.appendChild(li);
    });
}

fetchGroupData();
setInterval(fetchGroupData, 1000);  // Refresh data every second
