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
        print("[GPS_Unit] GPS is Run.")
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
                print(f"[GPS_Unit] Setting change! Connect to port: {active_port}...")
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
            self.state.gps_connected = True
            print(f"[GPS_Unit] Connect to port:: {port} ({baud} baud)")
        except Exception as e:
            print(f"[GPS_Unit] Error port {port}: {e}. Repiat {delay} sec...")
            self.connected = False
            self.state.gps_connected = False
            if hasattr(self.state, 'gps_sats'): self.state.gps_sats = 0
            if hasattr(self.state, 'hdop'): self.state.hdop = 0.0
            if hasattr(self.state, 'vdop'): self.state.vdop = 0.0
            if hasattr(self.state, 'pdop'): self.state.pdop = 0.0
            self.state.rtk = 0
            time.sleep(delay)

    # def read_and_parse(self):
    #     try:
    #         raw_line = self.serial_device.readline()
    #         if not raw_line:
    #             raise serial.SerialException("Time out data")

    #         line = raw_line.decode("ascii", errors="ignore").strip()

    #         # 1. Парсинг GGA (Координаты, RTK-статус, Супутники, HDOP)
    #         if "GGA" in line:
    #             msg = pynmea2.parse(line)
    #             self.state.gps_sats = int(msg.num_sats or 0)
    #             self.state.rtk = int(msg.gps_qual or 0)
    #             self.state.hdop = float(msg.hdop or 0.0)

    #             if msg.latitude and msg.longitude:
    #                 self.state.last_lat = msg.latitude
    #                 self.state.last_lon = msg.longitude
    #             else:
    #                 self.state.rtk = 0
    #                 # Если координат нет, сбрасываем точность в ноль
    #                 self.state.hdop = 0.0

    #         # 2. Парсинг GSA (Здесь гарантированно живут VDOP и PDOP)
    #         if "GSA" in line:
    #             msg = pynmea2.parse(line)
    #             self.state.vdop = float(msg.vdop or 0.0)
    #             self.state.pdop = float(msg.pdop or 0.0)
                
    #             # Дополнительная страховка: если в GGA почему-то не было HDOP
    #             if not getattr(self.state, 'hdop', 0.0):
    #                 self.state.hdop = float(msg.hdop or 0.0)

    #         # 3. Парсинг VTG (Скорость и Курс)
    #         if "VTG" in line:
    #             msg = pynmea2.parse(line)
    #             self.state.speed = float(msg.spd_over_grnd_kmph or 0.0)
    #             # Безопасное получение курса без риска AttributeError при первом старте
    #             self.state.hdg = float(msg.true_track or getattr(self.state, 'hdg', 0.0))

    #     except Exception as e:
    #         print(f"[GPS_Unit] Lost connect GPS: {e}")
    #         self.close_port()
    def read_and_parse(self):
        try:
            raw_line = self.serial_device.readline()
            if not raw_line:
                raise serial.SerialException("Time out data")

            line = raw_line.decode("ascii", errors="ignore").strip()

            # 1. Парсинг GGA (Координаты, RTK-статус, Спутники, HDOP)
            if "GGA" in line:
                msg = pynmea2.parse(line)
                
                # Безопасно вытягиваем спутники и RTK статус
                self.state.gps_sats = int(getattr(msg, 'num_sats', 0) or 0)
                self.state.rtk = int(getattr(msg, 'gps_qual', 0) or 0)
                
                # БЕЗОПАСНЫЙ СБОР HDOP: проверяем наличие атрибута через hasattr
                if hasattr(msg, 'hdop') and msg.hdop:
                    try:
                        self.state.hdop = float(msg.hdop)
                    except (ValueError, TypeError):
                        self.state.hdop = 0.0
                else:
                    self.state.hdop = 0.0

                # Проверка валидности координат
                if hasattr(msg, 'latitude') and msg.latitude and hasattr(msg, 'longitude') and msg.longitude:
                    self.state.last_lat = msg.latitude
                    self.state.last_lon = msg.longitude
                else:
                    self.state.rtk = 0
                    self.state.hdop = 0.0

            # 2. Парсинг GSA (VDOP и PDOP)
            if "GSA" in line:
                msg = pynmea2.parse(line)
                
                # Безопасный сбор VDOP
                if hasattr(msg, 'vdop') and msg.vdop:
                    try: self.state.vdop = float(msg.vdop)
                    except: self.state.vdop = 0.0
                else:
                    self.state.vdop = 0.0
                    
                # Безопасный сбор PDOP
                if hasattr(msg, 'pdop') and msg.pdop:
                    try: self.state.pdop = float(msg.pdop)
                    except: self.state.pdop = 0.0
                else:
                    self.state.pdop = 0.0
                
                # Дополнительный сбор HDOP из GSA (если в GGA его не было)
                if not getattr(self.state, 'hdop', 0.0) and hasattr(msg, 'hdop') and msg.hdop:
                    try: self.state.hdop = float(msg.hdop)
                    except: pass

            # 3. Парсинг VTG (Скорость и Курс)
            if "VTG" in line:
                msg = pynmea2.parse(line)
                
                spd = getattr(msg, 'spd_over_grnd_kmph', 0.0)
                self.state.speed = float(spd or 0.0)
                
                track = getattr(msg, 'true_track', None)
                self.state.hdg = float(track or getattr(self.state, 'hdg', 0.0))

        except Exception as e:
            # Теперь код не будет вылетать из-за пустых строк NMEA
            print(f"[GPS_Unit] Lost connect GPS: {e}")
            self.close_port()


    def close_port(self):
        self.connected = False
        self.state.gps_connected = False
        
        # Обнуляем DOPы и спутники при отключении физического кабеля
        if hasattr(self.state, 'gps_sats'): self.state.gps_sats = 0
        if hasattr(self.state, 'hdop'): self.state.hdop = 0.0
        if hasattr(self.state, 'vdop'): self.state.vdop = 0.0
        if hasattr(self.state, 'pdop'): self.state.pdop = 0.0
        self.state.rtk = 0
        
        if self.serial_device:
            try:
                self.serial_device.close()
                print("[GPS_Unit] Close port.")
            except:
                pass
        self.serial_device = None

    def stop(self):
        self.running = False
        self.close_port()
