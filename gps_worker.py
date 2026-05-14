# gps_worker.py
import serial
import pynmea2
import time
import threading
import config_manager


class GPSWorker(threading.Thread):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.running = True
        self.serial_device = None
        self.connected = False

        # Запоминаем текущие настройки, чтобы видеть изменения «на лету»
        self.current_port = None
        self.current_baud = None

    def run(self):
        print("[GPS_Unit] Поток GPS запущен.")
        while self.running:
            # 1. Проверяем режим эмуляции
            if self.state.emu_enabled:
                if self.connected:
                    self.close_port()
                time.sleep(0.2)
                continue

            # 2. Перечитываем актуальный конфиг (изменения из фронтенда)
            cfg = config_manager.load_config()

            if not cfg.get("GPS_ENABLE", False):
                if self.connected:
                    self.close_port()
                time.sleep(0.5)
                continue

            active_port = cfg.get("GPS_PORT", "com1")
            active_baud = cfg.get("GPS_PORT_SPEED", 9600)
            reconnect_delay = cfg.get("GPS_TIME_RECONNECT", 5000) / 1000.0

            # 3. Если фронтенд изменил настройки «на лету» — сбрасываем порт
            if self.connected and (
                active_port != self.current_port or active_baud != self.current_baud
            ):
                print(
                    f"[GPS_Unit] Настройки изменены во фронтенде! Переключение на {active_port}..."
                )
                self.close_port()

            # 4. Соединение / Чтение
            if not self.connected:
                self.connect_port(active_port, active_baud, reconnect_delay)
            else:
                self.read_and_parse()

            time.sleep(0.01)

    def connect_port(self, port, baud, delay):
        try:
            # Универсальный инициализатор pySerial (сам поймет и COM1, и /dev/ttyUSB0)
            self.serial_device = serial.Serial(port=port, baudrate=baud, timeout=1.0)
            self.current_port = port
            self.current_baud = baud
            self.connected = True
            print(f"[GPS_Unit] Успешно подключено к железу: {port} ({baud} baud)")
        except Exception as e:
            print(f"[GPS_Unit] Ошибка порта {port}: {e}. Повтор через {delay} сек...")
            self.connected = False
            time.sleep(delay)

    def read_and_parse(self):
        try:
            raw_line = self.serial_device.readline()
            if not raw_line:
                raise serial.SerialException("Тайм-аут данных")

            line = raw_line.decode("ascii", errors="ignore").strip()

            if "GGA" in line:
                msg = pynmea2.parse(line)
                if msg.latitude and msg.longitude:
                    self.state.last_lat = msg.latitude
                    self.state.last_lon = msg.longitude
                    self.state.rtk = int(msg.gps_qual)
                else:
                    self.state.rtk = 0

            if "VTG" in line:
                msg = pynmea2.parse(line)
                self.state.speed = float(msg.spd_over_grnd_kmph or 0)
                self.state.hdg = float(msg.true_track or self.state.hdg)

        except Exception as e:
            print(f"[GPS_Unit] Потеряна связь с GPS-модулем: {e}")
            self.close_port()

    def close_port(self):
        self.connected = False
        if self.serial_device:
            try:
                self.serial_device.close()
                print("[GPS_Unit] Порт успешно освобожден.")
            except:
                pass
        self.serial_device = None

    def stop(self):
        self.running = False
        self.close_port()
