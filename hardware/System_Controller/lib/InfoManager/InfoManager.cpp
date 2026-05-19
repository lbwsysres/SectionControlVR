#include "InfoManager.h"

InfoManager::InfoManager(VraNetworkManager* netMgr) 
    : _led(NUM_LEDS, RGB_LED_PIN, NEO_GRB + NEO_KHZ800) {
    _netMgr = netMgr;
    _currentStatus = STATUS_WIFI_CONNECTING;
    _ledState = false;
    _lastBlinkTime = 0;
}

void InfoManager::begin() {
    _led.begin();
    _led.setBrightness(50); // Ставимо 50 з 255, щоб не випалювало очі на столі
    _led.show();
    DBG_OUTPUT_PORT.println(F("[INFO] WS2812B Indicator initialized."));
}

SystemStatus InfoManager::evaluateStatus() {
    // Якщо LittleFS не завівся або вказівник порожній
    if (_netMgr == nullptr) return STATUS_BOOT_ERROR;

    // Перевіряємо сценарій "ОЙ ВСЕ ПРОПАЛО"
    if (_netMgr->isEmergency()) return STATUS_EMERGENCY;

    // Перевіряємо режими Wi-Fi
    if (WiFi.getMode() == WIFI_AP) return STATUS_AP_MODE;

    if (WiFi.getMode() == WIFI_STA) {
        if (WiFi.status() != WL_CONNECTED) {
            return STATUS_WIFI_CONNECTING;
        } else {
            // Wi-Fi підключено. Якщо у вас в майбутньому буде прапорець, 
            // що Python надіслав перший пакет, поставимо STATUS_OK. 
            // Поки що вважаємо: якщо зв'язок є і немає Emergency — все ОК.
            return STATUS_OK;
        }
    }
    return STATUS_BOOT_ERROR;
}

void InfoManager::setLedColor(uint8_t r, uint8_t g, uint8_t b) {
    _led.setPixelColor(0, _led.Color(r, g, b));
    _led.show();
}

void InfoManager::update() {
    SystemStatus newStatus = evaluateStatus();
    uint32_t now = millis();

    // Якщо статус змінився — миттєво реагуємо, не чекаючи таймерів блимання
    if (newStatus != _currentStatus) {
        _currentStatus = newStatus;
        _ledState = true;
        _lastBlinkTime = now;
    }

    switch (_currentStatus) {
        case STATUS_BOOT_ERROR:
            setLedColor(255, 0, 0); // Постійний чистий ЧЕРВОНИЙ
            break;

        case STATUS_EMERGENCY:
            // Часто блимає ЧЕРВОНИМ (кожні 150 мс) - Тривога!
            if (now - _lastBlinkTime > 150) {
                _ledState = !_ledState;
                if (_ledState) setLedColor(255, 0, 0);
                else setLedColor(0, 0, 0);
                _lastBlinkTime = now;
            }
            break;

        case STATUS_AP_MODE:
            // Спокійно переливається або блимає СИНІМ (кожні 600 мс)
            if (now - _lastBlinkTime > 600) {
                _ledState = !_ledState;
                if (_ledState) setLedColor(0, 0, 255); // СИНІЙ
                else setLedColor(100, 50, 0);          // ЖОВТИЙ підказка
                _lastBlinkTime = now;
            }
            break;

        case STATUS_WIFI_CONNECTING:
            // Блимає ЖОВТИМ (кожні 300 мс) - шукає мережу
            if (now - _lastBlinkTime > 300) {
                _ledState = !_ledState;
                if (_ledState) setLedColor(200, 150, 0);
                else setLedColor(0, 0, 0);
                _lastBlinkTime = now;
            }
            break;

        case STATUS_OK:
            // Все ідеально - горить красивим стабільним ЗЕЛЕНИМ
            setLedColor(0, 255, 0); 
            break;
            
        default:
            setLedColor(0, 0, 0);
            break;
    }
}
