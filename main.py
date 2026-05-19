# main.py
import threading
import time
import math
import logging
import config_manager
import web_server
import dump_manager
from section_engine import SectionControl
import pyproj

# ІМПОРТ ВСІХ НАШИХ ІЗОЛЬОВАНИХ ЮНІТІВ-ВОРКЕРІВ
from gps_worker import GPSWorker
from board_worker import BoardWorker
from emulator_worker import EmulatorWorker  # <-- Наш новий модуль
from vra_manager import VRAManager


class SharedState:
    def __init__(self):
        cfg = config_manager.load_config()
        self.current_states = [False] * len(cfg.get("SECTION_WIDTHS", [3.0]))
        self.last_lat, self.last_lon = 49.7604988, 29.0021806
        self.area, self.speed, self.hdg, self.rtk = 0.0, 0.0, 0.0, 0
        self.path_history = []
        self.reset_flag = False


        # --- НАШІ ГОЛІ ЦИФРИ VRA ДЛЯ BOARD_WORKER ---
        self.vra_flows = [0.0] * len(cfg.get("SECTION_WIDTHS", [3.0]))
        # Параметри для нашого нового квадратного джойстика
        self.emu_enabled = False
        self.emu_hdg = 0.0
        self.emu_speed = 0.0

        self.point_a = None
        self.point_b = None
        self.guidance_error = 0.0
        self.flow_percents = []

        self.gps_connected = False
        self.board_connected = False
        self.gps_sats = 0  # Чтобы парсер NMEA писал сюда число спутников
        self.current_file = "NEW"
        # --- ДОДАНО ДЛЯ РЕЖИМІВ GPS ТА КЕРУВАННЯ НАПІВ-АВТОМАТОМ ---
        self.gps_mode = 0  # 0 = хана, 1 = ОК, 2 = так собі, 3 = стоїмо на місці
        self.gps_mode_text = "CRITICAL: Initializing..."  # Текстовий опис для логів

        self.esp_current_flow = 0.0  # Реальна витрата рідини (л/хв)
        self.esp_pressure = 0.0      # Поточний тиск у системі (бар)
        self.esp_pwm = 0             # Поточна потужність насоса (0..1023)


# Ініціалізація глобальних об'єктів (Singletons)
state = SharedState()
cfg = config_manager.load_config()
sc = SectionControl(cfg)
sc.path_history = state.path_history


def main_calculation_loop():
    """
    Головне математичне ядро. Частота 10 Гц.
    Керує режимами роботи системи через цифрові коди стану (state.gps_mode).
    """
    print("[Main_Engine] Tread calculate is Run.")

    last_track_x = None
    last_track_y = None

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
            last_track_x = last_track_y = None

        # Перевіряємо наявність базового зв'язку з GPS
        has_gps_signal = state.last_lat != 0 and state.last_lon != 0

        if has_gps_signal:
            is_moving = state.speed >= active_cfg.get("MIN_SPEED", 1.0)
            master_on = active_cfg.get("MASTER_SW", False)

            if is_moving:
                # 1. Перевірка на аномальний стрибок координат
                gps_jump_detected = False
                # пока блокируем
                # if sc.last_x is not None and sc.transformer_to_m is not None:
                #     tx, ty = sc.transformer_to_m.transform(state.last_lon, state.last_lat)
                #     dist_step = math.sqrt((tx - sc.last_x)**2 + (ty - sc.last_y)**2)
                #     if dist_step > 1.5:
                #         gps_jump_detected = True

                # 2. Перевірка якості RTK
                min_rtk_allowed = active_cfg.get("MIN_REQUIRED_RTK", 4)
                is_rtk_good = (state.rtk >= min_rtk_allowed) or state.emu_enabled

                # 3. ВИЗНАЧЕННЯ РЕЖИМУ ТА РОЗРАХУНОК ГЕОМЕТРІЇ
                if master_on and is_rtk_good and not gps_jump_detected:
                    # =======================================================================
                    # РЕЖИМ 1: ОК (ПОВНИЙ АВТОМАТ)
                    # =======================================================================
                    # state.gps_mode = 1
                    # state.gps_mode_text = "OK: Full Auto Mode"

                    # auto_res = sc.process(
                    #     state.last_lat, state.last_lon, state.hdg, state.speed
                    # )
                    # state.flow_percents = sc.curve_compensation(
                    #     state.speed, state.hdg, state.rtk
                    # )

                    # final_states = []
                    # modes = active_cfg.get(
                    #     "SECTION_MODES", ["AUTO"] * len(active_cfg["SECTION_WIDTHS"])
                    # )
                    # for i in range(len(active_cfg["SECTION_WIDTHS"])):
                    #     mode = modes[i]
                    #     if mode == "ON":
                    #         final_states.append(True)
                    #     elif mode == "OFF":
                    #         final_states.append(False)
                    #     else:
                    #         final_states.append(auto_res[i] if auto_res else False)
                    # state.current_states = final_states

                    # last_track_x = last_track_y = None
                    # =======================================================================
                    # РЕЖИМ 1: ОК (ПОВНИЙ АВТОМАТ) - ОНОВЛЕНО ПІД ГОЛІ ЦИФРИ VRA
                    # =======================================================================
                    state.gps_mode = 1
                    state.gps_mode_text = "OK: Full Auto Mode"
                    
                    # 1. Твій базовий прорахунок геометрії перекриттів та поворотів штанги
                    auto_res = sc.process(state.last_lat, state.last_lon, state.hdg, state.speed)
                    state.flow_percents = sc.curve_compensation(state.speed, state.hdg, state.rtk)
                    
                    # 2. Витягуємо залізне налаштування алгоритму сканування карти з config.json
                    vra_mode = active_cfg.get("VRA_CALC_MODE", "boom")
                    widths = active_cfg.get("SECTION_WIDTHS", [1.0] * 8)
                    num_sections = len(widths)
                    
                    # Масиви для голих цифр VRA, які забере BoardWorker
                    vra_flows = [0.0] * num_sections
                    final_states = []
                    modes = active_cfg.get("SECTION_MODES", ["AUTO"] * num_sections)
                    
                    # 3. ХАРДКОРНИЙ СКАНИР ЗОН КАРТИ ПОЛЯ
                    if vra_mode == "boom":
                        # Режим "Вся штанга": 1 запит за координатами антени трактора
                        base_boom_rate = state.vra_manager.get_target_rate(state.last_lon, state.last_lat)
                        vra_flows = [base_boom_rate] * num_sections
                    else:
                        # Режим "Посекційно": кожна секція прораховує свої власні координати
                        if sc.transformer_to_m is not None:
                            # Проектуємо поточні координати трактора в локальні метри
                            ux, uy = sc.transformer_to_m.transform(state.last_lon, state.last_lat)
                            th_rad = math.radians(state.hdg)
                            
                            l_offset = -sum(widths) / 2
                            for i, w in enumerate(widths):
                                # Считаем центр конкретной секции на штанге в метрах
                                sec_center_offset = l_offset + (w / 2)
                                sec_x, sec_y = sc.get_section_point(ux, uy, th_rad, sec_center_offset)
                                
                                # Обратный перевод локальных метров в глобальные GPS-градусы для Shapefile
                                # (Используем обратный трансформер geopandas/pyproj)
                                try:
                                    transformer_back = pyproj.Transformer.from_crs(sc.transformer_to_m.target_crs, "epsg:4326", always_xy=True)
                                    sec_lon, sec_lat = transformer_back.transform(sec_x, sec_y)
                                    # Запитуємо індивідуальну дозу з карти
                                    vra_flows[i] = state.vra_manager.get_target_rate(sec_lon, sec_lat)
                                except:
                                    vra_flows[i] = state.vra_manager.rate_default # Захисний дефолт при збої
                                l_offset += w
                    
                    # 4. Формуємо On/Off стани форсунок з урахуванням тумблерів ON/OFF/AUTO
                    for i in range(num_sections):
                        mode = modes[i]
                        if mode == "ON":
                            final_states.append(True)
                        elif mode == "OFF":
                            final_states.append(False)
                        else:
                            final_states.append(auto_res[i] if auto_res else False)
                    
                    # 5. Записуємо голі цифри у глобальний SharedState для BoardWorker
                    state.current_states = final_states              # Масив [True, False, ...] -> on/off
                    state.vra_flows = vra_flows                      # Голі дози з карти [100.0, 150.0, ...] -> flow
                    # state.flow_percents уже заповнений від curve_compensation -> percent
                    
                    last_track_x = last_track_y = None


                elif master_on and (not is_rtk_good or gps_jump_detected):
                    # =======================================================================
                    # РЕЖИМ 2: ТАК СОБІ (НАПІВ-АВТОМАТ / ЗАМОРОЗКА КАРТИ)
                    # =======================================================================
                    state.gps_mode = 2
                    state.gps_mode_text = f"WARNING: Low Accuracy ({'GPS Jump' if gps_jump_detected else 'Float'}). Fallback to Semi-Auto."
                    print(f"[Main_Engine] {state.gps_mode_text}")

                    # Заморожуємо карту (sc.process НЕ викликається).
                    # Утримуємо останні стабільні стани AUTO-секцій, щоб уникнути хаотичного торохтіння клапанів
                    modes = active_cfg.get(
                        "SECTION_MODES", ["AUTO"] * len(active_cfg["SECTION_WIDTHS"])
                    )
                    fallback_states = []
                    for i, mode in enumerate(modes):
                        if mode == "OFF":
                            fallback_states.append(False)
                        elif mode == "ON":
                            fallback_states.append(True)
                        else:
                            # Для AUTO: утримуємо попередній стан, якщо він був, інакше примусово вмикаємо (True) проти пропусків
                            fallback_states.append(
                                state.current_states[i]
                                if state.current_states
                                else True
                            )

                    state.current_states = fallback_states
                    state.flow_percents = [100] * len(
                        active_cfg.get("SECTION_WIDTHS", [])
                    )

                else:
                    # =======================================================================
                    # РЕЖИМ 1 (АЛЕ MASTER_SW = FALSE): ТРАКТОР РУХАЄТЬСЯ, АЛЕ ОБПРИСКУВАННЯ ВИМКНЕНО
                    # =======================================================================
                    state.gps_mode = 1
                    state.gps_mode_text = "OK: Spraying is Disabled (Master Off)"

                    state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                    state.flow_percents = [100] * len(
                        active_cfg.get("SECTION_WIDTHS", [])
                    )

                    # Запис спрощеного фонового треку через кожні 2.5 метри
                    if sc.transformer_to_m is not None:
                        tx, ty = sc.transformer_to_m.transform(
                            state.last_lon, state.last_lat
                        )
                        dist_moved = (
                            math.sqrt(
                                (tx - last_track_x) ** 2 + (ty - last_track_y) ** 2
                            )
                            if last_track_x is not None
                            else 999.0
                        )

                        if dist_moved >= 2.5:
                            pt_blank = [
                                state.last_lat,
                                state.last_lon,
                                state.hdg,
                                list(state.current_states),
                            ]
                            sc.path_history.append(pt_blank)
                            if len(sc.path_history) > 10000:
                                sc.path_history.pop(0)
                            last_track_x, last_track_y = tx, ty

                # Розрахунок ліній паралельного водіння А-Б (потрібен у режимах 1 та 2)
                if state.point_a and state.point_b:
                    if sc.transformer_to_m is None:
                        zone = int((state.last_lon + 180) / 6) + 1
                        sc.transformer_to_m = pyproj.Transformer.from_crs(
                            "epsg:4326", f"epsg:326{zone}", always_xy=True
                        )

                    tx, ty = sc.transformer_to_m.transform(
                        state.last_lon, state.last_lat
                    )
                    ax, ay = state.point_a
                    bx, by = state.point_b

                    num = (by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax
                    den = math.sqrt((by - ay) ** 2 + (bx - ax) ** 2)
                    if den > 0:
                        dist_to_ab = num / den
                        sw = sum(active_cfg["SECTION_WIDTHS"])
                        pass_num = round(dist_to_ab / sw)
                        state.guidance_error = dist_to_ab - (pass_num * sw)

            else:
                # =======================================================================
                # РЕЖИМ 3: СОВСЕМ ПЛОХО (ТРАКТОР СТОЇТЬ НА МІСЦІ)
                # =======================================================================
                state.gps_mode = 3
                state.gps_mode_text = "STOPPED: Speed is too low. Valves closed."

                state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                state.flow_percents = [100] * len(active_cfg.get("SECTION_WIDTHS", []))

            state.area = sc.get_area_ha()
            state.path_history = sc.path_history

            if len(state.path_history) % 50 == 0 and len(state.path_history) > 0:
                dump_manager.save_session_dump(state, sc)
        else:
            # =======================================================================
            # РЕЖИМ 0: ХАНА (ПОВНА ВТРАТА СИГНАЛУ GPS / NO FIX)
            # =======================================================================
            state.gps_mode = 0
            state.gps_mode_text = "CRITICAL: No GPS Signal! All valves forced closed."

            state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])

        time.sleep(0.1)  # Суворі 10 Гц розрахунків


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dump_manager.load_session_dump(state, sc)

    # Инициализируем менеджер карт-предписаний
    vra_manager = VRAManager(cfg)
    # Загружаем карту из папки корень/geodata/test_Shapefile.zip
    vra_manager.load_map_from_zip("test_Shapefile.zip")
    state.vra_manager = vra_manager
    # 3. АВТОЗАГРУЗКА: Проверяем, был ли в прошлой сессии активный файл карты
    # ИСПРАВЛЕНО: Читаем атрибут напрямую из SharedState с дефолтом None
    last_active_file = getattr(state, "active_vra_file", None)
    
    if last_active_file:
        print(f"[VRA DUMP]: Обнаружена активная карта из прошлой сессии: {last_active_file}")
        success = vra_manager.load_map_from_zip(last_active_file)
        if not success:
            # Если файл поврежден, безопасно сбрасываем атрибут в объекте
            state.active_vra_file = None
    else:
        print("[VRA DUMP]: В прошлой сессии карта задач не использовалась. Работа по базовой норме.")


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
    app.run(host="0.0.0.0", port=80, debug=True, use_reloader=False)
