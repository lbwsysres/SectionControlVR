#ifndef VRA_UDP_LINK_H
#define VRA_UDP_LINK_H

#include "CommunicationLink.h"
#include <WiFiUdp.h>
#include "DebugLog.h"

class VraUdpLink : public CommunicationLink {
private:
    WiFiUDP _udp;
    int _port;
    char _packetBuffer[2048]; // Буфер для сирих байтів пакета
    IPAddress _remoteIP;      // IP-адреса Питона, який нам надіслав пакет
    uint16_t _remotePort;

public:
    VraUdpLink();
    ~VraUdpLink() override;

    bool begin(int port) override;
    bool readPacket(String &outputJson) override;
    void sendPacket(const String &inputJson) override;
};

#endif
