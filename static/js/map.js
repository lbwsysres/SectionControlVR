// ==============================================================================
// 1. ГЛОБАЛЬНІ ЗМІННІ ТА ІНІЦІАЛІЗАЦІЯ ГРАФІЧНОГО ДВИГУНА
// ==============================================================================

// ==========================================
// НОВЕ СХОВИЩЕ ДЛЯ ДИНАМІЧНИХ ЧАНКІВ КАРТИ
// ==========================================
let mapChunks = {}; // Сюди будемо складати створені RenderTexture для кожного квадрата
const CHUNK_SIZE_METERS = 400.0; // Повинно збігатися з Python!


let failedAttempts = 0;
const MAX_FAILED_ATTEMPTS = 2; // 10 попыток по 200мс = 2 секунды тишины

const zoom = 10; // Жорсткий базовий масштаб: 1 метр = 10 пікселів.
let refLat = null;
let refLon = null;
let lastReceivedIndex = 0;
const metersPerDegree = 111320;

// Пам'ять залізобетонного плавного ходу (Чистий LERP)
let targetX = 0;         // Реальна цільова координата X від GPS сервера в метрах
let targetY = 0;         // Реальна цільова координата Y від GPS сервера в метрах
let targetHdg = 0;       // Реальний курс від GPS сервера у градусах
let interpolatedX = 0;   // Плавна позиція X на екрані (наздоганяє ціль)
let interpolatedY = 0;   // Плавна позиція Y на екрані (наздоганяє ціль)
let interpolatedHdg = 0; // Плавний кут повороту карти на екрані

// Пам'ять координат GPS від сервера для ліній А-В та розрахунків
let lastLatForCamera = null;
let lastLonForCamera = null;
let lastHdgForCamera = null;
let globalAbData = null; // Збережені лінії А-В

let pointsQueue = [];
let isProcessingQueue = false;
let lastPointFromPreviousFetch = null;
let prevSectionsCoords = []; // Історія країв кожної секції штанги
let totalPolygonsRendered = 0; // Лічильник об'єктів покриття

// Статусы карты заданий VRA
//let isVraMapRendered = false;
//let isVraLoading = false;

// Ш Т А Н Г А
// Глобальні текстури PixiJS для секцій штанги
let activeSecTex = null;   // Сюди збережемо текстуру для ВКЛЮЧЕНОЇ (зеленої) секції
let inactiveSecTex = null; // Сюди збережемо текстуру для ВИМКНЕНОЇ (темної) секции

// Масив, де будуть зберігатися посилання на кожен окремий спрайт-секцію
let sectionSprites = [];





// Форсуємо використання сумісного WebGL2 рушія (захист від зависань на Android)
PIXI.settings.PREFER_ENV = PIXI.ENV.WEBGL2;

const app = new PIXI.Application({
    width: window.innerWidth,
    height: window.innerHeight,
    backgroundColor: 0x141414,
    antialias: false,//true,
    resolution: window.devicePixelRatio || 1,
    autoDensity: true,
    powerPreference: "high-performance",
    preserveDrawingBuffer: false,
    clearBeforeRender: true
});
document.body.appendChild(app.view);

console.log("Часть 1 готова: Мобільний двигун ініціалізовано.");

// ==============================================================================
// ЧАСТЬ 2: СЛОИ, РАДАРНАЯ ПОДЛОЖКА И ОБРАБОТЧИКИ ЭКРАНА
// ==============================================================================

// Главные слои контейнеров
const world = new PIXI.Container();
const uiLayer = new PIXI.Container();

// Отдельный нижний подслой для изоляции фоновой подложки поля
const gridContainer = new PIXI.Container();

const vraGraphics = new PIXI.Graphics();

app.stage.addChild(world);
app.stage.addChild(uiLayer);

// Первым делом в ручной мир кладем слой подложки (всегда индекс 0)
world.addChild(gridContainer);

// Центрируем камеру при старте
world.position.set(app.screen.width / 2, app.screen.height / 2);

// БЕЗПЕЧНИЙ РОЗМІР ДЛЯ СТАРИХ ПЛАНШЕТІВ (Защита Redmi 5 Plus и Samsung)
// Создаем виртуальное полотно 4000х4000 пикселей в памяти GPU
const mapRenderTexture = PIXI.RenderTexture.create({
    width: 4000,
    height: 4000,
    scaleMode: PIXI.SCALE_MODES.LINEAR
});

// Спрайт, отображающий текстуру шлейфа на земле поля
const trackSprite = new PIXI.Sprite(mapRenderTexture);
trackSprite.anchor.set(0.5); // Центрируем картинку в нулях рухомого мира

// Временный микро-объект для выпекания одного текущего шага шлейфа
const tempTrackGraphics = new PIXI.Graphics();

// Создаем остальные графические слои на поле
const abLinesGraphics = new PIXI.Graphics();
const liveConnectorGraphics = new PIXI.Graphics(); // Наш сглаживающий соединитель зазоров
const boomGraphics = new PIXI.Graphics();          // 🔥 ВОЗВРАЩАЕМ ПЕРЕМЕННУЮ ШТАНГИ НА ПОЛЕ!

// Неподвижный указатель трактора в кабине
const tractorGraphics = new PIXI.Graphics();

// Раскладываем объекты по жестким слоям (Z-Index)
world.addChild(vraGraphics);            // Слой 1: Карта предписаний VRA (на самом дне поля)
world.addChild(trackSprite);            // Слой 1: Постоянный шлейф покрытия
world.addChild(abLinesGraphics);        // Слой 2: Синие параллельные гоны А-В
world.addChild(liveConnectorGraphics);   // Слой 3: Временный живой хвостик шлейфа
world.addChild(boomGraphics);           // Слой 4: Штанга на земле поля (зумится со шлейфом)
uiLayer.addChild(tractorGraphics);      // Слой 5: Нерушимая желтая кабина водителя всегда сверху

tractorGraphics.position.set(app.screen.width / 2, app.screen.height / 2);

// Векторная радарная подложка (Идеально четкая при любых поворотах)
const radarGraphics = new PIXI.Graphics();
gridContainer.addChild(radarGraphics);





function drawRadarGrid() {
    radarGraphics.clear();
    radarGraphics.lineStyle(1, 0xffffff, 0.04); // Очень тонкие ниточки колец

    // Рисуем круги дальности (10м, 20м, 30м, 50м, 75м от трактора)
    const radii = [10, 20, 30, 50, 75];
    radii.forEach(r => {
        radarGraphics.drawCircle(0, 0, r * zoom);
    });

    // Рисуем осевые направляющие лучи (вперед, назад, влево, вправо)
    radarGraphics.moveTo(0, -100 * zoom); radarGraphics.lineTo(0, 100 * zoom);
    radarGraphics.moveTo(-100 * zoom, 0); radarGraphics.lineTo(100 * zoom, 0);
}
drawRadarGrid(); // Отрисовываем один раз в локальном центре поля

// #region ОБРАБОТЧИКИ ИНТЕРФЕЙСА (РЕСАЙЗ И ЗУМ КНОПКАМИ И ТАЧЕМ)
window.addEventListener('resize', () => {
    app.renderer.resize(window.innerWidth, window.innerHeight);
    if (tractorGraphics) {
        tractorGraphics.position.set(app.screen.width / 2, app.screen.height / 2);
    }
    if (lastLatForCamera !== null) {
        renderCameraAndBoomSmooth(interpolatedX, interpolatedY, interpolatedHdg);
    }
});

// Кнопки зума на панели управления
//document.getElementById('btn-zoom-in').addEventListener('click', () => changeWorldScale(1.2));
//document.getElementById('btn-zoom-out').addEventListener('click', () => changeWorldScale(0.8));

// Обычный зум колесиком мыши
window.addEventListener('wheel', (e) => { changeWorldScale(e.deltaY < 0 ? 1.1 : 0.9); }, { passive: true });

// Жест Pinch-to-Zoom для Android (два пальца)
let lastTouchDist = 0;

window.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
        // Чётко берём координаты ПЕРВОГО [0] и ВТОРОГО [1] пальца
        lastTouchDist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
    }
}, { passive: true });

window.addEventListener('touchmove', (e) => {
    if (e.touches.length === 2 && lastTouchDist > 0) {
        // Рассчитываем текущее расстояние между двумя движущимися пальцами
        const currentDist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );

        // Коэффициент изменения расстояния
        const delta = currentDist / lastTouchDist;

        // Корректируем общий масштаб WebGL-мира (0.2 — коэффициент мягкости зума)
        changeWorldScale(1 + (delta - 1) * 0.8);

        lastTouchDist = currentDist;
    }
}, { passive: true });

window.addEventListener('touchend', (e) => { if (e.touches.length < 2) { lastTouchDist = 0; } }, { passive: true });

// #endregion





function initVehicleGraphics() {
    // 1. Малюємо жовту кабіну трактора ОДИН раз (це векторна графіка, вона статична)
    tractorGraphics.lineStyle(2, 0xffffff, 1.0);
    tractorGraphics.beginFill(0xf1c40f, 1.0);
    tractorGraphics.drawPolygon([
        0, -25,   // Ніс дивиться вгору
        12, 5,    // Праве крило
        -12, 5    // Ліве крило
    ]);
    tractorGraphics.endFill();

    // 2. Будуємо білу рамку-підкладку для штанги
    // Вона потрібна, щоб візуально розділити секції білими лініями
    const totalWidthMeters = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const bDistPixels = (cfg.OFFSET_BACK || 0) * zoom;
    let currentStartX = -(totalWidthMeters / 2) * zoom;

    // Малюємо суцільну білу лінію штанги на полі
    const bgOutline = new PIXI.Graphics();
    bgOutline.lineStyle(1, 0xffffff, 1.0);
    bgOutline.beginFill(0xffffff, 1.0);
    bgOutline.drawRect(currentStartX, bDistPixels, totalWidthMeters * zoom, 8);
    bgOutline.endFill();
    boomGraphics.addChild(bgOutline);

    // 3. Наповнюємо масив sectionSprites кольоровими прямокутниками
    cfg.SECTION_WIDTHS.forEach((width, i) => {
        const sw = width * zoom; // Фізична ширина секції на полі

        // Створюємо спрайт на основі вбудованої білої текстури Pixi
        const secSprite = new PIXI.Sprite(PIXI.Texture.WHITE);

        // Робимо ширину трохи меншою, щоб залишився білий зазор між секціями
        secSprite.position.set(currentStartX + 1, bDistPixels + 1);
        secSprite.width = sw - 2;
        secSprite.height = 6;

        // Стартовий колір при завантаженні — темно-сірий (вимкнено)
        secSprite.tint = 0x1a1a1a;
        secSprite.alpha = 0.7;

        // Додаємо його як дитину на штангу і зберігаємо посилання в наш глобальний масив
        boomGraphics.addChild(secSprite);
        sectionSprites.push(secSprite);

        currentStartX += sw; // Рухаємось до наступної секції
    });
}

// ВИКЛИКАЄМО ФУНКЦІЮ ОДИН РАЗ ПРИ СТАРТІ СТОРІНКИ:
initVehicleGraphics();

function redrawTractorVehicle(states, isMaster, lat, lon, heading) {
    // 1. Для кабіни трактора залишаємо ваш робочий clear, 
    // бо вона малюється на окремому шарі uiLayer і не зв'язана зі штангою
    tractorGraphics.alpha = isMaster ? 1.0 : 0.4;
    // 2. Ваша оригінальна математика фізичних координат поля
    // Ми її НЕ чіпаємо, вона потрібна для розрахунку шлейфу далі по коду
    if (refLat === null) return;
    let cx = (lon - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    let cy = -(lat - refLat) * metersPerDegree;

    // 3. УПРАВЛІННЯ СЕКЦІЯМИ (Без методів clear() та drawRect()!)
    // Пробігаємося по масиву станів, який прислав Flask
    states.forEach((active, i) => {
        // Перевіряємо, чи існує такий спрайт у нашому запеченому масиві
        if (i >= sectionSprites.length) return;

        const sec = sectionSprites[i]; // Беремо посилання на готову секцію з пам'яті

        if (active) {
            sec.tint = 0x2ecc71; // Відеокарта сама миттєво фарбує її в ЗЕЛЕНИЙ
            sec.alpha = 0.9;
        } else {
            sec.tint = 0x1a1a1a; // Відеокарта сама миттєво фарбує її в ТЕМНО-СІРИЙ
            sec.alpha = 0.7;
        }
    });
}

// Универсальная функция масштабирования WebGL
function changeWorldScale(factor) {
    world.scale.x *= factor;
    world.scale.y *= factor;

    // Ограничители оптического зума
    world.scale.x = Math.max(0.1, Math.min(8, world.scale.x));
    world.scale.y = world.scale.x;

    if (lastLatForCamera !== null) {
        renderCameraAndBoomSmooth(interpolatedX, interpolatedY, interpolatedHdg);
    }
    if (globalAbData) {
        drawABLines(globalAbData); // Перерисовываем А-В под новую толщину
    }
}



console.log("Часть 2 зафиксирована: Ошибка ReferenceError полностью устранена.");

// ==============================================================================
// ВЕКТОРНИЙ ШАР ТА ТРИГЕРИ ДЛЯ КАРТИ ЗАВДАНЬ VRA
// ==============================================================================
let isVraMapRendered = false; // Чи зарендерена вже карта завдань VRA
let isVraLoading = false;      // Прапорець контролю паралельних запитів до Flask

// Ця команда буде автоматично шукати першу GPS точку поля кожну секунду,
// і як тільки база з'явиться — моментально завантажить карту завдань VRA з сервера!
function checkAndLoadVra() {
    if (isVraMapRendered || isVraLoading) return;

    if (refLat === null || refLon === null) {
        setTimeout(checkAndLoadVra, 1000); // Бази ще немає, чекаємо 1 секунду
        return;
    }

    // База поля є! Запускаємо завантаження
    initVraBuffer();
}
// ==============================================================================
// ЧАСТЬ 3 ДЛЯ VRA: ВЕКТОРНАЯ ОТРИСОВКА ПОЛИГОНОВ НА РУХОМОМ ПОЛЕ PIXI
// ==============================================================================
function renderVraPolygonsToPixi(polygons, cosLat, getColorForRateHex) {
    // Очищаем старые контуры задания перед новым рендером
    vraGraphics.clear();

    // Задаём стиль тонкой обводки границ зон (как ваши vCtx.strokeStyle)
    vraGraphics.lineStyle(1 / (world.scale.x || 1.0), 0xffffff, 0.15);

    polygons.forEach(poly => {
        if (!poly.points || poly.points.length < 3) return;

        // Рассчитываем цвет зоны на основе нормы вылива в Hex
        const hexColor = getColorForRateHex(poly.rate);

        // Начинаем заливку полигона на видеокарте с прозрачностью 0.35 (как ваши 35%)
        vraGraphics.beginFill(hexColor, 0.35);

        // Массив, в который мы соберём плоские пиксели всех вершин контура для Pixi.js
        const pixiPointsArray = [];

        poly.points.forEach(point => {
            const lat = point[0];
            const lon = point[1];

            // ВАША ОРИГИНАЛЬНАЯ ГЕОГРАФИЧЕСКАЯ ПРОЕКЦИЯ МЕТРОВ ОТ БАЗЫ:
            const gx = (lon - refLon) * metersPerDegree * cosLat;
            const gy = -(lat - refLat) * metersPerDegree; // Инвертируем Y под экран Pixi

            // Переводим в базовые пиксели поля Pixi (zoom = 10)
            pixiPointsArray.push(gx * zoom, gy * zoom);
        });

        // Выжигаем полигон на WebGL одной быстрой аппаратной командой
        vraGraphics.drawPolygon(pixiPointsArray);
        vraGraphics.endFill();
    });

    // Фиксируем статусы: карта успешно зарендерена на земле поля!
    isVraMapRendered = true;
    isVraLoading = false;
    console.log(`[VRA PIXI] Карта заданий успешно выжжена на GPU! Нарисовано зон: ${polygons.length}.`);
}

// Запускаємо сторожа перевірки VRA при старті сторінки
checkAndLoadVra();
console.log("Часть 2 зафиксирована:VRA.");

// ==============================================================================
// ЧАСТЬ 3: ОРИГИНАЛЬНАЯ МАТЕМАТИКА И МОНОЛИТНЫЙ ТРАКТОР СО ШТАНГОЙ
// ==============================================================================

function redrawTractorVehicle_work_new(states, isMaster, lat, lon, heading) {
    // 1. Кабина трактора
    tractorGraphics.clear();
    tractorGraphics.lineStyle(2, 0xffffff, 1.0);
    tractorGraphics.beginFill(0xf1c40f, isMaster ? 1.0 : 0.4);
    tractorGraphics.drawPolygon([
        0, -25,   // Нос смотрит вверх
        12, 5,    // Правое крыло
        -12, 5    // Левое крыло
    ]);
    tractorGraphics.endFill();

    // 2. Штанга поля
    boomGraphics.clear();
    if (refLat === null) return;

    let cx = (lon - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    let cy = -(lat - refLat) * metersPerDegree;

    let totalWidthMeters = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    let bDistPixels = (cfg.OFFSET_BACK || 0) * zoom;
    let currentStartX = -(totalWidthMeters / 2) * zoom;

    // ОПТИМИЗАЦИЯ: Настраиваем стиль линий ОДИН раз для всей штанги, а не в цикле!
    boomGraphics.lineStyle(1, 0xffffff, 0.8);

    states.forEach((active, i) => {
        if (i >= cfg.SECTION_WIDTHS.length) return;
        const sw = cfg.SECTION_WIDTHS[i] * zoom;

        if (active) {
            boomGraphics.beginFill(0x2ecc71, 0.9); // Зелёная активная
        } else {
            boomGraphics.beginFill(0x1a1a1a, 0.5); // Тёмная выключенная
        }

        boomGraphics.drawRect(currentStartX, bDistPixels, sw, 8);
        boomGraphics.endFill();

        currentStartX += sw;
    });
}
// 1. Монолитное рисование треугольника трактора и штанг на его корме
function redrawTractorVehicle_work(states, isMaster, lat, lon, heading) {
    // 1. Жёлтый треугольник кабины (остаётся неподвижным на экране)
    tractorGraphics.clear();
    tractorGraphics.lineStyle(2, 0xffffff, 1.0);
    tractorGraphics.beginFill(0xf1c40f, isMaster ? 1.0 : 0.4);
    tractorGraphics.drawPolygon([
        0, -25,   // Нос смотрит вверх
        12, 5,    // Правое крыло
        -12, 5    // Левое крыло
    ]);
    tractorGraphics.endFill();

    // 2. Рисуем штангу, которая лежит на земле поля (будет зумиться вместе со следом)
    boomGraphics.clear();
    if (refLat === null) return;

    // Рассчитываем физическую позицию трактора в метрах поля
    let cx = (lon - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    let cy = -(lat - refLat) * metersPerDegree;

    let totalWidthMeters = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);

    // ВАЖНО: используем оригинальный backOffset БЕЗ умножения на vScale, 
    // так как штанга на поле должна идеально повторять математику шлейфа!
    let bDistPixels = (cfg.OFFSET_BACK || 0) * zoom;
    let currentStartX = -(totalWidthMeters / 2) * zoom;

    states.forEach((active, i) => {
        if (i >= cfg.SECTION_WIDTHS.length) return;
        const sw = cfg.SECTION_WIDTHS[i] * zoom;

        boomGraphics.lineStyle(1, 0xffffff, 0.8);
        if (active) {
            boomGraphics.beginFill(0x2ecc71, 0.9); // Зелёная активная
        } else {
            boomGraphics.beginFill(0x1a1a1a, 0.5); // Тёмная выключенная
        }

        // Отрисовка секции в чистых пикселях поля (zoom = 10)
        boomGraphics.drawRect(currentStartX, bDistPixels, sw, 8);
        boomGraphics.endFill();

        currentStartX += sw;
    });

    // Перемещаем и крутим штангу на поле вслед за трактором
    // LBW штанга
    //boomGraphics.position.set(cx * zoom, cy * zoom);
    //boomGraphics.rotation = heading * Math.PI / 180; 
}

// 2. ВАША ОРИГИНАЛЬНАЯ МАТЕМАТИКА ИЗ GITHUB GIST (100% ПРОВЕРЕННАЯ)
function getGlobalCoordsPixi(lat, lon, heading, sectionIdx, isRightSide, customWidths) {
    let cx = (lon - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    let cy = -(lat - refLat) * metersPerDegree;

    let widths = customWidths || cfg.SECTION_WIDTHS;
    const backOffset = cfg.OFFSET_BACK || 0;

    let offsetMeters = 0;
    for (let i = 0; i < sectionIdx; i++) {
        if (i < widths.length) offsetMeters += widths[i];
    }
    if (isRightSide && sectionIdx < widths.length) {
        offsetMeters += widths[sectionIdx];
    }

    let totalWidth = widths.reduce((a, b) => a + b, 0);
    offsetMeters -= totalWidth / 2;

    // ЧИСТЫЙ КУРС ИЗ ВАШЕГО КОДА БЕЗ КОРЕЖЕНЬЯ ЗНАКОВ:
    let rad = (heading * Math.PI / 180);

    // ВАША ЗАЛИЗОБЕТОННАЯ ТРИГОНОМЕТРИЯ ПРОЕКЦИИ:
    let rx = cx + offsetMeters * Math.cos(rad) - backOffset * Math.sin(rad);
    let ry = cy + offsetMeters * Math.sin(rad) + backOffset * Math.cos(rad);

    return { x: rx * zoom, y: ry * zoom };
}
// Було: function appendTrackSegmentPixi(lat, lon, heading, states, widths)
// Стане:

//function appendTrackSegmentPixi(lat, lon, heading, states, widths, currentChunkKey) {

function appendTrackSegmentPixi(lat, lon, heading, states, customWidths) {
    //function appendTrackSegmentPixi(lat, lon, heading, states, customWidths) {
    if (refLat === null || !states || !Array.isArray(states)) return;

    // Настраиваем стиль линий один раз на точку (толщина 0 — чистая заливка)
    tempTrackGraphics.lineStyle(0);

    const drawOff = cfg.DRAW_OFF_SECTIONS;

    states.forEach((isActive, i) => {
        if (!isActive && drawOff === false) {
            prevSectionsCoords[i] = null;
            return;
        }

        const cL = getGlobalCoordsPixi(lat, lon, heading, i, false, customWidths);
        const cR = getGlobalCoordsPixi(lat, lon, heading, i, true, customWidths);

        if (prevSectionsCoords[i]) {
            const prev = prevSectionsCoords[i];

            // Защита от линий к старту и разрывов GPS (Прыжок > 5 метров)
            const dx = cL.x - prev.cL.x;
            const dy = cL.y - prev.cL.y;
            if (Math.sqrt(dx * dx + dy * dy) > 50) {
                prevSectionsCoords[i] = { cL: cL, cR: cR };
                return;
            }

            // Накапливаем полигоны в общем буфере tempTrackGraphics БЕЗ рендеринга
            tempTrackGraphics.beginFill(isActive ? 0x2ecc71 : 0xe74c3c, isActive ? 0.7 : 0.5);
            tempTrackGraphics.drawPolygon([
                prev.cL.x + 2000, prev.cL.y + 2000,
                cL.x + 2000, cL.y + 2000,
                cR.x + 2000, cR.y + 2000,
                prev.cR.x + 2000, prev.cR.y + 2000
            ]);
            tempTrackGraphics.endFill();

            totalPolygonsRendered++;
        }

        prevSectionsCoords[i] = { cL: cL, cR: cR };
    });
}

console.log("Часть 3 готова: Оригинальная геометрия из Gist и монолитная штанга зафиксированы.");

// ==========================================
// ЧАСТЬ 4: ЧАНКИ, ПЛАВНИЙ LERP, ЛІНІЇ А-В ТА WATCHDOG FLASK
// ==========================================

// 1. Двигун моментального вивантаження історії чанками (last=0)
function updateFieldMapPixi(newPoints) {
    if (!newPoints || newPoints.length === 0) return;

    // 1. Возвращаем твою родную стабильную очередь точек
    pointsQueue.push(...newPoints);

    if (isProcessingQueue) return;
    isProcessingQueue = true;

    const CHUNK_SIZE = 1000;

    function processNextChunk() {
        if (pointsQueue.length === 0) {
            isProcessingQueue = false;
            lastQueueProgressTime = performance.now(); // Сторож (Watchdog) спокоен
            return;
        }

        // Очищаем векторную графику перед началом обсчета всей пачки
        tempTrackGraphics.clear();

        const chunk = pointsQueue.splice(0, CHUNK_SIZE);

        chunk.forEach((pt) => {
            // Защита: массив теперь длиннее, так как первым элементом идет ["0_0", lat, lon...]
            if (!pt || pt.length < 5) return;

            // =================================================================
            // СДВИГАЕМ ИНДЕКСЫ НА +1, ЧТОБЫ УЧЕСТЬ КЛЮЧ ЧАНКА ОТ СЕРВЕРА
            // =================================================================
            const chunkKey = pt[0]; // "0_0", "1_0" тощо
            const lat = pt[1]; // Раньше было pt[0]
            const lon = pt[2]; // Раньше было pt[1]
            const hdg = pt[3]; // Раньше было pt[2]
            const states = pt[4]; // Раньше было pt[3]
            const customWidths = pt[5] || null; // Раньше было pt[4]

            // Вызываем твою оригинальную, нетронутую тригонометрию штанги
            appendTrackSegmentPixi(lat, lon, hdg, states, customWidths);
        });

        // 2. Запекаем пачку в твою СТАРУЮ ОРИГИНАЛЬНУЮ текстуру (без матриц смещения)
        if (typeof mapRenderTexture !== 'undefined') {
            app.renderer.render(tempTrackGraphics, {
                renderTexture: mapRenderTexture,
                clear: false
            });
        }

        // Моментально очищаем векторную память GPU после массового запекания
        tempTrackGraphics.clear();

        // Обновляем счетчик полигонов на UI
        const polyElem = document.getElementById('total_point');
        if (polyElem) {
            polyElem.innerText = "Poligon count: " + totalPolygonsRendered;
        }

        // Переходим к следующей пачке
        setTimeout(processNextChunk, 1);
    }

    processNextChunk();
}


// 2. ПРИЙМАЄ ДАНІ ВІД СЕРВЕРА 4 РАЗИ НА СЕКУНДУ І ВИЗНАЧАЄ ЦІЛЬ (Без ділення на мс)
function updateCamera(lat, lon, heading) {
    if (refLat === null) return;

    // Переводимо GPS градуси в реальні метри поля відносно базової точки
    targetX = (lon - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    targetY = -(lat - refLat) * metersPerDegree;
    targetHdg = heading;

    // Зберігаємо в глобальну пам'ять для ліній А-В та камери
    lastLatForCamera = lat;
    lastLonForCamera = lon;
    lastHdgForCamera = heading;
}

// 3. Головний залізобетонний цикл плавності LERP (М'яке наздоганяння)
const TARGET_FPS = 30;
app.ticker.maxFPS = TARGET_FPS;

app.ticker.add(() => {
    if (refLat === null || targetX === 0 || targetY === 0) return;

    // Скидаємо початкові координати на старті
    if (interpolatedX === 0 && interpolatedY === 0) {
        interpolatedX = targetX;
        interpolatedY = targetY;
        interpolatedHdg = targetHdg;
    }

    // М'яко наздоганяємо ціль GPS
    interpolatedX += (targetX - interpolatedX) * 0.10;
    interpolatedY += (targetY - interpolatedY) * 0.10;

    let angleDiff = targetHdg - interpolatedHdg;
    angleDiff = Math.atan2(Math.sin(angleDiff * Math.PI / 180), Math.cos(angleDiff * Math.PI / 180)) * 180 / Math.PI;
    interpolatedHdg += angleDiff * 0.10;

    // Виводимо прораховані плавні координати на екран з частотою TARGET_FPS
    renderCameraAndBoomSmooth(interpolatedX, interpolatedY, interpolatedHdg);
});

// 4. Виклик з Pixi Ticker із частотою TARGET_FPS (Масляний рендер екрана)
function renderCameraAndBoomSmooth(x, y, heading) {
    let worldX = x * zoom;
    let worldY = y * zoom;

    // Рухаємо та крутимо карту поля
    world.pivot.x = worldX;
    world.pivot.y = worldY;
    world.rotation = -heading * Math.PI / 180;

    world.position.x = app.screen.width / 2;
    world.position.y = app.screen.height / 2;

    if (tractorGraphics) {
        tractorGraphics.position.set(app.screen.width / 2, app.screen.height / 2);
    }

    if (radarGraphics) {
        radarGraphics.position.set(worldX, worldY);
    }

    // 🔥 СГЛАДЖУЮЧИЙ СОЕДИНИТЕЛЬ ЗАЗОРІВ (БЕЗ ДИРОК ПРИ ЗУМІ)
    liveConnectorGraphics.clear();
    if (prevSectionsCoords.length > 0 && window.lastReceivedStates && lastLatForCamera !== null) {
        liveConnectorGraphics.lineStyle(0);

        window.lastReceivedStates.forEach((isActive, i) => {
            if (!isActive || !prevSectionsCoords[i]) return;

            const prev = prevSectionsCoords[i];

            // Берём чистые плавные края штанги с учётом текущего поворота heading
            const cL = getGlobalCoordsPixi(lastLatForCamera, lastLonForCamera, heading, i, false, null);
            const cR = getGlobalCoordsPixi(lastLatForCamera, lastLonForCamera, heading, i, true, null);

            liveConnectorGraphics.beginFill(0x2ecc71, 0.7); // Зелений хвостик
            liveConnectorGraphics.drawPolygon([
                prev.cL.x, prev.cL.y,
                cL.x, cL.y,
                cR.x, cR.y,
                prev.cR.x, prev.cR.y
            ]);
            liveConnectorGraphics.endFill();
        });
    }
    // LBW Штанга
    if (boomGraphics) {
        boomGraphics.position.set(worldX, worldY);
        // Ставим чистый плавный курс БЕЗ МИНУСА для удержания горизонтали
        boomGraphics.rotation = heading * Math.PI / 180;
    }
}

// 5. Професійний двигун паралельних ліній гонів А-В (на 2 км навколо кабіни)
function drawABLines(data) {
    abLinesGraphics.clear();

    if (!data || !data.ab_line || !data.ab_line.a || !data.ab_line.b || data.ux === null || data.uy === null) return;
    if (refLat === null || lastLatForCamera === null) return;

    const [ax, ay] = data.ab_line.a;
    const [bx, by] = data.ab_line.b;
    const tx = data.ux;
    const ty = data.uy;

    const dx = bx - ax;
    const dy = by - ay;
    const angleAB = Math.atan2(dy, dx);

    const fullWidth = cfg.SECTION_WIDTHS.reduce((a, b) => a + b, 0);
    const length = 2000;

    const distToAB = ((by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax) / Math.sqrt(dx * dx + dy * dy);
    const currentPassNum = Math.round(distToAB / fullWidth);
    if (currentPassNum > 0) {
        _abLineNum = `(+${currentPassNum})`;
    } else {
        _abLineNum = `(${currentPassNum})`;
    }
    // ОПТИМІЗАЦІЯ 1: Рахуємо масштаб і товщину ліній ОДИН РАЗ ЗА МЕЖАМИ ЦИКЛУ
    const currentWorldScale = world.scale.x || 1.0;
    const thickWidth = 4 / currentWorldScale;
    const thinWidth = 1 / currentWorldScale;

    // ОПТИМІЗАЦІЯ 2: Перший прохід — налаштовуємо синій колір і малюємо ТІЛЬКИ рядові лінії
    abLinesGraphics.lineStyle(thinWidth, 0x64c8ff, 0.25);

    for (let i = -3; i <= 3; i++) {
        if (i === 0) continue; // Пропускаємо поточний гон, намалюємо його пізніше

        const absolutePass = currentPassNum + i;
        const offset = absolutePass * fullWidth;

        const offsetX = ax + offset * Math.sin(angleAB);
        const offsetY = ay - offset * Math.cos(angleAB);

        let localLineX = (offsetX - tx) + (lastLonForCamera - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
        let localLineY = -(offsetY - ty) - (lastLatForCamera - refLat) * metersPerDegree;

        let startX = (localLineX - Math.cos(angleAB) * length) * zoom;
        let startY = (localLineY + Math.sin(angleAB) * length) * zoom;
        let endX = (localLineX + Math.cos(angleAB) * length) * zoom;
        let endY = (localLineY - Math.sin(angleAB) * length) * zoom;

        abLinesGraphics.moveTo(startX, startY);
        abLinesGraphics.lineTo(endX, endY);
    }

    // ОПТИМІЗАЦІЯ 3: Другий прохід — окремо малюємо один єдиний ПОТОЧНИЙ БІЛИЙ гон (i === 0)
    abLinesGraphics.lineStyle(thickWidth, 0xffffff, 0.5);

    const offsetZero = currentPassNum * fullWidth;
    const offsetXZero = ax + offsetZero * Math.sin(angleAB);
    const offsetYZero = ay - offsetZero * Math.cos(angleAB);

    let localLineXZero = (offsetXZero - tx) + (lastLonForCamera - refLon) * metersPerDegree * Math.cos(refLat * Math.PI / 180);
    let localLineYZero = -(offsetYZero - ty) - (lastLatForCamera - refLat) * metersPerDegree;

    let startXZero = (localLineXZero - Math.cos(angleAB) * length) * zoom;
    let startYZero = (localLineYZero + Math.sin(angleAB) * length) * zoom;
    let endXZero = (localLineXZero + Math.cos(angleAB) * length) * zoom;
    let endYZero = (localLineYZero - Math.sin(angleAB) * length) * zoom;

    abLinesGraphics.moveTo(startXZero, startYZero);
    abLinesGraphics.lineTo(endXZero, endYZero);
}

// ==============================================================================
// ЧАСТЬ 2 ДЛЯ VRA: ФУНКЦИЯ ЗАГРУЗКИ И РАСЧЁТА ЦВЕТОВ ПОЛИГОНОВ
// ==============================================================================
function initVraBuffer() {
    if (isVraMapRendered || isVraLoading) return;

    if (refLat === null || refLon === null) {
        setTimeout(initVraBuffer, 1000);
        return;
    }

    isVraLoading = true;
    console.log("[VRA] База поля найдена. Загружаем карту предписания VRA с Flask...");

    const cosLat = Math.cos(refLat * Math.PI / 180);

    fetch('/api/taskmaps/map')
        .then(response => response.json())
        .then(data => {
            if (data.status === "error" || data.status === "no_map" || data.status !== "success") {
                console.log("[VRA] Карта на сервере отсутствует или повреждена.");
                isVraLoading = false;
                return;
            }

            if (!data.polygons || !Array.isArray(data.polygons)) {
                console.error("[VRA] Данные полигонов повреждены.");
                isVraLoading = false;
                return;
            }

            const minR = data.min_rate;
            const maxR = data.max_rate;
            const rateRange = maxR - minR;

            // ВАША ОРИГИНАЛЬНАЯ МАТЕМАТИКА ГРАДИЕНТА ЦВЕТА (ПЕРЕВЕДЕНА НА HEX ДЛЯ GPU)
            function getColorForRateHex(rate) {
                if (rate <= minR || rateRange <= 0) return 0x2ecc71; // Зелёный (норма)
                if (rate >= maxR) return 0xe74c3c;                  // Красный (максимум)

                const percent = (rate - minR) / rateRange;

                if (percent < 0.5) {
                    const factor = percent * 2;
                    const r = Math.round(46 + (241 - 46) * factor);
                    const g = Math.round(204 + (196 - 204) * factor);
                    const b = Math.round(113 + (15 - 113) * factor);
                    return (r << 16) + (g << 8) + b; // Быстрая сборка в Hex формат
                } else {
                    const factor = (percent - 0.5) * 2;
                    const r = Math.round(241 + (231 - 241) * factor);
                    const g = Math.round(196 + (76 - 196) * factor);
                    const b = Math.round(15 + (60 - 15) * factor);
                    return (r << 16) + (g << 8) + b; // Быстрая сборка в Hex формат
                }
            }

            // Вызываем Часть 3 для отрисовки полигонов на поле
            renderVraPolygonsToPixi(data.polygons, cosLat, getColorForRateHex);
        })
        .catch(err => {
            console.error("Ошибка загрузки карты VRA предписания:", err);
            isVraLoading = false;
        });
}

// 6. РОЗУМНИЙ МЕРЕЖЕВИЙ ЦИКЛ З ТАЙМАУТ-СТОРОЖЕМ (WATCHDOG)
let lastQueueProgressTime = performance.now();

function requestDataFromServer() {
    const now = performance.now();

    // Сторож реанімації мережі для Redmi: Якщо графіка заклинила довше 1.5 сек — зриваємо замок!
    if (isProcessingQueue && (now - lastQueueProgressTime > 1500)) {
        console.warn("⚠️ Сторож виявив зависання графіки! Примусове скидання черги для старого заліза.");
        pointsQueue = [];
        isProcessingQueue = false;
        lastQueueProgressTime = now;
    }

    if (isProcessingQueue) {
        setTimeout(requestDataFromServer, 250);
        return;
    }

    fetch(`/map_data?last=${lastReceivedIndex}`)
        .then(response => {
            if (!response.ok) throw new Error(`Помилка сервера: ${response.status}`);
            return response.json();
        })
        .then(data => {
            lastQueueProgressTime = performance.now();

            if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
                hideModal(); // Скрываем окно, если оно было открыто
            }
            failedAttempts = 0;
            if (!data) {
                setTimeout(requestDataFromServer, 250);
                return;
            }

            // Малюємо лінії А-В ЗАВЖДИ, як тільки вони прийшли в JSON
            if (data.ab_line) {
                globalAbData = data;
                drawABLines(data);
            }

            // if (data.new_points && data.new_points.length > 0) {
            //     updateFieldMapPixi(data.new_points);

            //     const lastPointArray = data.new_points[data.new_points.length - 1];
            //     const lastLat = lastPointArray[0];
            //     const lastLon = lastPointArray[1];
            //     const lastHdg = lastPointArray[2];
            //     const lastStates = lastPointArray[3];

            //     window.lastReceivedStates = lastStates;

            //     updateCamera(lastLat, lastLon, lastHdg);
            //     redrawTractorVehicle(lastStates, data.master !== undefined ? data.master : true, lastLat, lastLon, lastHdg);
            // }

            // ==========================================
            // МОДЕРНІЗОВАНИЙ БЛОК ОБРОБКИ ТЕЛЕМЕТРІЇ ТА ШЛЕЙФУ
            // ==========================================

            // 1. ЖИВА ТЕЛЕМЕТРІЯ (Камера, компас, трактор) — працює ЗАВЖДИ, незалежно від шлейфу!
            if (data.pos && data.pos.length >= 2 && data.hdg !== undefined) {
                const currentLat = data.pos[0];
                const currentLon = data.pos[1];
                const currentHdg = data.heading !== undefined ? data.heading : data.hdg; // Захист від різних назв ключів

                // Автоматична ініціалізація бази (refLat/refLon) при першій появі трактора в мережі
                if (refLat === null || refLon === null) {
                    refLat = currentLat;
                    refLon = currentLon;
                    prevSectionsCoords = []; // Скидаємо хвости з'єднувача
                    console.log(`[CORE LOG] Карта успішно ініціалізувала БАЗУ поля від поточного pos: Lat=${refLat}, Lon=${refLon}`);
                }

                // Рухаємо камеру (LERP ціль) за "живими" координатами трактора
                updateCamera(currentLat, currentLon, currentHdg);

                // Оновлюємо візуал кабіни та штанги на полі
                const currentStates = data.states || [false, false, false, false, false, false];
                window.lastReceivedStates = currentStates;
                redrawTractorVehicle(currentStates, data.master !== undefined ? data.master : true, currentLat, currentLon, currentHdg);
            } else {
                // Критичний лог: якщо сервер перестав віддавати базову телеметрію
                if (failedAttempts === 0) {
                    console.warn("[CORE LOG] Увага: Сервер прислав пакет без координат 'pos' або курсу 'hdg'!");
                }
            }

            // 2. АВТОНОМНИЙ ШЛЕЙФ (Випікання геометрії) — малює тільки тоді, коли є нові точки!
            if (data.new_points && data.new_points.length > 0) {
                console.log(`[CORE LOG] Отримано пачку шлейфу: +${data.new_points.length} точок. Відправляємо в PixiJS...`);
                updateFieldMapPixi(data.new_points);
            }



            if (data.last_index !== undefined) {
                lastReceivedIndex = data.last_index;
            } else if (data.new_points) {
                lastReceivedIndex += data.new_points.length;
            }

            updateUI(data);

            setTimeout(requestDataFromServer, 250);
        })
        .catch(err => {
            failedAttempts++;

            if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
                // const sec = (failedAttempts * 0.2).toFixed(1); // Время отсутствия связи
                // showModal(`Связь потеряна: ${sec} сек.`);
                showModal(``);

                // Пищим один раз при достижении порога
                if (failedAttempts === MAX_FAILED_ATTEMPTS) {
                    //playAlarmSound();
                }
            }
            console.error("Connection lost:", err);
            console.warn("Агронавігатор не відповідає. Очікування Flask...", err);
            lastQueueProgressTime = performance.now();
            setTimeout(requestDataFromServer, 1000);
        });
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
    //console.log(cfg);
}
buildManual();
// #region РАБОЧИЙ ЦИКЛ ОБНОВЛЕНИ ЕЛЕМЕНТОВ 
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
const modesOrder = ["AUTO", "ON", "OFF"];
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

function askUser_1(text, theme, confirmText, onConfirm) {
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
// #endregion

// #region ФУНКЦИИ РАБОТЫ С ТОЧКАМИ АВ
// ==============================================================================
// ФУНКЦИИ РАБОТЫ С ТОЧКАМИ АВ
// ==============================================================================
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
        //if (btn) btn.style.color = '#2ecc71';
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
        "Видалити лінію А-В?",
        "danger",
        "ВИДАЛИТИ",
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
                askUser("ПОМИЛКА ЗВ'ЯЗКУ", "danger", "ПРИЙНЯТИ", null);
            });
        }
    );
}
function recordManualCoords(label) {
    const lat = document.getElementById('manual_lat').value;
    const lon = document.getElementById('manual_lon').value;

    if (!lat || !lon) {
        askUser("Введіть Lat та Lon!", "danger", "ОК", null);
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
// #endregion


let currentCompassRotation = 0;
let lastServerHeading = 0;
let lastTractorPos = [0, 0];
let lastPointAPos = null; // Будемо зберігати [lat, lon] для А
let lastPointBPos = null; // Будемо зберігати [lat, lon] для В
let _abLineNum = "НЕМАЄ ЛІНІЇ";

function updateUISection(d) {
    // ********************************************************************
    //                      РАБОТА С СЕКЦИЯМИ
    // ********************************************************************
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
    const statusPanel = document.getElementById('lb_gps_mode_text'); // Замініть на ваш реальний ID елемента
    if (statusPanel) {
        statusPanel.innerText = d.gps_mode_text; // Виводимо текст із бекенду, як зараз
        // Динамічно змінюємо стиль плашки залежно від цифрового коду
        switch (d.gps_mode) {
            case 1: // ПОВНИЙ АВТОМАТ (Все ОК)
                statusPanel.style.color = "#2ecc71";
                break;
            case 2: // НАПІВ-АВТОМАТ (Заморозка карти через втрату RTK або стрибок)
                statusPanel.style.color = "#f1c40f";
                break;
            case 3: // СТОЇМО НА МІСЦІ (Ваша поточна картинка)
                statusPanel.style.color = "#fff";
                break;
            case 0: // ХАНА (Втрата GPS сигналу)
                statusPanel.style.color = "#e74c3c";
                break;
        }
    }
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
}

function updateUICompassLineAB(d) {
    // ********************************************************************
    //                      РАБОТА С КОМПАС ЛИНИЯ АВ
    // ********************************************************************
    if (d.hdg !== undefined) {
        const needle = document.getElementById('needle');
        if (needle) {
            let diff = d.hdg - lastServerHeading;
            diff = ((diff + 180) % 360 + 360) % 360 - 180;
            currentCompassRotation += diff;
            lastServerHeading = d.hdg;
            needle.style.transform = `rotate(${currentCompassRotation}deg)`;
        }
    }
    // 2. Координати точок А та В у градусах (якщо сервер їх прислав)
    if (d.ab_gps) {
        lastPointAPos = d.ab_gps.a; // [lat, lon]
        lastPointBPos = d.ab_gps.b; // [lat, lon]
    }
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

}
let updateIndexCount = 0;
function updateUI(d) {
    if (d.pos && d.pos.length >= 2) {
        lastTractorPos = [d.pos[0], d.pos[1]];
    }

    switch (updateIndexCount) {
        case 0:
            updateUISection(d);
            break;
        case 1:
            updateUICompassLineAB(d);
            break;
        case 2:

            break;
        case 3:

            break;
    }

    updateIndexCount++;
    if (updateIndexCount > 1) {
        updateIndexCount = 0;
    }


    //updateUISection(d);
    //updateUICompassLineAB(d);



    document.getElementById('area').innerText = d.area.toFixed(4);

}


// #region РАБОТА С ФАЙЛАМИ
// ==============================================================================
// ФУНКЦИИ РАБОТА С ФАЙЛАМИ
// ==============================================================================
function resetAll() {
    askUser(
        "УВАГА! <br>Очистити мапу?",
        "danger",
        "ОЧИСТИТИ",
        () => {

            fetch('/reset_area_current_file')
                .then(r => {
                    if (!r.ok) throw new Error("Сервер вернул ошибку при сбросе");
                    return r.json();
                })
                .then(data => {
                    if (data.status === "ok") {
                        console.log("Поле и карта задач успешно очищены на сервере");
                        askUser("Поле та мапа завдань <br> успішно очищені на сервері", "", "ПРИЙНЯТИ", () => {
                            setTimeout(() => {
                                location.reload();
                            }, 500);
                        });
                    }
                })
                .catch(err => {
                    console.error("Ошибка сети при вызове /reset_area:", err);
                    askUser("СЕРВЕР НЕ ВІДПОВІДАЄ<br>Перевірте зв'язок з контролером.", "danger", "ПРИЙНЯТИ", () => { });
                });
        }
    );
}

function goBack() {
    askUser(
        "УВАГА! Ви дійсно хочете <br><br>ЗКІНЧИТИ РОБОТУ?",
        "danger",
        "ЗКІНЧИТИ",
        () => {

            fetch('/save_area_current_file_and_back')
                .then(r => {
                    if (!r.ok) throw new Error("Сервер вернул ошибку при выходе из поля");
                    return r.json();
                })
                .then(data => {
                    if (data.status === "ok") {
                        console.log("goBack Поле и карта задач успешно сохранены на сервере");
                        askUser("Поле та мапа завдань <br> успішно збережені на сервері", "", "ВИХІД", () => {
                            setTimeout(() => {
                                window.location.href = '/';
                            }, 500);
                        });
                    }
                })
                .catch(err => {
                    console.error("Ошибка сети при вызове /save_field:", err);
                    askUser("СЕРВЕР НЕ ВІДПОВІДАЄ<br>Перевірте зв'язок з контролером.", "danger", "ПРИЙНЯТИ", () => { });
                });
        }
    );
}
// #endregion

//#endregion НОВОЕ ОКНО ASKUSER
// Розкладка символів для промислової екранної клавіатури (Безпечні символи)
const KB_LAYOUT = [
    '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
    'Й', 'Ц', 'У', 'К', 'Е', 'Н', 'Г', 'Ш', 'Щ', 'З',
    'Х', 'Ї', 'Ф', 'І', 'В', 'А', 'П', 'Р', 'О', 'Л',
    'Д', 'Ж', 'Є', 'Я', 'Ч', 'С', 'М', 'И', 'Т', 'Ь',
    'Б', 'Ю', '_', '-', 'SPACE', 'BACKSPACE'
];

// Ініціалізація форми (Аналог TForm.FormCreate)
document.addEventListener("DOMContentLoaded", () => {
    //loadFileList();
    initVirtualKeyboard();
});

// Генерація матриці кнопок віртуальної клавіатури
function initVirtualKeyboard() {
    const kbContainer = document.getElementById('virtualKeyboard');
    kbContainer.innerHTML = '';
    const input = document.getElementById('modalInput');

    KB_LAYOUT.forEach(key => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.innerText = key;

        // Стилізація тач-зони під пальці водія на ходу
        btn.style.cssText = `
                    height: 55px; background: #2c2c2c; color: #fff; border: 1px solid #444; 
                    border-radius: 8px; font-size: 1.2rem; font-weight: bold; cursor: pointer;
                    user-select: none; -webkit-user-select: none;
                `;

        // Обробка спеціальних розширених кнопок
        if (key === 'SPACE') {
            btn.style.gridColumn = 'span 2';
            btn.style.background = '#444';
            btn.onclick = () => input.value += ' ';
        } else if (key === 'BACKSPACE') {
            btn.style.gridColumn = 'span 2';
            btn.style.background = '#d32f2f';
            btn.onclick = () => input.value = input.value.slice(0, -1);
        } else {
            btn.onclick = () => input.value += key;
        }

        kbContainer.appendChild(btn);
    });
}

// Модернізована функція askUser (Підтримує режими ShowMessage, Confirm та InputBox)
function askUser(text, theme, confirmText, onConfirm, isPrompt = false) {
    const modal = document.getElementById('customModal');
    const modalContent = document.getElementById('modalContent');
    const modalText = document.getElementById('modalText');
    const confirmBtn = document.getElementById('modalConfirmBtn');
    const cancelBtn = document.getElementById('modalCancelBtn');
    const inputWrapper = document.getElementById('inputWrapper');
    const keyboardWrapper = document.getElementById('keyboardWrapper');
    const input = document.getElementById('modalInput');

    modalText.innerHTML = text;
    confirmBtn.innerText = confirmText;
    if (isPrompt) {
        // Вмикаємо режим введення тексту (InputBox)
        input.value = '';
        inputWrapper.style.display = 'block';
        keyboardWrapper.style.display = 'block';
        modalContent.style.maxWidth = '750px'; // Розширюємо геометрію під клавіатуру
        confirmBtn.style.background = 'var(--accent)';
        confirmBtn.style.color = '#000';
        cancelBtn.style.display = 'block';
    } else {
        // Стандартний режим інформації або підтвердження дій
        inputWrapper.style.display = 'none';
        keyboardWrapper.style.display = 'none';
        modalContent.style.maxWidth = '500px';

        if (theme === 'danger') {
            confirmBtn.style.background = '#ff4444';
            confirmBtn.style.color = '#fff';
            cancelBtn.style.display = 'block';
        } else if (theme === 'success') {
            confirmBtn.style.background = 'var(--accent)';
            confirmBtn.style.color = '#000';
            cancelBtn.style.display = 'block';
        } else {
            // Режим суто інформаційного алерту (ОК)
            confirmBtn.style.background = '#3498db';
            confirmBtn.style.color = '#fff';
            cancelBtn.style.display = 'none';
        }
    }

    // Надійна фіксація єдиного обробника події
    confirmBtn.onclick = null;
    confirmBtn.onclick = () => {
        if (isPrompt && input.value.trim() === "") {
            return; // Захист від створення порожніх файлів
        }
        modal.style.display = 'none';
        if (onConfirm) {
            onConfirm(isPrompt ? input.value.trim() : null);
        }
    };

    modal.style.display = 'flex';
}

function closeModal() {
    document.getElementById('customModal').style.display = 'none';
}
//#region 



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

// Запускаємо рекурсивну машину мережі при старті
requestDataFromServer();

console.log("Часть 4 готова: Збірка V2.6 завершена. Навігатор повністю запущено на вашій математиці з GitHub!");

