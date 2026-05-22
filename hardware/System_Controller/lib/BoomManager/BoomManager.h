#ifndef BOOM_MANAGER_H
#define BOOM_MANAGER_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h> // Основний заголовок драйвера PCA9685
#include "DebugLog.h"
#include "ConfigManager.h"

// Налаштування пінів шини I2C для ESP32-S3
#define I2C_SDA_PIN 1
#define I2C_SCL_PIN 2

class BoomManager {
private:
    ConfigManager* _configMgr;
    Adafruit_PWMServoDriver _pca; // Об'єкт для роботи з платою PCA9685
    int _totalSections;
    int _hardwareMode; // 0 - Прості клапани (MOSFET/Реле), 1 - Сервоприводи DS5160
    int _sectionStates[16];

public:
    BoomManager(ConfigManager* configMgr);
    
    void begin();
    
    // Головний метод керування (приймає ID секції 1..8 та стан 1/0)
    void setSectionState(int sectionId, int state);
    
    // Миттєвий Fail-Safe захист — загальне вимкнення штанги
    void shutDownAll();
};

#endif
