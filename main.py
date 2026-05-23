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
import multiprocessing


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
        self.esp_pressure = 0.0  # Поточний тиск у системі (бар)
        self.esp_pwm = 0  # Поточна потужність насоса (0..1023)


# Ініціалізація глобальних об'єктів (Singletons)
state = SharedState()
cfg = config_manager.load_config()
sc = SectionControl(cfg)
sc.path_history = state.path_history
data_queue = multiprocessing.Queue(maxsize=2)
cmd_queue = multiprocessing.Queue()


def main_calculation_loop():
    """
    Головне математичне ядро. Частота 10 Гц.
    Керує режимами роботи системи через цифрові коди стану (state.gps_mode).
    """
    print("[Main_Engine] Tread calculate is Run.")

    last_track_x = None
    last_track_y = None

    while True:
        # 1. ОБРОБКА КОМАНД З ВЕБ-ІНТЕРФЕЙСУ (Flask -> Математика)
        while not cmd_queue.empty():
            try:
                cmd_data = cmd_queue.get_nowait()
                cmd = cmd_data.get("cmd")

                if cmd == "reset" or cmd == "reset_area":
                    sc.current_wkb_filename = "current_session.wkb"
                    state.current_file = "NEW"

                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        vra.reset_manager()
                    # ПРАВИЛЬНЫЙ ФЕН-ШУЙ: Записываем в маркер, что мы в чистом поле
                    try:
                        with open(
                            os.path.join(dump_manager.DUMP_DIR, "last_field.txt"), "w"
                        ) as f:
                            f.write("current_session")
                    except:
                        pass

                    state.reset_flag = True

                # if cmd == "reset":
                #     state.reset_flag = True
                elif cmd == "reload_config":
                    # config_manager у нас на кеші, тому просто релоадимо
                    config_manager._cached_config = None
                    active_cfg = config_manager.load_config()
                    sc.cfg = active_cfg
                    # ЖЕСТКИЙ ФЕН-ШУЙ ФИКС: Сбрасываем память штанги!
                    # Когда Master Switch щелкает (Вкл/Выкл), геометрия ОБЯЗАНА забыть
                    # предыдущие координаты, чтобы не строить полигоны-телепорты через пол поля.
                    sc.last_p1_list = []
                    sc.last_p2_list = []
                    sc.last_x = None
                    sc.last_y = None
                    print(
                        "[Main_Engine] Переключатель Master Switch изменен. Координаты штанги синхронизированы."
                    )

                elif cmd == "reset_area":
                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        vra.reset_manager()
                    state.reset_flag = True
                elif cmd == "activate_vra":
                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        if vra.activate_existing_map(cmd_data["filename"]):
                            state.active_vra_file = cmd_data["filename"]
                elif cmd == "deactivate_vra":
                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        vra.deactivate_map()
                    state.active_vra_file = None
                elif cmd == "emu_control":
                    state.emu_hdg = cmd_data["hdg"]
                    state.emu_speed = cmd_data["spd"]
                    state.emu_enabled = cmd_data["enabled"]

                # elif cmd == "load_field":
                #     import os
                #     import shutil
                #     from shapely import wkb

                #     base_name = os.path.basename(cmd_data["filename"])  # Наприклад: "1.json"
                #     name_without_ext, _ = os.path.splitext(base_name)   # "1"

                #     # Шляхи до архівних файлів поля, яке ми хочемо відкрити
                #     archive_json_path = os.path.join(dump_manager.DUMP_DIR, base_name)
                #     archive_wkb_path = os.path.join(dump_manager.DUMP_DIR, f"{name_without_ext}.wkb")

                #     if os.path.exists(archive_json_path):
                #         print(f"[Main_Engine] АКТИВАЦІЯ ПОЛЯ: {name_without_ext}")

                #         # --- ГОЛОВНИЙ ФЕН-ШУЙ ФІКС ---
                #         # Копіюємо вибране поле поверх поточної робочої сесії,
                #         # щоб при перезапуску сервера завантажувалося саме ВОНО!
                #         current_json_path = os.path.join(dump_manager.DUMP_DIR, "current_session.json")
                #         current_wkb_path = os.path.join(dump_manager.DUMP_DIR, "current_session.wkb")

                #         try:
                #             shutil.copyfile(archive_json_path, current_json_path)
                #             if os.path.exists(archive_wkb_path):
                #                 shutil.copyfile(archive_wkb_path, current_wkb_path)
                #         except Exception as e:
                #             print(f"[Main_Engine] Помилка синхронізації сесії: {e}")

                #         # Присвоюємо актуальні робочі імена у двигун геометрії
                #         sc.current_wkb_filename = f"{name_without_ext}.wkb"
                #         state.current_file = name_without_ext

                #         # 1. Завантажуємо історію точок (для Canvas)
                #         dump_manager.load_session_dump(state, sc, filename=archive_json_path)

                #         # 2. Завантажуємо бінарну геометрию
                #         if os.path.exists(archive_wkb_path):
                #             try:
                #                 with open(archive_wkb_path, "rb") as f:
                #                     sc.covered_area = wkb.loads(f.read())
                #                 print(f"[Main_Engine] Геометрія поля '{name_without_ext}' успішно піднята в ОЗУ!")
                #             except Exception as e:
                #                 print(f"[Main_Engine] Помилка парсингу WKB: {e}")
                #         else:
                #             from shapely.geometry import MultiPolygon
                #             sc.covered_area = MultiPolygon()
                elif cmd == "load_field":
                    import os
                    from shapely import wkb

                    base_name = os.path.basename(cmd_data["filename"])  # "1.json"
                    name_without_ext, _ = os.path.splitext(base_name)  # "1"

                    archive_json_path = os.path.join(dump_manager.DUMP_DIR, base_name)
                    archive_wkb_path = os.path.join(
                        dump_manager.DUMP_DIR, f"{name_without_ext}.wkb"
                    )

                         # --- ПОТОКОВЕ ЗАВАНТАЖЕННЯ АРХІВНОГО ПОЛЯ ЧЕРЕЗ ЕШЕЛОНИ ---
                    if os.path.exists(archive_wkb_path):
                        try:
                            all_chunks = []
                            with open(archive_wkb_path, "rb") as f:
                                while True:
                                    try:
                                        chunk = wkb.load(f)
                                        if chunk and not chunk.is_empty:
                                            all_chunks.append(chunk)
                                    except EOFError:
                                        break
                                    except:
                                        break
                            if all_chunks:
                                sc.covered_area = unary_union(all_chunks)
                                print(f"[Main_Engine] Геометрія поля '{name_without_ext}' успішно відновлена з {len(all_chunks)} ешелонів WKB!")
                            else:
                                from shapely.geometry import MultiPolygon
                                sc.covered_area = MultiPolygon()
                        except Exception as e:
                            print(f"[Main_Engine] Помилка потокового читання WKB поля {name_without_ext}: {e}")
                    else:
                        from shapely.geometry import MultiPolygon
                        sc.covered_area = MultiPolygon()
                        print(f"[Main_Engine] Попередження: Файл {name_without_ext}.wkb не знайдено. Карта чиста.")

                    # if os.path.exists(archive_json_path):
                    #     print(f"[Main_Engine] АКТИВАЦІЯ ПОЛЯ: {name_without_ext}")

                    #     # ПРАВИЛЬНЫЙ ФЕН-ШУЙ: Запоминаем имя активного поля в маркер!
                    #     try:
                    #         with open(os.path.join(dump_manager.DUMP_DIR, "last_field.txt"), "w") as f:
                    #             f.write(name_without_ext)
                    #     except: pass

                    #     sc.current_wkb_filename = f"{name_without_ext}.wkb"
                    #     state.current_file = name_without_ext

                    #     dump_manager.load_session_dump(state, sc, filename=archive_json_path)

                    #     if os.path.exists(archive_wkb_path):
                    #         with open(archive_wkb_path, "rb") as f:
                    #             sc.covered_area = wkb.loads(f.read())

                # elif cmd == "save_field":
                #     import os
                #     base_name = os.path.basename(cmd_data["filename"]) # Например: "Люцерна_2026.json"
                #     name_without_ext, _ = os.path.splitext(base_name)

                #     # Формируем фен-шуйное имя для WKB-файла
                #     wkb_name = f"{name_without_ext}.wkb"

                #     # Присваиваем новые имена файлов в движок расчетов
                #     sc.current_wkb_filename = wkb_name
                #     state.current_file = name_without_ext

                #     # 1. Сохраняем текстовый JSON через ваш дамп-менеджер
                #     json_full_path = os.path.join(dump_manager.DUMP_DIR, base_name)
                #     dump_manager.save_session_dump(state, sc, filename=json_full_path)

                #     # 2. Сразу же принудительно сохраняем бинарный WKB-файл геометрии!
                #     sc.save_to_disk()
                #     print(f"[Main_Engine] Поле успешно сохранено: {name_without_ext}.json + {wkb_name}")
                # elif cmd == "save_field":
                #     import os

                #     base_name = os.path.basename(cmd_data["filename"])  # "1.json"
                #     name_without_ext, _ = os.path.splitext(base_name)  # "1"

                #     # ПРАВИЛЬНЫЙ ФЕН-ШУЙ: Запоминаем имя созданного поля в маркер!
                #     try:
                #         with open(
                #             os.path.join(dump_manager.DUMP_DIR, "last_field.txt"), "w"
                #         ) as f:
                #             f.write(name_without_ext)
                #     except:
                #         pass

                #     sc.current_wkb_filename = f"{name_without_ext}.wkb"
                #     state.current_file = name_without_ext

                #     json_full_path = os.path.join(dump_manager.DUMP_DIR, base_name)
                #     dump_manager.save_session_dump(state, sc, filename=json_full_path)
                #     sc.save_to_disk()
                elif cmd == "save_field":
                    import os
                    from shapely import wkb
                    base_name = os.path.basename(cmd_data["filename"]) # "1.json"
                    name_without_ext, _ = os.path.splitext(base_name)  # "1"
                    
                    try:
                        with open(os.path.join(dump_manager.DUMP_DIR, "last_field.txt"), "w") as f:
                            f.write(name_without_ext)
                    except: pass

                    sc.current_wkb_filename = f"{name_without_ext}.wkb"
                    state.current_file = name_without_ext
                    
                    json_full_path = os.path.join(dump_manager.DUMP_DIR, base_name)
                    dump_manager.save_session_dump(state, sc, filename=json_full_path)
                    
                    # ПРИМУСОВИЙ СКИД ВСІЄЇ КАРТИ ПРИ СТВОРЕННІ НОВОГО ФАЙЛУ FIELD
                    # 2. Зберігаємо чистий базовий ешелон геометрії у файл поля
                    wkb_full_path = os.path.join(dump_manager.DUMP_DIR, f"{name_without_ext}.wkb")
                    try:
                        # Записуємо через потоковий dump у режимі "wb" (створення бази)
                        with open(wkb_full_path, "wb") as f:
                            wkb.dump(sc.covered_area, f, hex=False)
                        print(f"[Main_Engine] Поле успішно створено: {name_without_ext}.json + {name_without_ext}.wkb")
                    except Exception as e:
                        print(f"[Main_Engine] Не вдалося створити базу WKB: {e}")


                elif cmd == "set_point":
                    label = cmd_data["label"]
                    if label == "a":
                        state.point_a = (sc.last_x, sc.last_y)
                    elif label == "b":
                        state.point_b = (sc.last_x, sc.last_y)
                    elif label == "reset":
                        state.point_a = state.point_b = None
                    elif label == "manual_coords":
                        mx, my = sc.transformer_to_m.transform(
                            float(cmd_data["lon"]), float(cmd_data["lat"])
                        )
                        if cmd_data["target"] == "a":
                            state.point_a = (mx, my)
                        else:
                            state.point_b = (mx, my)
            except:
                pass
        # ***********************************************************************
        active_cfg = config_manager.load_config()
        sc.cfg = active_cfg

        if state.reset_flag:
            sc.current_wkb_filename = "current_session.wkb"
            state.current_file = "NEW"
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
                    auto_res = sc.process(
                        state.last_lat, state.last_lon, state.hdg, state.speed
                    )
                    state.flow_percents = sc.curve_compensation(
                        state.speed, state.hdg, state.rtk
                    )

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
                        base_boom_rate = state.vra_manager.get_target_rate(
                            state.last_lon, state.last_lat
                        )
                        vra_flows = [base_boom_rate] * num_sections
                    else:
                        # Режим "Посекційно": кожна секція прораховує свої власні координати
                        if sc.transformer_to_m is not None:
                            # Проектуємо поточні координати трактора в локальні метри
                            ux, uy = sc.transformer_to_m.transform(
                                state.last_lon, state.last_lat
                            )
                            th_rad = math.radians(state.hdg)

                            l_offset = -sum(widths) / 2
                            for i, w in enumerate(widths):
                                # Считаем центр конкретной секции на штанге в метрах
                                sec_center_offset = l_offset + (w / 2)
                                sec_x, sec_y = sc.get_section_point(
                                    ux, uy, th_rad, sec_center_offset
                                )

                                # Обратный перевод локальных метров в глобальные GPS-градусы для Shapefile
                                # (Используем обратный трансформер geopandas/pyproj)
                                try:
                                    transformer_back = pyproj.Transformer.from_crs(
                                        sc.transformer_to_m.target_crs,
                                        "epsg:4326",
                                        always_xy=True,
                                    )
                                    sec_lon, sec_lat = transformer_back.transform(
                                        sec_x, sec_y
                                    )
                                    # Запитуємо індивідуальну дозу з карти
                                    vra_flows[i] = state.vra_manager.get_target_rate(
                                        sec_lon, sec_lat
                                    )
                                except:
                                    vra_flows[i] = (
                                        state.vra_manager.rate_default
                                    )  # Захисний дефолт при збої
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
                    state.current_states = (
                        final_states  # Масив [True, False, ...] -> on/off
                    )
                    state.vra_flows = (
                        vra_flows  # Голі дози з карти [100.0, 150.0, ...] -> flow
                    )
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
            # 2. Якщо активовано конкретне поле, пишемо дубль у його особистий файл!
            current_file_name = getattr(state, "current_file", "NEW")
            if current_file_name != "NEW":
                import os

                field_json_path = os.path.join(
                    dump_manager.DUMP_DIR, f"{current_file_name}.json"
                )
                dump_manager.save_session_dump(state, sc, filename=field_json_path)
        else:
            # =======================================================================
            # РЕЖИМ 0: ХАНА (ПОВНА ВТРАТА СИГНАЛУ GPS / NO FIX)
            # =======================================================================
            state.gps_mode = 0
            state.gps_mode_text = "CRITICAL: No GPS Signal! All valves forced closed."

            state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])

        # 3. ВІДПРАВКА СНІМКА СТАНУ В ПРОЦЕС FLASK (Математика -> Flask)
        # Формуємо ультра-легкий пакет, де немає важких C++ об'єктів
        snapshot = {
            "area": state.area,
            "states": list(state.current_states),
            "pos": [state.last_lat, state.last_lon],
            "flow_percents": list(state.flow_percents),
            "vra_flows": list(state.vra_flows),
            "speed": state.speed,
            "hdg": state.hdg,
            "rtk": state.rtk,
            "point_a": state.point_a,
            "point_b": state.point_b,
            "guidance_error": getattr(state, "guidance_error", 0.0),
            "new_points": list(state.path_history),
            "total_count": len(state.path_history),
            "gps_mode": state.gps_mode,
            "gps_mode_text": state.gps_mode_text,
            "gps_connected": getattr(state, "gps_connected", False),
            "board_connected": getattr(state, "board_connected", False),
            "gps_sats": getattr(state, "gps_sats", 0),
            "hdop": getattr(state, "hdop", 0.0),
            "vdop": getattr(state, "vdop", 0.0),
            "pdop": getattr(state, "pdop", 0.0),
            "current_file": getattr(state, "current_file", "NEW"),
            "esp_current_flow": getattr(state, "esp_current_flow", 0.0),
            "esp_pressure": getattr(state, "esp_pressure", 0.0),
            "esp_pwm": getattr(state, "esp_pwm", 0),
            "active_vra_file": getattr(state, "active_vra_file", None),
        }

        # Очищаємо чергу перед записом, щоб Flask завжди бачив тільки найсвіжіший кадр
        if data_queue.full():
            try:
                data_queue.get_nowait()
            except:
                pass
        try:
            data_queue.put_nowait(snapshot)
        except:
            pass

        time.sleep(0.25)  # Суворі 4 Гц розрахунків


def start_flask_process(d_queue, c_queue):
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import os
    import json
    import dump_manager
    import web_server

    # Читаем маркер, чтобы Flask знал, какой JSON поднять для Canvas!
    marker_path = os.path.join(dump_manager.DUMP_DIR, "last_field.txt")
    active_field_name = "current_session"

    if os.path.exists(marker_path):
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                saved_name = f.read().strip()
                if saved_name:
                    active_field_name = saved_name
        except:
            pass

    target_json_path = os.path.join(dump_manager.DUMP_DIR, f"{active_field_name}.json")

    if os.path.exists(target_json_path):
        try:
            with open(target_json_path, "r", encoding="utf-8") as f:
                dump_data = json.load(f)
                history = dump_data.get("path_history", [])

                web_server.WEB_CACHE["new_points"] = history
                web_server.WEB_CACHE["total_count"] = len(history)
                web_server.WEB_CACHE["area"] = dump_data.get("area", 0.0)
                web_server.WEB_CACHE["current_file"] = dump_data.get(
                    "current_file", "NEW"
                )
                web_server.WEB_CACHE["active_vra_file"] = dump_data.get(
                    "active_vra_file", None
                )
                print(
                    f"[Web_Server Autoload] УСПЕХ: Загружен трек поля '{active_field_name}' ({len(history)} точек)."
                )
        except Exception as e:
            print(f"[Web_Server Autoload] Ошибка предзагрузки кеша: {e}")

    app = web_server.create_app(d_queue, c_queue)
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


def start_flask_process_0(d_queue, c_queue):
    """Кастомна функція-ініціатор для ізольованого запуску Flask"""
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # --- ФЕН-ШУЙ ФИКС ХОЛОДНОГО СТАРТА ДЛЯ КАНВАСА ---
    # Принудительно читаем последний JSON-дамп прямо силами процесса Flask,
    # чтобы веб-cache сразу заполнился старым следом для планшета!
    import os
    import json
    import dump_manager
    import web_server

    current_json_path = os.path.join(dump_manager.DUMP_DIR, "current_session.json")
    if os.path.exists(current_json_path):
        try:
            with open(current_json_path, "r", encoding="utf-8") as f:
                dump_data = json.load(f)
                # Достаем сохраненный массив path_history из дампа
                history = dump_data.get("path_history", [])

                # Забиваем историю в локальный ОЗУ-кеш этого процесса Flask
                web_server.WEB_CACHE["new_points"] = history
                web_server.WEB_CACHE["total_count"] = len(history)
                web_server.WEB_CACHE["area"] = dump_data.get("area", 0.0)
                web_server.WEB_CACHE["current_file"] = dump_data.get(
                    "current_file", "NEW"
                )
                web_server.WEB_CACHE["active_vra_file"] = dump_data.get(
                    "active_vra_file", None
                )

                print(
                    f"[Web_Server Autoload] УСПЕХ: {len(history)} точек истории загружено в веб-кеш для Canvas."
                )
        except Exception as e:
            print(f"[Web_Server Autoload] Не удалось предзагрузить JSON трек: {e}")

    # Создаем и запускаем фабрику Flask (теперь кеш уже полный!)
    app = web_server.create_app(d_queue, c_queue)
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


def start_flask_process_1(d_queue, c_queue):
    """Кастомна функція-ініціатор для ізольованого запуску Flask"""
    # Створюємо чистий екземпляр програми всередині нового ядра CPU
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = web_server.create_app(d_queue, c_queue)
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
   
    import os
    from shapely import wkb
    from shapely.geometry import MultiPolygon

    # 1. ОПРЕДЕЛЯЕМ ИМЯ ПОСЛЕДНЕГО АКТИВНОГО ФАЙЛА ПО МАРКЕРУ
    marker_path = os.path.join(dump_manager.DUMP_DIR, "last_field.txt")
    active_field_name = "current_session"  # Дефолт, если маркер пустой

    if os.path.exists(marker_path):
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                saved_name = f.read().strip()
                if saved_name:
                    active_field_name = saved_name
        except:
            pass

    # Формируем правильные пути к файлам на основе маркера
    target_json_name = f"{active_field_name}.json"
    target_wkb_name = f"{active_field_name}.wkb"

    json_path = os.path.join(dump_manager.DUMP_DIR, target_json_name)
    wkb_path = os.path.join(dump_manager.DUMP_DIR, target_wkb_name)

    # Задаем рабочие имена файлов в движок, чтобы автосохранение знало куда писать дальше!
    if active_field_name == "current_session":
        sc.current_wkb_filename = "current_session.wkb"
        state.current_file = "NEW"
    else:
        sc.current_wkb_filename = target_wkb_name
        state.current_file = active_field_name

    # 2. ЗАГРУЖАЕМ ПРАВИЛЬНЫЙ ТЕКСТОВЫЙ ТРЕК JSON
    if os.path.exists(json_path):
        dump_manager.load_session_dump(state, sc, filename=json_path)
        print(
            f"[DumpManager Autoload] УСПЕХ: Состояние восстановлено из активного поля: {target_json_name}"
        )
    else:
        # Если файл поля почему-то пропал, откатываемся на резерв
        dump_manager.load_session_dump(state, sc)
        print("[DumpManager Autoload] Файл поля не найден, загружена резервная сессия.")

    # # 3. ЗАГРУЖАЕМ РОДНУЮ БИНАРНУЮ ГЕОМЕТРИЮ WKB
    # if os.path.exists(wkb_path):
    #     try:
    #         with open(wkb_path, "rb") as f:
    #             sc.covered_area = wkb.loads(f.read())
    #         print(
    #             f"[Main_Engine Autoload] УСПЕХ: Геометрия поля восстановлена из WKB! Шлях: {wkb_path}"
    #         )
    #     except Exception as e:
    #         sc.covered_area = MultiPolygon()
    #         print(f"[Main_Engine Autoload] Ошибка парсинга WKB: {e}")
    # else:
    #     sc.covered_area = MultiPolygon()
    #     print(
    #         f"[Main_Engine Autoload] Предупреждение: WKB-файл {target_wkb_name} не найден. Карта чистая."
    #     )
        # =================================================================================
    # 3. ПОТОКОВИЙ ВІДНОВЛЮВАЧ ГЕОМЕТРІЇ ПРИ СТАРТІ (ЧИТАННЯ ЕШЕЛОНІВ)
    # =================================================================================
    if os.path.exists(wkb_path):
        try:
            from shapely import wkb
            from shapely.ops import unary_union
            from shapely.geometry import MultiPolygon
            
            all_chunks = []
            # Відкриваємо двійковий файл на послідовне зчитування
            with open(wkb_path, "rb") as f:
                while True:
                    try:
                        # Метод wkb.load (без s) зчитує ОДИН пакет і автоматично зсуває вказівник далі
                        chunk = wkb.load(f)
                        if chunk and not chunk.is_empty:
                            all_chunks.append(chunk)
                    except EOFError:
                        # Ловимо чистий кінець файлу (End Of File) — Delphi стиль!
                        break
                    except Exception as parse_err:
                        # Захист на випадок мікро-бітих байт у самому кінці файлу
                        break
            
            if all_chunks:
                # Зшиваємо всі знайдені пакети в один MultiPolygon в ОЗУ математики
                sc.covered_area = unary_union(all_chunks)
                print(f"[Main_Engine Autoload] УСПІХ: Потоковий WKB зібрано. Відновлено {len(all_chunks)} ешелонів роботи.")
            else:
                sc.covered_area = MultiPolygon()
                print("[Main_Engine Autoload] Файл геометрії порожній.")
                
        except Exception as e:
            sc.covered_area = MultiPolygon()
            print(f"[Main_Engine Autoload] Критична помилка відновлення WKB: {e}")
    else:
        sc.covered_area = MultiPolygon()
        print(f"[Main_Engine Autoload] Попередження: WKB-файл {target_wkb_name} не знайдено. Карта чиста.")

    # Инициализируем менеджер карт-предписаний
    vra_manager = VRAManager(cfg)
    # Загружаем карту из папки корень/geodata/test_Shapefile.zip
    # vra_manager.load_map_from_zip("test_Shapefile.zip")
    state.vra_manager = vra_manager
    # 3. АВТОЗАГРУЗКА: Проверяем, был ли в прошлой сессии активный файл карты
    # ИСПРАВЛЕНО: Читаем атрибут напрямую из SharedState с дефолтом None
    last_active_file = getattr(state, "active_vra_file", None)

    if last_active_file:
        print(
            f"[VRA DUMP]: Обнаружена активная карта из прошлой сессии: {last_active_file}"
        )
        success = vra_manager.load_map_from_zip(last_active_file)
        if not success:
            # Если файл поврежден, безопасно сбрасываем атрибут в объекте
            state.active_vra_file = None
    else:
        print(
            "[VRA DUMP]: В прошлой сессии карта задач не использовалась. Работа по базовой норме."
        )

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
    # threading.Thread(target=main_calculation_loop, daemon=True).start()

    # 1. Запуск математичного ядра як звичайного потоку (має прямий доступ до пам'яті state)
    import threading

    threading.Thread(target=main_calculation_loop, daemon=True).start()

    # 4. Запуск Flask веб-сервера
    # app = web_server.create_app(state, sc)
    # app.run(host="0.0.0.0", port=80, debug=True, use_reloader=False)
    # 2. А ось Flask ми запускаємо у СПРАВЖНЬОМУ ОКРЕМУ ПРОЦЕСІ на іншому ядрі CPU
    # Передаємо туди тільки безпечні черги зв'язку
    flask_process = multiprocessing.Process(
        target=start_flask_process, args=(data_queue, cmd_queue), daemon=True
    )
    flask_process.start()

    # Тримаємо головний потік активним
    while True:
        time.sleep(1)
