# main.py
import threading
import time
import math
import logging
import config_manager
import web_server
import dump_manager
from section_engine import SectionControl

# ІМПОРТ ВСІХ НАШИХ ІЗОЛЬОВАНИХ ЮНІТІВ-ВОРКЕРІВ
from gps_worker import GPSWorker
from board_worker import BoardWorker
from emulator_worker import EmulatorWorker # <-- Наш новий модуль

class SharedState:
    def __init__(self):
        cfg = config_manager.load_config()
        self.current_states = [False] * len(cfg.get("SECTION_WIDTHS", [3.0]))
        self.last_lat, self.last_lon = 49.0, 29.0
        self.area, self.speed, self.hdg, self.rtk = 0.0, 0.0, 0.0, 0
        self.path_history = []
        self.reset_flag = False
        
        # Параметри для нашого нового квадратного джойстика
        self.emu_enabled = False
        self.emu_hdg = 0.0
        self.emu_speed = 0.0
        
        self.point_a = None
        self.point_b = None
        self.guidance_error = 0.0
        self.flow_percents = []

# Ініціалізація глобальних об'єктів (Singletons)
state = SharedState()
cfg = config_manager.load_config()
sc = SectionControl(cfg)
sc.path_history = state.path_history

def main_calculation_loop():
    """ 
    Головне математичне ядро. Воно працює на частоті 10 Гц.
    Йому абсолютно байдуже, ХТО наповнив коордитати у state (залізо чи емулятор).
    Воно просто бере їх і рахує геометрію відсікання секцій.
    """
    print("[Main_Engine] Потік математичних розрахунків секцій запущен.")
    while True:
        active_cfg = config_manager.load_config()
        sc.cfg = active_cfg

        if state.reset_flag:
            sc.reset()
            state.path_history = []
            state.area = 0.0
            state.guidance_error = 0.0
            dump_manager.clear_current_dump()
            state.reset_flag = False

        # Математика запускається, якщо є реальний Fix АБО якщо увімкнено емулятор
        if state.last_lat != 0 and (state.rtk >= 1 or state.emu_enabled):
            is_moving = state.speed >= active_cfg.get("MIN_SPEED", 1.0)
            master_on = active_cfg.get("MASTER_SW", False)

            if is_moving:
                auto_res = sc.process(state.last_lat, state.last_lon, state.hdg, state.speed)
                state.flow_percents = sc.curve_compensation(state.speed, state.hdg, state.rtk)
                
                # Розрахунок ліній паралельного водіння А-Б
                if state.point_a and state.point_b and sc.last_x is not None:
                    ax, ay = state.point_a
                    bx, by = state.point_b
                    tx, ty = sc.last_x, sc.last_y
                    num = (by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax
                    den = math.sqrt((by - ay) ** 2 + (bx - ax) ** 2)
                    if den > 0:
                        dist_to_ab = num / den
                        sw = sum(active_cfg["SECTION_WIDTHS"])
                        pass_num = round(dist_to_ab / sw)
                        state.guidance_error = dist_to_ab - (pass_num * sw)
                
                # Застосування режимів секцій (AUTO / ON / OFF)
                final_states = []
                modes = active_cfg.get("SECTION_MODES", ["AUTO"] * len(active_cfg["SECTION_WIDTHS"]))
                for i in range(len(active_cfg["SECTION_WIDTHS"])):
                    mode = modes[i]
                    if mode == "ON" and master_on: final_states.append(True)
                    elif mode == "OFF": final_states.append(False)
                    else: final_states.append(auto_res[i] if auto_res else False)
                state.current_states = final_states
            else:
                # Трактор стоїть — вимикаємо всі секції штанги
                state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                state.flow_percents = [100] * len(active_cfg.get("SECTION_WIDTHS", []))

            state.area = sc.get_area_ha()
            state.path_history = sc.path_history

            # Безпечний Snapshot системи на диск кожні 50 точок
            if len(state.path_history) % 50 == 0 and len(state.path_history) > 0:
                dump_manager.save_session_dump(state, sc)
        else:
            # Якщо немає жодних координат — штанга закрита
            state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])

        time.sleep(0.1) # Суворі 10 Гц розрахунків

if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dump_manager.load_session_dump(state, sc)

    # 1. Запуск апаратного заліза (потоки самі дивляться в конфіг увімкнені вони чи ні)
    gps_hardware = GPSWorker(state)
    gps_hardware.daemon = True
    gps_hardware.start()

    board_hardware = BoardWorker(state)
    board_hardware.daemon = True
    board_hardware.start()

    # 2. Запуск відокремленого емулятора руху трактора
    emulator_logic = EmulatorWorker(state)
    emulator_logic.daemon = True
    emulator_logic.start()

    # 3. Запуск розрахункового циклу геометрії поля
    threading.Thread(target=main_calculation_loop, daemon=True).start()

    # 4. Запуск Flask веб-сервера
    app = web_server.create_app(state, sc)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
