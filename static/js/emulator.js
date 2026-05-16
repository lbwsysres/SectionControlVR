/* static/js/emulator.js */
let emuEnabled = false;
let currentHdg = 0;
let currentSpd = 0;

let joyZone, joyStick, emuStatusBtn;
let isDragging = false;
const halfSize = 75;

const defaultX = 0;
const defaultY = halfSize;

let currentX = defaultX;
let currentY = defaultY;
let animationFrameId = null;

// Функція ініціалізації, яку викличемо після завантаження DOM
function initEmulator() {
    joyZone = document.getElementById('joy_zone');
    joyStick = document.getElementById('joy_stick');
    emuStatusBtn = document.getElementById('emu_status_btn');

    if (!joyZone || !joyStick) return;

    updateStickPosition(defaultX, defaultY);
    setupEmulatorEvents();
}

function updateEmuUI() {
    //document.getElementById('hdg_val').innerText = currentHdg;
    //document.getElementById('spd_val').innerText = currentSpd.toFixed(1);
    sendEmuData();
}

function sendEmuData() {
    //console.log(`Sending: hdg=${currentHdg}, speed=${currentSpd}`);
    // Тут буде ваш fetch або WebSocket відправка
    const data = {
        enabled: emuEnabled,
        hdg: currentHdg,
        spd: currentSpd
    };
    fetch('/emu_control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).catch(err => console.error("Emu error:", err));
}

function toggleEmu() {
    emuEnabled = !emuEnabled;

    emuStatusBtn.innerText = emuEnabled ? "RUN" : "STOP";
    emuStatusBtn.style.background = emuEnabled ? "#2ecc71" : "#444";
    joyStick.style.borderColor = emuEnabled ? "#2ecc71" : "#e74c3c";

    if (!emuEnabled) {
        currentHdg = 0;
        currentSpd = 0;
        currentX = defaultX;
        currentY = defaultY;
        joyStick.style.transition = "left 0.3s ease-out, top 0.3s ease-out";
        updateStickPosition(defaultX, defaultY);
        updateEmuUI();
    }
}

function updateStickPosition(x, y) {
    joyStick.style.left = `calc(50% + ${x}px)`;
    joyStick.style.top = `calc(50% + ${y}px)`;
}

function handleMove(clientX, clientY) {
    if (!isDragging || !emuEnabled) return;

    const rect = joyZone.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    currentX = clientX - centerX;
    currentY = clientY - centerY;

    currentX = Math.max(-halfSize, Math.min(halfSize, currentX));
    currentY = Math.max(-halfSize, Math.min(halfSize, currentY));

    updateStickPosition(currentX, currentY);

    currentHdg = Math.round((currentX / halfSize) * 30);
    const invertedY = -currentY;
    const speedPercent = (invertedY + halfSize) / (halfSize * 2);
    currentSpd = speedPercent * 10;

    updateEmuUI();
}

function smoothResetX() {
    if (isDragging) return;
    currentX = currentX * 0.82;

    if (Math.abs(currentX) < 0.5) {
        currentX = 0;
        currentHdg = 0;
        updateStickPosition(currentX, currentY);
        updateEmuUI();
        cancelAnimationFrame(animationFrameId);
        return;
    }

    updateStickPosition(currentX, currentY);
    currentHdg = Math.round((currentX / halfSize) * 30);
    updateEmuUI();

    animationFrameId = requestAnimationFrame(smoothResetX);
}

function startResetAnimation() {
    cancelAnimationFrame(animationFrameId);
    joyStick.style.transition = "left 0.1s linear";
    smoothResetX();
}

function setupEmulatorEvents() {
    // Миша
    joyStick.addEventListener('mousedown', (e) => {
        if (!emuEnabled) return;
        isDragging = true;
        cancelAnimationFrame(animationFrameId);
        joyStick.style.transition = "none";
        joyStick.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => handleMove(e.clientX, e.clientY));

    window.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            joyStick.style.cursor = 'grab';
            startResetAnimation();
        }
    });

    // Тач (Мобільні)
    joyStick.addEventListener('touchstart', (e) => {
        if (!emuEnabled) return;
        isDragging = true;
        cancelAnimationFrame(animationFrameId);
        joyStick.style.transition = "none";
    });

    window.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) handleMove(e.touches[0].clientX, e.touches[0].clientY);
    });

    window.addEventListener('touchend', () => {
        if (isDragging) {
            isDragging = false;
            startResetAnimation();
        }
    });
}

// Автоматичний запуск після завантаження сторінки
document.addEventListener("DOMContentLoaded", initEmulator);
