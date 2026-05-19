import socket
import json
import time
import threading
import struct
import serial
import config_manager


class BoardWorker(threading.Thread):
    def __init__(self, shared_state):
        super().__init__()
        self.state = shared_state
        self.running = True
        self.daemon = True

        # Переменные для проводного UART режима
        self.serial_device = None
        self.uart_connected = False
        self.current_port = None
        self.current_baud = None

        # Переменные для беспроводного Wi-Fi (UDP) режима
        self.udp_sock = None
        # ИСПОЛЬЗУЕМ BROADCAST: Отвязываемся от жестких IP насовсем
        self.broadcast_ip = "255.255.255.255"
        self.udp_port = 5005

        # Считываем геометрию штанги (ширины секций) из твоего config.json
        cfg = config_manager.load_config()
        self.section_widths = cfg.get("SECTION_WIDTHS", [3.0] * 1)

    def run(self):
        print("[Board_Unit] Universal Broadcast-Network/UART thread STARTED.")

        # Запускаем асинхронного слушателя ответов от ESP32-S3
        threading.Thread(target=self.incoming_data_listener, daemon=True).start()

        while self.running:
            try:
                cfg = config_manager.load_config()

                # Проверяем главный тумблер активации железного блока в конфиге Питона
                if not cfg.get("CONTROL_BOARD_ENABLE", False):
                    self.state.board_connected = False
                    if self.uart_connected:
                        self.close_uart()
                    time.sleep(0.5)
                    continue

                # Выбираем тип линка: "udp" (Wi-Fi) или "uart" (Провод)
                connection_type = cfg.get("CONTROL_BOARD_TYPE", "udp")

                if connection_type == "udp":
                    # =======================================================================
                    # РЕЖИМ 1: WI-FI (UDP BROADCAST JSON)
                    # =======================================================================
                    if self.uart_connected:
                        self.close_uart()
                    self.udp_port = cfg.get("CONTROL_BOARD_PORT_NUM", 5005)

                    if self.udp_sock is None:
                        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        # Включаем на уровне ОС право сокета вещать на всю подсеть
                        self.udp_sock.setsockopt(
                            socket.SOL_SOCKET, socket.SO_BROADCAST, 1
                        )
                        self.udp_sock.settimeout(
                            0.05
                        )  # Быстрый таймаут, чтобы не вешать поток

                    self.send_udp_broadcast_packet()
                    self.state.board_connected = True

                else:
                    # =======================================================================
                    # РЕЖИМ 2: ПРОВОД (UART БИНАРНЫЙ ПАКЕТ С XOR CRC)
                    # =======================================================================
                    if self.udp_sock:
                        self.udp_sock.close()
                        self.udp_sock = None

                    active_port = cfg.get("CONTROL_BOARD_PORT", "com2")
                    active_baud = cfg.get("CONTROL_BOARD_PORT_SPEED", 115200)
                    reconnect_delay = (
                        cfg.get("CONTROL_BOARD_TIME_RECONNECT", 5000) / 1000.0
                    )

                    # Смена COM-порта или скорости "на лету" без перезапуска Питона
                    if self.uart_connected and (
                        active_port != self.current_port
                        or active_baud != self.current_baud
                    ):
                        self.close_uart()

                    if not self.uart_connected:
                        self.connect_uart(active_port, active_baud, reconnect_delay)
                    else:
                        self.send_binary_uart_packet()

            except Exception as e:
                print(f"[Board_Unit ERROR] Loop crash averted: {e}")
                self.state.board_connected = False

            # Работаем на стабильной частоте 20 Гц (раз в 50 мс) — для точного ПІД-контроля
            time.sleep(0.05)

    # --- ЛОГИКА BROADCAST WI-FI ---
    def send_udp_broadcast_packet(self):
        # 1. ЧИТАЕМ СВЕЖИЙ КОНФИГ НА КАЖДОМ ТАКТЕ (Динамика 100%)
        cfg = config_manager.load_config()
        section_widths = cfg.get("SECTION_WIDTHS", [3.0] * 8)

        states = getattr(self.state, "current_states", [])
        percents = getattr(self.state, "flow_percents", [])
        flows = getattr(self.state, "vra_flows", [])

        sections_list = []
        total_target_flow = 0.0

        # Цикл теперь крутится строго по актуальной длине свежего массива ширин
        for i in range(len(section_widths)):
            is_active = 1 if (states[i] if i < len(states) else False) else 0
            vra_rate = flows[i] if i < len(flows) else 0.0
            turn_comp = percents[i] if i < len(percents) else 100.0

            actual_rate_ha = vra_rate * (turn_comp / 100.0)
            width = section_widths[i]  # Берем актуальную ширину из свежего конфига
            speed = self.state.speed

            if is_active == 1 and speed > 0.2:
                section_flow_min = (actual_rate_ha * width * speed) / 600.0
            else:
                section_flow_min = 0.0

            total_target_flow += section_flow_min

            sections_list.append(
                {
                    "id": i + 1,
                    "st": is_active,
                    "mo": "AUTO",
                    "vr": round(section_flow_min, 2),
                }
            )

        packet = {
            "ms": total_target_flow > 0.05,
            "tf": round(total_target_flow, 2),
            "sp": round(self.state.speed, 1),
            "hd": round(self.state.hdg, 1),
            "sections": sections_list,
        }

        packet_bytes = json.dumps(packet).encode("utf-8")
        try:
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except:
            pass

        self.udp_sock.sendto(packet_bytes, (self.broadcast_ip, self.udp_port))

    def send_udp_broadcast_packet_1(self):
        # Достаем тройку массивов из твоего математического ядра SharedState
        states = getattr(self.state, "current_states", [])
        percents = getattr(self.state, "flow_percents", [])
        flows = getattr(self.state, "vra_flows", [])

        sections_list = []
        total_target_flow = 0.0

        for i in range(len(self.section_widths)):
            # 1. Проверяем On/Off состояние секции (с учетом перекрытий Shapely)
            is_active = 1 if (states[i] if i < len(states) else False) else 0

            # 2. Доза вылива из Shapefile (л/га)
            vra_rate = flows[i] if i < len(flows) else 0.0

            # 3. Курсовая компенсация на поворотах штанги
            turn_comp = percents[i] if i < len(percents) else 100.0

            # Рассчитываем итоговую гектарную норму конкретной секции
            actual_rate_ha = vra_rate * (turn_comp / 100.0)
            width = self.section_widths[i]
            speed = self.state.speed

            # Считаем минутный потік по формуле: (л/га * м * км/ч) / 600
            if is_active == 1 and speed > 0.2:
                section_flow_min = (actual_rate_ha * width * speed) / 600.0
            else:
                section_flow_min = 0.0

            total_target_flow += section_flow_min

            # Собираем динамический JSON массив объектов
            sections_list.append(
                {
                    "id": i + 1,
                    "st": is_active,
                    "mo": "AUTO",
                    "vr": round(section_flow_min, 2),
                }
            )

        # Общий пакет управления штангой
        packet = {
            "ms": total_target_flow > 0.05,
            "tf": round(total_target_flow, 2),
            "sp": round(self.state.speed, 1),
            "hd": round(self.state.hdg, 1),
            "sections": sections_list,
        }

        packet_bytes = json.dumps(packet).encode("utf-8")
        # Стреляем пакетом в вещательный адрес подсети
        self.udp_sock.sendto(packet_bytes, (self.broadcast_ip, self.udp_port))

    # --- ЛОГИКА ПРОВОДНОГО UART ---
    def connect_uart(self, port, baud, delay):
        try:
            self.serial_device = serial.Serial(port=port, baudrate=baud, timeout=0.5)
            self.current_port = port
            self.current_baud = baud
            self.uart_connected = True
            self.state.board_connected = True
            print(f"[Board_Unit] UART Link Connected: {port} ({baud} baud)")
        except Exception as e:
            print(f"[Board_Unit] UART Connect Fail: {e}. Retry in {delay} sec...")
            self.uart_connected = False
            self.state.board_connected = False
            time.sleep(delay)

    def send_binary_uart_packet(self):
        try:
            states = getattr(self.state, "current_states", [])
            percents = getattr(self.state, "flow_percents", [])
            flows = getattr(self.state, "vra_flows", [])
            num_sections = len(states)

            if num_sections == 0:
                return

            # Заголовок пакета: Префикс (0xAA) + Кол-во активных секций
            packet = bytearray(struct.pack("<BB", 0xAA, num_sections))

            for i in range(num_sections):
                sec_on = 1 if states[i] else 0
                sec_pct = int(percents[i]) if i < len(percents) else 100
                sec_flow = float(flows[i]) if i < len(flows) else 0.0

                # Упаковка в сирые байты: 1 байт (On/Off) + 2 байта (Comp %) + 4 байта (л/га)
                packet.extend(struct.pack("<BHf", sec_on, sec_pct, sec_flow))

            # Считаем XOR контрольную суму по всему бинарному пакету
            crc = 0
            for b in packet:
                crc ^= b
            packet.extend(struct.pack("<B", crc))

            self.serial_device.write(packet)
            self.serial_device.flush()
        except Exception as e:
            print(f"[Board_Unit] UART Write Error: {e}")
            self.close_uart()

    def close_uart(self):
        self.uart_connected = False
        if self.serial_device:
            try:
                self.serial_device.close()
            except:
                pass
        self.serial_device = None
        print("[Board_Unit] UART Port successfully closed.")

    # --- АСИНХРОННЫЙ СЛУШАТЕЛ БОЛЬШОЙ ЗЕМЛИ ---
    def incoming_data_listener(self):
        """Фоновый поток, который выдергивает из эфира ответы от ESP32-S3"""
        while self.running:
            try:
                cfg = config_manager.load_config()
                connection_type = cfg.get("CONTROL_BOARD_TYPE", "udp")

                if connection_type == "udp" and self.udp_sock:
                    try:
                        # Слушаем входящие датаграммы от нашей кормы
                        data, _ = self.udp_sock.recvfrom(2048)
                        reply = json.loads(data.decode("utf-8"))

                        # Аккуратно раскладываем реальный вылив, виртуальное давление и ШИМ в SharedState Питона
                        self.state.esp_current_flow = reply.get("cf", 0.0)
                        self.state.esp_pressure = reply.get("vp", 0.0)
                        self.state.esp_pwm = reply.get("pwm", 0)
                    except socket.timeout:
                        pass
                else:
                    time.sleep(0.1)
            except:
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self.close_uart()
        if self.udp_sock:
            self.udp_sock.close()
