#ifndef CONFIG_MANAGER_H
#define CONFIG_MANAGER_H

#include <Arduino.h>
#include <LittleFS.h>
#include <ArduinoJson.h>

// Структура конфігурації (аналог Record у Delphi)
struct SystemConfig {
    char ssid[32] = "";        // Строго 32 байти під назву Wi-Fi
    char password[64] = "";    // Строго 64 байти під пароль
    char server_ip[16] = "192.168.0.100"; // Строго 16 байт під IP-адресу
    
    int flow_pulses = 4380;
    int pwm_min = 20;
    int pwm_max = 100;
    int deadband = 2;
    int total_sections = 5;
    int hardware_mode = 0; 
    int flow_window = 3;

    // --- НАЛАШТУВАННЯ ДЛЯ ВАРІАНТА 1 (ЗАШИТІ В КОД) ---
    int hydroType = 1;            // 1 - Електронасос + клапани ON/OFF
    bool invertSections = false;  // false - клапани NC (нормально закриті), true - NO
    float maxPumpFlow = 8.0f;    // Максимальний вилив твого насоса в л/хв (наприклад, 15.0)

    // Твої існуючі коефіцієнти ПІД (можеш підправити дефолтні значення)
    float kp = 2.5f;               
    float ki = 0.5f;               
    float kd = 0.1f;
};

class ConfigManager {
private:
    const char* _filename;
    SystemConfig _config;
    bool _isInitialized;

public:
    ConfigManager(const char* filename = "/config.json");
    
    bool begin();
    bool load();
    bool save();
    
    // Геттер та сеттер для доступу до структури (Інкапсуляція)
    SystemConfig& getConfig() { return _config; }
    void setConfig(const SystemConfig& newConfig) { _config = newConfig; }
};

#endif
