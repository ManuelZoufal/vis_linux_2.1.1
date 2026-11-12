// Page "Visualisierung konfigurieren": live previews of the opacity and the ticker

const opacityInput = document.getElementById('opacity');
if (opacityInput) {
    opacityInput.addEventListener('input', () => {
        document.getElementById('opacity-value').textContent = opacityInput.value;
        document.getElementById('preview-image').style.opacity = opacityInput.value / 100;
    });
}

const marqueePreview = document.getElementById('marquee-preview');
const marqueeInput = document.getElementById('marquee_text');
setMarquee(marqueePreview, marqueePreview.dataset.initial);
marqueeInput.addEventListener('input', () => setMarquee(marqueePreview, marqueeInput.value));
window.addEventListener('resize', () => setMarquee(marqueePreview, marqueeInput.value));
