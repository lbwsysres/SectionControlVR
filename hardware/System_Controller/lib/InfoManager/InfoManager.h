#ifndef INFO_MANAGER_H
#define INFO_MANAGER_H

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include "DebugLog.h"
#include "NetworkManager.h" // Щоб бачити статус аварії [EMERGENCY]

// Визначаємо піни світлодіода. На ESP32-S3 DevKit це найчастіше 48 або 38
#define RGB_LED_PIN 48
#define NUM_LEDS     1

// Перелік станів системи для індикації
enum SystemStatus {
    STATUS_BOOT_ERROR,     // Постійний ЧЕРВОНИЙ (Крах LittleFS / заліза)
    STATUS_AP_MODE,        // Повільно блимає СИНІМ/ЖОВТИМ (Режим точки доступу, чекає на веб)
    STATUS_WIFI_CONNECTING,// Швидко блимає ЖОВТИМ (Шукає Wi-Fi трактора)
    STATUS_CONNECTED_NO_PY,// Блимає ЗЕЛЕНИМ (Wi-Fi є, але Питона з кабіни ще не чути)
    STATUS_OK,             // Постійний ЗЕЛЕНИЙ або м'яке «дихання» (Все ідеально, робота)
    STATUS_EMERGENCY       // Часто блимає ЧЕРВОНИЙ (ОЙ ВСЕ ПРОПАЛО! Відвал зв'язку на ходу)
};

class InfoManager {
private:
    Adafruit_NeoPixel _led;
    VraNetworkManager* _netMgr;
    SystemStatus _currentStatus;
    bool _ledState;
    uint32_t _lastBlinkTime;

    void setLedColor(uint8_t r, uint8_t g, uint8_t b);
    SystemStatus evaluateStatus();

public:
    InfoManager(VraNetworkManager* netMgr);
    
    void begin();
    void update(); // Цей метод буде викликатися в циклі на Ядрі 0
};

#endif
