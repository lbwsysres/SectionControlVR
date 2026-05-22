#include "DebugLog.h"
#include "ConfigManager.h"

ConfigManager::ConfigManager(const char *filename)
{
    _filename = filename;
    _isInitialized = false;
}

bool ConfigManager::begin()
{
    if (!LittleFS.begin(true))
    {
        DBG_OUTPUT_PORT.println(F("[FS ERROR] LittleFS Mount Failed!"));
        return false;
    }
    DBG_OUTPUT_PORT.println(F("[FS OK] LittleFS Mount"));
    _isInitialized = true;
    return load();
}
bool ConfigManager::load()
{
    // === ТИМЧАСОВЕ БЛОКУВАННЯ ДЛЯ ТЕСТІВ НА СТОЛІ ===
    // Заповнюємо структуру дефолтними даними

    strlcpy(_config.ssid, "LbwHome", sizeof(_config.ssid));
    strlcpy(_config.password, "password", sizeof(_config.password));
    strlcpy(_config.server_ip, "192.168.0.100", sizeof(_config.server_ip));
    /*
    _config.flow_pulses = 450;
    _config.pwm_min = 15;
    _config.pwm_max = 100;
    _config.deadband = 2;
    _config.total_sections = 5;
    _config.hardware_mode = 0;
    _config.flow_window = 3;

    // Нові змінні для Варіанта 1
    _config.hydroType = 1;
    _config.invertSections = false;
    _config.maxPumpFlow = 15.0f; // Твоя базова продуктивність
    */
    if (!_isInitialized || !LittleFS.exists(_filename))
    {
        DBG_OUTPUT_PORT.println(F("[FS INFO] Config file missing. Using memory defaults."));
        return false;
    }
    File file = LittleFS.open(_filename, "r");
    if (!file)
        return false;

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, file);
    file.close();

    // ФІКС: Замість падіння та return false, просто виводимо попередження і йдемо далі!
    // Якщо файл старий, ArduinoJson просто підставить дефолти (вертикальна риска |)
    if (error)
    {
        DBG_OUTPUT_PORT.println(F("[JSON WARN] Config file structure mismatch or empty. Appending defaults..."));
    }
    // Безпечне читання (якщо поля немає в старому файлі, береться дефолт праворуч)
    strlcpy(_config.ssid, doc["ssid"] | "LbwHome", sizeof(_config.ssid));
    strlcpy(_config.password, doc["password"] | "password", sizeof(_config.password));
    strlcpy(_config.server_ip, doc["server_ip"] | "192.168.0.100", sizeof(_config.server_ip));

    _config.flow_pulses = doc["flow_pulses"] | 450;
    _config.pwm_min = doc["pwm_min"] | 15;
    _config.pwm_max = doc["pwm_max"] | 100;
    _config.deadband = doc["deadband"] | 2;
    _config.total_sections = doc["total_sections"] | 5;
    _config.hardware_mode = doc["hardware_mode"] | 0;
    _config.flow_window = doc["flow_window"] | 3;
    _config.maxPumpFlow = doc["max_pump_flow"] | 8.0f;

    // Тепер цей принт викликатиметься ГАРАНТОВАНО!
    DBG_OUTPUT_PORT.println(F("[FS SUCCESS] Configuration successfully loaded from LittleFS."));
    return true;
}
bool ConfigManager::save()
{
    if (!_isInitialized)
    {
        DBG_OUTPUT_PORT.println(F("[FS ERROR] LittleFS Mount Failed!"));
        return false;
    }

    File file = LittleFS.open(_filename, "w");
    if (!file)
    {
        DBG_OUTPUT_PORT.println(F("[FS INFO] Config file missing. Error save"));
        return false;
    }
    JsonDocument doc;
    doc["ssid"] = _config.ssid;
    doc["password"] = _config.password;
    doc["server_ip"] = _config.server_ip;
    doc["flow_pulses"] = _config.flow_pulses;
    doc["pwm_min"] = _config.pwm_min;
    doc["pwm_max"] = _config.pwm_max;
    doc["deadband"] = _config.deadband;
    doc["total_sections"] = _config.total_sections;
    doc["hardware_mode"] = _config.hardware_mode;
    doc["flow_window"] = _config.flow_window;
    doc["max_pump_flow"] = _config.maxPumpFlow; 

    bool success = (serializeJson(doc, file) != 0);
    file.close();
    return success;
}
