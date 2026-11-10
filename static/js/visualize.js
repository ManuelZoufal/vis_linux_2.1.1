async function fetchGroupData() {
    const response = await fetch('/api/get_data');
    const data = await response.json();
    const groupList = document.getElementById('group-list');
    groupList.replaceChildren();
    data.groups.forEach(group => {
        const li = document.createElement('li');
        const span = document.createElement('span');
        span.textContent = `${group.name} (Max: ${group.max_occupancy})`;  // text, never HTML
        li.appendChild(span);
        li.onclick = () => window.location.href = `/visualize/display?group_id=${encodeURIComponent(group.group_id)}`;
        groupList.appendChild(li);
    });
}

fetchGroupData();
setInterval(fetchGroupData, 1000);  // Refresh data every second
