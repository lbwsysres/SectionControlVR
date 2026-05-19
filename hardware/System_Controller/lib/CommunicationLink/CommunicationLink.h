#ifndef COMMUNICATION_LINK_H
#define COMMUNICATION_LINK_H

#include <Arduino.h>

// Абстрактний базовий клас (Інтерфейс у стилі Delphi)
class CommunicationLink {
public:
    // Віртуальний деструктор для коректного видалення об'єктів з пам'яті
    virtual ~CommunicationLink() {}

    // Чисто віртуальні методи (абстрактні методи без реалізації)
    virtual bool begin(int portOrBaud) = 0;
    virtual bool readPacket(String &outputJson) = 0;
    virtual void sendPacket(const String &inputJson) = 0;
};

#endif
