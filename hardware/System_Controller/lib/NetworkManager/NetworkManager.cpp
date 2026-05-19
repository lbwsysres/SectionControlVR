#include "DebugLog.h"
#include "NetworkManager.h"

VraNetworkManager::VraNetworkManager(ConfigManager *configMgr) : _server(80)
{
    _configMgr = configMgr;
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
        // while (WiFi.status() != WL_CONNECTED && attempts < 20)
        // {
        //     delay(500);
        //     DBG_OUTPUT_PORT.print(".");
        //     attempts++;
        // }
        while (WiFi.status() != WL_CONNECTED && attempts < 20)
        {
            vTaskDelay(pdMS_TO_TICKS(500)); // Використовуємо функцію сну FreeRTOS замість delay
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
        _lastHeartbeat = millis(); // Скидаємо таймер при успішному лінку
    }

    setupEndpoints();
    _server.begin();
}

void VraNetworkManager::checkConnection()
{
    // Перевірка втрати Wi-Fi в режимі клієнта
    if (WiFi.getMode() == WIFI_STA && WiFi.status() != WL_CONNECTED)
    {
        WiFi.disconnect();
        WiFi.reconnect();
        delay(2000);
        return;
    }

    // СЦЕНАРІЙ: "ОЙ, ВСЕ ПРОПАЛО!" (Зв'язок з Python)
    // Якщо ми підключені до мережі, але пакетів немає більше 1 секунди
    if (WiFi.getMode() == WIFI_STA && (millis() - _lastHeartbeat > _heartbeatTimeout))
    {
        if (!_isEmergency)
        {
            _isEmergency = true;
            DBG_OUTPUT_PORT.println(F("[EMERGENCY] Connection with Python LOST! Shutting down spray..."));
            // Тут ми нічого не затримуємо через delay, просто ставимо прапорець.
            // Бойове ядро побачить цей true і миттєво вирубить насос.
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

void VraNetworkManager::setupEndpoints()
{
    // 1. Головна сторінка
    // _server.on("/", HTTP_GET, [this](AsyncWebServerRequest *request)
    //            { request->send_P(200, "text/html", index_html); });
    _server.on("/", HTTP_GET, [this](AsyncWebServerRequest *request)
               {
                   request->send(200, "text/html", index_html); // Просто прибираємо _P
               });

    // 2. Віддача поточних налаштувань
    _server.on("/get-config", HTTP_GET, [this](AsyncWebServerRequest *request)
               {
        SystemConfig& cfg = _configMgr->getConfig();
        JsonDocument doc;
        doc["ssid"] = cfg.ssid;
        doc["password"] = cfg.password;
        doc["server_ip"] = cfg.server_ip;
        doc["flow_pulses"] = cfg.flow_pulses;
        doc["pwm_min"] = cfg.pwm_min;
        doc["pwm_max"] = cfg.pwm_max;
        doc["deadband"] = cfg.deadband;
        doc["total_sections"] = cfg.total_sections;
        doc["hardware_mode"] = cfg.hardware_mode;

        String response;
        serializeJson(doc, response);
        request->send(200, "application/json", response); });

    // 3. Збереження налаштувань
    // AsyncCallbackJsonWebHandler *jsonHandler = new AsyncCallbackJsonWebHandler("/save-config", [this](AsyncWebServerRequest *request, JsonVariant &json)
    //                                                                            {
    //     JsonObject doc = json.as<JsonObject>();
    //     SystemConfig cfg; // Тимчасова структура

    //     strlcpy(cfg.ssid, doc["ssid"] | "", sizeof(cfg.ssid));
    //     strlcpy(cfg.password, doc["password"] | "", sizeof(cfg.password));
    //     strlcpy(cfg.server_ip, doc["server_ip"] | "192.168.1.100", sizeof(cfg.server_ip));
    //     cfg.flow_pulses = doc["flow_pulses"] | 450;
    //     cfg.pwm_min = doc["pwm_min"] | 15;
    //     cfg.pwm_max = doc["pwm_max"] | 100;
    //     cfg.deadband = doc["deadband"] | 2;
    //     cfg.total_sections = doc["total_sections"] | 5;
    //     cfg.hardware_mode = doc["hardware_mode"] | 0;

    //     _configMgr->setConfig(cfg);
    //     _configMgr->save();

    //     request->send(200, "text/plain", "OK.");

    //     delay(2000);
    //     ESP.restart(); });
    // 3. Збереження налаштувань
    // 3. Збереження налаштувань
    // 3. Збереження налаштувань (БЕЗПЕЧНИЙ ВАРИАНТ)
    AsyncCallbackJsonWebHandler *jsonHandler = new AsyncCallbackJsonWebHandler("/save-config", [this](AsyncWebServerRequest *request, JsonVariant &json)
                                                                               {
        JsonObject doc = json.as<JsonObject>();
        
        // Отримуємо ПРЯМИЙ вказівник на живу пам'ять конфігу нашої системи
        SystemConfig& cfg = _configMgr->getConfig();
        
        // Пишемо дані НАПРЯМУ в оперативку, минаючи тимчасові милиці стеку
        strlcpy(cfg.ssid, doc["ssid"] | "", sizeof(cfg.ssid));
        strlcpy(cfg.password, doc["password"] | "", sizeof(cfg.password));
        strlcpy(cfg.server_ip, doc["server_ip"] | "192.168.0.100", sizeof(cfg.server_ip));                                                                    
        cfg.flow_pulses    = doc["flow_pulses"]    | 450;
        cfg.pwm_min        = doc["pwm_min"]        | 17;
        cfg.pwm_max        = doc["pwm_max"]        | 100;
        cfg.deadband       = doc["deadband"]       | 2;
        cfg.total_sections = doc["total_sections"] | 5;
        cfg.hardware_mode  = doc["hardware_mode"]  | 0;
        cfg.flow_window    = doc["flow_window"]    | 3;
        // Тепер просто кажемо менеджеру: «Запиши поточний стан оперативки на диск!»
        _configMgr->save();

        // Миттєво відповідаємо браузеру
        request->send(200, "text/plain", "OK.");
        
        // Безпечний рестарт через фоновий такт FreeRTOS
        xTaskCreate([](void* id){
            vTaskDelay(pdMS_TO_TICKS(1000));
            ESP.restart();
        }, "reboot_task", 2048, NULL, 1, NULL); });

    _server.addHandler(jsonHandler);
}
