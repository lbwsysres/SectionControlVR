#ifndef CONFIG_MANAGER_H
#define CONFIG_MANAGER_H

#include <Arduino.h>
#include <ArduinoJson.h>

// ============================================================================
// 1. ОДИН СУВОРИЙ СПИСОК УСІХ ПОЛІВ (Міняти/додавати нові параметри ТІЛЬКИ ТУТ!)
// Формат: TYPE, NAME, DEFAULT_VALUE
// ============================================================================
#define CONFIG_FIELDS(X) \
    X(String, ssid, "") \
    X(String, password, "") \
    X(String, server_ip, "192.168.0.100") \
    X(int, flow_pulses, 4380) \
    X(int, pwm_min, 20) \
    X(int, pwm_max, 100) \
    X(int, deadband, 2) \
    X(int, total_sections, 5) \
    X(int, hardware_mode, 0) \
    X(int, flow_window, 3) \
    X(int, hydroType, 1) \
    X(bool, invertSections, false) \
    X(float, maxPumpFlow, 8.0f) \
    X(float, kp, 2.5f) \
    X(float, ki, 0.5f) \
    X(float, kd, 0.1f)

// ============================================================================
// 2. АВТОМАТИЧНА ГЕНЕРАЦІЯ СТРУКТУРИ КЛАСУ
// ============================================================================
struct SystemConfig {
    // Макрос сам розгорне список у реальні змінні: int flow_pulses = 4380; тощо.
    #define GENERATE_STRUCT_FIELD(type, name, def) type name = def;
    CONFIG_FIELDS(GENERATE_STRUCT_FIELD)
    #undef GENERATE_STRUCT_FIELD

    // Автоматичний експорт СТРУКТУРИ -> JSON об'єкт
    void toJson(JsonVariant doc) const {
        #define FIELD_TO_JSON(type, name, def) doc[#name] = name;
        CONFIG_FIELDS(FIELD_TO_JSON)
        #undef FIELD_TO_JSON
    }

    // Автоматичний імпорт JSON об'єкт -> СТРУКТУРА (з дефолтами, якщо поля немає)
    void fromJson(JsonVariant doc) {
        #define FIELD_FROM_JSON(type, name, def) name = doc[#name].as<type>() | def;
        CONFIG_FIELDS(FIELD_FROM_JSON)
        #undef FIELD_FROM_JSON
    }
};

// Решта твого коду класу ConfigManager...
#endif

***********************************************************************************
Приведи ці методи у своєму файлі ConfigManager.cpp до такого ладу:
bool ConfigManager::load()
{
    if (!_isInitialized || !LittleFS.exists(_filename))
    {
        DBG_OUTPUT_PORT.println(F("[FS INFO] Config file missing. Using defaults."));
        return false;
    }
    
    File file = LittleFS.open(_filename, "r");
    if (!file) return false;

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, file);
    file.close();

    if (error) {
        DBG_OUTPUT_PORT.println(F("[JSON WARN] Config error or empty. Appending defaults..."));
    }

    // ОДИН РЯДОК ЗАМІСТЬ КУПИ СТРАШНОГО КОДУ!
    // Весь JSON автоматично розпакується у твою структуру з урахуванням дефолтів!
    _config.fromJson(doc.as<JsonVariant>());

    DBG_OUTPUT_PORT.println(F("[FS SUCCESS] Configuration automatically loaded."));
    return true;
}

// Якщо у тебе є метод збереження на диск:
bool ConfigManager::save() {
    if (!_isInitialized) return false;

    File file = LittleFS.open(_filename, "w");
    if (!file) return false;

    JsonDocument doc;
    
    // ОДИН РЯДОК ОНОВЛЕННЯ ДИСКУ!
    // Структура сама збере себе в JSON документ
    _config.toJson(doc.as<JsonVariant>());

    serializeJson(doc, file);
    file.close();
    
    DBG_OUTPUT_PORT.println(F("[FS SUCCESS] Configuration automatically saved to disk."));
    return true;
}

***********************************************************************************
Знайди методи /get-config та /save-config у NetworkManager.cpp та заміни їх на ці:
// 1. Віддача конфігу браузеру
_server.on("/get-config", HTTP_GET, [this](AsyncWebServerRequest *request) {
    SystemConfig& cfg = _configMgr->getConfig();
    JsonDocument doc;
    
    // Автоматично пакуємо ВСІ поля, які є в списку макросу
    cfg.toJson(doc.as<JsonVariant>());

    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response); 
});

// 2. Збереження налаштувань, які прийшли з форми сайту
AsyncCallbackJsonWebHandler *jsonHandler = new AsyncCallbackJsonWebHandler("/save-config", [this](AsyncWebServerRequest *request, JsonVariant &json) {
    SystemConfig& cfg = _configMgr->getConfig();
    
    // Автоматично розпаковуємо ВСІ надіслані поля сайту прямо в оперативку!
    cfg.fromJson(json.as<JsonVariant>());
    
    _configMgr->save(); // Записуємо на диск LittleFS
    request->send(200, "text/plain", "OK.");
    
    // Фоновий рестарт
    xTaskCreate([](void* id){
        vTaskDelay(pdMS_TO_TICKS(1000));
        ESP.restart();
    }, "reboot_task", 2048, NULL, 1, NULL); 
});
