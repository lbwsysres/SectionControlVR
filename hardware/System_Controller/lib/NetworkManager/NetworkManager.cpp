#include "DebugLog.h"
#include "NetworkManager.h"
#include "FlowController.h" // Обов'язковий інклуд для зв'язку
#include <LittleFS.h>

// Ініціалізуємо сокет на шляху /ws
VraNetworkManager::VraNetworkManager(ConfigManager *configMgr)
    : _server(80), _ws("/ws")
{
    _configMgr = configMgr;
    _flowController = nullptr;
    _lastHeartbeat = millis();
    _isEmergency = false;
}

void VraNetworkManager::begin()
{
    SystemConfig &cfg = _configMgr->getConfig();

    if (strlen(cfg.ssid) == 0)
    {
        WiFi.mode(WIFI_AP);
    }
    else
    {
        DBG_OUTPUT_PORT.print(F("[WIFI] Connecting to: "));
        DBG_OUTPUT_PORT.println(cfg.ssid);
        WiFi.mode(WIFI_STA);
        WiFi.begin(cfg.ssid, cfg.password);

        int attempts = 0;
        while (WiFi.status() != WL_CONNECTED && attempts < 20)
        {
            vTaskDelay(pdMS_TO_TICKS(500)); // Безпечний сон FreeRTOS
            DBG_OUTPUT_PORT.print(".");
            attempts++;
        }
        DBG_OUTPUT_PORT.println();
    }

    if (WiFi.status() != WL_CONNECTED)
    {
        DBG_OUTPUT_PORT.println(F("[WIFI] Fallback to Access Point..."));
        WiFi.mode(WIFI_AP);
        WiFi.softAP("VRA-Sprayer-Setup", "");
        DBG_OUTPUT_PORT.print(F("[WIFI] AP Web-UI: "));
        DBG_OUTPUT_PORT.println(WiFi.softAPIP());
    }
    else
    {
        DBG_OUTPUT_PORT.print(F("[WIFI] Connected! IP: "));
        DBG_OUTPUT_PORT.println(WiFi.localIP());
        _lastHeartbeat = millis();
    }

    setupEndpoints();
    _server.begin();
}

void VraNetworkManager::checkConnection()
{
    // Якщо зараз увімкнено будь-який режим калібрування — повністю ігноруємо відсутність Python!
    if (_flowController != nullptr && _flowController->isInAnyCalibMode())
    {
        _isEmergency = false;      // Скидаємо аварію
        _lastHeartbeat = millis(); // Обманюємо таймер, щоб він не цокав
        return;
    }
    if (WiFi.getMode() == WIFI_STA && WiFi.status() != WL_CONNECTED)
    {
        WiFi.disconnect();
        WiFi.reconnect();
        vTaskDelay(pdMS_TO_TICKS(2000));
        return;
    }

    if (WiFi.getMode() == WIFI_STA && (millis() - _lastHeartbeat > _heartbeatTimeout))
    {
        if (!_isEmergency)
        {
            _isEmergency = true;
            DBG_OUTPUT_PORT.println(F("[EMERGENCY] Connection LOST! Shutting down spray..."));
        }
    }
}

void VraNetworkManager::updateHeartbeat()
{
    _lastHeartbeat = millis();
    if (_isEmergency)
    {
        _isEmergency = false;
        DBG_OUTPUT_PORT.println(F("[SYSTEM] Connection restored. Emergency cleared."));
    }
}

// ОБРОБНИК СИРИХ ПОДІЙ ВЕБ-СОКЕТУ
void VraNetworkManager::onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client,
                                  AwsEventType type, void *arg, uint8_t *data, size_t len)
{
    if (type == WS_EVT_CONNECT)
    {
        DBG_OUTPUT_PORT.printf("[WS] Client #%u connected from %s\n", client->id(), client->remoteIP().toString().c_str());
    }
    else if (type == WS_EVT_DISCONNECT)
    {
        DBG_OUTPUT_PORT.printf("[WS] Client #%u disconnected\n", client->id());
    }
    else if (type == WS_EVT_DATA)
    {
        AwsFrameInfo *info = (AwsFrameInfo *)arg;
        if (info->opcode == WS_TEXT)
        {
            data[len] = 0; // Перетворюємо масив байт на C-рядок
            String msg = String((char *)data);
            handleWebSocketMessage(msg, client->id());
        }
    }
}

// ПАРСИНГ ТЕКСТОВИХ КОМАНД КАЛІБРУВАННЯ З САЙТУ
void VraNetworkManager::handleWebSocketMessage(String msg, uint32_t client_id)
{
    DBG_OUTPUT_PORT.print(F("[WS CALIB] SocketMessage"));
    DBG_OUTPUT_PORT.println(msg);

    if (_flowController == nullptr)
        return;

    if (msg == "START_FLOW_CALIB")
    {
        DBG_OUTPUT_PORT.println(F("[WS CALIB] Command: START_FLOW_CALIB"));
        _flowController->startCalibrationMode();
        return;
    }

    if (msg == "STOP_FLOW_CALIB")
    {
        DBG_OUTPUT_PORT.println(F("[WS CALIB] Command: STOP_FLOW_CALIB"));
        int totalPulses = _flowController->stopCalibrationMode();

        // Повертаємо накопичені імпульси саме тому клієнту, який викликав тест
        _ws.text(client_id, "PULSES:" + String(totalPulses));
        return;
    }

    if (msg == "START_PUMP_TEST")
    {
        DBG_OUTPUT_PORT.println(F("[WS CALIB] Command: START_PUMP_TEST"));
        _flowController->startPumpMaxTest();
        return;
    }
}

/*
void VraNetworkManager::setupEndpoints()
{
    // Підключаємо наш обробник подій сокету до сервера
    _ws.onEvent([this](AsyncWebSocket *s, AsyncWebSocketClient *c, AwsEventType t, void *a, uint8_t *d, size_t l)
                { this->onWsEvent(s, c, t, a, d, l); });
    _server.addHandler(&_ws);

    _server.on("/", HTTP_GET, [](AsyncWebServerRequest *request)
               {
    if (LittleFS.exists("/index.html")) {
        request->send(LittleFS, "/index.html", "text/html");
    } else {
        request->send(404, "text/plain", "CRITICAL ERROR: /index.html missing!");
    } });

    // ОНОВЛЕНО: Додано віддачу параметра max_pump_flow у JSON
    _server.on("/get-config", HTTP_GET, [this](AsyncWebServerRequest *request)
               {
        SystemConfig& cfg = _configMgr->getConfig();
        JsonDocument doc;
        doc["ssid"] = cfg.ssid;
        doc["password"] = cfg.password;
        doc["server_ip"] = cfg.server_ip;
        doc["flow_pulses"] = cfg.flow_pulses;
        doc["max_pump_flow"] = cfg.maxPumpFlow; // НАШЕ НОВЕ ПОЛЕ
        doc["pwm_min"] = cfg.pwm_min;
        doc["pwm_max"] = cfg.pwm_max;
        doc["deadband"] = cfg.deadband;
        doc["total_sections"] = cfg.total_sections;
        doc["hardware_mode"] = cfg.hardware_mode;

        String response;
        serializeJson(doc, response);
        request->send(200, "application/json", response); });

    // ОНОВЛЕНО: Додано приймання параметра max_pump_flow у POST запиті
    AsyncCallbackJsonWebHandler *jsonHandler = new AsyncCallbackJsonWebHandler("/save-config", [this](AsyncWebServerRequest *request, JsonVariant &json)
                                                                               {
        JsonObject doc = json.as<JsonObject>();
        SystemConfig& cfg = _configMgr->getConfig();

        strlcpy(cfg.ssid, doc["ssid"] | "", sizeof(cfg.ssid));
        strlcpy(cfg.password, doc["password"] | "", sizeof(cfg.password));
        strlcpy(cfg.server_ip, doc["server_ip"] | "192.168.0.100", sizeof(cfg.server_ip));
        cfg.flow_pulses    = doc["flow_pulses"]    | 450;
        cfg.maxPumpFlow  = doc["max_pump_flow"]  | 15.0f; // НАШЕ НОВЕ ПОЛЕ
        cfg.pwm_min        = doc["pwm_min"]        | 17;
        cfg.pwm_max        = doc["pwm_max"]        | 100;
        cfg.deadband       = doc["deadband"]       | 2;
        cfg.total_sections = doc["total_sections"] | 5;
        cfg.hardware_mode  = doc["hardware_mode"]  | 0;
        cfg.flow_window    = doc["flow_window"]    | 3;

        _configMgr->save();
        request->send(200, "text/plain", "OK.");

        xTaskCreate([](void* id){
            vTaskDelay(pdMS_TO_TICKS(1000));
            ESP.restart();
        }, "reboot_task", 2048, NULL, 1, NULL); });

    // *******************************************************************************
    // 1. Ендпоінт для отримання динамічного списку файлів у форматі JSON
    _server.on("/list-files", HTTP_GET, [](AsyncWebServerRequest *request)
               {
    String json = "[";
    File root = LittleFS.open("/");
    if (root && root.isDirectory()) {
        File file = root.openNextFile();
        while (file) {
            if (json != "[") json += ",";
            json += "\"" + String(file.path()) + "\"";
            file = root.openNextFile();
        }
    }
    json += "]";
    request->send(200, "application/json", json); });

    // 2. Роздача статичних файлів з папки /ace (щоб завантажувалися скрипти)
    _server.serveStatic("/ace/", LittleFS, "/ace/").setCacheControl("max-age=86400");

    _server.on("/ace/ace.js", HTTP_GET, [](AsyncWebServerRequest *request)
               {
    if (LittleFS.exists("/ace/ace.js.gz")) {
        AsyncWebServerResponse *response = request->beginResponse(LittleFS, "/ace/ace.js.gz", "application/javascript");
        response->addHeader("Content-Encoding", "gzip");
        request->send(response);
    } else {
        request->send(LittleFS, "/ace/ace.js", "application/javascript");
    } });

    _server.on("/edit", HTTP_GET, [](AsyncWebServerRequest *request)
               {
    if (LittleFS.exists("/edit.html.gz")) {
        AsyncWebServerResponse *response = request->beginResponse(LittleFS, "/edit.html.gz", "text/html");
        response->addHeader("Content-Encoding", "gzip");
        request->send(response);
    } else if (LittleFS.exists("/edit.html")) {
        request->send(LittleFS, "/edit.html", "text/html");
    } else {
        request->send(404, "text/plain", "CRITICAL ERROR: /edit.html missing!");
    } });

    // 4. Обробник для завантаження та перезапису файлів з редактора
    _server.on("/edit-upload", HTTP_POST, [](AsyncWebServerRequest *request)
               { request->send(200, "text/plain", "OK"); }, [](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final)
               {
    static File uploadFile;
    if (!index) {
        String path = request->arg("path");
        if (path.length() == 0) path = "/" + filename;
        // Відкриваємо у режимі "w" (write) — це очищує старий файл і пише новий
        uploadFile = LittleFS.open(path, "w");
    }
    if (uploadFile) {
        uploadFile.write(data, len);
    }
    if (final && uploadFile) {
        uploadFile.close();
    } });

    _server.addHandler(jsonHandler);
}
*/
void VraNetworkManager::setupEndpoints()
{
    // Підключаємо наш обробник подій сокету до сервера
    _ws.onEvent([this](AsyncWebSocket *s, AsyncWebSocketClient *c, AwsEventType t, void *a, uint8_t *d, size_t l)
                { this->onWsEvent(s, c, t, a, d, l); });
    _server.addHandler(&_ws);

    // Головна сторінка
    _server.on("/", HTTP_GET, [](AsyncWebServerRequest *request)
               {
        if (LittleFS.exists("/index.html")) {
            request->send(LittleFS, "/index.html", "text/html");
        } else {
            request->send(404, "text/plain", "CRITICAL ERROR: /index.html missing!");
        } });

    // Отримання конфігурації у JSON
    _server.on("/get-config", HTTP_GET, [this](AsyncWebServerRequest *request)
               {
        SystemConfig& cfg = _configMgr->getConfig();
        JsonDocument doc;
        doc["ssid"] = cfg.ssid;
        doc["password"] = cfg.password;
        doc["server_ip"] = cfg.server_ip;
        doc["flow_pulses"] = cfg.flow_pulses;
        doc["max_pump_flow"] = cfg.maxPumpFlow;
        doc["pwm_min"] = cfg.pwm_min;
        doc["pwm_max"] = cfg.pwm_max;
        doc["deadband"] = cfg.deadband;
        doc["total_sections"] = cfg.total_sections;
        doc["hardware_mode"] = cfg.hardware_mode;

        String response;
        serializeJson(doc, response);
        request->send(200, "application/json", response); });

    // Збереження конфігурації у POST
    AsyncCallbackJsonWebHandler *jsonHandler = new AsyncCallbackJsonWebHandler("/save-config", [this](AsyncWebServerRequest *request, JsonVariant &json)
                                                                               {
        JsonObject doc = json.as<JsonObject>();
        SystemConfig& cfg = _configMgr->getConfig();
        
        strlcpy(cfg.ssid, doc["ssid"] | "", sizeof(cfg.ssid));
        strlcpy(cfg.password, doc["password"] | "", sizeof(cfg.password));
        strlcpy(cfg.server_ip, doc["server_ip"] | "192.168.0.100", sizeof(cfg.server_ip));                                                                    
        cfg.flow_pulses    = doc["flow_pulses"]    | 450;
        cfg.maxPumpFlow    = doc["max_pump_flow"]  | 15.0f;
        cfg.pwm_min        = doc["pwm_min"]        | 17;
        cfg.pwm_max        = doc["pwm_max"]        | 100;
        cfg.deadband       = doc["deadband"]       | 2;
        cfg.total_sections = doc["total_sections"] | 5;
        cfg.hardware_mode  = doc["hardware_mode"]  | 0;
        cfg.flow_window    = doc["flow_window"]    | 3;
        
        _configMgr->save();
        request->send(200, "text/plain", "OK.");
        
        xTaskCreate([](void* id){
            vTaskDelay(pdMS_TO_TICKS(1000));
            ESP.restart();
        }, "reboot_task", 2048, NULL, 1, NULL); });
    _server.addHandler(jsonHandler);

    // 1. Ендпоінт для отримання динамічного списку файлів у форматі JSON (Виправлено помилку 500)
    // _server.on("/list-files", HTTP_GET, [](AsyncWebServerRequest *request)
    //            {
    //     String json = "[";
    //     File root = LittleFS.open("/");
    //     if (root && root.isDirectory()) {
    //         File file = root.openNextFile();
    //         while (file) {
    //             if (json != "[") json += ",";
    //             json += "\"" + String(file.path()) + "\"";
    //             file.close(); // Обов'язково закриваємо файл, щоб уникнути витоку пам'яті (Error 500)
    //             file = root.openNextFile();
    //         }
    //         root.close();
    //     }
    //     json += "]";
    //     request->send(200, "application/json", json); });
    // 1. Эндпоинт для получения динамического списка файлов (Исправлено: исключаем папки)
    _server.on("/list-files", HTTP_GET, [](AsyncWebServerRequest *request)
               {
    String json = "[";
    File root = LittleFS.open("/");
    if (root && root.isDirectory()) {
        File file = root.openNextFile();
        while (file) {
            // Проверяем, что это файл, а не папка, и отсекаем возможные пустые пути
            if (!file.isDirectory() && String(file.path()).length() > 1) {
                if (json != "[") json += ",";
                json += "\"" + String(file.path()) + "\"";
            }
            file.close(); // Обязательно закрываем дескриптор!
            file = root.openNextFile();
        }
        root.close();
    }
    json += "]";
    request->send(200, "application/json", json); });

    // 2. Роздача Ace Editor. УВАГА: Прибираємо загальний serveStatic щоб уникнути конфліктів шляхів.
    // Обробник універсального перехоплення файлів всередині папки /ace/ з підтримкою .gz
    _server.on("/ace/*", HTTP_GET, [](AsyncWebServerRequest *request)
               {
        String url = request->url(); // Отримуємо повний шлях, наприклад: "/ace/ace.js"
        String gzUrl = url + ".gz";
        
        // Перевіряємо наявність стиснутої версії файлу
        if (LittleFS.exists(gzUrl)) {
            String contentType = "application/javascript";
            if (url.endsWith(".css")) contentType = "text/css";
            if (url.endsWith(".json")) contentType = "application/json";
            
            AsyncWebServerResponse *response = request->beginResponse(LittleFS, gzUrl, contentType);
            response->addHeader("Content-Encoding", "gzip");
            response->addHeader("Cache-Control", "max-age=86400");
            request->send(response);
        } 
        // Якщо стиснутої версії немає, шукаємо оригінальний сирий файл
        else if (LittleFS.exists(url)) {
            request->send(LittleFS, url);
        } 
        else {
            request->send(404, "text/plain", "File not found inside /ace/");
        } });

    // 3. Ендпоінт для самого редактора кодів
    _server.on("/edit", HTTP_GET, [](AsyncWebServerRequest *request)
               {
        if (LittleFS.exists("/edit.html.gz")) {
            AsyncWebServerResponse *response = request->beginResponse(LittleFS, "/edit.html.gz", "text/html");
            response->addHeader("Content-Encoding", "gzip");
            request->send(response);
        } else if (LittleFS.exists("/edit.html")) {
            request->send(LittleFS, "/edit.html", "text/html");
        } else {
            request->send(404, "text/plain", "CRITICAL ERROR: /edit.html missing!");
        } });

    // 4. Обробник для завантаження та перезапису файлів з редактора
    _server.on("/edit-upload", HTTP_POST, [](AsyncWebServerRequest *request)
               { request->send(200, "text/plain", "OK"); }, [](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final)
               {
        static File uploadFile;
        if (!index) {
            String path = request->arg("path");
            if (path.length() == 0) path = "/" + filename;
            // Відкриваємо у режимі "w" — очищує старий файл і пише новий
            uploadFile = LittleFS.open(path, "w");
        }
        if (uploadFile) {
            uploadFile.write(data, len);
        }
        if (final && uploadFile) {
            uploadFile.close();
        } });
    // 5. УНІВЕРСАЛЬНИЙ ОБРОБНИК КОРЕНЯ (Запобігає помилці 500 при прямих запитах до файлів)
    // Обов'язково має бути в самому кінці перед закриттям функції setupEndpoints()
    _server.on("/*", HTTP_GET, [](AsyncWebServerRequest *request)
               {
        String url = request->url();
        if (LittleFS.exists(url)) {
            request->send(LittleFS, url);
        } else {
            request->send(404, "text/plain", "File Not Found");
        } });
}

// Розсилка повідомлень усім відкритим сторінкам сайту
void VraNetworkManager::broadcastWebSocketMessage(String msg)
{
    _ws.textAll(msg);
}
