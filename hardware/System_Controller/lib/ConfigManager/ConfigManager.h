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
    
    int flow_pulses = 452;
    int pwm_min = 17;
    int pwm_max = 100;
    int deadband = 2;
    int total_sections = 5;
    int hardware_mode = 0; 
    int flow_window = 3;
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
