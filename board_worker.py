# board_worker.py
import serial
import time
import threading
import config_manager


class BoardWorker(threading.Thread):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.running = True
        self.serial_device = None
        self.connected = False

        self.current_port = None
        self.current_baud = None
        self.last_sent_states = []  # Для отправки данных ТОЛЬКО при изменении состояний

    def run(self):
        print("[Board_Unit] Tread section ON.")
        while self.running:
            cfg = config_manager.load_config()

            if not cfg.get("CONTROL_BOARD_ENABLE", False):
                if self.connected:
                    self.close_port()
                time.sleep(0.5)
                continue

            active_port = cfg.get("CONTROL_BOARD_PORT", "com2")
            active_baud = cfg.get("CONTROL_BOARD_PORT_SPEED", 115200)
            reconnect_delay = cfg.get("CONTROL_BOARD_TIME_RECONNECT", 5000) / 1000.0

            # Изменение настроек «на лету»
            if self.connected and (
                active_port != self.current_port or active_baud != self.current_baud
            ):
                print(f"[Board_Unit] Change port to {active_port}...")
                self.close_port()

            if not self.connected:
                self.connect_port(active_port, active_baud, reconnect_delay)
            else:
                self.send_commands_to_hardware()

            time.sleep(0.05)  # Плате секций достаточно работать на частоте 20 Гц

    def connect_port(self, port, baud, delay):
        try:
            self.serial_device = serial.Serial(port=port, baudrate=baud, timeout=0.5)
            self.current_port = port
            self.current_baud = baud
            self.connected = True
            self.state.board_connected = True 
            print(f"[Board_Unit] Board CONNECT: {port} ({baud} baud)")
        except Exception as e:
            print(
                f"[Board_Unit] Board port {port} Not : {e}. Repiat {delay} sec..."
            )
            self.connected = False
            self.state.board_connected = False 
            time.sleep(delay)

    def send_commands_to_hardware(self):
        try:
            # Проверяем, изменилось ли состояние секций, чтобы не спамить в порт зря
            current_states = list(self.state.current_states)

            if current_states != self.last_sent_states:
                # ПРИМЕР ФОРМИРОВАНИЯ КОМАНДЫ (замените под ваш протокол Arduino/Реле):
                # Переводим массив [True, False, True] в битовую маску или JSON строку
                # Например, преобразуем в строку вида "1,0,1,0,0,0,0,0\n"
                status_str = (
                    ",".join(["1" if s else "0" for s in current_states]) + "\n"
                )

                self.serial_device.write(status_str.encode("ascii"))
                self.serial_device.flush()  # Принудительно выталкиваем буфер в провод

                self.last_sent_states = current_states
                print(
                    f"[Board_Unit] Send command: {status_str.strip()}"
                )

        except Exception as e:
            print(f"[Board_Unit] Error send command: {e}")
            self.close_port()

    def close_port(self):
        self.connected = False
        self.state.board_connected = False 
        if self.serial_device:
            try:
                self.serial_device.close()
                print("[Board_Unit] Cloase port.")
            except:
                pass
        self.serial_device = None

    def stop(self):
        self.running = False
        self.close_port()
