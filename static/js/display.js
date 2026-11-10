async function fetchOccupancy(groupId) {
    try {
        const response = await fetch(`/api/get_data`);
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        const data = await response.json();
        const group = data.groups.find(g => String(g.group_id) === String(groupId));
        if (!group) {
            throw new Error('Group not found');
        }
        const total_occupancy = data.sensors
            .filter(sensor => String(sensor.group_id) === String(groupId))
            .reduce((sum, sensor) => sum + sensor.occupancy, 0);
        return {
            total_occupancy,
            max_occupancy: group.max_occupancy,
            welcome_text: group.welcome_text,
            maintenance_mode: group.maintenance_mode,
            display_images: group.display_images || []
        };
    } catch (error) {
        console.error('Fetch occupancy failed:', error);
        activateMaintenanceMode();
        throw error;
    }
}

function activateMaintenanceMode() {
    document.getElementById('visualization-section').style.display = 'none';
    document.getElementById('maintenance-section').style.display = 'block';
}

function deactivateMaintenanceMode() {
    document.getElementById('visualization-section').style.display = 'flex';
    document.getElementById('maintenance-section').style.display = 'none';
}

function updateImages(displayImages) {
    const panel = document.getElementById('images-panel');
    panel.innerHTML = '';
    (displayImages || []).forEach(filename => {
        if (filename) {
            const img = document.createElement('img');
            img.src = `/static/uploads/${filename}`;
            img.alt = '';
            img.className = 'display-image';
            panel.appendChild(img);
        }
    });
}

function updateChart(chart, data) {
    const maintenanceSection = document.getElementById('maintenance-section');
    const visualizationSection = document.getElementById('visualization-section');
    const greeting = document.getElementById('greeting');

    if (data.maintenance_mode) {
        maintenanceSection.style.display = 'flex';
        visualizationSection.style.display = 'none';
    } else {
        maintenanceSection.style.display = 'none';
        visualizationSection.style.display = 'flex';
        greeting.innerText = data.welcome_text;

        chart.data.datasets[0].data = [
            Math.max(0, data.total_occupancy),
            Math.max(0, data.max_occupancy - data.total_occupancy)
        ];
        chart.update();
    }
}

function updateTrafficLight(totalOccupancy, maxOccupancy) {
    const redLight = document.querySelector('.light.red');
    const greenLight = document.querySelector('.light.green');
    const statusText = document.getElementById('statusText');
    if (totalOccupancy >= maxOccupancy) {
        redLight.classList.add('active');
        greenLight.classList.remove('active');
        statusText.innerText = 'Bitte warten Sie!';
        statusText.style.color = 'red';
    } else {
        redLight.classList.remove('active');
        greenLight.classList.add('active');
        statusText.innerText = 'Bitte treten Sie ein!';
        statusText.style.color = 'green';
    }
}

function updateMarqueeText() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '{{ url_for("visualize.get_marquee_text") }}', true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4 && xhr.status === 200) {
            var response = JSON.parse(xhr.responseText);
            document.getElementById('marquee-text').innerText = response.marquee_text;
        }
    };
    xhr.send();
}

async function init() {
    const urlParams = new URLSearchParams(window.location.search);
    const groupId = urlParams.get('group_id') || '1';
    try {
        const data = await fetchOccupancy(groupId);
        deactivateMaintenanceMode();

        const centerTextPlugin = {
            id: 'centerText',
            afterDraw(chart) {
                const { ctx, chartArea: { left, top, width, height } } = chart;
                const meta = chart.getDatasetMeta(0);
                if (!meta.data || !meta.data[0]) return;
                const innerRadius = meta.data[0].innerRadius;
                const total = chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                const value = chart.data.datasets[0].data[0];
                const pct = total > 0 ? Math.round(value / total * 100) : 0;
                const text = `${pct}%`;
                const color = pct >= 100 ? '#ff2020' : '#00e000';

                // Scale font to fill the inner circle
                let fontSize = Math.floor(innerRadius * 1.3);
                ctx.font = `bold ${fontSize}px Arial`;
                const textWidth = ctx.measureText(text).width;
                const maxWidth = innerRadius * 1.8;
                if (textWidth > maxWidth) {
                    fontSize = Math.floor(fontSize * maxWidth / textWidth);
                }

                ctx.save();
                ctx.font = `bold ${fontSize}px Arial`;
                ctx.fillStyle = color;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(text, left + width / 2, top + height / 2);
                ctx.restore();
            }
        };

        const ctx = document.getElementById('occupancyChart').getContext('2d');
        const occupancyChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Belegt', 'Verfügbar'],
                datasets: [{
                    data: [Math.max(0, data.total_occupancy), Math.max(0, data.max_occupancy - data.total_occupancy)],
                    backgroundColor: ['#FF2020', '#00CC00'],
                    hoverBackgroundColor: ['#FF5555', '#00AA00']
                }]
            },
            options: {
                cutout: '70%',
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    datalabels: { display: false },
                    legend: { display: false }
                }
            },
            plugins: [centerTextPlugin]
        });

        updateImages(data.display_images);
        updateChart(occupancyChart, data);
        updateTrafficLight(data.total_occupancy, data.max_occupancy);
        setInterval(updateMarqueeText, 5000);

        setInterval(async () => {
            try {
                const newData = await fetchOccupancy(groupId);
                deactivateMaintenanceMode();
                updateImages(newData.display_images);
                updateChart(occupancyChart, newData);
                updateTrafficLight(newData.total_occupancy, newData.max_occupancy);
            } catch (error) {
                console.error('Error updating data:', error);
            }
        }, 1000);
    } catch (error) {
        console.error('Initialization failed:', error);
    }
}

init();
