#include "VraUdpLink.h"

VraUdpLink::VraUdpLink() {
    _port = 5005;
    memset(_packetBuffer, 0, sizeof(_packetBuffer));
}

VraUdpLink::~VraUdpLink() {
    _udp.stop();
}

bool VraUdpLink::begin(int port) {
    _port = port;
    if (_udp.begin(_port)) {
        DBG_OUTPUT_PORT.print(F("[LINK] UDP Listener opened successfully on port: "));
        DBG_OUTPUT_PORT.println(_port);
        return true;
    }
    DBG_OUTPUT_PORT.println(F("[LINK ERROR] Failed to open UDP port!"));
    return false;
}

bool VraUdpLink::readPacket(String &outputJson) {
    int packetSize = _udp.parsePacket();
    
    // Якщо датаграма прилетіла
    if (packetSize > 0) {
        // Обмежуємо розмір, щоб не підірвати наш буфер пам'яті
        if (packetSize > (int)sizeof(_packetBuffer) - 1) {
            packetSize = sizeof(_packetBuffer) - 1;
        }

        // Запам'ятовуємо, звідки прийшов пакет, щоб туди ж відправляти звіт
        _remoteIP = _udp.remoteIP();
        _remotePort = _udp.remotePort();

        // Зчитуємо байти з ефіру в буфер
        _udp.read(_packetBuffer, packetSize);
        _packetBuffer[packetSize] = '\0'; // Строгий нуль-термінатор для C-рядка

        // Переносимо чистий текст у наш вихідний JSON рядок
        outputJson = String(_packetBuffer);
        return true;
    }
    return false; // Пакетів у цьому такті немає
}

void VraUdpLink::sendPacket(const String &inputJson) {
    // Відправляємо відповідь Питону тільки якщо ми вже хоч раз отримали від нього пакет
    if (_remoteIP != INADDR_NONE) {
        _udp.beginPacket(_remoteIP, _remotePort);
        _udp.print(inputJson);
        _udp.endPacket();
    }
}
