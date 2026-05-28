// =======================================================================
// implements_logic.js --- ЧАСТИНА 1 З 3 (КЛОНУВАННЯ ТА СПИСОК)
// =======================================================================

let originalImplements = []; // Сховище оригіналів з сервера
let selectedImplementId = null;

// НАШІ КЛЮЧОВІ ЗМІННІ ОЗУ ДЛЯ РОЛБЕКУ
let originalCopy = null;      // Сліпок обраного знаряддя ДО редагування
let currentEditingCopy = null; // Поточна робоча копія під повзунки

// 1. ЗАВАНТАЖЕННЯ СПИСКУ ЗНАРЯДЬ ПРИ СТАРТІ СТОРІНКИ
async function loadImplementsList(selectIdAfterLoad = null) {
    try {
        const response = await fetch('/api/implements/list');
        originalImplements = await response.json();
        renderSidebarList();

        if (selectIdAfterLoad) {
            selectImplement(selectIdAfterLoad);
        } else if (selectedImplementId) {
            const exists = originalImplements.some(i => i.id === selectedImplementId);
            if (exists) selectImplement(selectedImplementId);
            else resetEditorView();
        } else {
            resetEditorView();
        }
    } catch (err) {
        console.error("Помилка завантаження списку знарядь:", err);
    }
}

// 2. ОТРИМАННЯ ПОВНИХ ДЕТАЛЕЙ ЗНАРЯДДЯ З ОРИГІНАЛЬНОГО МАСИВУ
function getFullImplementData(id) {
    const found = originalImplements.find(i => i.id === id);
    if (!found) return null;

    // Створюємо та повертаємо повну валідну структуру під залізо
    return {
        id: found.id,
        name: found.name || "Нове знаряддя",
        implement_type: found.implement_type || found.type || "MOUNTED",
        geometry: {
            section_widths: found.section_widths || [3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
            offset_back: found.offset_back !== undefined ? found.offset_back : 1.5,
            offset_side: 0.0
        },
        dynamics: {
            look_ahead_on_time: 0.8,
            look_ahead_off_time: 0.4
        }
    };
}

// 3. ВИБІР ЗНАРЯДДЯ У ЛІВІЙ КОЛОНЦІ ПАЛЬЦЕМ
function selectImplement(id) {
    selectedImplementId = id;

    const fullData = getFullImplementData(id);
    if (!fullData) return;

    // --- МАГІЯ ГЛИБОКОГО КЛОНУВАННЯ ДЛЯ ROLLBACK ---
    originalCopy = JSON.parse(JSON.stringify(fullData));        // Сліпок-еталон
    currentEditingCopy = JSON.parse(JSON.stringify(fullData)); // Робоча копія під інпути

    // Підсвічуємо активний рядок у списку
    document.querySelectorAll('.impl-item').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-id') === id);
    });

    // Вмикаємо інтерфейс редактора
    document.getElementById("no-selection-msg").style.display = "none";
    document.getElementById("editor-container").style.display = "flex";

    // Активуємо кнопки дій зліва
    document.getElementById("btn-activate-work").disabled = false;
    document.getElementById("btn-delete-work").disabled = false;
    // [МИТТЄВА АКТИВАЦІЯ ЛІВИХ КНОПОК ПРИ ВИБОРІ КАРТКИ]
    const btnActivate = document.getElementById("btn-activate-work");
    const btnDelete = document.getElementById("btn-delete-work");

    if (btnActivate && btnDelete) {
        // Знімаємо апаратне блокування
        btnActivate.disabled = false;
        btnDelete.disabled = false;

        // Запалюємо кнопки на 100% яскравості під палець!
        btnActivate.style.opacity = "1.0";
        btnDelete.style.opacity = "1.0";
    }


    // Заповнюємо поля в кутку редагування
    updateEditorUiFields();
}
// =======================================================================
// implements_logic.js --- ЧАСТИНА 2 З 3 (СИНХРОНІЗАЦІЯ ТА ТАЧ-СПІННЕРИ)
// =======================================================================

// 4. ОНОВЛЕННЯ ПОЛІВ НА ЕКРАНІ З ПОТОЧНОЇ РОБОЧОЇ КОПІЇ
function updateEditorUiFields() {
    if (!currentEditingCopy) return;

    try {
        document.getElementById("impl-name-input").value = currentEditingCopy.name;
        document.getElementById("impl-type-select").value = currentEditingCopy.implement_type;
        document.getElementById("impl-offset-back").value = currentEditingCopy.geometry.offset_back.toFixed(1);

        const widths = currentEditingCopy.geometry.section_widths || [3.0];
        document.getElementById("impl-sections-count").value = widths.length;

        // Чистий фікс індексу масиву для toFixed
        const singleWidth = (Array.isArray(widths) && widths.length > 0) ? widths[0] : 3.0;
        document.getElementById("impl-section-width").value = Number(singleWidth).toFixed(1);

        // МИТТЄВЕ ПОРІВНЯННЯ ОЗУ ДЛЯ КНОПОК
        const isChanged = JSON.stringify(originalCopy) !== JSON.stringify(currentEditingCopy);

        // Перевіряємо наявність елементів на екрані, щоб уникнути помилок в консолі
        const saveBtn = document.getElementById("btn-save-disk");
        const rollbackBtn = document.getElementById("btn-rollback");

        if (saveBtn && rollbackBtn) {
            // Кнопки активуються ТІЛЬКИ якщо водій реально щось змінив (шлях, назву або форсунки)
            saveBtn.disabled = !isChanged;
            rollbackBtn.disabled = !isChanged;

            // =======================================================================
            // 🎨 ДОДАТКОВИЙ ВІЗУАЛЬНИЙ ФЕН - ШУЙ(Тач - ергономіка):
            // Якщо кнопка вимкнена — робимо її напівпрозорою, щоб водій бачив, 
            // що тицяти її зараз немає сенсу.Як тільки змінив щось — вона спалахує на 100 % !
            // =======================================================================
            saveBtn.style.opacity = isChanged ? "1.0" : "0.3";
            rollbackBtn.style.opacity = isChanged ? "1.0" : "0.3";
        }

    } catch (err) {
        console.error("Помилка оновлення полів форми:", err);
    }
}

function updateEditorUiFields_1() {
    if (!currentEditingCopy) return;

    document.getElementById("impl-name-input").value = currentEditingCopy.name;
    document.getElementById("impl-type-select").value = currentEditingCopy.implement_type;
    document.getElementById("impl-offset-back").value = currentEditingCopy.geometry.offset_back.toFixed(1);

    const widths = currentEditingCopy.geometry.section_widths || [3.0];
    document.getElementById("impl-sections-count").value = widths.length;

    // Беремо ширину першої секції для виведення в загальне поле тач-спіннера
    const singleWidth = widths[0] || 3.0;
    document.getElementById("impl-section-width").value = singleWidth.toFixed(1);

    // МИТТЄВЕ ПОРІВНЯННЯ ОЗУ: Якщо копія відрізняється від еталону — запалюємо кнопки!
    const isChanged = JSON.stringify(originalCopy) !== JSON.stringify(currentEditingCopy);
    document.getElementById("btn-save-disk").disabled = !isChanged;
    document.getElementById("btn-rollback").disabled = !isChanged;
}

// 5. ОНОВЛЕННЯ ДАНИХ У РОБОЧІЙ КОПІЇ ПРИ ВВЕДЕННІ ТЕКСТУ
function updateCurrentCopy(key, value) {
    if (!currentEditingCopy) return;
    currentEditingCopy[key] = value;
    updateEditorUiFields();
}

// 6. РОБОТА ВЕЛИКИХ КНОПОК ПЛЮС / МИНУС (ГЕОМЕТРІЯ)
function adjustGeometryValue(field, delta) {
    if (!currentEditingCopy) return;

    if (field === 'offset_back') {
        let val = currentEditingCopy.geometry.offset_back + delta;
        // Захист меж: винос штанги назад від 0 до 15 метрів
        currentEditingCopy.geometry.offset_back = Math.max(0.0, Math.min(15.0, val));
    }
    else if (field === 'single_section_width') {
        let widths = currentEditingCopy.geometry.section_widths || [3.0];
        let currentSingleWidth = widths[0] || 3.0;
        let newVal = currentSingleWidth + delta;

        // Захист меж ширини однієї секції від 0.5 до 10 метрів
        newVal = Math.max(0.5, Math.min(10.0, newVal));

        // Прирівнюємо всі секції до цієї нової ширини для лінійного обприскувача
        currentEditingCopy.geometry.section_widths = widths.map(() => newVal);
    }
    updateEditorUiFields();
}

// 7. КЕРУВАННЯ КІЛЬКІСТЮ СЕКЦІЙ ШТАНГИ (Додавання / видалення елементів масиву)
function adjustSectionsCount(delta) {
    if (!currentEditingCopy) return;

    let currentWidths = currentEditingCopy.geometry.section_widths || [3.0];
    let currentCount = currentWidths.length;
    let newCount = currentCount + delta;

    // Апаратні межі: від 1 до 24 секцій (реле) на обприскувачі
    newCount = Math.max(1, Math.min(24, newCount));

    if (newCount > currentCount) {
        // Якщо секцій побільшало — копіюємо ширину поточної крайньої секції
        const baseWidth = currentWidths[currentCount - 1] || 3.0;
        for (let i = currentCount; i < newCount; i++) {
            currentWidths.push(baseWidth);
        }
    } else if (newCount < currentCount) {
        // Якщо секцій поменшало — просто відрізаємо хвіст масиву штанги
        currentWidths = currentWidths.slice(0, newCount);
    }

    currentEditingCopy.geometry.section_widths = currentWidths;
    updateEditorUiFields();
}
// =======================================================================
// implements_logic.js --- ЧАСТИНА 3 З 3 (ROLLBACK, ЗБЕРЕЖЕННЯ ТА СТАРТ)
// =======================================================================

// 8. 🟢 МЕХАНІЗМ РОЛБЕКУ (МИТТЄВИЙ ВІДКАТ ЗМІН В ОЗУ)
function rollbackChanges() {
    if (!originalCopy) return;

    // Просто праємо поточну копію і заново глибоко клонуємо оригінал-еталон
    currentEditingCopy = JSON.parse(JSON.stringify(originalCopy));

    // Оновлюємо екран за 1 мілісекунду. eMMC і диск взагалі відпочивали!
    updateEditorUiFields();
    printConsoleLog("Зміни скасовані. ОЗУ успішно відкочено до оригіналу.");
}

// 9. ЗАПИС ПЕРЕВІРЕНОЇ КОНФІГУРАЦІЇ НА ДИСК EMMC
async function saveChangesToDisk() {
    console.log(currentEditingCopy);
    if (!currentEditingCopy) return;

    try {
        const response = await fetch('/api/implements/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentEditingCopy)
        });

        if (response.ok) {
            // Оновлюємо еталонний сліпок — тепер змінена копія стала новим стандартом
            originalCopy = JSON.parse(JSON.stringify(currentEditingCopy));

            // Блокуємо кнопки, бо ОЗУ знову ідентичне диску
            document.getElementById("btn-save-disk").disabled = true;
            document.getElementById("btn-rollback").disabled = true;

            // Перезавантажуємо ліву колонку, щоб оновилися метри та дати
            await loadImplementsList(currentEditingCopy.id);
            printConsoleLog("Конфігурація успішно записана на диск eMMC.");
        }
    } catch (err) {
        console.error("Помилка збереження знаряддя на сервері:", err);
    }
}

// 10. АКТИВАЦІЯ ТЕХНІКИ (Кнопка В РОБОТУ — Миттєва зміна маски штанги)
async function activateImplement() {
    if (!selectedImplementId) return;

    try {
        const response = await fetch('/api/implements/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: selectedImplementId })
        });

        if (response.ok) {
            printConsoleLog(`Знаряддя ${selectedImplementId} успішно активоване в ОЗУ математики.`);
            // Викликаємо ваше дельфійське вікно для красивого підтвердження водію
            if (typeof askUser === 'function') {
                const found = originalImplements.find(i => i.id === selectedImplementId);
                const name = found ? found.name : "знаряддя";
                askUser(`<b>Успішно активовано!</b><br><small>Конфігурація "${name}" передана в автопілот.</small>`, 'success', 'ОК', null);
            }
        }
    } catch (err) {
        console.error("Помилка активації знаряддя через API:", err);
    }
}

// 11. СТВОРЕННЯ НОВОГО ЧИСТОГО ШАБЛОНУ (Додати ➕)
async function createNewImplement() {
    try {
        const response = await fetch('/api/implements/create', { method: 'POST' });
        const newTemplate = await response.json();

        // Штучно штовхаємо заготовку на початок нашого ОЗУ масиву
        if (!originalImplements) originalImplements = [];
        originalImplements.unshift({
            id: newTemplate.id,
            name: newTemplate.name,
            type: newTemplate.implement_type,
            section_widths: newTemplate.geometry.section_widths,
            offset_back: newTemplate.geometry.offset_back,
            width: newTemplate.geometry.section_widths.reduce((a, b) => a + b, 0),
            date: "Щойно створено"
        });

        // Оновлюємо ліву колонку та примусово відкриваємо редагування нової заготовки
        renderSidebarList();
        selectImplement(newTemplate.id);
    } catch (err) {
        console.error("Помилка створення шаблону знаряддя:", err);
    }
}

// 12. ВИДАЛЕННЯ КАРТКИ ЗНАРЯДДЯ (🗑️)
function deleteImplement() {
    if (!selectedImplementId) return;

    // Викликаємо дельфійську модалку замість стандартного потворного confirm() браузера!
    if (typeof askUser === 'function') {
        const found = originalImplements.find(i => i.id === selectedImplementId);
        const name = found ? found.name : "це знаряддя";

        askUser(`Видалити конфігурацію "${name}" з пам'яті?<br><small>Ця дія повністю зітре файл з диска eMMC.</small>`, 'danger', 'ВИДАЛИТЬ', async () => {
            try {
                const response = await fetch('/api/implements/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: selectedImplementId })
                });

                if (response.ok) {
                    selectedImplementId = null;
                    await loadImplementsList();
                }
            } catch (err) {
                console.error("Помилка видалення знаряддя:", err);
            }
        });
    }
}

// 13. РЕНДЕРИНГ ЛІВОЇ КОЛОНКИ СПИСКУ (ВЕЛИКІ РЯДКИ ПІД ПАЛЬЦІ)
function renderSidebarList() {
    const container = document.getElementById("implements-list-container");
    container.innerHTML = "";

    if (!originalImplements || originalImplements.length === 0) {
        container.innerHTML = `
            <div style="padding: 30px 20px; color: #666; text-align: center; font-size: 1.1rem; line-height: 1.4;">
                Список знарядь порожній.<br><br>Натисніть ➕ для створення.
            </div>
        `;
        return;
    }

    originalImplements.forEach(impl => {
        const item = document.createElement("div");
        item.className = `impl-item ${selectedImplementId === impl.id ? 'active' : ''}`;
        item.setAttribute('data-id', impl.id);
        item.onclick = () => selectImplement(impl.id);

        // Визначаємо загальну ширину для швидкого виведення
        let totalW = 0;
        if (impl.width !== undefined) totalW = impl.width;
        else if (impl.geometry && impl.geometry.section_widths) {
            totalW = impl.geometry.section_widths.reduce((a, b) => a + b, 0);
        } else totalW = 21.0;

        item.innerHTML = `
            <div class="impl-info">
                <div class="impl-title">${impl.name || "Без назви"}</div>
                <div class="impl-meta">Ширина: ${totalW.toFixed(1)}м | Змінено: ${impl.date || "---"}</div>
            </div>
        `;
        container.appendChild(item);
    });
}
function resetEditorView() {
    selectedImplementId = null;
    originalCopy = null;
    currentEditingCopy = null;

    document.getElementById("no-selection-msg").style.display = "flex";
    document.getElementById("editor-container").style.display = "none";
    
    // [БЛОКУВАННЯ ТА ЗГАСАННЯ ЛІВИХ КНОПОК]
    const btnActivate = document.getElementById("btn-activate-work");
    const btnDelete = document.getElementById("btn-delete-work");

    if (btnActivate && btnDelete) {
        btnActivate.disabled = true;
        btnDelete.disabled = true;
        
        // Робимо кнопки тьмяними, показуючи, що тицяти немає сенсу
        btnActivate.style.opacity = "0.3";
        btnDelete.style.opacity = "0.3";
    }
}

function resetEditorView_1() {
    selectedImplementId = null;
    originalCopy = null;
    currentEditingCopy = null;

    document.getElementById("no-selection-msg").style.display = "flex";
    document.getElementById("editor-container").style.display = "none";
    document.getElementById("btn-activate-work").disabled = true;
    document.getElementById("btn-delete-work").disabled = true;
}

function printConsoleLog(msg) {
    console.log(`[ImplementManager JS] ${msg}`);
}

// =======================================================================
// 🟢 ОФІЦІЙНІ ФУНКЦІЇ-МІСТКИ ДЛЯ ДЕЛЬФІЙСЬКИХ МОДАЛОК
// Вони точно збігаються з onclick="..." ваших великих кнопок в HTML!
// =======================================================================

// Викликається при натисканні на кнопку СКАСУВАТИ (onclick="askRollback()")
function askRollback() {
    console.log("askRollback");
    askUser(
        'Скасувати всі поточні зміни?<br><small>Конфігурація ОЗУ повернеться до збереженого оригіналу</small>',
        'danger',
        'ОТМЕНА',
        () => { rollbackChanges(); } // викликає рідний метод відкату з ОЗУ
    );
}

// Викликається при натисканні на кнопку ЗБЕРЕГТИ (onclick="confirmSaveImplement()")
function confirmSaveImplement() {
    console.log("confirmSaveImplement");
    askUser(
        'Зберегти конфігурацію знаряддя на eMMC?<br><small>Зміни будуть записані в базу даних обладнання</small>',
        'success',
        'ЗБЕРЕГТИ',
        () => { saveChangesToDisk(); } // викликає рідний метод запису на диск
    );
}

// 14. СТАРТОВА ІНІЦІАЛІЗАЦІЯ ПРИ ЗАВАНТАЖЕННІ СТОРІНКИ БРАУЗЕРОМ
document.addEventListener("DOMContentLoaded", () => {
    printConsoleLog("Запуск інтерфейсу Менеджера знарядь...");
    loadImplementsList();
});
