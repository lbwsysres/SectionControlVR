#ifndef NETWORK_MANAGER_H
#define NETWORK_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncJson.h>
#include <ArduinoJson.h>
#include "ConfigManager.h"

// Вперед оголошуємо клас FlowController, щоб уникнути циклічних інклудів
class FlowController;

class VraNetworkManager {
private:
    ConfigManager* _configMgr;
    FlowController* _flowController; // Посилання на контролер потоку
    
    AsyncWebServer _server;
    AsyncWebSocket _ws; // НАШ НОВИЙ ВЕБ-СОКЕТ

    uint32_t _lastHeartbeat;
    const uint32_t _heartbeatTimeout = 1000; // 1 секунда
    bool _isEmergency;

    void setupEndpoints();
    
    // Обробник сирих подій веб-сокету (підключення, пакети, відключення)
    void onWsEvent(AsyncWebSocket* server, AsyncWebSocketClient* client, 
                   AwsEventType type, void* arg, uint8_t* data, size_t len);
                   
    // Обробник текстових повідомлень, що прилітають з сайту
    void handleWebSocketMessage(String msg, uint32_t client_id);

public:
    VraNetworkManager(ConfigManager* configMgr);
    
    void begin();
    void checkConnection();
    void updateHeartbeat();
    
    // Сетер, щоб зв'язати мережу з контролером потоку
    void setFlowController(FlowController* flowCtrl) { _flowController = flowCtrl; }
    
    bool isEmergency() const { return _isEmergency; }
    
    // Функція розсилки повідомлень усім вкладкам браузера
    void broadcastWebSocketMessage(String msg);
};

#endif
