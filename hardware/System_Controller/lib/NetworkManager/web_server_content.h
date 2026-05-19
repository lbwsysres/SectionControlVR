#ifndef WEB_SERVER_CONTENT_H
#define WEB_SERVER_CONTENT_H

#include <Arduino.h>

// Красива і легка сторінка на чистому CSS з вкладками
const char index_html[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VRA System Setup</title>
    <style>
        body { font-family: sans-serif; background: #1e1e1e; color: #eaedd5; margin: 0; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background: #2d2d2d; padding: 20px; border-radius: 8px; border-top: 4px solid #2ecc71; }
        h2 { text-align: center; color: #2ecc71; margin-top: 0; }
        
        /* Стилі вкладок */
        .tabs { display: flex; margin-bottom: 20px; border-bottom: 2px solid #444; }
        .tab-btn { background: none; border: none; color: #888; padding: 10px 20px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .tab-btn.active { color: #2ecc71; border-bottom: 3px solid #2ecc71; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        /* Стилі форм */
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 14px; }
        input, select { width: 100%; padding: 10px; border: 1px solid #444; background: #1e1e1e; color: #fff; border-radius: 4px; box-sizing: border-box; }
        input:focus { border-color: #2ecc71; outline: none; }
        .btn { background: #2ecc71; color: #1e1e1e; border: none; padding: 12px; width: 100%; font-size: 16px; font-weight: bold; border-radius: 4px; cursor: pointer; margin-top: 10px; }
        .btn:hover { background: #27ae60; }
        .status { text-align: center; font-weight: bold; margin-top: 15px; color: #3498db; }
    </style>
</head>
<body>

<div class="container">
    <h2>SectionControlVR Setup</h2>
    
    <div class="tabs">
        <button class="tab-btn active" onclick="openTab('network')">Мережа</button>
        <button class="tab-btn" onclick="openTab('hydraulics')">Гідравліка</button>
        <button class="tab-btn" onclick="openTab('boom')">Штанга</button>
    </div>

    <form id="configForm">
        <!-- ВКЛАДКА: МЕРЕЖА -->
        <div id="network" class="tab-content active">
            <div class="form-group">
                <label>Wi-Fi SSID (Назва мережі):</label>
                <input type="text" name="ssid" id="ssid" placeholder="Введіть назву мережі">
            </div>
            <div class="form-group">
                <label>Wi-Fi Пароль:</label>
                <input type="password" name="password" id="password" placeholder="Введіть пароль">
            </div>
            <div class="form-group">
                <label>IP-адреса Сервера (Python):</label>
                <input type="text" name="server_ip" id="server_ip" placeholder="Приклад: 192.168.1.100">
            </div>
        </div>

        <!-- ВКЛАДКА: ГІДРАВЛІКА -->
        <div id="hydraulics" class="tab-content">
            <div class="form-group">
                <label>Імпульсів витратоміра на 1 літр:</label>
                <input type="number" name="flow_pulses" id="flow_pulses" value="450">
            </div>
            <div class="form-group">
                <label>Мінімальний ШІМ насоса (%):</label>
                <input type="number" name="pwm_min" id="pwm_min" value="15" min="0" max="100">
            </div>
            <div class="form-group">
                <label>Максимальний ШІМ насоса (%):</label>
                <input type="number" name="pwm_max" id="pwm_max" value="100" min="0" max="100">
            </div>
            <div class="form-group">
                <label>Зона нечутливості ПІД (Deadband %):</label>
                <input type="number" name="deadband" id="deadband" value="2" min="0" max="20">
            </div>
        </div>

        <!-- ВКЛАДКА: ШТАНГА -->
        <div id="boom" class="tab-content">
            <div class="form-group">
                <label>Загальна кількість секцій/клапанів:</label>
                <input type="number" name="total_sections" id="total_sections" value="5" min="1" max="32">
            </div>
            <div class="form-group">
                <label>Тип виконання клапанів:</label>
                <select name="hardware_mode" id="hardware_mode">
                    <option value="0">Локальні MOSFET / Реле</option>
                    <option value="1">Мережеві CAN-клапани (Китай)</option>
                </select>
            </div>
        </div>

        <button type="button" class="btn" onclick="saveConfig()">Зберегти налаштування</button>
    </form>
    
    <div id="statusMessage" class="status"></div>
</div>

<script>
    // Логіка перемикання вкладок
    function openTab(tabId) {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');
        event.currentTarget.classList.add('active');
    }

    // Завантаження поточних налаштувань - ЖОРСТКО і прямо за ID полів
    window.onload = function() {
        fetch('/get-config')
            .then(response => response.json())
            .then(data => {
                if(data.ssid) document.getElementById('ssid').value = data.ssid;
                if(data.password) document.getElementById('password').value = data.password;
                if(data.server_ip) document.getElementById('server_ip').value = data.server_ip;
                
                // Переконуємося, що числа записуються як чисті числа
                document.getElementById('flow_pulses').value    = parseInt(data.flow_pulses) || 452;
                document.getElementById('pwm_min').value        = parseInt(data.pwm_min) || 17;
                document.getElementById('pwm_max').value        = parseInt(data.pwm_max) || 100;
                document.getElementById('deadband').value       = parseInt(data.deadband) || 2;
                document.getElementById('total_sections').value = parseInt(data.total_sections) || 5;
                document.getElementById('hardware_mode').value  = parseInt(data.hardware_mode) || 0;
                //document.getElementById('flow_window').value    = parseInt(data.flow_window) || 3;
            });
    };

    // Відправка нових налаштувань - Збираємо чистий правильний JSON вручну
    function saveConfig() {
        const msgDiv = document.getElementById('statusMessage');
        msgDiv.style.color = '#3498db';
        msgDiv.innerText = "Збереження...";

        // Збираємо об'єкт вручну, примусово перетворюючи текстові інпути на чисті Int
        const obj = {
            ssid:           document.getElementById('ssid').value,
            password:       document.getElementById('password').value,
            server_ip:      document.getElementById('server_ip').value,
            flow_pulses:    parseInt(document.getElementById('flow_pulses').value) || 452,
            pwm_min:        parseInt(document.getElementById('pwm_min').value) || 17,
            pwm_max:        parseInt(document.getElementById('pwm_max').value) || 100,
            deadband:       parseInt(document.getElementById('deadband').value) || 2,
            total_sections: parseInt(document.getElementById('total_sections').value) || 5,
            hardware_mode:  parseInt(document.getElementById('hardware_mode').value) || 0,
            //flow_window:    parseInt(document.getElementById('flow_window').value) || 3
        };

        fetch('/save-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(obj) // Шлемо чисті інтеджери, без лапок!
        })
        .then(res => res.text())
        .then(text => {
            msgDiv.style.color = '#2ecc71';
            msgDiv.innerText = "Конфіг оновлено успішно! Контролер перезавантажується...";
        })
        .catch(err => {
            msgDiv.style.color = '#e74c3c';
            msgDiv.innerText = "Помилка збереження!";
        });
    }
</script>

</body>
</html>
)rawhtml";

#endif
