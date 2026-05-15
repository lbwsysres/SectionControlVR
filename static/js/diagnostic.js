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

            txtGpsSats.innerText = `Спутники: ${data.sats}`;

            if (data.emu_enabled) {
                svgGps.setAttribute('stroke', '#2ecc71');
                gpsSlash.style.opacity = '0';
                txtGpsStatus.innerText = "СИМУЛЯТОР";
                txtGpsStatus.style.color = "#2ecc71";
                txtGpsSats.style.color = "#888";
            } else {
                if (data.rtk_status === 4) {
                    svgGps.setAttribute('stroke', '#2ecc71');
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "RTK: FIX";
                    txtGpsStatus.style.color = "#2ecc71";
                    txtGpsSats.style.color = "#3498db";
                } else if (data.rtk_status === 5 || data.rtk_status === 2) {
                    svgGps.setAttribute('stroke', '#f1c40f');
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "RTK: FLOAT";
                    txtGpsStatus.style.color = "#f1c40f";
                    txtGpsSats.style.color = "#f1c40f";
                } else if (data.rtk_status === 1) {
                    svgGps.setAttribute('stroke', '#e67e22');
                    gpsSlash.style.opacity = '0';
                    txtGpsStatus.innerText = "СИГНАЛ: GPS";
                    txtGpsStatus.style.color = "#e67e22";
                    txtGpsSats.style.color = "#e67e22";
                } else {
                    svgGps.setAttribute('stroke', '#e74c3c');
                    gpsSlash.style.opacity = '1';
                    txtGpsStatus.innerText = "NO FIX";
                    txtGpsStatus.style.color = "#e74c3c";
                    txtGpsSats.style.color = "#555";
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
                txtBoardStatus.innerText = "ПЛАТА: ОК";
                txtBoardStatus.style.color = "#2ecc71";
                t1.innerText = "Вольтаж: —";
                t1.style.color = "#888";
            } else {
                svgBoard.setAttribute('stroke', '#e74c3c');
                boardSlash.style.opacity = '1';
                txtBoardStatus.innerText = "ОФФЛАЙН";
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
            document.getElementById('txt_gps_status').innerText = "СЕРВЕР DOWN";
            document.getElementById('txt_board_status').innerText = "СЕРВЕР DOWN";
        });
}

// Опрос раз в секунду
setInterval(updateDiagnosticPanel, 1000);
