/* static/js/diagnostic.js */
function updateDiagnosticPanel() {
    fetch('/api/status')
        .then(res => res.json())
        .then(data => {
            // === ОБРАБОТКА GPS ===
            const svgGps = document.getElementById('svg_gps');
            const gpsSlash = document.getElementById('gps_slash');
            const txtGpsStatus = document.getElementById('txt_gps_status');
            const txtGpsSats = document.getElementById('txt_gps_sats');
            const txtGpsSpeed = document.getElementById('txt_gps_speed');
            const txtcurrent_file = document.getElementById('current_file');
            

            txtcurrent_file.innerText = `Field: ${data.file}`;
            txtGpsSats.innerText = `Sattelite: ${data.sats}`;
            txtGpsSpeed.innerText = `Speed: ${data.speed} km/h`;
            // 2. Получаем ссылки на новые элементы DOP
            const hdopEl = document.getElementById('txt_gps_hdop');
            const vdopEl = document.getElementById('txt_gps_vdop');
            const pdopEl = document.getElementById('txt_gps_pdop');

            // 3. Записываем значения с принудительным форматированием до 1 знака после запятой
            if (hdopEl) hdopEl.innerText = Number(data.hdop || 0).toFixed(1);
            if (vdopEl) vdopEl.innerText = Number(data.vdop || 0).toFixed(1);
            if (pdopEl) pdopEl.innerText = Number(data.pdop || 0).toFixed(1);

            // 4. Динамическое изменение цвета PDOP в зависимости от точности для планшета
            if (pdopEl) {
                const pValue = Number(data.pdop || 0);
                if (pValue === 0) {
                    pdopEl.style.color = '#bdc3c7'; // Серый (нет данных)
                } else if (pValue > 3.0) {
                    pdopEl.style.color = '#e74c3c'; // Красный (плохая точность)
                } else if (pValue > 1.5) {
                    pdopEl.style.color = '#f39c12'; // Оранжевый (средняя точность)
                } else {
                    pdopEl.style.color = '#2ecc71'; // Зеленый (отличная точность)
                }
            }

            if (data.emu_enabled) {
                svgGps.setAttribute('stroke', '#2ecc71');
                gpsSlash.style.opacity = '0';
                txtGpsStatus.innerText = "SIMULATOR";
                txtGpsStatus.style.color = "#2ecc71";
                txtGpsSats.style.color = "#888";
                txtGpsSpeed.style.color = "#888";
            } else {
                // Повний список станів якості згідно специфікації NMEA GGA (data.rtk_status)
                const rtk = parseInt(data.rtk_status || 0);

                if (rtk === 4) {
                    // 4 = RTK Fix (Найвища точність, сантиметри)
                    svgGps.setAttribute('stroke', '#2ecc71'); // Яскраво-зелений
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "RTK: FIX";
                    txtGpsStatus.style.color = "#2ecc71";
                    txtGpsSats.style.color = "#3498db";
                    txtGpsSpeed.style.color = "#3498db";
                }
                else if (rtk === 5) {
                    // 5 = RTK Float (Поправки є, але точність плаває, дециметри)
                    svgGps.setAttribute('stroke', '#f1c40f'); // Жовтий
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "RTK: FLOAT";
                    txtGpsStatus.style.color = "#f1c40f";
                    txtGpsSats.style.color = "#f1c40f";
                    txtGpsSpeed.style.color = "#f1c40f";
                }
                else if (rtk === 2) {
                    // 2 = DGPS / SBAS (Працюють супутникові поправки EGNOS/WAAS)
                    svgGps.setAttribute('stroke', '#3498db'); // Синій (чудово підходить для диференційного режиму)
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "DGPS";
                    txtGpsStatus.style.color = "#3498db";
                    txtGpsSats.style.color = "#bdc3c7";
                    txtGpsSpeed.style.color = "#bdc3c7";
                }
                else if (rtk === 1) {
                    // 1 = Autonomous GPS (Звичайний режим без поправок, точність ~2-3 метри)
                    svgGps.setAttribute('stroke', '#e67e22'); // Помаранчевий
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "GPS";
                    txtGpsStatus.style.color = "#e67e22";
                    txtGpsSats.style.color = "#e67e22";
                    txtGpsSpeed.style.color = "#e67e22";
                }
                else if (rtk === 6) {
                    // 6 = Estimated / Dead Reckoning (Навігація за датчиками/гіроскопами без супутників)
                    svgGps.setAttribute('stroke', '#9b59b6'); // Фіолетовий
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "INERTIAL";
                    txtGpsStatus.style.color = "#9b59b6";
                    txtGpsSats.style.color = "#555";
                    txtGpsSpeed.style.color = "#555";
                }
                else if (rtk === 3) {
                    // 3 = PPS (Військовий або прецизійний режим високої точності)
                    svgGps.setAttribute('stroke', '#1abc9c'); // Бірюзовий
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "PPS";
                    txtGpsStatus.style.color = "#1abc9c";
                    txtGpsSats.style.color = "#bdc3c7";
                    txtGpsSpeed.style.color = "#bdc3c7";
                }
                else {
                    // 0 = Invalid/No Fix (Немає зв'язку або супутників менше 3-х)
                    svgGps.setAttribute('stroke', '#e74c3c'); // Червоний
                    gpsSlash.style.opacity = '1';
                    txtGpsStatus.innerText = "NO FIX";
                    txtGpsStatus.style.color = "#e74c3c";
                    txtGpsSats.style.color = "#555";
                    txtGpsSpeed.style.color = "#555";
                }

            }

            // === ОБРАБОТКА BOARD ===
            const svgBoard = document.getElementById('svg_board');
            const boardSlash = document.getElementById('board_slash');
            const txtBoardStatus = document.getElementById('txt_board_status');
            const t1 = document.getElementById('board_template_1');

            if (data.board_connected) {
                svgBoard.setAttribute('stroke', '#2ecc71');
                boardSlash.style.opacity = '0';
                txtBoardStatus.innerText = "CONNECT";
                txtBoardStatus.style.color = "#2ecc71";
                t1.innerText = "Вольтаж: —";
                t1.style.color = "#888";
            } else {
                svgBoard.setAttribute('stroke', '#e74c3c');
                boardSlash.style.opacity = '1';
                txtBoardStatus.innerText = "OFF LINE";
                txtBoardStatus.style.color = "#e74c3c";
                t1.innerText = "Параметр: —";
                t1.style.color = "#444";
            }
        })
        .catch(err => {
            console.error("Diag error:", err);
            document.getElementById('svg_gps').setAttribute('stroke', '#e74c3c');
            document.getElementById('svg_board').setAttribute('stroke', '#e74c3c');
            document.getElementById('gps_slash').style.opacity = '1';
            document.getElementById('board_slash').style.opacity = '1';
            document.getElementById('txt_gps_status').innerText = "OFF LINE";
            document.getElementById('txt_board_status').innerText = "OFF LINE";
            document.getElementById('txt_gps_speed').innerText = "-.- km/h";
            document.getElementById('txtcurrent_file').innerText = "NONE";
        });
}

// Опрос раз в секунду
setInterval(updateDiagnosticPanel, 1000);
