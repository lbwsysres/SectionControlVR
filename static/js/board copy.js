
const modesOrder = ["AUTO", "ON", "OFF"];
const bgCanvas = document.getElementById('bgCanvas'), bgCtx = bgCanvas.getContext('2d');
const fgCanvas = document.getElementById('fgCanvas'), fgCtx = fgCanvas.getContext('2d');
let zoom = 15;
//const cfg = {{ cfg| tojson }};
let localPathHistory = [];
let lastReceivedIndex = 0;
let failedAttempts = 0;
const MAX_FAILED_ATTEMPTS = 10; // 10 попыток по 200мс = 2 секунды тишины
// Глобальная переменная только для текущих координат [lat, lon]
let lastTractorPos = [0, 0];
let lastPointAPos = null; // Будемо зберігати [lat, lon] для А
let lastPointBPos = null; // Будемо зберігати [lat, lon] для В

const fieldCanvas = document.createElement('canvas');
const fCtx = fieldCanvas.getContext('2d');
fieldCanvas.width = 10000;  // 10000 пікселів = приблизно 1-2 км поля
fieldCanvas.height = 10000;

// НАШ НОВИЙ БУФЕР ДЛЯ КАРТИ ЗАВДАНЬ (VRA)
const vraCanvas = document.createElement('canvas');
const vCtx = vraCanvas.getContext('2d');
vraCanvas.width = fieldCanvas.width;  // Такий самий розмір 10000x10000 пікселів
vraCanvas.height = fieldCanvas.height;

const fCenterX = fieldCanvas.width / 2;
const fCenterY = fieldCanvas.height / 2;

// Точка відліку (щоб перетворити GPS у метри один раз)
let refLat = null;
let refLon = null;
let lastPointFromPreviousFetch = null; // Зберігає останню точку для з'єднання пакетів
let _timeRead = 0;
let _abLineNum = "НЕМАЄ ЛІНІЇ";

let isVraMapRendered = false;
let isVraLoading = false; // Прапорець-запобіжник від подвійного запуску



function resize() { bgCanvas.width = fgCanvas.width = window.innerWidth; bgCanvas.height = fgCanvas.height = window.innerHeight; }
window.onresize = resize; resize();
window.addEventListener('wheel', (e) => { zoom *= (e.deltaY < 0 ? 1.1 : 0.9); }, { passive: true });


function toggleMaster() {
    const btn = document.getElementById('mBtn');
    const turnOn = btn.innerText.includes('OFF');
    fetch('/set_master/' + (turnOn ? 1 : 0)).then(() => location.reload());
    //fetch('/set_master/' + (turnOn ? 1 : 0));
}

function setSectionMode(idx, mode) {
    console.log(`Setting section ${idx} to mode ${mode}`);
    fetch(`/set_mode/${idx}/${mode}`).then(() => {
        // Находим ВСЕ кнопки в этой колонке и убираем активный класс
        const allBtns = document.querySelectorAll(`.mode-btn-${idx}`);
        allBtns.forEach(btn => btn.classList.remove('active'));

        // Находим конкретную нажатую кнопку по атрибуту
        const targetBtn = document.querySelector(`.mode-btn-${idx}[data-mode="${mode}"]`);
        if (targetBtn) {
            targetBtn.classList.add('active');
        }
    });
}

function toggleSectionMode(idx) {
    // Находим кнопку, чтобы узнать её текущий режим
    const btn = document.querySelector(`.mode-btn-${idx}.active`);
    if (!btn) return;

    const currentMode = btn.getAttribute('data-mode');
    const currentIndex = modesOrder.indexOf(currentMode);
    // Берем следующий режим (с возвратом в начало через %)
    const nextMode = modesOrder[(currentIndex + 1) % modesOrder.length];

    console.log(`Switching section ${idx} to ${nextMode}`);
    fetch(`/set_mode/${idx}/${nextMode}`);
    // Цвет обновится сам через 200мс из setInterval
}

function buildManual() {
    const container = document.getElementById('manual_ctrl');
    if (!container) return;
    let h = "";
    cfg.SECTION_WIDTHS.forEach((_, i) => {
        h += `
            <div class="section-column">
                <div id="lamp_${i}" class="lamp-indicator"></div>
                <!-- div class="section-label">S${i + 1}</div -->
                <div id="flow_percents_${i}" class="section-label">0</div>
                <div id="vra_flows_${i}" class="section-label">0</div>
                <button id="btn_sec_${i}" class="mode-btn mode-btn-${i} active" data-mode="AUTO" onclick="toggleSectionMode(${i})">AUTO</button>
            </div>`;
    });
    container.innerHTML = h;
}

buildManual();
// *************************************************************************************** //
// 1: Налаштування прихованого шару (FrameBuffer)


function initVraBuffer_1() {
    // 1. Якщо карта вже малюється або вже намальована — миттєво виходимо
    if (isVraMapRendered || isVraLoading) return;

    // 2. Якщо координати ще нульові — плануємо наступну перевірку через 1 секунду
    if (refLat === null || refLon === null) {
        setTimeout(initVraBuffer, 1000);
        return;
    }

    // 3. Блокуємо функцію, щоб жоден інший потік чи таймер не викликав її паралельно
    isVraLoading = true;
    console.log("[VRA] Знайдено refLat/refLon. Починаємо завантаження з Flask...");

    fetch('/api/vra/map')
        .then(response => response.json())
        .then(data => {
            if (data.status !== "success") {
                console.log("[VRA] Карта на сервері відсутня.");
                isVraLoading = false; // Знімаємо блок, раптом карту завантажать пізніше
                return;
            }

            const minR = data.min_rate;
            const maxR = data.max_rate;

            function projectGeoToBuffer(lat, lon) {
                const gx = (lon - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
                const gy = (lat - refLat) * 111320;
                return {
                    x: Math.round(gx * 10 + fCenterX),
                    y: Math.round(-gy * 10 + fCenterY)
                };
            }

            function getColorForRate(rate) {
                if (rate <= minR) return "rgba(46, 204, 113, 0.35)";
                if (rate >= maxR) return "rgba(231, 76, 60, 0.35)";

                const percent = (rate - minR) / (maxR - minR);
                if (percent < 0.5) {
                    const r = Math.round(46 + (241 - 46) * (percent * 2));
                    const g = Math.round(204 + (196 - 204) * (percent * 2));
                    const b = Math.round(113 + (15 - 113) * (percent * 2));
                    return `rgba(${r}, ${g}, ${b}, 0.35)`;
                } else {
                    const p2 = (percent - 0.5) * 2;
                    const r = Math.round(241 + (231 - 241) * p2);
                    const g = Math.round(196 + (76 - 196) * p2);
                    const b = Math.round(15 + (60 - 15) * p2);
                    return `rgba(${r}, ${g}, ${b}, 0.35)`;
                }
            }

            // Отрисовка подложки полигонов внутри initVraBuffer()
            data.polygons.forEach(poly => {
                // Перевірка: для полігону потрібно мінімум 3 точки
                if (!poly.points || poly.points.length < 3) return;

                // Встановлюємо динамічний колір для зони
                vCtx.fillStyle = getColorForRate(poly.rate);
                vCtx.beginPath();

                // 1. Беремо найпершу точку масиву (poly.points[0])
                // points[0][0] — це Lat (49.76...), points[0][1] — це Lon (29.00...)
                const firstPoint = poly.points[0];
                const startPt = projectGeoToBuffer(firstPoint[0], firstPoint[1]);
                vCtx.moveTo(startPt.x, startPt.y);

                // 2. Ведемо лінії по всіх наступних точках контуру
                for (let i = 1; i < poly.points.length; i++) {
                    const currentPoint = poly.points[i];
                    const pt = projectGeoToBuffer(currentPoint[0], currentPoint[1]);
                    vCtx.lineTo(pt.x, pt.y);
                }

                vCtx.closePath();
                vCtx.fill(); // Заливаємо зону кольором

                // Тонка біла лінія між зонами, щоб бачити межі, навіть якщо кольори схожі
                vCtx.strokeStyle = "rgba(255, 255, 255, 0.15)";
                vCtx.lineWidth = 1;
                vCtx.stroke();
            });

            isVraMapRendered = true; // Фіксуємо, що буфер успішно заповнено
            console.log("[VRA BUFFER] Карта успішно зарендерена в буфер.");

        })
        .catch(err => {
            console.error("Помилка генерації VRA буфера:", err);
            isVraLoading = false; // У разі помилки мережі даємо шанс спробувати знову
        });
}

function initVraBuffer() {
    // 1. Перевірка статусів
    if (isVraMapRendered || isVraLoading) return;

    // 2. Очікування координат
    if (refLat === null || refLon === null) {
        setTimeout(initVraBuffer, 1000);
        return;
    }

    // 3. Блокування паралельних викликів
    isVraLoading = true;
    console.log("[VRA] Знайдено refLat/refLon. Починаємо завантаження з Flask...");

    // Оптимізація: виносимо незмінний коефіцієнт проекції (Cos для поточної широти)
    const cosLat = Math.cos(refLat * Math.PI / 180);
    const metersPerDegree = 111320;

    fetch('/api/vra/map')
        .then(response => response.json())
        .then(data => {
            if (data.status !== "success") {
                console.log("[VRA] Карта на сервері відсутня.");
                askUser("Карта на сервері відсутня.", "danger", "ПРИНЯТЬ", () => { });
                isVraLoading = false;
                return;
            }

            // Перевірка наявності даних, щоб уникнути crash в JS
            if (!data.polygons || !Array.isArray(data.polygons)) {
                console.error("[VRA] Дані полігонів пошкоджені або відсутні.");
                askUser("Дані полігонів пошкоджені або відсутні.", "danger", "ПРИНЯТЬ", () => { });
                isVraLoading = false;
                return;
            }

            const minR = data.min_rate;
            const maxR = data.max_rate;
            const rateRange = maxR - minR;

            // Оптимізована функція проекції (використовує константи з замикання)
            function projectGeoToBuffer(lat, lon) {
                const gx = (lon - refLon) * metersPerDegree * cosLat;
                const gy = (lat - refLat) * metersPerDegree;
                return {
                    x: Math.round(gx * 10 + fCenterX),
                    y: Math.round(-gy * 10 + fCenterY)
                };
            }

            function getColorForRate(rate) {
                if (rate <= minR) return "rgba(46, 204, 113, 0.35)";
                if (rate >= maxR) return "rgba(231, 76, 60, 0.35)";
                if (rateRange <= 0) return "rgba(46, 204, 113, 0.35)"; // Захист від ділення на нуль

                const percent = (rate - minR) / rateRange;
                if (percent < 0.5) {
                    const factor = percent * 2;
                    const r = Math.round(46 + (241 - 46) * factor);
                    const g = Math.round(204 + (196 - 204) * factor);
                    const b = Math.round(113 + (15 - 113) * factor);
                    return `rgba(${r}, ${g}, ${b}, 0.35)`;
                } else {
                    const factor = (percent - 0.5) * 2;
                    const r = Math.round(241 + (231 - 241) * factor);
                    const g = Math.round(196 + (76 - 196) * factor);
                    const b = Math.round(15 + (60 - 15) * factor);
                    return `rgba(${r}, ${g}, ${b}, 0.35)`;
                }
            }

            // Налаштування обведення меж один раз перед циклом (пришвидшує рендер)
            vCtx.strokeStyle = "rgba(255, 255, 255, 0.15)";
            vCtx.lineWidth = 1;

            // Отрисовка подложки полігонів
            data.polygons.forEach(poly => {
                if (!poly.points || poly.points.length < 3) return;

                vCtx.fillStyle = getColorForRate(poly.rate);
                vCtx.beginPath();

                // Рендеринг точок контуру
                const startPt = projectGeoToBuffer(poly.points[0][0], poly.points[0][1]);
                vCtx.moveTo(startPt.x, startPt.y);

                for (let i = 1; i < poly.points.length; i++) {
                    const pt = projectGeoToBuffer(poly.points[i][0], poly.points[i][1]);
                    vCtx.lineTo(pt.x, pt.y);
                }

                vCtx.closePath();
                vCtx.fill();
                vCtx.stroke();
            });

            isVraMapRendered = true;
            isVraLoading = false; // Обов'язково знімаємо статус завантаження після успіху
            console.log("[VRA BUFFER] Карта успішно зарендерена в буфер.");
            //askUser("Дані полігонів пошкоджені або відсутні.", "danger", "ПРИНЯТЬ", () => { });
        })
        .catch(err => {
            console.error("Помилка генерації VRA буфера:", err);
            isVraLoading = false; // Звільняємо тригер для повторних спроб у разі помилки мережі
        });
}

// Запускаємо цей саморегульований конвеєр один раз при старті сторінки:
document.addEventListener("DOMContentLoaded", () => {
    initVraBuffer();
});


// НАШ НОВИЙ НЕВБИВАЄМИЙ РОЗРАХУНОК КООРДИНАТ
function getGlobalCoords(lat, lon, heading, sectionIdx, isRightSide = false, localWidths = null) {
    if (refLat === null) { refLat = lat; refLon = lon; }

    // ФЕН-ШУЙ ЗАХИСТ: якщо точка треку має свій масив ширин, беремо його. 
    // Якщо точка стара — беремо поточний конфіг з меню.
    const activeWidths = localWidths || cfg.SECTION_WIDTHS;

    const totalW = activeWidths.reduce((a, b) => a + b, 0);
    const backDist = (cfg.OFFSET_BACK || 0);

    // Розрахунок відступу конкретної секції на основі АКТУАЛЬНИХ для цієї точки ширин
    let sideOff = -totalW / 2;
    for (let j = 0; j < sectionIdx; j++) {
        if (activeWidths[j] !== undefined) {
            sideOff += activeWidths[j];
        }
    }
    if (isRightSide && activeWidths[sectionIdx] !== undefined) {
        sideOff += activeWidths[sectionIdx];
    }

    const rad = heading * Math.PI / 180;

    // Математика повороту штанги (залишається твоя рідна)
    const mx = (sideOff * Math.cos(rad)) - (backDist * Math.sin(rad));
    const my = (-sideOff * Math.sin(rad)) - (backDist * Math.cos(rad));

    // Перевід GPS у метри відносно точки старту
    const gx = (lon - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const gy = (lat - refLat) * 111320;

    return {
        x: (gx + mx) * 10 + fCenterX, // фіксований масштаб буфера 10 пікс/метр
        y: -(gy + my) * 10 + fCenterY
    };
}

// 2: Функція розрахунку координат
function getGlobalCoords_1(lat, lon, heading, sectionIdx, isRightSide = false) {
    if (refLat === null) { refLat = lat; refLon = lon; }

    const totalW = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const backDist = (cfg.OFFSET_BACK || 0);

    // Розрахунок відступу секції від центру трактора
    let sideOff = -totalW / 2;
    for (let j = 0; j < sectionIdx; j++) sideOff += cfg.SECTION_WIDTHS[j];
    if (isRightSide) sideOff += cfg.SECTION_WIDTHS[sectionIdx];

    const rad = heading * Math.PI / 180;
    // Математика повороту штанги
    const mx = (sideOff * Math.cos(rad)) - (backDist * Math.sin(rad));
    const my = (-sideOff * Math.sin(rad)) - (backDist * Math.cos(rad));

    // Перевід GPS у метри (відносно точки refLat/refLon)
    const gx = (lon - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const gy = (lat - refLat) * 111320;

    // return {
    //     x: (gx + mx) * zoom + fCenterX,
    //     y: -(gy + my) * zoom + fCenterY
    // };
    return {
        x: (gx + mx) * 10 + fCenterX, // фіксований масштаб 10 пікс/метр
        y: -(gy + my) * 10 + fCenterY
    };
}


// Безпечна черга для фонової обробки великих масивів даних
let isProcessingQueue = false;
const pointsQueue = [];

function updateFieldMap(newPoints) {
    if (!newPoints || newPoints.length === 0) return;

    // Додаємо нові точки в загальну чергу обробки
    pointsQueue.push(...newPoints);

    if (isProcessingQueue) return;
    isProcessingQueue = true;

    const CHUNK_SIZE = 500;

    function processNextChunk() {
        if (pointsQueue.length === 0) {
            isProcessingQueue = false;
            return;
        }

        const chunk = pointsQueue.splice(0, CHUNK_SIZE);
        const pointsToProcess = lastPointFromPreviousFetch
            ? [lastPointFromPreviousFetch, ...chunk]
            : chunk;

        const start = performance.now();

        pointsToProcess.forEach((pt, idx) => {
            if (idx === 0) return;
            const prev = pointsToProcess[idx - 1];

            const dist = Math.sqrt(Math.pow((pt[0] - prev[0]) * 111320, 2) + Math.pow((pt[1] - prev[1]) * 111320, 2));
            if (dist > 3) return;

            // РЕДУКЦІЯ СТРУКТУРИ:
            // pt[3] — це масив станів форсунок [True, False...]
            // pt[4] — це наш новий масив індивідуальних ширин [0.8, 0.7...]
            const currentStates = pt[3];
            const currentWidths = pt[4] || null; // Якщо точка стара — тут буде null

            const prevWidths = prev[4] || null;

            currentStates.forEach((isActive, i) => {
                if (!isActive && cfg.DRAW_OFF_SECTIONS === false) return;

                fCtx.fillStyle = isActive ? "rgba(46, 204, 113, 0.7)" : "rgba(231, 76, 60, 0.5)";

                // ПЕРЕДАЄМО ЛОКАЛЬНІ ШИРИНИ В РОЗРАХУНОК КООРДИНАТ КОЖНОЇ СЕКЦІЇ
                const cL = getGlobalCoords(pt[0], pt[1], pt[2], i, false, currentWidths);
                const cR = getGlobalCoords(pt[0], pt[1], pt[2], i, true, currentWidths);
                const pL = getGlobalCoords(prev[0], prev[1], prev[2], i, false, prevWidths);
                const pR = getGlobalCoords(prev[0], prev[1], prev[2], i, true, prevWidths);

                fCtx.beginPath();
                fCtx.moveTo(Math.round(cL.x), Math.round(cL.y));
                fCtx.lineTo(Math.round(cR.x), Math.round(cR.y));
                fCtx.lineTo(Math.round(pR.x), Math.round(pR.y));
                fCtx.lineTo(Math.round(pL.x), Math.round(pL.y));
                fCtx.fill();
            });
        });

        lastPointFromPreviousFetch = chunk[chunk.length - 1];
        const end = performance.now();
        _timeRead = end - start;

        setTimeout(processNextChunk, 1);
    }

    processNextChunk();
}

function updateFieldMap_0(newPoints) {
    if (!newPoints || newPoints.length === 0) return;

    // Додаємо нові точки в загальну чергу обробки
    pointsQueue.push(...newPoints);

    // Якщо черга вже крутиться — просто виходимо, вона сама все дожує
    if (isProcessingQueue) return;

    isProcessingQueue = true;
    const CHUNK_SIZE = 500; // Розмір порції точок за один прохід

    function processNextChunk() {
        if (pointsQueue.length === 0) {
            isProcessingQueue = false;
            return;
        }

        // Забираємо першу порцію точок із черги
        const chunk = pointsQueue.splice(0, CHUNK_SIZE);

        // Збираємо масив «хвіст + поточний шматок» для безперервності ліній
        const pointsToProcess = lastPointFromPreviousFetch
            ? [lastPointFromPreviousFetch, ...chunk]
            : chunk;

        const start = performance.now();

        pointsToProcess.forEach((pt, idx) => {
            if (idx === 0) return;
            const prev = pointsToProcess[idx - 1];

            // Дистанція між точками
            const dist = Math.sqrt(Math.pow((pt[0] - prev[0]) * 111320, 2) + Math.pow((pt[1] - prev[1]) * 111320, 2));
            if (dist > 3) return;

            pt[3].forEach((isActive, i) => {
                if (!isActive && cfg.DRAW_OFF_SECTIONS === false) return;

                fCtx.fillStyle = isActive ? "rgba(46, 204, 113, 0.7)" : "rgba(231, 76, 60, 0.5)";

                // Виклик координат (з округленням Math.round для стабільності в Safari)
                const cL = getGlobalCoords(pt[0], pt[1], pt[2], i, false);
                const cR = getGlobalCoords(pt[0], pt[1], pt[2], i, true);
                const pL = getGlobalCoords(prev[0], prev[1], prev[2], i, false);
                const pR = getGlobalCoords(prev[0], prev[1], prev[2], i, true);

                fCtx.beginPath();
                fCtx.moveTo(Math.round(cL.x), Math.round(cL.y));
                fCtx.lineTo(Math.round(cR.x), Math.round(cR.y));
                fCtx.lineTo(Math.round(pR.x), Math.round(pR.y));
                fCtx.lineTo(Math.round(pL.x), Math.round(pL.y));
                fCtx.fill();
            });
        });

        // Запам'ятовуємо останню точку поточного обробленого шматка
        lastPointFromPreviousFetch = chunk[chunk.length - 1];

        const end = performance.now();
        _timeRead = end - start; // Оновлюємо лічильник часу для монітора

        // Віддаємо контроль браузеру на 1 мілісекунду, щоб він обробив мережу/малювання,
        // і плануємо обробку наступного шматка
        setTimeout(processNextChunk, 1);
    }

    // Запускаємо конвеєр
    processNextChunk();
}

function updateFieldMap_1(newPoints) {
    if (!newPoints || newPoints.length === 0) return;

    // Створюємо масив: хвіст + нові точки
    const pointsToProcess = lastPointFromPreviousFetch
        ? [lastPointFromPreviousFetch, ...newPoints]
        : newPoints;

    pointsToProcess.forEach((pt, idx) => {
        if (idx === 0) return;
        const prev = pointsToProcess[idx - 1];

        // Дистанція між точками (твій код без змін)
        const dist = Math.sqrt(Math.pow((pt[0] - prev[0]) * 111320, 2) + Math.pow((pt[1] - prev[1]) * 111320, 2));
        if (dist > 3) return;

        pt[3].forEach((isActive, i) => {
            if (!isActive && cfg.DRAW_OFF_SECTIONS === false) return;

            fCtx.fillStyle = isActive ? "rgba(46, 204, 113, 0.7)" : "rgba(231, 76, 60, 0.5)";
            //fCtx.fillStyle = isActive ? "rgba(46, 204, 113, 1.0)" : "rgba(231, 76, 60, 1.0)";

            // Виклик координат (твій код без змін)
            const cL = getGlobalCoords(pt[0], pt[1], pt[2], i, false);
            const cR = getGlobalCoords(pt[0], pt[1], pt[2], i, true);
            const pL = getGlobalCoords(prev[0], prev[1], prev[2], i, false);
            const pR = getGlobalCoords(prev[0], prev[1], prev[2], i, true);

            fCtx.beginPath();
            fCtx.moveTo(cL.x, cL.y);
            fCtx.lineTo(cR.x, cR.y);
            fCtx.lineTo(pR.x, pR.y);
            fCtx.lineTo(pL.x, pL.y);
            fCtx.fill();

            // fCtx.strokeStyle = isActive ? "rgba(39, 174, 96, 1.0)" : "rgba(192, 57, 43, 1.0)"; // Темніший відтінок для контуру
            // fCtx.lineWidth = 1; // Товщина рамки в пікселях
            // fCtx.stroke();
        });
    });

    // ОНОВЛЕННЯ: Запам'ятовуємо останню точку для наступного виклику fetch
    lastPointFromPreviousFetch = newPoints[newPoints.length - 1];
}


// **************** НОВЫЙ DRAWGRID *********************
// =================================================================================
// 1. ФУНКЦІЯ МАЛЮВАННЯ РУХОМОЇ СІТКИ (ЧИСТА МАТЕМАТИКА)
// =================================================================================
function drawGrid(cx, cy, ty_m, zoom) {
    bgCtx.strokeStyle = "rgba(255,255,255,0.1)";
    bgCtx.lineWidth = 1;

    let gridStep = 20 * zoom; // Крок сітки в пікселях
    const offsetX = 0;
    const offsetY = ty_m * zoom;

    // Розраховуємо циклічний зсув ліній сітки (залишок від ділення на крок)
    const startX = (cx - offsetX) % gridStep;
    const startY = (cy - offsetY) % gridStep;

    // Малюємо вертикальні лінії
    for (let x = startX; x < bgCanvas.width; x += gridStep) {
        bgCtx.beginPath();
        bgCtx.moveTo(x, 0);
        bgCtx.lineTo(x, bgCanvas.height);
        bgCtx.stroke();
    }

    // Малюємо горизонтальні лінії
    for (let y = startY; y < bgCanvas.height; y += gridStep) {
        bgCtx.beginPath();
        bgCtx.moveTo(0, y);
        bgCtx.lineTo(bgCanvas.width, y);
        bgCtx.stroke();
    }
}
// =================================================================================
// 2. ФУНКЦІЯ МАЛЮВАННЯ СІТКИ ЛІНІЙ А-В (КОМПАС ТА ПАРАЛЕЛЬНЕ ВОДІННЯ)
// =================================================================================
function drawABLines_1(data, zoom) {
    if (!data.ab_line || !data.ab_line.a || !data.ab_line.b || data.ux === null || data.uy === null) return;

    const [ax, ay] = data.ab_line.a;
    const [bx, by] = data.ab_line.b;
    const tx = data.ux; // Поточний X трактора в метрах з сервера
    const ty = data.uy; // Поточний Y трактора в метрах з сервера
    
    const dx = bx - ax;
    const dy = by - ay;
    const angleAB = Math.atan2(dy, dx);

    // Загальна ширина штанги оприскувача з конфігу
    const fullWidth = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const length = 2000; // Довжина ліній (2 км)

    // Рахуємо відстань від трактора до базової лінії А-В
    const distToAB = ((by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax) / Math.sqrt(dx * dx + dy * dy);
    
    // Номер проходу, на якому ЗАРАЗ стоїть трактор
    const currentPassNum = Math.round(distToAB / fullWidth);
    _abLineNum = currentPassNum > 0 ? `(+${currentPassNum})` : `(${currentPassNum})`;

    // Малюємо по 3 проходи вліво і вправо від поточного
    for (let i = -3; i <= 3; i++) {
        const absolutePass = currentPassNum + i;
        const offset = absolutePass * fullWidth;

        // Світові координати цієї лінії на полі
        const offsetX = ax + offset * Math.sin(angleAB);
        const offsetY = ay - offset * Math.cos(angleAB);

        // Переклад у координати екрана відносно трактора (в метрах) з масштабуванням
        const screenX = (offsetX - tx) * zoom;
        const screenY = -(offsetY - ty) * zoom;

        bgCtx.beginPath();

        if (i === 0) {
            bgCtx.lineWidth = 20 / zoom; // Поточний прохід — найтовстіший
            bgCtx.strokeStyle = "rgba(255, 255, 255, 0.9)"; // Яскраво-білий
        } else {
            bgCtx.lineWidth = 10 / zoom;
            bgCtx.strokeStyle = (absolutePass % 5 === 0) ? "rgba(100, 220, 255, 0.6)" : "rgba(100, 200, 255, 0.25)";
        }

        // Малюємо лінію проходу
        bgCtx.moveTo(
            screenX - Math.cos(angleAB) * length * zoom,
            screenY + Math.sin(angleAB) * length * zoom
        );
        bgCtx.lineTo(
            screenX + Math.cos(angleAB) * length * zoom,
            screenY - Math.sin(angleAB) * length * zoom
        );
        bgCtx.stroke();
    }
}
function drawABLines_2(data, zoom) {
    if (!data.ab_line || !data.ab_line.a || !data.ab_line.b || !data.pos) return;

    const [ax, ay] = data.ab_line.a;
    const [bx, by] = data.ab_line.b;
    
    // =================================================================================
    // ЖЕСТКИЙ ФЕН-ШУЙ ФИКС: Считаем текущие метры трактора прямо здесь (как в функции draw)
    // Это полностью защищает от путаницы градусов и метров с сервера!
    // =================================================================================
    const tx = (data.pos[1] - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const ty = -(data.pos[0] - refLat) * 111320;
    
    const dx = bx - ax;
    const dy = by - ay;
    const angleAB = Math.atan2(dy, dx);

    // Суммарная ширина штанги опрыскивателя из конфига
    const fullWidth = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const length = 2000; // Длина линий (2 км)

    // Теперь расчет расстояния будет абсолютно точным (метры к метрам)
    const distToAB = ((by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax) / Math.sqrt(dx * dx + dy * dy);
    
    // Номер текущего гона
    const currentPassNum = Math.round(distToAB / fullWidth);
    _abLineNum = currentPassNum > 0 ? `(+${currentPassNum})` : `(${currentPassNum})`;

    // Малинуем по 3 прохода влево и вправо от текущего
    for (let i = -3; i <= 3; i++) {
        const absolutePass = currentPassNum + i;
        const offset = absolutePass * fullWidth;

        // Мировые координаты линии
        const offsetX = ax + offset * Math.sin(angleAB);
        const offsetY = ay - offset * Math.cos(angleAB);

        // Перевод в экранные пиксели относительно центра трактора
        const screenX = (offsetX - tx) * zoom;
        const screenY = -(offsetY - ty) * zoom;

        bgCtx.beginPath();

        if (i === 0) {
            bgCtx.lineWidth = 20 / zoom; // Главная линия жирнее
            bgCtx.strokeStyle = "rgba(255, 255, 255, 0.9)"; // Белая
        } else {
            bgCtx.lineWidth = 10 / zoom;
            bgCtx.strokeStyle = (absolutePass % 5 === 0) ? "rgba(100, 220, 255, 0.6)" : "rgba(100, 200, 255, 0.25)";
        }

        bgCtx.moveTo(
            screenX - Math.cos(angleAB) * length * zoom,
            screenY + Math.sin(angleAB) * length * zoom
        );
        bgCtx.lineTo(
            screenX + Math.cos(angleAB) * length * zoom,
            screenY - Math.sin(angleAB) * length * zoom
        );
        bgCtx.stroke();
    }
}

function drawABLines(data, zoom) {
    if (!data.ab_line || !data.ab_line.a || !data.ab_line.b || data.ab_line.error === undefined) return;

    // Определяем центр экрана планшета напрямую из холста
    const cx = bgCanvas.width / 2;
    const cy = bgCanvas.height / 2;

    const [ax, ay] = data.ab_line.a;
    const [bx, by] = data.ab_line.b;
    
    // Вычисляем угол линии А-В в радианах относительно поля
    const dx = bx - ax;
    const dy = by - ay;
    const angleAB = Math.atan2(dy, dx); 

    // Текущий курс трактора от сервера
    const tractorRad = (data.hdg || 0) * Math.PI / 180;
    
    // Относительный угол наклона линии на экране (трактор смотрит строго ВВЕРХ)
    const relativeAngle = angleAB - tractorRad + Math.PI / 2;

    const fullWidth = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const length = 2000; // Длина линий (2 км)

    // Масштабируем ошибку отклонения с сервера в экранные пиксели
    // Умножаем на 10, так как ваш базовый масштаб карты fCenterX/fCenterY завязан на 10 пикс/метр!
    const baseOffsetX = -data.ab_line.error * zoom * 10; 

    // Рисуем центральный гон и 3 соседних прохода слева и справа
    for (let i = -3; i <= 3; i++) {
        // Шаг смещения боковых гонов в пикселях с учетом масштаба 10 пикс/метр
        const offset = i * fullWidth * zoom * 10;

        bgCtx.save();
        
        // =================================================================================
        // ФЕН-ШУЙ ФИКС: Сначала переносим начало координат в ЦЕНТР ЭКРАНА (к трактору)
        // А уже потом смещаем на ошибку курса и шаг параллельного гона!
        // =================================================================================
        bgCtx.translate(cx, cy); 
        bgCtx.translate(baseOffsetX + offset, 0);
        
        // Поворачиваем линию вокруг локальной точки трактора
        bgCtx.rotate(relativeAngle);

        bgCtx.beginPath();
        if (i === 0) {
            bgCtx.lineWidth = 4; // Центральная линия — жирный ориентир
            bgCtx.strokeStyle = "rgba(241, 196, 15, 0.9)"; // Красивый золотой цвет (УАЗ)
        } else {
            bgCtx.lineWidth = 1.5;
            bgCtx.strokeStyle = "rgba(52, 152, 219, 0.35)"; // Синие маркеры соседних рядков
        }

        // Рисуем бесконечную направляющую линию вверх и вниз через локальный центр гона
        bgCtx.moveTo(0, -length);
        bgCtx.lineTo(0, length);
        bgCtx.stroke();
        
        bgCtx.restore();
    }
}



function drawABLines_Test_Circle(data, zoom) {
    // ВРЕМЕННЫЙ ТЕСТ-КРУГ: Рисуем прямо в центре экрана трактора
    bgCtx.save();
    bgCtx.setTransform(1, 0, 0, 1, 0, 0); // Сбрасываем все повороты в пиксели экрана
    
    bgCtx.beginPath();
    bgCtx.arc(bgCanvas.width / 2, bgCanvas.height / 2, 50, 0, 2 * Math.PI);
    bgCtx.fillStyle = "rgba(231, 76, 60, 0.8)"; // Ярко-красный
    bgCtx.fill();
    bgCtx.strokeStyle = "white";
    bgCtx.lineWidth = 3;
    bgCtx.stroke();
    
    bgCtx.restore();
}

// =================================================================================
// 3. ФУНКЦІЯ МАЛЮВАННЯ ПІДТЛАДКИ (КАРТА VRA + СЛІД ТРАКТОРУ)
// =================================================================================
function drawFieldMap(tx_m, ty_m, hdg, zoom) {
    bgCtx.save();
    
    // Переносимо центр матриці в центр екрану планшета
    bgCtx.translate(bgCanvas.width / 2, bgCanvas.height / 2);
    
    // Обертаємо всю землю під трактором
    bgCtx.rotate(-hdg * Math.PI / 180);
    
    // Розраховуємо масштаб відносно нашого буфера (10 пікс/метр)
    const scaleFactor = zoom / 10;
    bgCtx.scale(scaleFactor, scaleFactor);

    // ШАР 1: Карта диференційованого внесення добрив VRA
    if (isVraMapRendered) {
        bgCtx.drawImage(vraCanvas, -(tx_m * 10 + fCenterX), -(ty_m * 10 + fCenterY));
    }

    // ШАР 2: Буфер проходів обприскувача (слід малюється ПОВЕРХ карти VRA)
    bgCtx.drawImage(fieldCanvas, -(tx_m * 10 + fCenterX), -(ty_m * 10 + fCenterY));
    
    bgCtx.restore(); // Повертаємо матрицю назад
}
// =================================================================================
// 4. ФУНКЦІЯ МАЛЮВАННЯ ТРАКТОРА ТА КРИЛ ШТАНГИ (ПЕРЕДНІЙ ПЛАН)
// =================================================================================
function drawTractorBoom(cx, cy, totalW, data, vScale) {
    fgCtx.save();
    fgCtx.translate(cx, cy);
    
    const bDist = (cfg.OFFSET_BACK || 0) * zoom * vScale;
    let sX = -(totalW / 2) * zoom * vScale;

    // Малюємо рамки та заливаємо кольором активні секції штанги
    data.states.forEach((active, i) => {
        const sw = cfg.SECTION_WIDTHS[i] * zoom * vScale;
        
        fgCtx.strokeStyle = "rgba(255, 255, 255, 0.8)";
        fgCtx.strokeRect(sX, bDist, sw, 8);
        
        if (active) {
            fgCtx.fillStyle = "rgba(46, 204, 113, 0.9)";
            fgCtx.fillRect(sX, bDist, sw, 8);
        }
        sX += sw;
    });

    // Малюємо жовтий трикутник кабіни трактора
    fgCtx.globalAlpha = data.master ? 1.0 : 0.4;
    fgCtx.fillStyle = "#f1c40f";
    fgCtx.beginPath();
    fgCtx.moveTo(0, -25); 
    fgCtx.lineTo(12, 5); 
    fgCtx.lineTo(-12, 5);
    fgCtx.closePath(); 
    fgCtx.fill();
    
    fgCtx.strokeStyle = "white"; 
    fgCtx.lineWidth = 2; 
    fgCtx.stroke();
    
    fgCtx.restore();
}
// =================================================================================
// 5. ФУНКЦІЯ ВІДМАЛЬОВКИ ДІАГНОСТИКИ СИСТЕМИ (FPS / ЧАС ОБРОБКИ)
// =================================================================================
function drawSystemMonitor(start, padding = 20, lineHeight = 20) {
    bgCtx.save();
    bgCtx.setTransform(1, 0, 0, 1, 0, 0); // Скидаємо матрицю в абсолютні пікселі екрана
    
    bgCtx.fillStyle = "white";
    bgCtx.font = "14px monospace";
    bgCtx.textAlign = "right";
    
    const x = bgCanvas.width - padding;
    const y = bgCanvas.height - padding;
    const end = performance.now();

    bgCtx.fillText(`Read: ${_timeRead.toFixed(3)} ms`, x, y - lineHeight);
    bgCtx.fillText(`Draw: ${(end - start).toFixed(3)} ms`, x, y - lineHeight * 2);
    
    bgCtx.restore();
}
// =================================================================================
// ГОЛОВНЕ ЯДРО ВІДМАЛЬОВКИ (ФЕН-ШУЙ ЗБІРКА)
// =================================================================================
function draw_(data) {
    const now = performance.now();
    const delta = now - (window.lastTime || now);
    window.lastTime = now;
    const fps = delta > 0 ? (1000 / delta).toFixed(0) : 60;
    const start = performance.now();

    const cx = bgCanvas.width / 2;
    const cy = bgCanvas.height / 2;
    const vScale = cfg.VISUAL_SCALE || 1.0;
    const totalW = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);

    // Тотальне очищення екрану перед новим тактом 60 Гц
    bgCtx.clearRect(0, 0, bgCanvas.width, bgCanvas.height);
    fgCtx.clearRect(0, 0, fgCanvas.width, fgCanvas.height);

    // Конвертація поточних координат трактора в робочі метри від старту
    const tx_m = (data.pos[1] - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const ty_m = -(data.pos[0] - refLat) * 111320;

    // 1. Малюємо рухому сітку координат
    drawGrid(cx, cy, ty_m, zoom);

    // 2. Малюємо підкладку (Карту VRA + колірний слід поля обприскування)
    drawFieldMap(tx_m, ty_m, data.hdg, zoom);

    // 3. Малюємо динамічні паралельні лінії навігації А-В навколо трактора
    drawABLines(data, zoom);

    // 4. Малюємо жовтий кабінний трикутник та штангу форсунок на передньому плані
    drawTractorBoom(cx, cy, totalW, data, vScale);

    // 5. Виводимо телеметрію швидкодії рендерингу (FPS / мілісекунди) у куток екрану
    drawSystemMonitor(start);
}

// 4: Головна функція Draw
function draw(data) {
    const now = performance.now();
    const delta = now - (window.lastTime || now);
    window.lastTime = now;
    const fps = delta > 0 ? (1000 / delta).toFixed(0) : 60;
    const start = performance.now();

    const cx = bgCanvas.width / 2;
    const cy = bgCanvas.height / 2;
    const vScale = cfg.VISUAL_SCALE || 1.0;
    const totalW = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);

    bgCtx.clearRect(0, 0, bgCanvas.width, bgCanvas.height);
    fgCtx.clearRect(0, 0, fgCanvas.width, fgCanvas.height);
    const tx_m = (data.pos[1] - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const ty_m = -(data.pos[0] - refLat) * 111320;

    bgCtx.strokeStyle = "rgba(255,255,255,0.1)";
    let gridStep = 20 * zoom; // Крок сітки в пікселях

    const offsetX = 0;
    const offsetY = ty_m * zoom;

    // Розраховуємо циклічний зсув ліній сітки (залишок від ділення на крок)
    // Віднімаємо від центру екрана (cx, cy) зміщення трактора
    const startX = (cx - offsetX) % gridStep;
    const startY = (cy - offsetY) % gridStep;

    // Малюємо вертикальні лінії, які тепер рухаються
    for (let x = startX; x < bgCanvas.width; x += gridStep) {
        bgCtx.beginPath();
        bgCtx.moveTo(x, 0);
        bgCtx.lineTo(x, bgCanvas.height);
        bgCtx.stroke();
    }

    // Малюємо горизонтальні лінії, які тепер рухаються
    for (let y = startY; y < bgCanvas.height; y += gridStep) {
        bgCtx.beginPath();
        bgCtx.moveTo(0, y);
        bgCtx.lineTo(bgCanvas.width, y);
        bgCtx.stroke();
    }
    // *************************************************************************************** //
    // ОБ'ЄДНАНА ОТРЕТИСОВКА КАРТИ ЗАВДАННЯ (VRA) ТА СЛІДУ ТРАКТОРУ (ОДИН БЛОК SAVE)
    bgCtx.save();
    bgCtx.translate(bgCanvas.width / 2, bgCanvas.height / 2);
    bgCtx.rotate(-data.hdg * Math.PI / 180);

    const scaleFactor = zoom / 10; // Розраховуємо коефіцієнт масштабування відносно нашого буфера (10 пікс/метр)
    bgCtx.scale(scaleFactor, scaleFactor); // Масштабуємо всю матрицю підкладки

    // ШАР 1: Малюємо карту диференційованого внесення (підкладка)
    // Вона малюється найпершою знизу
    if (isVraMapRendered) {
        bgCtx.drawImage(vraCanvas, -(tx_m * 10 + fCenterX), -(ty_m * 10 + fCenterY));
    }
    //console.log(isVraMapRendered);
    // ШАР 2: Малюємо буфер проходів (слід трактора малюється ПОВЕРХ карти)
    // Завдяки тому, що ми прибрали другий такий виклик нижче, карта більше не затирається!

    bgCtx.drawImage(fieldCanvas, -(tx_m * 10 + fCenterX), -(ty_m * 10 + fCenterY));

    bgCtx.restore(); // Повертаємо контекст назад, очищуючи матрицю для ліній А-В

    // *************************************************************************************** //
    // --- 2. МАЛЮЄМО ДИНАМІЧНІ ЛІНІЇ А-В (КРУТЯТЬСЯ І СЛІДУЮТЬ ЗА ТРАКТОРОМ) ---
    if (data.ab_line && data.ab_line.a && data.ab_line.b && data.ux !== null && data.uy !== null) {
       
        const [ax, ay] = data.ab_line.a;
        const [bx, by] = data.ab_line.b;
        const tx = data.ux; // Поточний X трактора в метрах з сервера
        const ty = data.uy; // Поточний Y трактора в метрах з сервера
        const dx = bx - ax;
        const dy = by - ay;
        const angleAB = Math.atan2(dy, dx);
        // Загальна ширина штанги оприскувача з конфігу
        const fullWidth = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
        const length = 2000; // Довжина ліній (2 км)
        // ------------------------------------------------------------------------
        // ГОЛОВНА МАТЕМАТИКА ЗМІЩЕННЯ:
        // Рахуємо відстань від трактора (tx, ty) до базової лінії А-В (ax, ay)
        const distToAB = ((by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax) / Math.sqrt(dx * dx + dy * dy);

         //console.log(distToAB);

        // Визначаємо точний номер проходу, на якому ЗАРАЗ стоїть трактор (округлюємо до найближчого)
        const currentPassNum = Math.round(distToAB / fullWidth);
        if (currentPassNum > 0) {
            _abLineNum = `(+${currentPassNum})`;
        } else {
            _abLineNum = `(${currentPassNum})`; // Для 0 та від'ємних знак підставиться сам
        }
        // ------------------------------------------------------------------------
        // Малюємо сітку ліній навколо ТРАКТОРА (по 10 проходів вліво і вправо від поточного)
        for (let i = -3; i <= 3; i++) {
            // Абсолютний номер проходу на полі (базовий номер + зміщення циклу)
            const absolutePass = currentPassNum + i;
            // Відступ конкретної лінії в метрах від оригінальної осі А-В (i=0)
            const offset = absolutePass * fullWidth;
            // Світові координати цієї лінії на полі
            const offsetX = ax + offset * Math.sin(angleAB);
            const offsetY = ay - offset * Math.cos(angleAB);
            // Переклад у координати екрана відносно трактора (в метрах) з масштабуванням
            const screenX = (offsetX - tx) * zoom;
            const screenY = -(offsetY - ty) * zoom;
            bgCtx.beginPath();
            // Якщо absolutePass === 0 — це оригінальна (найперша) лінія А-В
            // Якщо i === 0 — це ПОТОЧНА ГОЛОВНА ЛІНІЯ, до якої зараз найближче трактор
            if (i === 0) {
                bgCtx.lineWidth = 20 / zoom; // Робимо поточний прохід найтовстішим
                bgCtx.strokeStyle = "rgba(255, 255, 255, 0.9)"; // Яскраво-білий колір
            } else {
                bgCtx.lineWidth = 10 / zoom;
                // Кожну п'яту лінію підсвічуємо трохи яскравіше для зручності орієнтування
                bgCtx.strokeStyle = (absolutePass % 5 === 0) ? "rgba(100, 220, 255, 0.6)" : "rgba(100, 200, 255, 0.25)";
            }
            // Малюємо лінію проходу
            bgCtx.moveTo(
                screenX - Math.cos(angleAB) * length * zoom,
                screenY + Math.sin(angleAB) * length * zoom
            );
            bgCtx.lineTo(
                screenX + Math.cos(angleAB) * length * zoom,
                screenY - Math.sin(angleAB) * length * zoom
            );
            bgCtx.stroke();
        }
    }
    bgCtx.restore();
    // *************************************************************************************** //
    // 3. ТРАКТОР И ВИРТУАЛЬНАЯ ШТАНГА (на переднем плане)
    fgCtx.save();
    fgCtx.translate(cx, cy);
    const bDist = (cfg.OFFSET_BACK || 0) * zoom * vScale;
    let sX = -(totalW / 2) * zoom * vScale;
    data.states.forEach((active, i) => {
        const sw = cfg.SECTION_WIDTHS[i] * zoom * vScale;
        // Рамка секции
        fgCtx.strokeStyle = "rgba(255, 255, 255, 0.8)";
        fgCtx.strokeRect(sX, bDist, sw, 8);

        if (active) {
            fgCtx.fillStyle = "rgba(46, 204, 113, 0.9)";
            fgCtx.fillRect(sX, bDist, sw, 8);
        }
        sX += sw;
    });
    // Рисуем треугольник трактора
    fgCtx.globalAlpha = data.master ? 1.0 : 0.4;
    fgCtx.fillStyle = "#f1c40f";
    fgCtx.beginPath();
    fgCtx.moveTo(0, -25); fgCtx.lineTo(12, 5); fgCtx.lineTo(-12, 5);
    fgCtx.closePath(); fgCtx.fill();
    fgCtx.strokeStyle = "white"; fgCtx.lineWidth = 2; fgCtx.stroke();
    fgCtx.restore();
    // *************************************************************************************** //
    // Млнитор системы
    bgCtx.save(); // Сохраняем состояние (чтобы не сбить трансформации)
    bgCtx.setTransform(1, 0, 0, 1, 0, 0); // Сбрасываем translate/rotate, чтобы рисовать в экранных координатах

    bgCtx.fillStyle = "white"; // Цвет текста
    bgCtx.font = "14px monospace"; // Моноширинный шрифт лучше для цифр
    bgCtx.textAlign = "right";     // Выравнивание по правому краю

    const padding = 20;            // Отступ от края
    const lineHeight = 20;         // Высота строки
    const x = bgCanvas.width - padding;
    const y = bgCanvas.height - padding;
    const end = performance.now();

    bgCtx.fillText(`Read: ${_timeRead.toFixed(3)} ms`, x, y - lineHeight);
    bgCtx.fillText(`Draw: ${(end - start).toFixed(3)} ms`, x, y - lineHeight * 2);
    //bgCtx.fillText(`FPS: ${fps}`, x, y - lineHeight * 3);

    bgCtx.restore(); // Возвращаем состояние
    //console.log(`Time: ${(end - start).toFixed(3)} ms`);
}


// =================================================================================
// ЗМІННІ ДЛЯ ПЛАВНОЇ ІНТЕРПОЛЯЦІЇ РУХУ КАРТИ (КАМЕРИ)
// =================================================================================
let renderCamX = null;
let renderCamY = null;
let renderCamHdg = null;
// =================================================================================
// МАТЕМАТИЧНИЙ ФІЛЬТР НЧ ДЛЯ ПЛАВНОГО ХОДУ КАРТИ (60 Гц)
// =================================================================================
function updateCameraFilter(targetX, targetY, targetHdg) {
    // Перша ініціалізація, щоб при старті системи камера не телепортувалася
    if (renderCamX === null) {
        renderCamX = targetX;
        renderCamY = targetY;
        renderCamHdg = targetHdg;
        return;
    }

    // Коефіцієнт 0.15 означає, що за 1 кадр монітора карта наздоганяє ціль на 15%
    const K = 0.15;
    
    renderCamX += (targetX - renderCamX) * K;
    renderCamY += (targetY - renderCamY) * K;

    // Плавний фільтр кута курсу (нормалізація розвороту через 0/360 градусів)
    let diffHdg = targetHdg - renderCamHdg;
    if (diffHdg > 180)  diffHdg -= 360;
    if (diffHdg < -180) diffHdg += 360;
    renderCamHdg += diffHdg * K;
}
// =================================================================================
// ГОЛОВНЕ ЯДРО ВІДМАЛЬОВКИ З ПЛАВНОЮ ІНТЕРПОЛЯЦІЄЮ КАРТИ
// =================================================================================
function draw_00(data) {
    const now = performance.now();
    const delta = now - (window.lastTime || now);
    window.lastTime = now;
    const fps = delta > 0 ? (1000 / delta).toFixed(0) : 60;
    const start = performance.now();

    const cx = bgCanvas.width / 2;
    const cy = bgCanvas.height / 2;
    const vScale = cfg.VISUAL_SCALE || 1.0;
    const totalW = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);

    // Тотальне очищення обох холстів перед новим тактом 60 Гц
    bgCtx.clearRect(0, 0, bgCanvas.width, bgCanvas.height);
    fgCtx.clearRect(0, 0, fgCanvas.width, fgCanvas.height);

    // 1. "Жорсткі" метрові координати від сервера
    const tx_m = (data.pos[1] - refLon) * 111320 * Math.cos(refLat * Math.PI / 180);
    const ty_m = -(data.pos[0] - refLat) * 111320;

    // 2. ОНОВЛЕННЯ ФІЛЬТРА КАМЕРИ: плавно наздоганяємо сервер на 60 Гц екрана
    updateCameraFilter(tx_m, ty_m, data.hdg);

    // 3. МАЛЮЄМО СІТКУ (використовуємо ПЛАВНЕ зміщення renderCamY)
    drawGrid(cx, cy, renderCamY / zoom, zoom);

    // 4. МАЛЮЄМО ПІДТЛАДКУ ПОЛЯ (Карта VRA + Кольоровий слід)
    // Використовуємо плавні змінні камери замість жорстких tx_m/ty_m/data.hdg!
    drawFieldMap(renderCamX, renderCamY, renderCamHdg, zoom);

    // 5. МАЛЮЄМО ЛІНІЇ НАВІГАЦІЇ А-В
    // Вони теж мають плавно крутитися і ковзати разом із полем
    bgCtx.save();
    bgCtx.translate(cx, cy);
    bgCtx.rotate(-renderCamHdg * Math.PI / 180);
    drawABLines(data, zoom);
    bgCtx.restore();

    // 6. МАЛЮЄМО ТРАКТОР ТА ШТАНГУ (Він нерухомий, чітко по центру)
    drawTractorBoom(cx, cy, totalW, data, vScale);

    // 7. Виводимо телеметрію швидкодії рендерингу
    drawSystemMonitor(start);
}


// *************************************************************************************** //
// Эмулятор сброс угла поворота
function resetSteer() {
    // const slider = document.getElementById('emu_hdg');
    // slider.value = 0;
    // updateEmuUI();
    document.getElementById('emu_hdg').value = 0;
    updateEmuUI();
}
// *************************************************************************************** //
let currentCompassRotation = 0;
let lastServerHeading = 0;
setInterval(() => {
    fetch(`/map_data?last=${lastReceivedIndex}`)
        .then(r => {
            if (!r.ok) throw new Error("Server Error");
            return r.json();
        })
        .then(d => {
            // --- СВЯЗЬ ЕСТЬ ---
            if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
                hideModal(); // Скрываем окно, если оно было открыто
            }
            failedAttempts = 0;

            // *************************************************************************************** //
            // Обновляем площадь и скорость
            document.getElementById('area').innerText = d.area.toFixed(4);
            //document.getElementById('spd').innerText = d.speed.toFixed(1);

            // *************************************************************************************** //
            // GPS Статус
            // const dot = document.getElementById('rtk_dot');
            // const val = document.getElementById('rtk_val');
            // if (d.rtk >= 4) { dot.style.background = '#2ecc71'; val.innerText = 'FIX'; }
            // else if (d.rtk >= 2) { dot.style.background = '#f1c40f'; val.innerText = 'FLOAT'; }
            // else { dot.style.background = '#e74c3c'; val.innerText = 'SINGLE'; }

            // *************************************************************************************** //
            // Кнопка MASTER ON/OFF
            const mBtn = document.getElementById('mBtn');
            if (d.master) {
                mBtn.classList.remove('master-off');
                mBtn.classList.add('master-on');
            } else {
                mBtn.classList.remove('master-on');
                mBtn.classList.add('master-off');
            }

            if (d.modes) {
                d.modes.forEach((mode, i) => {
                    const btn = document.getElementById(`btn_sec_${i}`);
                    if (btn) {
                        btn.setAttribute('data-mode', mode); // Меняем атрибут для CSS
                        btn.innerText = mode; // Меняем текст на кнопке
                    }
                });
            }
            // *************************************************************************************** //
            // ОБНОВЛЯЕМ ЛАМПОЧКИ-ИНДИКАТОРЫ (из d.states)
            if (d.states) {
                d.states.forEach((isOn, i) => {
                    const lamp = document.getElementById(`lamp_${i}`);
                    if (lamp) {
                        // Если isOn == true, ставим класс lamp-on (зеленый), иначе lamp-off (красный)
                        lamp.className = isOn ? 'lamp-indicator lamp-on' : 'lamp-indicator lamp-off';
                    }
                });
            }
            //const lb_gps_mode_text_in = document.getElementById(`lb_gps_mode_text`);
            //lb_gps_mode_text_in.innerText = d.gps_mode_text;

            const statusPanel = document.getElementById('lb_gps_mode_text'); // Замініть на ваш реальний ID елемента

            if (statusPanel) {
                statusPanel.innerText = d.gps_mode_text; // Виводимо текст із бекенду, як зараз

                // Динамічно змінюємо стиль плашки залежно від цифрового коду
                switch (d.gps_mode) {
                    case 1: // ПОВНИЙ АВТОМАТ (Все ОК)
                        //statusPanel.style.background = "rgba(46, 204, 113, 0.2)"; // Прозоро-зелений фон
                        //statusPanel.style.border = "1px solid #2ecc71";
                        statusPanel.style.color = "#2ecc71";
                        break;

                    case 2: // НАПІВ-АВТОМАТ (Заморозка карти через втрату RTK або стрибок)
                        //statusPanel.style.background = "rgba(241, 196, 15, 0.2)"; // Прозоро-жовтий фон
                        //statusPanel.style.border = "1px solid #f1c40f";
                        statusPanel.style.color = "#f1c40f";
                        break;

                    case 3: // СТОЇМО НА МІСЦІ (Ваша поточна картинка)
                        //statusPanel.style.background = "rgba(44, 62, 80, 0.6)"; // Акуратний темний фон, як зараз
                        //statusPanel.style.border = "1px solid #7f8c8d";
                        statusPanel.style.color = "#fff";
                        break;

                    case 0: // ХАНА (Втрата GPS сигналу)
                        //statusPanel.style.background = "rgba(231, 76, 60, 0.3)"; // Прозоро-червоний тривожний фон
                        //statusPanel.style.border = "1px solid #e74c3c";
                        statusPanel.style.color = "#e74c3c";
                        break;
                }
            }



            // *************************************************************************************** //
            // Индикатор отклонения от линии A B
            // <div class="lightbar-section">
            //     <div id="lb_text">SET A-B LINE</div>
            //     <div class="lightbar">
            //         <div class="lb-center"></div>
            //         <div id="lb_pointer"></div>
            //     </div>
            // </div>
            if (d.ab_line && d.ab_line.a && d.ab_line.b) {
                const ab_line = document.getElementById('id_lightbar');
                const width = ab_line.offsetWidth;
                const pointer = document.getElementById('lb_pointer');
                const txt = document.getElementById('lb_text');
                //let pos = 150 + (d.ab_line.error * 200); // Розрахунок позиції (Центр 150px + відхилення * коефіцієнт чутливості // Коефіцієнт 200 означає, що 0.5 метра відхилення = 100 пікселів зсуву)
                let pos = (width / 2) + (d.ab_line.error * 200);
                //pos = Math.max(15, Math.min(285, pos)); // Обмежуємо шкалою
                pos = Math.max(15, Math.min(width - 15, pos)); // Обмежуємо шкалою

                pointer.style.left = pos + 'px';
                const absErr = Math.abs(d.ab_line.error); // Динамічний колір залежно від точності
                let color = "#2ecc71"; // Зелений (ОК)
                if (absErr > 0.15) color = "#f1c40f"; // Жовтий (Увага)
                if (absErr > 0.40) color = "#e74c3c"; // Червоний (Погано)
                pointer.style.background = color;
                pointer.style.boxShadow = `0 0 15px ${color}`;
                txt.style.color = color;
                const side = d.ab_line.error > 0 ? "R " : "L "; // Форматуємо текст: "L 0.15 m" або "R 0.05 m"

                txt.innerText = _abLineNum + " " + side + absErr.toFixed(2) + " m";
            } else {
                // Якщо лінії не встановлені - ховаємо текст або пишемо "AB NOT SET"
                document.getElementById('lb_text').innerText = "SET A-B LINE";
                document.getElementById('lb_text').style.color = "#555";
            }
            // *************************************************************************************** //
            // ОБРОБКА НОВИХ ТОЧОК
            if (d.new_points && d.new_points.length > 0) {
                // localPathHistory.push(...d.new_points); // Локальная история ? нужна или нет ?

                const start = performance.now();
                updateFieldMap(d.new_points);
                const end = performance.now();
                _timeRead = end - start;
                //console.log(`Time: ${(end - start).toFixed(3)} ms`);

                lastReceivedIndex = d.total_count;
            }
            draw(d);
            //draw(d, localPathHistory);
            if (d.pos && d.pos.length >= 2) {
                lastTractorPos = [d.pos[0], d.pos[1]];
            }

            // if (d.hdg !== undefined) {
            //     const needle = document.getElementById('needle');
            //     if (needle) {
            //         // Обертаємо стрілку на кут курсу
            //         needle.style.transform = `rotate(${d.hdg}deg)`;
            //     }
            // }
            if (d.hdg !== undefined) {
                const needle = document.getElementById('needle');
                if (needle) {
                    // Считаем разницу между новым курсом и предыдущим
                    let diff = d.hdg - lastServerHeading;
                    // Нормализуем разницу в диапазон от -180 до +180 градусов (кратчайший путь поворота)
                    diff = ((diff + 180) % 360 + 360) % 360 - 180;
                    // Прибавляем эту разницу к общему накопленному углу вращения
                    currentCompassRotation += diff;
                    // Запоминаем текущий курс сервера для следующего кадра
                    lastServerHeading = d.hdg;
                    // Поворачиваем стрелку. Она будет плавно скользить благодаря CSS-переходу
                    needle.style.transform = `rotate(${currentCompassRotation}deg)`;
                }
            }
            // 2. Координати точок А та В у градусах (якщо сервер їх прислав)
            if (d.ab_gps) {
                lastPointAPos = d.ab_gps.a; // [lat, lon]
                lastPointBPos = d.ab_gps.b; // [lat, lon]
            }
            // *********************************************************************************
            if (d.flow_percents && d.flow_percents.length > 0) {
                d.flow_percents.forEach((val, i) => {
                    const rateEl = document.getElementById(`flow_percents_${i}`);
                    if (rateEl) {
                        // Виводимо значення
                        rateEl.innerText = val + "%";

                        // Додамо кольорову індикацію для наочності
                        if (val > 105) {
                            rateEl.style.color = "#3498db"; // Синій (прискорення)
                        } else if (val < 95) {
                            rateEl.style.color = "#f39c12"; // Помаранчевий (уповільнення)
                        } else {
                            rateEl.style.color = "#2ecc71"; // Зелений (норма)
                        }
                    }
                });
            }

            if (d.vra_flows && d.vra_flows.length > 0) {
                d.vra_flows.forEach((val, i) => {
                    const vraEl = document.getElementById(`vra_flows_${i}`);
                    if (vraEl) {
                        // Виводимо значення
                        vraEl.innerText = val;
                        vraEl.style.color = "#2ecc71"; // Зелений (норма)
                    }
                });
            }

            // *********************************************************************************
            if (d.pos && d.pos.length >= 2) {
                const latVal = d.pos[0];
                const lonVal = d.pos[1];

                // Захист: якщо координати нульові (немає супутників), пишемо прочерк
                if (latVal === 0 && lonVal === 0) {
                    document.getElementById('gps-lat').innerText = "SEARCHING...";
                    document.getElementById('gps-lon').innerText = "SEARCHING...";
                } else {
                    // Виводимо з точністю 8 знаків після коми (критично для RTK назавігації)
                    document.getElementById('gps-lat').innerText = latVal.toFixed(8);
                    document.getElementById('gps-lon').innerText = lonVal.toFixed(8);
                }
            }
            window.lastServerHdg = d.hdg; // Зберігаємо курс для нашого емулятора

        })
        .catch(err => {
            // --- ОШИБКА СВЯЗИ ---
            failedAttempts++;

            if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
                const sec = (failedAttempts * 0.2).toFixed(1); // Время отсутствия связи
                showModal(`Связь потеряна: ${sec} сек.`);

                // Пищим один раз при достижении порога
                if (failedAttempts === MAX_FAILED_ATTEMPTS) {
                    //playAlarmSound();
                }
            }
            console.error("Connection lost:", err);
        });
}, 200);

// Вспомогательные функции (если еще не добавил)
function showModal(text) {
    const modal = document.getElementById('connectionModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.querySelector('p').innerText = text;
    }
}

function hideModal() {
    const modal = document.getElementById('connectionModal');
    if (modal) modal.style.display = 'none';
}


function resetAll() {
    askUser(
        "ВНИМАНИЕ!<br>Очистить карту и сбросить текущее поле?",
        "danger",
        "ОЧИСТИТЬ",
        () => {
            fetch('/reset_area')
                .then(r => {
                    if (!r.ok) throw new Error("Сервер вернул ошибку при сбросе");
                    return r.json();
                })
                .then(data => {
                    if (data.status === "ok") {
                        console.log("Поле и карта задач успешно очищены на сервере");

                        // 1. Очищаем локальные массивы истории (на всякий случай до перезагрузки)
                        localPathHistory = [];
                        lastReceivedIndex = 0;

                        // 2. Полностью очищаем наш холст карты задач, чтобы картинка не зависла в памяти
                        if (window.vraCanvas && window.vCtx) {
                            vCtx.clearRect(0, 0, vraCanvas.width, vraCanvas.height);
                        }
                        isVraMapRendered = false;
                        if (typeof isVraLoading !== 'undefined') isVraLoading = false;

                        // 3. Выполняем ОДИН аккуратный перезапуск страницы через полсекунды,
                        // чтобы дать серверу гарантированно завершить дисковые операции записи/стирания
                        setTimeout(() => {
                            location.reload();
                        }, 500);
                    }
                })
                .catch(err => {
                    console.error("Ошибка сети при вызове /reset_area:", err);
                    askUser("СЕРВЕР НЕ ОТВЕЧАЕТ<br>Проверьте связь с контроллером.", "danger", "ПРИНЯТЬ", () => { });
                });
        }
    );
}


function resetAll_1() {
    askUser(
        "ВНИМАНИЕ!<br>Очистить карту ?",
        "danger",
        "ОЧИСТИТЬ",
        () => {
            fetch('/reset_area')
                //.then(r => r.json())
                .then(r => {
                    if (!r.ok) throw new Error("Сервер повернув помилку"); // Якщо статус не 200
                    return r.json();
                })
                .then(data => {
                    if (data.status === "ok") {
                        location.reload(); // Перезавантажуємо, щоб побачити чисте поле
                        localPathHistory = []; // он пришлет пустую историю сам.
                        lastReceivedIndex = 0; // 2. Скидаємо індекс, щоб наступний запит знову почався з 0
                        console.log("Поле очищено локально та на сервері");
                        setTimeout(() => {
                            location.reload();
                        }, 500);
                    }
                })
                .catch(err => {
                    // ОСЬ ТУТ: сервер не відповів, або мережа недоступна
                    console.error("Ошибка сети:", err);
                    askUser("СЕРВЕР НЕ ОТВЕЧАЕТ<br>Проверьте связь с контроллером. ", "danger", "ПРИНЯТЬ", () => { });
                });

        }
    );
}
// *************************************************************************************** //
// Відкриття налаштувань
function openSettings() {
    // Якщо у тебе є модальне вікно або інша сторінка
    // Наприклад, показуємо прихований div:
    const panel = document.getElementById('settings_panel');
    if (panel) {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    } else {
        alert("Налаштування будуть доступні в наступному оновленні");
    }
}

// *************************************************************************************** //
// Перемикач Master Switch (без reload!)
function toggleMaster() {
    const btn = document.getElementById('mBtn');
    // Якщо кнопка має клас master-on, значить зараз включено, і треба ВИМКНУТИ (0)
    const isNowOn = btn.classList.contains('master-on');
    const newState = isNowOn ? 0 : 1;

    console.log("Відправляю команду Master:", newState);

    fetch('/set_master/' + newState)
        .then(response => {
            if (!response.ok) console.error("Помилка сервера");
        });
}
// *************************************************************************************** //
// 
function askUser(text, theme, confirmText, onConfirm) {
    const modal = document.getElementById('customModal');
    const modalText = document.getElementById('modalText');
    const confirmBtn = document.getElementById('modalConfirmBtn');
    const cancelBtn = document.getElementById('modalCancelBtn');

    //modalText.innerText = text;
    modalText.innerHTML = text;
    confirmBtn.innerText = confirmText;
    confirmBtn.style.background = (theme === 'danger') ? '#c0392b' : '#2ecc71';

    modal.style.display = 'flex';

    confirmBtn.onclick = () => {
        onConfirm();
        modal.style.display = 'none';
    };
    cancelBtn.onclick = () => {
        modal.style.display = 'none';
    };
}
// *************************************************************************************** //

function abToggleMenu() {
    // 1. Ищем само окно меню
    const menu = document.getElementById('ab-quick-menu');
    // 2. Ищем сетку с кнопками A и B внутри него
    const mainGrid = document.getElementById('ab-main-grid');
    // 3. Ищем панель с цифрами внутри него
    const editPanel = document.getElementById('ab-edit-panel');

    if (!menu) {
        console.error("Ошибка: Не найден элемент 'ab-quick-menu'");
        return;
    }
    const isHidden = menu.style.display === 'none' || menu.style.display === '';
    // Переключаем видимость главного окна
    menu.style.display = isHidden ? 'block' : 'none';
    // Если мы открываем меню, всегда показываем сначала кнопки A и B
    if (isHidden) {
        if (mainGrid) mainGrid.style.display = 'grid';
        if (editPanel) editPanel.style.display = 'none';
    }
}

function toggleAbEdit() {
    const grid = document.getElementById('ab-main-grid');
    const panel = document.getElementById('ab-edit-panel');

    // Переключаем видимость
    const isOpening = grid.style.display !== 'none';
    grid.style.display = isOpening ? 'none' : 'grid';
    panel.style.display = isOpening ? 'flex' : 'none';
    console.log("TEST 0");

    // Если мы ОТКРЫВАЕМ панель редактирования — заполняем координаты
    if (isOpening) {
        // Эта функция сама проверит координаты, заполнит инпуты и подсветит кнопку "T"
        switchAbTab('T');
        // Сбрасываем только поле сдвига (Nudge) в ноль
        const nudgeInput = document.getElementById('ab_off_val');
        if (nudgeInput) nudgeInput.value = "0.00";
    }
}

function setPoint(label) {
    fetch('/set_point/' + label).then(r => {
        if (r.ok) {
            const btn = document.getElementById('btn_set_' + label);
            if (btn) btn.style.color = '#2ecc71';
            if (label === 'b') setTimeout(abToggleMenu, 1000);
        }
    });
}
function nudgeAB(val) {
    const input = document.getElementById('ab_off_val');
    let current = parseFloat(input.value) || 0;

    // Обновляем цифру в окошке для наглядности
    input.value = (current + val).toFixed(2);
    console.log(val);
    // САМОЕ ВАЖНОЕ: запрос к серверу
    fetch(`/set_point/nudge?value=${val}`)
        .then(r => {
            if (!r.ok) console.error("Ошибка сервера при смещении");
        })
        .catch(err => console.error("Ошибка сети:", err));
}

function saveAbManual() {
    const input = document.getElementById('ab_off_val');
    const val = parseFloat(input.value);

    // Если человек что-то ВПИСАЛ руками (и это не 0), тогда отправляем.
    // Но кнопки +5/-5 уже сами всё отправили, поэтому тут нужно быть аккуратным.
    // Проще всего оставить ручной ввод только для контроля, а кнопки для дела.

    input.value = "";
    toggleAbEdit();
    abToggleMenu();
}

// Обработчик удаления линии (через твою модалку askUser)
function abResetHandler() {
    askUser(
        "Удалить линию А-В?",
        "danger",
        "УДАЛИТЬ",
        () => {
            // Отправляем 'reset' в твой существующий роут /set_point/
            fetch('/set_point/reset').then(r => {
                if (r.ok) {
                    // 1. Сбрасываем цвет кнопок в меню обратно в белый
                    const btnA = document.getElementById('btn_set_a');
                    const btnB = document.getElementById('btn_set_b');
                    if (btnA) btnA.style.color = 'white';
                    if (btnB) btnB.style.color = 'white';

                    // 2. Закрываем быстрое меню
                    abToggleMenu();

                    console.log("Линия АВ успешно удалена на сервере");
                }
            }).catch(err => {
                askUser("ОШИБКА СВЯЗИ", "danger", "ПРИНЯТЬ", null);
            });
        }
    );
}
function recordManualCoords(label) {
    const lat = document.getElementById('manual_lat').value;
    const lon = document.getElementById('manual_lon').value;

    if (!lat || !lon) {
        askUser("Введите Lat и Lon!", "danger", "ОК", null);
        return;
    }

    // Отправляем координаты и метку точки (a или b)
    fetch(`/set_point/manual_coords?lat=${lat}&lon=${lon}&label=${label}`)
        .then(r => {
            if (r.ok) {
                console.log(`Точка ${label.toUpperCase()} установлена вручную`);

                // Подсвечиваем соответствующую кнопку в главном меню
                const btn = document.getElementById('btn_set_' + label);
                if (btn) btn.style.color = '#2ecc71';

                // Очищаем поля (опционально)
                // document.getElementById('manual_lat').value = "";
                // document.getElementById('manual_lon').value = "";

                // Если это была точка B, можно закрыть меню, так как линия готова
                if (label === 'b') abToggleMenu();
            }
        });
}
function switchAbTab(type) {
    // Візуал кнопок (підсвітка активної)
    document.querySelectorAll('.ab-tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + type).classList.add('active');

    let targetPos = null;

    if (type === 'T') targetPos = lastTractorPos;
    if (type === 'A') targetPos = lastPointAPos;
    if (type === 'B') targetPos = lastPointBPos;

    const latInput = document.getElementById('manual_lat');
    const lonInput = document.getElementById('manual_lon');

    if (targetPos) {
        latInput.value = targetPos[0].toFixed(8);
        lonInput.value = targetPos[1].toFixed(8);
    } else {
        // Якщо точки ще немає, очищаємо поля
        latInput.value = "";
        lonInput.value = "";
    }
}

