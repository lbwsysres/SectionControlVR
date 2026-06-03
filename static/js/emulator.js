/* static/js/emulator.js */
let emuEnabled = false;
let currentHdg = 0;
let currentSpd = 0;
let joyZone, joyStick;
let isDraggingEmu = false;
const halfSize = 75;
const defaultX = 0;
const defaultY = halfSize; // Стартовая позиция внизу (выключен)
let currentX = defaultX;
let currentY = defaultY;
let animationFrameId = null;

function initEmulator() {
    //openEmulator(this);
    joyZone = document.getElementById('joy_zone');
    joyStick = document.getElementById('joy_stick');
    if (!joyZone || !joyStick) return;

    updateStickPosition(defaultX, defaultY);
    setupEmulatorEvents();
    updateVisualState();

}

function updateEmuUI() {
    sendEmuData();
}

function sendEmuData() {
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

// Изменение цвета ободка джойстика в зависимости от статуса
function updateVisualState() {
    joyStick.style.borderColor = emuEnabled ? "#2ecc71" : "#e74c3c";
}

function updateStickPosition(x, y) {
    joyStick.style.left = `calc(50% + ${x}px)`;
    joyStick.style.top = `calc(50% + ${y}px)`;
    
}

function handleMove(clientX, clientY) {
    if (!isDraggingEmu) return;

    const rect = joyZone.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    currentX = clientX - centerX;
    currentY = clientY - centerY;

    currentX = Math.max(-halfSize, Math.min(halfSize, currentX));
    currentY = Math.max(-halfSize, Math.min(halfSize, currentY));

    // ЛОГИКА ПЕРЕКЛЮЧЕНИЯ:
    // currentY < 0 означает, что джойстик потянули выше центральной оси
    if (!emuEnabled && currentY < (halfSize * 0.5)) {
        emuEnabled = true;
        updateVisualState();
    }
    // currentY === halfSize означает, что джойстик опустили в самый низ (до упора)
    else if (emuEnabled && currentY >= halfSize) {
        emuEnabled = false;
        updateVisualState();
    }

    updateStickPosition(currentX, currentY);

    if (emuEnabled) {
        currentHdg = Math.round((currentX / halfSize) * 30);
        const invertedY = -currentY;
        const speedPercent = (invertedY + halfSize) / (halfSize * 2);
        currentSpd = speedPercent * 10;
    } else {
        currentHdg = 0;
        currentSpd = 0;
    }

    updateEmuUI();
}

function smoothResetX() {
    if (isDraggingEmu) return;

    // Возвращаем по горизонтали к центру (0)
    currentX = currentX * 0.82;

    if (Math.abs(currentX) < 0.5) {
        currentX = 0;
        if (emuEnabled) {
            currentHdg = 0;
        }
        updateStickPosition(currentX, currentY);
        updateEmuUI();
        cancelAnimationFrame(animationFrameId);
        return;
    }

    updateStickPosition(currentX, currentY);
    if (emuEnabled) {
        currentHdg = Math.round((currentX / halfSize) * 30);
    }
    updateEmuUI();
    animationFrameId = requestAnimationFrame(smoothResetX);
}

function startResetAnimation() {
    cancelAnimationFrame(animationFrameId);
    joyStick.style.transition = "left 0.1s linear";
    smoothResetX();
}

function setupEmulatorEvents() {
    // Мышь
    joyStick.addEventListener('mousedown', (e) => {
        isDraggingEmu = true;
        cancelAnimationFrame(animationFrameId);
        joyStick.style.transition = "none";
        joyStick.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => handleMove(e.clientX, e.clientY));
    window.addEventListener('mouseup', () => {
        if (isDraggingEmu) {
            isDraggingEmu = false;
            joyStick.style.cursor = 'grab';
            startResetAnimation();
        }
    });

    // Тач устройства
    joyStick.addEventListener('touchstart', (e) => {
        isDraggingEmu = true;
        cancelAnimationFrame(animationFrameId);
        joyStick.style.transition = "none";
    });

    window.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) handleMove(e.touches[0].clientX, e.touches[0].clientY);
    });

    window.addEventListener('touchend', () => {
        if (isDraggingEmu) {
            isDraggingEmu = false;
            startResetAnimation();
        }
    });
}
/**
 * Разворачивает эмулятор: прячет круглую кнопку, показывает окно джойстика
 */
/**
 * Разворачивает эмулятор: прячет круглую кнопку, показывает фиксированное окно 200px
 */
function openEmulator() {
    const btn = document.getElementById('emu_toggle_btn');
    const emu = document.getElementById('emulator');
    
    if (btn && emu) {
        btn.style.setProperty('display', 'none', 'important');   // Намертво прячем кнопку
        emu.style.setProperty('display', 'block', 'important');  // Намертво показываем окно
    }
}

/**
 * Сворачивает эмулятор: прячет окно, возвращает круглую кнопку
 */
function closeEmulator() {
    const btn = document.getElementById('emu_toggle_btn');
    const emu = document.getElementById('emulator');
    
    if (btn && emu) {
        emu.style.setProperty('display', 'none', 'important');   // Намертво прячем окно
        btn.style.setProperty('display', 'flex', 'important');   // Возвращаем кнопку (flex для центрирования иконки)
    }
}



document.addEventListener("DOMContentLoaded", initEmulator);
