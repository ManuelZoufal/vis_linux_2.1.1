// Ticker that repeats its text without a gap: the text is placed next to itself as often
// as needed to fill the width, and the row moves left by exactly one repetition, endlessly.
const MARQUEE_SPEED_FACTOR = 3;  // pixels per second = this factor times the font size
const MARQUEE_SEPARATOR = '***';  // shown between two repetitions: <text> *** <text> *** <text>

function setMarquee(container, text) {
    text = (text || '').trim();
    const width = container.clientWidth;
    if (container.dataset.marqueeText === text && Number(container.dataset.marqueeWidth) === width) return;
    container.replaceChildren();
    delete container.dataset.marqueeText;
    if (!text || !width) return;  // nothing to show, or not visible yet: the next call tries again

    const track = document.createElement('div');
    track.className = 'marquee-track';
    const item = document.createElement('span');
    item.className = 'marquee-item';
    item.textContent = text;
    const separator = document.createElement('span');
    separator.className = 'marquee-separator';
    separator.textContent = MARQUEE_SEPARATOR;
    item.appendChild(separator);
    track.appendChild(item);
    container.appendChild(track);

    const itemWidth = item.getBoundingClientRect().width;
    if (!itemWidth) return;
    const copies = Math.ceil(width / itemWidth) + 1;
    for (let i = 0; i < copies; i++) track.appendChild(item.cloneNode(true));
    const fontSize = parseFloat(getComputedStyle(container).fontSize) || 16;
    track.style.setProperty('--marquee-shift', `-${itemWidth}px`);
    track.style.animationDuration = `${itemWidth / (fontSize * MARQUEE_SPEED_FACTOR)}s`;
    container.dataset.marqueeText = text;
    container.dataset.marqueeWidth = width;
}
