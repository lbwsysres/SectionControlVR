#ifndef FLOW_CONTROLLER_H
#define FLOW_CONTROLLER_H

#include <Arduino.h>
#include "DebugLog.h"
#include "ConfigManager.h"
#include "NetworkManager.h"

// Піни для драйвера насоса BTS7960 (IBT-2)
#define PUMP_R_PWM_PIN 16
#define PUMP_L_PWM_PIN 17

// Налаштування ШІМ (LEDC периферія ESP32-S3)
#define PUMP_PWM_FREQ     20000 // 20 кГц, щоб мотор насоса не пищав
#define PUMP_PWM_RES      10    // 10 біт розрядність (значення від 0 до 1023)
#define PUMP_PWM_CHANNEL_R 0
#define PUMP_PWM_CHANNEL_L 1

class FlowController {
private:
    ConfigManager* _configMgr;
    VraNetworkManager* _netMgr;
    
    float _targetFlow;     // Цільовий потік (л/хв)
    float _currentFlow;    // Реальний потік з витратоміра (л/хв)
    float _virtualPressure;// Віртуальний тиск (бар)
    int _currentPwm;       // Поточний ШІМ, що видається на мотор (0..1023)
    
    // Налаштування емулятора для тесту на столі без води
    bool _emulationMode;
    
    // ПІД-коефіцієнти (для початку базові)
    float _Kp;
    float _Ki;
    float _integral;

public:
    FlowController(ConfigManager* configMgr, VraNetworkManager* netMgr);
    
    void begin();
    
    // Приймає нову цільову норму виливу
    void setTargetFlow(float flow);
    
    // Головний бойовий такт (викликається за жорстким таймером на Ядрі 1)
    void update(bool isEmergency, int activeSectionsCount);
    
    // Геттери, щоб мережеве ядро могло забирати дані та відправляти їх назад у Python
    float getCurrentFlow() const { return _currentFlow; }
    float getVirtualPressure() const { return _virtualPressure; }
    int getCurrentPwm() const { return _currentPwm; }
};

#endif
