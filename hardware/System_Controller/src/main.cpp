#include <Arduino.h>
#include <ArduinoJson.h>
#include "DebugLog.h"
#include "ConfigManager.h"
#include "NetworkManager.h"
#include "InfoManager.h"
#include "VraUdpLink.h"
#include "BoomManager.h"
#include "FlowController.h" // <-- Підключаємо серце гідравліки

ConfigManager *configManager = nullptr;
VraNetworkManager *networkManager = nullptr;
InfoManager *infoManager = nullptr;
CommunicationLink *commLink = nullptr;
BoomManager *boomManager = nullptr;
FlowController *flowController = nullptr; // <-- Вказівник на ПІД

// Глобальні змінні для безпечного між'ядерного обміну (між Ядром 0 та Ядром 1)
volatile float sharedTargetFlow = 0.0f;
volatile int sharedActiveSectionsCount = 0;
volatile bool sharedIsEmergency = true;

// ЗАДАЧА ДЛЯ ЯДРА 0: Мережа, Веб, Індикація, Прийом JSON
void coreZeroNetworkTask(void *pvParameters)
{
    networkManager->begin();
    infoManager->begin();
    boomManager->begin();
    commLink->begin(5005);

    String incomingJson = "";
    JsonDocument doc;

    for (;;)
    {
        networkManager->checkConnection();
        bool emergencyState = networkManager->isEmergency();
        sharedIsEmergency = emergencyState;

        if (emergencyState)
        {
            boomManager->shutDownAll();
        }

        if (commLink->readPacket(incomingJson))
        {
            networkManager->updateHeartbeat();
            DeserializationError error = deserializeJson(doc, incomingJson);

            // ПЕРЕВІРКА: Якщо запущено калібрування з веб-сайту — повністю ігноруємо цей пакет!
            if (flowController != nullptr && flowController->isInAnyCalibMode())
            {
                vTaskDelay(pdMS_TO_TICKS(5)); // <--- Даємо ядру 0 дихнути 5 мс, щоб не тригерувати Watchdog
                continue;
            }
            if (!error)
            {
                int activeCount = 0;
                float totalVraSum = 0.0f;

                // Витягуємо базовий потік середини штанги з карти
                float mapCenterFlow = doc["tf"] | 0.0f;

                if (doc.containsKey("sections") && doc["sections"].is<JsonArray>())
                {
                    JsonArray sections = doc["sections"].as<JsonArray>();

                    for (JsonObject sec : sections)
                    {
                        int id = sec["id"] | 0;
                        int st = sec["st"] | 0;
                        float vraFlow = sec["vr"] | 0.0f; // Індивідуальна VRA норма секції (л/хв)

                        if (id > 0)
                        {
                            boomManager->setSectionState(id, st);
                            if (st == 1)
                            {
                                activeCount++;
                                totalVraSum += vraFlow; // Плюсуємо індивідуальні норми
                            }
                        }
                    }
                }

                // Логіка вибору цільового потоку:
                // Якщо секції прислали свої індивідуальні VRA норми ("vr") — працюємо по їх сумі.
                // Якщо індивідуальних норм немає, але є загальний "tf" середини штанги — беремо його.
                sharedTargetFlow = (totalVraSum > 0.05f) ? totalVraSum : mapCenterFlow;
                sharedActiveSectionsCount = activeCount;
                flowController->setTargetFlow(sharedTargetFlow);
            }

            // ЗВІТ У КАБІНУ: Відправляємо Питону реальний стан заліза у зворотному JSON-пакеті
            JsonDocument replyDoc;
            replyDoc["cf"] = flowController->getCurrentFlow();
            replyDoc["vp"] = flowController->getVirtualPressure();
            replyDoc["pwm"] = flowController->getCurrentPwm();
            String replyString;
            serializeJson(replyDoc, replyString);
            commLink->sendPacket(replyString);
        }

        infoManager->update();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

// ЗАДАЧА ДЛЯ ЯДРА 1: Жорсткий таймерний цикл ПІД-регулятора (Кожні 50 мс)
void coreOneFlowTask(void *pvParameters)
{
    DBG_OUTPUT_PORT.println(F("[CORE 1] Hardware PID Loop started successfully."));
    flowController->begin();

    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(50); // Рівно 50 мілісекунд (20 Гц)

    for (;;)
    {
        // Викликаємо бойовий такт регулювання
        flowController->update(sharedIsEmergency, sharedActiveSectionsCount);

        // Жорстка FreeRTOS стабілізація частоти такту (ігнорує будь-які затримки коду)
        vTaskDelayUntil(&xLastWakeTime, xFrequency);
    }
}
/*
{"ms":true,"tf":2.5,"sections":[{"id":1,"st":1,"mo":"AUTO","vr":0.0}]}
{"ms":true,"tf":0.0,"sections":[{"id":1,"st":1,"mo":"AUTO","vr":1.5},{"id":2,"st":1,"mo":"AUTO","vr":2.0}]}


*/
void setup()
{
    DBG_OUTPUT_PORT.begin(115200);
    delay(3000);

    DBG_OUTPUT_PORT.println(F("\n\n===================================="));
    DBG_OUTPUT_PORT.println(F("[SYSTEM] VRA Hardware Booted Successfully!"));

    configManager = new ConfigManager();
    configManager->begin();

    networkManager = new VraNetworkManager(configManager);
    infoManager = new InfoManager(networkManager);
    boomManager = new BoomManager(configManager);
    // flowController = new FlowController(configManager, networkManager); // <-- Ініціалізація ПІД
    flowController = new FlowController(configManager, networkManager, boomManager);
    networkManager->setFlowController(flowController);

    commLink = new VraUdpLink();

    DBG_OUTPUT_PORT.println(F("\n\n===================================="));
    // Запуск Мережевого Ядра 0
    xTaskCreatePinnedToCore(coreZeroNetworkTask, "NetworkTask", 8192, NULL, 1, NULL, 0);

    // Запуск БОЙОВОГО ЯДРА 1 (Ставимо пріоритет вище — 2, щоб залізо керувалося за будь-яких умов)
    xTaskCreatePinnedToCore(coreOneFlowTask, "FlowPIDTask", 4096, NULL, 2, NULL, 1);
}

void loop()
{
    // DBG_OUTPUT_PORT.printf(
    //     "[VRA] Link:%s | Sections:%d | Target:%.2f L/m | Real:%.2f L/m | Pres:%.1f Bar | PWM:%d/1023\n",
    //     networkManager->isEmergency() ? "EMERG" : "OK",
    //     sharedActiveSectionsCount,
    //     sharedTargetFlow,
    //     flowController->getCurrentFlow(),
    //     flowController->getVirtualPressure(),
    //     flowController->getCurrentPwm());
    vTaskDelay(pdMS_TO_TICKS(1000));
}
