document.getElementById('marquee-form').addEventListener('submit', function(event) {
    event.preventDefault();
    var marqueeText = document.getElementById('marquee_text').value;
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '{{ url_for("visualize.update_marquee") }}', true);
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4 && xhr.status === 200) {
            alert('Laufschrift Text erfolgreich aktualisiert');
        }
    };
    xhr.send('marquee_text=' + encodeURIComponent(marqueeText));
});
