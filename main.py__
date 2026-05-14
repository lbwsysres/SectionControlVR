import threading, socket, pynmea2, json, os, math, time
from section_engine import SectionControl
import config_manager
import web_server
import logging
import pyproj
import dump_manager


class SharedState:
    def __init__(self):
        cfg = config_manager.load_config()
        self.current_states = [False] * len(cfg.get("SECTION_WIDTHS", [3.0]))
        self.last_lat, self.last_lon = 49.0, 29.0
        self.area, self.speed, self.hdg, self.rtk = 0.0, 0.0, 0.0, 0
        self.path_history = []
        self.reset_flag = False
        self.emu_enabled = False
        self.emu_hdg = 0.0
        self.emu_speed = 0.0
        self.point_a = None
        self.point_b = None
        self.guidance_error = 0.0
        self.flow_percents = []  # Порожній список за замовчуванням

        # Завантажуємо історію при старті
        if os.path.exists("history.json"):
            try:
                with open("history.json", "r") as f:
                    self.path_history = json.load(f)
            except:
                self.path_history = []


# 1. Ініціалізуємо глобальні об'єкти один раз
state = SharedState()
cfg = config_manager.load_config()
sc = SectionControl(cfg)
# Передаємо завантажену історію в двигун
sc.path_history = state.path_history


def emulator_logic():
    """
    Логіка руху трактора в режимі емуляції.
    wheel_angle — це положення повзунка (кут коліс).
    hdg — це реальний курс компаса.
    """
    while True:
        if state.emu_enabled and state.emu_speed > 0:
            dt = 0.1  # Працюємо на 10 Гц (як GPS)

            # 1. Читаємо кут коліс з повзунка (-30...+30)
            wheel_angle = state.emu_hdg

            # Жорстка "мертва зона" для керма, щоб курс міг ЗАВМЕРТИ
            if abs(wheel_angle) < 0.1:
                turn_rate = 0.0
            else:
                # Чим вища швидкість і більший кут — тим швидше міняється курс
                # Коефіцієнт 0.4 можна підправити для реалістичності
                turn_rate = (wheel_angle * (state.emu_speed / 10.0)) * 0.8 * dt

            # 2. Оновлюємо курс трактора
            if turn_rate != 0:
                state.hdg = (state.hdg + turn_rate) % 360

            # 3. Рахуємо рух вперед
            dist = (state.emu_speed / 3.6) * dt  # Шлях за 100мс у метрах
            rad = math.radians(state.hdg)

            # Оновлюємо GPS координати
            state.last_lat += (dist * math.cos(rad)) / 111320
            state.last_lon += (dist * math.sin(rad)) / (
                111320 * math.cos(math.radians(state.last_lat))
            )

            state.speed = state.emu_speed
            state.rtk = 4  # Імітуємо ідеальний сигнал

        time.sleep(0.1)


def gps_loop():
    # Використовуємо глобальний cfg для сокета
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", cfg["UDP_PORT"]))
    sock.settimeout(0.1)

    while True:
        # Оновлюємо конфіг для перевірки режимів та Master Switch
        active_cfg = config_manager.load_config()
        sc.cfg = active_cfg  # Синхронізуємо конфіг в двигуні

        # Обробка прапорця Reset (якщо натиснуто в інтерфейсі)
        # if state.reset_flag:
        #     sc.reset()
        #     state.path_history = []
        #     state.area = 0.0
        #     history_file = cfg.get("HISTORY_FILE", "history.json")
        #     if os.path.exists(history_file):
        #         os.remove(history_file)
        #     state.reset_flag = False
        if state.reset_flag:
            sc.reset()
            state.path_history = []
            state.area = 0.0
            state.guidance_error = 0.0
            dump_manager.clear_current_dump()  # Видаляємо тимчасовий дамп з диска
            state.reset_flag = False

        if not state.emu_enabled:
            try:
                data, _ = sock.recvfrom(2048)
                lines = data.decode("ascii", errors="ignore").split("\n")
                for line in lines:
                    if "$GPGGA" in line:
                        msg = pynmea2.parse(line)
                        state.last_lat, state.last_lon, state.rtk = (
                            msg.latitude,
                            msg.longitude,
                            int(msg.gps_qual),
                        )
                    if "$GPVTG" in line:
                        msg = pynmea2.parse(line)
                        state.speed = float(msg.spd_over_grnd_kmph or 0)
                        state.hdg = float(msg.true_track or state.hdg)
            except (socket.timeout, Exception):
                pass
        # ГОЛОВНА ЛОГІКА ОБРОБКИ
        if state.last_lat != 0 and state.rtk >= 1:
            is_moving = state.speed >= active_cfg.get("MIN_SPEED", 1.0)
            master_on = active_cfg.get("MASTER_SW", False)

            # Викликаємо process ЗАВЖДИ при русі.
            # Внутрішня логіка sc сама вирішить, чи додавати полігон у covered_area
            if is_moving:

                # Отримуємо стани секцій (з урахуванням Master та Auto)
                auto_res = sc.process(
                    state.last_lat, state.last_lon, state.hdg, state.speed
                )

                # Отримуємо стани секцій (компенсация на поворотах)
                state.flow_percents = sc.curve_compensation(
                    state.speed, state.hdg, state.rtk
                )

                if state.point_a and state.point_b and sc.last_x is not None:
                    ax, ay = state.point_a
                    bx, by = state.point_b
                    tx, ty = sc.last_x, sc.last_y  # Поточне положення трактора

                    # Формула відстані від точки до прямої
                    num = (by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax
                    den = math.sqrt((by - ay) ** 2 + (bx - ax) ** 2)

                    if den > 0:
                        dist_to_ab = num / den
                        sw = sum(active_cfg["SECTION_WIDTHS"])  # Ширина штанги

                        # Визначаємо номер проходу (0, 1, 2, -1...)
                        pass_num = round(dist_to_ab / sw)
                        # Рахуємо помилку саме для поточного проходу
                        state.guidance_error = dist_to_ab - (pass_num * sw)
                else:
                    # Якщо координат немає (після Reset), скидаємо помилку в 0
                    state.guidance_error = 0.0

                # Формуємо фінальні стани для заліза/інтерфейсу (враховуючи ручні режими ON/OFF)
                final_states = []
                modes = active_cfg.get(
                    "SECTION_MODES", ["AUTO"] * len(active_cfg["SECTION_WIDTHS"])
                )

                for i in range(len(active_cfg["SECTION_WIDTHS"])):
                    mode = modes[i]
                    if not is_moving:
                        final_states.append(False)
                    elif mode == "ON" and master_on:
                        final_states.append(True)
                    elif mode == "OFF":
                        final_states.append(False)
                    else:  # AUTO
                        final_states.append(auto_res[i] if auto_res else False)

                state.current_states = final_states
                state.area = sc.get_area_ha()
                state.path_history = (
                    sc.path_history
                )  # Синхронізація історії для веб-сервера

                # Зберігаємо історію на диск раз на 50 точок
                # if len(state.path_history) % 50 == 0 and len(state.path_history) > 0:
                #     try:
                #         with open("history.json", "w") as f:
                #             json.dump(state.path_history[-5000:], f)
                #     except:
                #         pass
                # Зберігаємо повний Snapshot системи раз на 50 GPS точок (безпечно та монолітно)
                if len(state.path_history) % 50 == 0 and len(state.path_history) > 0:
                    dump_manager.save_session_dump(state, sc)

            else:
                # Якщо стоїмо - всі секції вимкнені
                state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                state.flow_percents = [100] * len(active_cfg.get("SECTION_WIDTHS", []))

        time.sleep(0.1)


if __name__ == "__main__":
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    # Запуск потоків
    # Перед стартом gps_loop та веб-сервера перевіряємо, чи не впало живлення раніше
    dump_manager.load_session_dump(state, sc)

    threading.Thread(target=gps_loop, daemon=True).start()
    threading.Thread(target=emulator_logic, daemon=True).start()

    # Запуск веб-сервера (передаємо state та sc)
    app = web_server.create_app(state, sc)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
