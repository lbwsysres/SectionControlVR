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

// #region ПЕРЕМИКАЧ MASTER SWITCH 
const modesOrder = ["AUTO", "ON", "OFF"];
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
// #endregion

// #region ФУНКЦИИ РАБОТЫ С ТОЧКАМИ АВ
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

// #region ОБНОВЛЕНИЕ ИНТЕРФЕЙСА
let currentCompassRotation = 0;
let lastServerHeading = 0;
let lastTractorPos = [0, 0];
let lastPointAPos = null; // Будемо зберігати [lat, lon] для А
let lastPointBPos = null; // Будемо зберігати [lat, lon] для В
let _abLineNum = "НЕМАЄ ЛІНІЇ";
let updateIndexCount = 0;
let uifailedAttempts = 0;
const UI_MAX_FAILED_ATTEMPTS = 2; // 10 попыток по 200мс = 2 секунды тишины

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

function errorConnect() {
    uifailedAttempts++;

    if (uifailedAttempts >= UI_MAX_FAILED_ATTEMPTS) {
        showModal(``);
        if (uifailedAttempts === UI_MAX_FAILED_ATTEMPTS) {
        }
    }
}
function updateUI(d) {
    //console.log("UI");
    //return;
    if (d.pos && d.pos.length >= 2) {
        lastTractorPos = [d.pos[0], d.pos[1]];
    }

    if (uifailedAttempts >= UI_MAX_FAILED_ATTEMPTS) {
        hideModal(); // Скрываем окно, если оно было открыто
    }
    uifailedAttempts = 0;

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

    document.getElementById('area').innerText = d.area.toFixed(4);
}

// #endregion

// #region РАБОТА С ПОЛЕМ
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

// #region НОВОЕ ОКНО ASKUSER
// Розкладка символів для промислової екранної клавіатури (Безпечні символи)
const KB_LAYOUT = [
    '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
    'Й', 'Ц', 'У', 'К', 'Е', 'Н', 'Г', 'Ш', 'Щ', 'З',
    'Х', 'Ї', 'Ф', 'І', 'В', 'А', 'П', 'Р', 'О', 'Л',
    'Д', 'Ж', 'Є', 'Я', 'Ч', 'С', 'М', 'И', 'Т', 'Ь',
    'Б', 'Ю', '_', '-', 'SPACE', 'BACKSPACE'
];

// // Ініціалізація форми (Аналог TForm.FormCreate)
// document.addEventListener("DOMContentLoaded", () => {
//     //loadFileList();
//     initVirtualKeyboard();
// });

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

function closeModal() {
    document.getElementById('customModal').style.display = 'none';
}
//#endregion 

console.log("UI is Load");
