#ifndef NETWORK_MANAGER_H
#define NETWORK_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncJson.h>
#include <ArduinoJson.h>
#include "ConfigManager.h"
#include "web_server_content.h"
//#include "web_server_content.h"

class VraNetworkManager{
private:
    ConfigManager* _configMgr;
    AsyncWebServer _server;
    unsigned long _lastHeartbeat;
    const unsigned long _heartbeatTimeout = 1000; // 1 секунда на відвал зв'язку
    bool _isEmergency;

    void setupEndpoints();

public:
    VraNetworkManager(ConfigManager* configMgr);
    
    void begin();
    void checkConnection();
    
    // Метод безпеки: викликається при отриманні будь-якого валідного пакету від Python
    void updateHeartbeat();
    
    // Перевірка, чи ми зараз в аварійному режимі
    bool isEmergency() const { return _isEmergency; }
};

#endif
