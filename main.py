# =======================================================================
#                                   main.py
# =======================================================================
import threading
import time
import math
import logging
import config_manager
import web_server
import pyproj
import os
import json
import multiprocessing
import shutil
import dump_manager

# ІМПОРТ ВСІХ НАШИХ ІЗОЛЬОВАНИХ ЮНІТІВ-ВОРКЕРІВ
from gps_worker import GPSWorker
from board_worker import BoardWorker
from emulator_worker import EmulatorWorker
from vra_manager import VRAManager
from section_engine import SectionControl


class SharedState:
    def __init__(self):
        cfg = config_manager.load_config()
        self.current_states = [False] * len(cfg.get("SECTION_WIDTHS", [3.0]))
        self.last_lat, self.last_lon = 49.7604988, 29.0021806
        self.area, self.speed, self.hdg, self.rtk = 0.0, 0.0, 0.0, 0
        self.path_history = []
        self.reset_flag = False

        # НАШІ ГОЛІ ЦИФРИ VRA ДЛЯ BOARD_WORKER
        self.vra_flows = [0.0] * len(cfg.get("SECTION_WIDTHS", [3.0]))

        # Параметри для квадратного джойстика
        self.emu_enabled = False
        self.emu_hdg = 0.0
        self.emu_speed = 0.0
        self.point_a = None
        self.point_b = None
        self.guidance_error = 0.0
        self.flow_percents = []
        self.gps_connected = False
        self.board_connected = False
        self.gps_sats = 0
        self.current_file = "NEW"

        # ДЛЯ РЕЖИМІВ GPS ТА КЕРУВАННЯ НАПІВ-АВТОМАТОМ
        self.gps_mode = 0
        self.gps_mode_text = "CRITICAL: Initializing..."
        self.esp_current_flow = 0.0
        self.esp_pressure = 0.0
        self.esp_pwm = 0


# Ініціалізація глобальних об'єктів (Singletons)
state = SharedState()
cfg = config_manager.load_config()
sc = SectionControl(cfg)
sc.path_history = state.path_history

data_queue = multiprocessing.Queue(maxsize=2)
cmd_queue = multiprocessing.Queue()
iteration_counter = 0


def main_calculation_loop():
    """
    Головне математичне ядро. Частота 10 Гц.
    Всі збереження та завантаження дампів повністю ВИДАЛЕНІ.
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
                    # === АВТОМАТИЧНЕ ОНОВЛЕННЯ АРХІВУ ПЕРЕД RESET ===
                    old_file = getattr(state, "current_file", "NEW")

                    # Якщо ми працювали в реальному іменованому полі — оновлюємо його оригінальні файли
                    if old_file and old_file != "NEW" and old_file != "current_session":
                        print(
                            f"[Main_Engine] Розумне оновлення поля '{old_file}' перед RESET..."
                        )
                        sc.save_to_disk()
                        if sc.track_buffer_to_disk:
                            dump_manager.append_batch_to_track_file(
                                sc.track_buffer_to_disk
                            )
                            sc.track_buffer_to_disk = []
                        dump_manager.save_lightweight_json(state)

                        # Перезаписуємо поверх оригінального архіву, без створення дублікатів
                        try:
                            shutil.copy2(
                                dump_manager.CURRENT_SESSION_FILE,
                                os.path.join(dump_manager.DUMP_DIR, f"{old_file}.json"),
                            )
                            shutil.copy2(
                                dump_manager.CURRENT_TRACK_FILE,
                                os.path.join(dump_manager.DUMP_DIR, f"{old_file}.txt"),
                            )
                            old_wkb = os.path.join(
                                dump_manager.DUMP_DIR, sc.current_wkb_filename
                            )
                            if os.path.exists(old_wkb):
                                shutil.copy2(
                                    old_wkb,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, f"{old_file}.wkb"
                                    ),
                                )
                        except Exception as e:
                            print(f"[Main_Engine Save-on-Reset Error] {e}")

                    # Тепер повністю вичищаємо робочу сесію current_session з диска та ОЗУ
                    state.current_file = "NEW"
                    dump_manager.clear_current_dump()

                    wkb_path = os.path.join(
                        dump_manager.DUMP_DIR, sc.current_wkb_filename
                    )
                    if os.path.exists(wkb_path):
                        try:
                            os.remove(wkb_path)
                        except:
                            pass

                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        vra.reset_manager()
                    state.reset_flag = True
                    state.point_a = state.point_b = None
                    print(
                        "[Main_Engine] Команда RESET виконана. Робоча сесія видалена, ОЗУ чисте."
                    )

                elif cmd == "save_field":
                    raw_name = cmd_data.get("filename", f"field_{int(time.time())}")
                    field_name = (
                        raw_name.replace(".json", "")
                        .replace(".txt", "")
                        .replace(".wkb", "")
                        .strip()
                    )

                    print(
                        f"[Main_Engine] Ручне збереження поля під іменем: {field_name}"
                    )

                    sc.save_to_disk()
                    if sc.track_buffer_to_disk:
                        dump_manager.append_batch_to_track_file(sc.track_buffer_to_disk)
                        sc.track_buffer_to_disk = []
                    dump_manager.save_lightweight_json(state)

                    try:
                        shutil.copy2(
                            dump_manager.CURRENT_SESSION_FILE,
                            os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json"),
                        )
                        shutil.copy2(
                            dump_manager.CURRENT_TRACK_FILE,
                            os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt"),
                        )
                        old_wkb = os.path.join(
                            dump_manager.DUMP_DIR, sc.current_wkb_filename
                        )
                        if os.path.exists(old_wkb):
                            shutil.copy2(
                                old_wkb,
                                os.path.join(
                                    dump_manager.DUMP_DIR, f"{field_name}.wkb"
                                ),
                            )

                        state.current_file = field_name
                        print(f"[Main_Engine] УСПІХ: Поле '{field_name}' збережено!")
                    except Exception as copy_err:
                        print(
                            f"[Main_Engine] Помилка копіювання файлів поля: {copy_err}"
                        )

                elif cmd == "load_field":
                    raw_name = cmd_data.get("filename")
                    if raw_name:
                        field_name = (
                            raw_name.replace(".json", "")
                            .replace(".txt", "")
                            .replace(".wkb", "")
                            .strip()
                        )

                        # === АВТОМАТИЧНЕ ОНОВЛЕННЯ МИНУЛОГО ПОЛЯ ПРИ ЗМІНІ ===
                        old_file = getattr(state, "current_file", "NEW")

                        # Якщо ми перемикаємося з одного архівного поля на інше — оновлюємо перше поверх його файлів
                        if (
                            old_file
                            and old_file != "NEW"
                            and old_file != "current_session"
                            and old_file != field_name
                        ):
                            print(
                                f"[Main_Engine] Розумне оновлення минулого поля перед перемиканням: {old_file}"
                            )
                            sc.save_to_disk()
                            if sc.track_buffer_to_disk:
                                dump_manager.append_batch_to_track_file(
                                    sc.track_buffer_to_disk
                                )
                                sc.track_buffer_to_disk = []
                            dump_manager.save_lightweight_json(state)
                            try:
                                shutil.copy2(
                                    dump_manager.CURRENT_SESSION_FILE,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, f"{old_file}.json"
                                    ),
                                )
                                shutil.copy2(
                                    dump_manager.CURRENT_TRACK_FILE,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, f"{old_file}.txt"
                                    ),
                                )
                                old_wkb = os.path.join(
                                    dump_manager.DUMP_DIR, sc.current_wkb_filename
                                )
                                if os.path.exists(old_wkb):
                                    shutil.copy2(
                                        old_wkb,
                                        os.path.join(
                                            dump_manager.DUMP_DIR, f"{old_file}.wkb"
                                        ),
                                    )
                            except:
                                pass

                        # Тепер спокійно завантажуємо нове вибране архівне поле
                        print(
                            f"[Main_Engine] Завантаження архівного поля: {field_name}"
                        )
                        sc.reset()
                        state.path_history = []
                        state.area = 0.0
                        state.guidance_error = 0.0

                        src_json = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.json"
                        )
                        src_txt = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.txt"
                        )
                        src_wkb = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.wkb"
                        )

                        if os.path.exists(src_json):
                            dump_manager.load_session_dump(state, sc, filename=src_json)

                        if os.path.exists(src_wkb):
                            try:
                                all_chunks = []
                                with open(src_wkb, "rb") as f:
                                    while True:
                                        try:
                                            chunk = wkb.load(f)
                                            if chunk and not chunk.is_empty:
                                                all_chunks.append(chunk)
                                        except EOFError:
                                            break
                                        except Exception:
                                            break
                                if all_chunks:
                                    sc.covered_area = unary_union(all_chunks)
                                    print(
                                        f"[Main_Engine] УСПІХ: Архівна карта WKB відновлена ({len(all_chunks)} ешелонів)."
                                    )
                            except Exception as e:
                                print(
                                    f"[Main_Engine] Помилка читання архівного WKB: {e}"
                                )

                        # Копіюємо файли завантаженого поля в робочий буфер current_session
                        try:
                            if os.path.exists(src_json):
                                shutil.copy2(
                                    src_json, dump_manager.CURRENT_SESSION_FILE
                                )
                            if os.path.exists(src_txt):
                                shutil.copy2(src_txt, dump_manager.CURRENT_TRACK_FILE)
                            if os.path.exists(src_wkb):
                                shutil.copy2(
                                    src_wkb,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, sc.current_wkb_filename
                                    ),
                                )
                            dump_manager.set_session_active()
                        except:
                            pass

                        state.current_file = field_name

                # =======================================================================
                # 🚜 НОВА КОМАНДА: ЗАВАНТАЖЕННЯ МУЛЬТИПРОФІЛЬНОЇ СЕСІЇ З ХАБУ
                # =======================================================================
                elif cmd == "load_hub_session":
                    print(f"[Main_Engine Hub] Запуск мультипрофільної ")
                    print(f"\n[CORE THREAD] Отримано команду load_hub_session з Хабу!", flush=True)
                    field_name = (
                        cmd_data.get("filename", "").replace(".json", "").strip()
                    )
                    impl_id = cmd_data.get("implement_id")
                    taskmap_file = cmd_data.get("taskmap_file")
                    target_rate = cmd_data.get("target_rate", 200.0)

                    if field_name:
                        print(
                            f"[Main_Engine Hub] Запуск мультипрофільної сесії для поля: {field_name}"
                        )

                        # 1. РОЗУМНЕ ЗБЕРЕЖЕННЯ МИНУЛОГО ПОЛЯ (Твоя рідна безпечна логіка)
                        old_file = getattr(state, "current_file", "NEW")
                        if (
                            old_file
                            and old_file != "NEW"
                            and old_file != "current_session"
                            and old_file != field_name
                        ):
                            print(
                                f"[Main_Engine Hub] Злив буферів минулого поля перед перемиканням: {old_file}"
                            )
                            sc.save_to_disk()
                            if sc.track_buffer_to_disk:
                                dump_manager.append_batch_to_track_file(
                                    sc.track_buffer_to_disk
                                )
                                sc.track_buffer_to_disk = []
                            dump_manager.save_lightweight_json(state)
                            try:
                                shutil.copy2(
                                    dump_manager.CURRENT_SESSION_FILE,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, f"{old_file}.json"
                                    ),
                                )
                                shutil.copy2(
                                    dump_manager.CURRENT_TRACK_FILE,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, f"{old_file}.txt"
                                    ),
                                )
                                old_wkb = os.path.join(
                                    dump_manager.DUMP_DIR, sc.current_wkb_filename
                                )
                                if os.path.exists(old_wkb):
                                    shutil.copy2(
                                        old_wkb,
                                        os.path.join(
                                            dump_manager.DUMP_DIR, f"{old_file}.wkb"
                                        ),
                                    )
                            except:
                                pass

                        # 2. СКИДАННЯ МАТЕМАТИКИ ПІД НОВУ ЗAГІНКУ
                        sc.reset()
                        state.path_history = []
                        state.area = 0.0
                        state.guidance_error = 0.0

                        src_json = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.json"
                        )
                        src_txt = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.txt"
                        )
                        src_wkb = os.path.join(
                            dump_manager.DUMP_DIR, f"{field_name}.wkb"
                        )

                        # Завантажуємо базову геометрію поля, якщо воно вже оброблялося раніше
                        if os.path.exists(src_json):
                            dump_manager.load_session_dump(state, sc, filename=src_json)
                        if os.path.exists(src_wkb):
                            try:
                                all_chunks = []
                                with open(src_wkb, "rb") as f:
                                    while True:
                                        try:
                                            chunk = wkb.load(f)
                                            if chunk and not chunk.is_empty:
                                                all_chunks.append(chunk)
                                        except EOFError:
                                            break
                                        except Exception:
                                            break
                                if all_chunks:
                                    sc.covered_area = unary_union(all_chunks)
                                    print(
                                        f"[Main_Engine Hub] Архівна карта WKB відновлена ({len(all_chunks)} ешелонів)."
                                    )
                            except Exception as e:
                                print(
                                    f"[Main_Engine Hub] Помилка читання архівного WKB: {e}"
                                )

                        # 3. ДИНАМІЧНА ПІДМІНА ШТАНГИ В ОЗУ SectionControl (sc)
                        if impl_id:
                            base_sys_dir = os.path.dirname(os.path.abspath(__file__))
                            impl_path = os.path.join(
                                base_sys_dir, "implements", f"{impl_id}.json"
                            )
                            if os.path.exists(impl_path):
                                with open(impl_path, "r", encoding="utf-8") as f_impl:
                                    impl_config = json.load(f_impl)

                                geometry = impl_config.get("geometry", {})
                                dynamics = impl_config.get("dynamics", {})

                                # Перебудовуємо крила обприскувача на льоту
                                sc.cfg["SECTION_WIDTHS"] = [
                                    float(x)
                                    for x in geometry.get(
                                        "section_widths", [3.0, 3.0, 3.0]
                                    )
                                ]
                                sc.cfg["OFFSET_BACK"] = float(
                                    geometry.get("offset_back", 0.0)
                                )
                                sc.cfg["LOOK_AHEAD_ON_TIME"] = float(
                                    dynamics.get("look_ahead_on_time", 0.8)
                                )
                                sc.cfg["LOOK_AHEAD_OFF_TIME"] = float(
                                    dynamics.get("look_ahead_off_time", 0.4)
                                )
                                sc.cfg["IMPLEMENT_TYPE"] = impl_config.get(
                                    "implement_type", "mounted"
                                )

                                # Скидаємо пам'ять осей, щоб штанга не робила математичних стрибків
                                sc.last_p1_list = []
                                sc.last_p2_list = []
                                sc.last_x = None
                                sc.last_y = None

                                sys_cfg = config_manager.load_config()
                                sys_cfg["ACTIVE_IMPLEMENT_ID"] = impl_id
                                sys_cfg["SECTION_MODES"] = ["AUTO"] * len(
                                    sc.cfg["SECTION_WIDTHS"]
                                )
                                config_manager.save_config(sys_cfg)
                                print(
                                    f"[Main_Engine Hub] Штанга знаряддя '{impl_id}' успішно впроваджена в ядро."
                                )

                        # 4. СИНХРОНІЗАЦІЯ КАРТИ VRA ТА БАЗОВОЇ НОРМИ
                        sys_cfg = config_manager.load_config()
                        sys_cfg["VRA_RATE_DEFAULT"] = float(target_rate)
                        if taskmap_file:
                            
                            vra = getattr(state, "vra_manager", None)
                            if vra:
                                if vra.activate_existing_map(taskmap_file):
                                    state.active_vra_file = taskmap_file

                            sys_cfg["ACTIVE_TASKMAP_FILE"] = taskmap_file
                            print(
                                f"[Main_Engine Hub] Підключено карту VRA: {taskmap_file}"
                            )
                        else:
                            sys_cfg["ACTIVE_TASKMAP_FILE"] = ""
                            print(
                                f"[Main_Engine Hub] Робота без карти VRA. Норма: {target_rate} л/га"
                            )
                        config_manager.save_config(sys_cfg)

                        # 5. КОПІЮВАННЯ В РОБОЧИЙ БУФЕР КАРТИ
                        try:
                            if os.path.exists(src_json):
                                shutil.copy2(
                                    src_json, dump_manager.CURRENT_SESSION_FILE
                                )
                            if os.path.exists(src_txt):
                                shutil.copy2(src_txt, dump_manager.CURRENT_TRACK_FILE)
                            if os.path.exists(src_wkb):
                                shutil.copy2(
                                    src_wkb,
                                    os.path.join(
                                        dump_manager.DUMP_DIR, sc.current_wkb_filename
                                    ),
                                )
                            dump_manager.set_session_active()
                        except:
                            pass

                        state.current_file = field_name
                        print(
                            f"[Main_Engine Hub] Мультипрофільна сесія успішно запущена в ОЗУ математики."
                        )

                elif cmd == "reload_config":
                    config_manager._cached_config = None
                    active_cfg = config_manager.load_config()
                    sc.cfg = active_cfg

                    # Скидаємо пам'ять штанги при зміні Master Switch
                    sc.last_p1_list = []
                    sc.last_p2_list = []
                    sc.last_x = None
                    sc.last_y = None
                    print("[Main_Engine] Master Switch змінено. Штанга синхронізована.")

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

                # elif cmd == "load_field" or cmd == "save_field":
                #     # Повністю заглушили команди, карта завжди чиста!
                #     state.current_file = "NEW"
                #     print(
                #         f"[Main_Engine] Команда {cmd} проігнорована. Працюємо на чистій карті."
                #     )

                elif cmd == "set_point":
                    label = cmd_data["label"]
                    print(
                        f"[Main_Engine] set_point: {label} lat:{sc.last_x} lon:{sc.last_y}"
                    )
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
            except Exception as e:
                print(f"[Main_Engine Cmd Error] Помилка обробки команди: {e}")

        # Скидання ОЗУ при прапорі Reset
        active_cfg = config_manager.load_config()
        sc.cfg = active_cfg

        if state.reset_flag:
            state.current_file = "NEW"
            sc.reset()
            state.path_history = []
            state.area = 0.0
            state.guidance_error = 0.0
            state.reset_flag = False
            last_track_x = last_track_y = None

        # =======================================================================
        #               (РОЗРАХУНОК РЕЖИМІВ ТА ЗОН VRA В ОЗУ)
        # =======================================================================

        # Перевіряємо наявність базового зв'язку з GPS
        has_gps_signal = state.last_lat != 0 and state.last_lon != 0
        if has_gps_signal:
            is_moving = state.speed >= active_cfg.get("MIN_SPEED", 1.0)
            master_on = active_cfg.get("MASTER_SW", False)

            if is_moving:
                gps_jump_detected = False
                min_rtk_allowed = active_cfg.get("MIN_REQUIRED_RTK", 4)
                is_rtk_good = (state.rtk >= min_rtk_allowed) or state.emu_enabled

                # =======================================================================
                # РЕЖИМ 1: ОК (ПОВНИЙ АВТОМАТ)
                # =======================================================================
                if master_on and is_rtk_good and not gps_jump_detected:
                    state.gps_mode = 1
                    state.gps_mode_text = "OK: Full Auto Mode"

                    # Прорахунок геометрії перекриттів та поворотів штанги в ОЗУ
                    auto_res = sc.process(
                        state.last_lat, state.last_lon, state.hdg, state.speed
                    )
                    state.flow_percents = sc.curve_compensation(
                        state.speed, state.hdg, state.rtk
                    )

                    vra_mode = active_cfg.get("VRA_CALC_MODE", "boom")
                    widths = active_cfg.get("SECTION_WIDTHS", [1.0] * 8)
                    num_sections = len(widths)

                    vra_flows = [0.0] * num_sections
                    final_states = []
                    modes = active_cfg.get("SECTION_MODES", ["AUTO"] * num_sections)

                    if vra_mode == "boom":
                        base_boom_rate = state.vra_manager.get_target_rate(
                            state.last_lon, state.last_lat
                        )
                        vra_flows = [base_boom_rate] * num_sections
                    else:
                        if sc.transformer_to_m is not None:
                            ux, uy = sc.transformer_to_m.transform(
                                state.last_lon, state.last_lat
                            )
                            th_rad = math.radians(state.hdg)
                            l_offset = -sum(widths) / 2
                            for i, w in enumerate(widths):
                                sec_center_offset = l_offset + (w / 2)
                                sec_x, sec_y = sc.get_section_point(
                                    ux, uy, th_rad, sec_center_offset
                                )
                                try:
                                    transformer_back = pyproj.Transformer.from_crs(
                                        sc.transformer_to_m.target_crs,
                                        "epsg:4326",
                                        always_xy=True,
                                    )
                                    sec_lon, sec_lat = transformer_back.transform(
                                        sec_x, sec_y
                                    )
                                    vra_flows[i] = state.vra_manager.get_target_rate(
                                        sec_lon, sec_lat
                                    )
                                except:
                                    vra_flows[i] = state.vra_manager.rate_default
                                l_offset += w

                    for i in range(num_sections):
                        mode = modes[i]
                        if mode == "ON":
                            final_states.append(True)
                        elif mode == "OFF":
                            final_states.append(False)
                        else:
                            final_states.append(auto_res[i] if auto_res else False)

                    state.current_states = final_states
                    state.vra_flows = vra_flows
                    last_track_x = last_track_y = None
                # =======================================================================
                # РЕЖИМ 2: ТАК СОБІ (НАПІВ-АВТОМАТ / ЗАМОРОЗКА КАРТИ)
                # =======================================================================
                elif master_on and (not is_rtk_good or gps_jump_detected):
                    state.gps_mode = 2
                    state.gps_mode_text = (
                        f"WARNING: Low Accuracy. Fallback to Semi-Auto."
                    )

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
                            fallback_states.append(
                                state.current_states[i]
                                if state.current_states
                                else True
                            )
                    state.current_states = fallback_states
                    state.flow_percents = [100] * len(
                        active_cfg.get("SECTION_WIDTHS", [])
                    )

                # =======================================================================
                # MASTER_SW = FALSE: ТРАКТОР РУХАЄТЬСЯ, АЛЕ ОБПРИСКУВАННЯ ВИМКНЕНО
                # =======================================================================
                else:
                    state.gps_mode = 1
                    state.gps_mode_text = "OK: Spraying is Disabled (Master Off)"
                    state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                    state.flow_percents = [100] * len(
                        active_cfg.get("SECTION_WIDTHS", [])
                    )

                    # Розрахунок та запис спрощеного білого треку в ОЗУ
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

            # =======================================================================
            # РЕЖИМ 3: ТРАКТОР СТОЇТЬ НА МІСЦІ
            # =======================================================================
            else:
                state.gps_mode = 3
                state.gps_mode_text = "STOPPED: Speed is too low. Valves closed."
                state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])
                state.flow_percents = [100] * len(active_cfg.get("SECTION_WIDTHS", []))

            # Розрахунок ліній паралельного водіння А-Б у реальному часі (тільки ОЗУ)
            if state.point_a and state.point_b and state.last_lon is not None:
                try:
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
                except Exception as e:
                    print(f"[Main_Engine AB Calc Error] {e}")
                    state.guidance_error = 0
            else:
                state.guidance_error = 0
            state.area = sc.get_area_ha()
            state.path_history = sc.path_history

        # =======================================================================
        # РЕЖИМ 0: ПОВНА ВТРАТА СИГНАЛУ GPS (NO FIX)
        # =======================================================================
        else:
            state.gps_mode = 0
            state.gps_mode_text = "CRITICAL: No GPS Signal! All valves forced closed."
            state.current_states = [False] * len(active_cfg["SECTION_WIDTHS"])

        # 3. ВІДПРАВКА СНІМКА СТАНУ В ПРОЦЕС FLASK (Математика -> Flask)
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
            "ux": sc.last_x,
            "uy": sc.last_y,
        }

        # Відправляємо зліпок ОЗУ, наприклад, раз на секунду
        if iteration_counter % 10 == 0:
            try:
                clean_state_dump = {}

                # Автоматично перебираємо ВСІ атрибути твого об'єкта SharedState
                for attr_name, attr_val in state.__dict__.items():
                    # ЗАХИСТ: Пропускаємо великі списки, масиви координат, Shapely-полігони та службові методи
                    if attr_name.startswith("_") or isinstance(
                        attr_val, (list, dict, tuple, set)
                    ):
                        continue

                    # Дозволяємо передачу ТІЛЬКИ базових інженерних типів даних
                    if (
                        isinstance(attr_val, (int, float, str, bool))
                        or attr_val is None
                    ):
                        clean_state_dump[attr_name] = attr_val
                    else:
                        # Якщо це складний об'єкт (наприклад, трансформатор координат), показуємо лише його тип
                        clean_state_dump[attr_name] = (
                            f"Object: {type(attr_val).__name__}"
                        )

                # Закидуємо чистий легкий пакет у міжпроцесну чергу
                data_queue.put(
                    {"type": "live_state_dump", "variables": clean_state_dump}
                )
            except Exception as e:
                print(f"[Main_Engine Debug Error] Збій фільтрації SharedState: {e}")

        if data_queue.full():
            try:
                data_queue.get_nowait()
            except:
                pass
        try:
            data_queue.put_nowait(snapshot)
        except:
            pass

        time.sleep(0.25)


def start_flask_process(d_queue, c_queue, restored_history=None):
    """
    Запуск веб-сервера з гарантованим відновленням кешу треку.
    Приймає готовий масив точок прямо з головного процесу.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    if restored_history:
        # Якщо математика передала нам старий трек — миттєво накочуємо його в кеш вебу!
        web_server.WEB_CACHE["new_points"] = list(restored_history)
        web_server.WEB_CACHE["total_count"] = len(restored_history)
        web_server.WEB_CACHE["current_file"] = "current_session"
        print(
            f"[Web_Server Autoload] УСПІХ: Flask-процес підхопив {len(restored_history)} точок з ОЗУ математики!"
        )
    else:
        # Повністю чистий старт
        web_server.WEB_CACHE["new_points"] = []
        web_server.WEB_CACHE["total_count"] = 0
        web_server.WEB_CACHE["current_file"] = "NEW"
        print("[Web_Server Autoload] Чистий старт. Веб-кеш порожній.")

    web_server.WEB_CACHE["area"] = 0.0
    web_server.WEB_CACHE["active_vra_file"] = None

    app = web_server.create_app(d_queue, c_queue)

    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # Вимикаємо кешування CSS/JS браузером

    # Запускаємо з debug=True, але BEZ use_reloader=True,
    # щоб автопілот і потоки заліза в main.py не перезапускалися і не ламалися!
    app.run(host="0.0.0.0", port=80, debug=True, use_reloader=False)

    # app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from shapely.geometry import MultiPolygon
    from shapely import wkb
    from shapely.ops import unary_union

    sc.current_wkb_filename = "current_session.wkb"
    wkb_path = os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename)

    # --- ГОЛОВНА ЛОГІКА РОЗПІЗНАВАННЯ СТАРТУ СИСТЕМИ ---
    if dump_manager.is_session_active():
        print(
            "[Main_Engine Autoload] Виявлено активну минулу сесію! Починаємо відновлення..."
        )

        # 1. Відновлюємо легкі змінні (лінії А-В, гектари) в об'єкт state
        dump_manager.load_session_dump(state, sc)

        # 2. Відновлюємо бінарну карту покриття для математики перекриттів
        if os.path.exists(wkb_path):
            try:
                all_chunks = []
                with open(wkb_path, "rb") as f:
                    while True:
                        try:
                            # Зчитуємо ешелони MultiPolygon один за одним
                            chunk = wkb.load(f)
                            if chunk and not chunk.is_empty:
                                all_chunks.append(chunk)
                        except EOFError:
                            break
                        except Exception:
                            break

                if all_chunks:
                    # Зшиваємо ешелони назад у монолітну карту ОЗУ
                    sc.covered_area = unary_union(all_chunks)
                    print(
                        f"[Main_Engine Autoload] УСПІХ: Математична карта відновлена. Зібрано {len(all_chunks)} ешелонів WKB."
                    )
                else:
                    sc.covered_area = MultiPolygon()
            except Exception as e:
                sc.covered_area = MultiPolygon()
                print(
                    f"[Main_Engine Autoload] Критична помилка читання ешелонів WKB: {e}"
                )
        else:
            sc.covered_area = MultiPolygon()
            print(
                "[Main_Engine Autoload] Попередження: WKB файл карти не знайдено. Маска покриття чиста."
            )
    else:
        # Повністю чистий запуск у новому полі
        state.current_file = "NEW"
        sc.covered_area = MultiPolygon()
        state.path_history = []
        state.area = 0.0
        dump_manager.clear_current_dump()
        print(
            "[Main_Engine Autoload] УСПІХ: Чистий старт системи. Маска покриття в ОЗУ порожня."
        )

    # Ініціалізуємо менеджер карт-предписань (VRA)
    vra_manager = VRAManager(cfg)
    state.vra_manager = vra_manager

    # Автозавантаження карти завдань VRA з минулої сесії, якщо вона була
    last_active_file = getattr(state, "active_vra_file", None)
    if last_active_file and dump_manager.is_session_active():
        print(
            f"[VRA DUMP]: Виявлено активну карту VRA з минулої сесії: {last_active_file}"
        )
        if not vra_manager.load_map_from_zip(last_active_file):
            state.active_vra_file = None
    else:
        print("[VRA DUMP]: Робота за базовою нормою (Карта VRA не використовується).")

    # 1. Запуск апаратних воркерів
    gps_hardware = GPSWorker(state)
    gps_hardware.daemon = True
    gps_hardware.start()

    board_hardware = BoardWorker(state)
    board_hardware.daemon = True
    board_hardware.start()

    emulator_logic = EmulatorWorker(state)
    emulator_logic.daemon = True
    emulator_logic.start()

    import threading

    threading.Thread(target=main_calculation_loop, daemon=True).start()

    # 3. ПЕРЕДАЄМО ВІДНОВЛЕНИЙ ТРЕК У ФЛАКС ПРИ СТАРТІ:
    # Беремо state.path_history, який щойно успішно прочитався з диска
    history_to_flask = getattr(state, "path_history", [])
    # print(history_to_flask)

    # Запуск Flask в окремому процесі з передачею історії
    flask_process = multiprocessing.Process(
        target=start_flask_process,
        args=(data_queue, cmd_queue, history_to_flask),  # <-- Передаємо масив сюди!
        daemon=True,
    )
    flask_process.start()

    while True:
        time.sleep(1)
