# =======================================================================
# main.py --- ЧАСТИНА 1 З 2 (ЧИСТИЙ СТАРТ БЕЗ ПЕРЕЗАВАНТАЖЕНЬ І ДАМПІВ)
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
import shutil        # <-- Перенесіть сюди з блоків save/load
import dump_manager  # <-- ГЛОБАЛЬНИЙ ІМПОРТ ТУТ!

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
                    state.current_file = "NEW"
                    
                    # 🟢 ВОРУЖАЄМО ЗАХИСТ: Повністю видаляємо файли поточної сесії з диска!
                    #import dump_manager
                    dump_manager.clear_current_dump()
                    
                    # Видаляємо також сам файл робочої карти WKB, щоб наступне поле писалося в чистий файл
                    wkb_path = os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename)
                    if os.path.exists(wkb_path):
                        try:
                            os.remove(wkb_path)
                            print("[Main_Engine] Робочий бінарний файл WKB успішно видалено з диска.")
                        except Exception as e:
                            print(f"[Main_Engine] Не вдалося видалити робочий WKB: {e}")
                    
                    # Скидаємо карту завдань (VRA)
                    vra = getattr(state, "vra_manager", None)
                    if vra:
                        vra.reset_manager()
                        
                    state.reset_flag = True
                    print("[Main_Engine] Команда RESET виконана: ОЗУ та дискова сесія повністю очищені!")


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

                # elif cmd == "save_field":
                #     field_name = cmd_data.get("filename", f"field_{int(time.time())}")
                #     print(f"[Main_Engine] Збереження поточного поля під іменем: {field_name}")
                    
                #     # 1. Примусово скидаємо залишки з ОЗУ-буферів на диск (Фінальний залп)
                #     sc.save_to_disk()
                #     if sc.track_buffer_to_disk:
                #         dump_manager.append_batch_to_track_file(sc.track_buffer_to_disk)
                #         sc.track_buffer_to_disk = []
                    
                #     # Зберігаємо легкі метадані (лінії А-В, гектари)
                #     dump_manager.save_lightweight_json(state)
                    
                #     # 2. Копіюємо робочі файли під новим іменем поля
                #     import shutil
                #     try:
                #         new_json = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json")
                #         new_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt")
                #         new_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.wkb")
                        
                #         if os.path.exists(dump_manager.CURRENT_SESSION_FILE):
                #             shutil.copy2(dump_manager.CURRENT_SESSION_FILE, new_json)
                #         if os.path.exists(dump_manager.CURRENT_TRACK_FILE):
                #             shutil.copy2(dump_manager.CURRENT_TRACK_FILE, new_txt)
                        
                #         # Копіюємо бінарну карту WKB
                #         old_wkb = os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename)
                #         if os.path.exists(old_wkb):
                #             shutil.copy2(old_wkb, new_wkb)
                            
                #         state.current_file = field_name
                #         print(f"[Main_Engine] УСПІХ: Поле '{field_name}' успішно зафіксовано на eMMC!")
                #     except Exception as copy_err:
                #         print(f"[Main_Engine] Помилка копіювання файлів поля: {copy_err}")

                # elif cmd == "load_field":
                #     field_name = cmd_data.get("filename")
                #     if field_name:
                #         print(f"[Main_Engine] Завантаження архівного поля: {field_name}")
                        
                #         # Повна зачистка поточного ОЗУ перед завантаженням старого поля
                #         sc.reset()
                #         state.path_history = []
                #         state.area = 0.0
                #         state.guidance_error = 0.0
                        
                #         # Формуємо шляхи до архівного поля
                #         src_json = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json")
                #         src_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt")
                #         src_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.wkb")
                        
                #         # 1. Відновлюємо легкі змінні та лінії А-В
                #         if os.path.exists(src_json):
                #             dump_manager.load_session_dump(state, sc, filename=src_json)
                        
                #         # 2. Відновлюємо бінарну карту покриття WKB для математики
                #         if os.path.exists(src_wkb):
                #             try:
                #                 all_chunks = []
                #                 with open(src_wkb, "rb") as f:
                #                     while True:
                #                         try:
                #                             chunk = wkb.load(f)
                #                             if chunk and not chunk.is_empty:
                #                                 all_chunks.append(chunk)
                #                         except EOFError: break
                #                         except Exception: break
                #                 if all_chunks:
                #                     sc.covered_area = unary_union(all_chunks)
                #                     print(f"[Main_Engine] УСПІХ: Архівна карта WKB відновлена ({len(all_chunks)} ешелонів).")
                #             except Exception as e:
                #                 print(f"[Main_Engine] Помилка читання архівного WKB: {e}")
                        
                #         # Копіюємо архівні файли в робочу сесію, щоб автозбереження працювало далі
                #         import shutil
                #         try:
                #             if os.path.exists(src_json): shutil.copy2(src_json, dump_manager.CURRENT_SESSION_FILE)
                #             if os.path.exists(src_txt): shutil.copy2(src_txt, dump_manager.CURRENT_TRACK_FILE)
                #             if os.path.exists(src_wkb): shutil.copy2(src_wkb, os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename))
                #             dump_manager.set_session_active()
                #         except: pass
                        
                #         state.current_file = field_name
                # elif cmd == "save_field":
                #     raw_name = cmd_data.get("filename", f"field_{int(time.time())}")
                    
                #     # --- ЗАХИСТ ВІД ПОДВІЙНИХ РОЗШИРЕНЬ ---
                #     # Очищаємо ім'я від .json, .txt, .wkb, якщо воно прилетіло з фронтенду
                #     field_name = raw_name.replace(".json", "").replace(".txt", "").replace(".wkb", "").strip()
                    
                #     print(f"[Main_Engine] Збереження поточного поля під іменем: {field_name}")
                    
                #     # Примусово скидаємо залишки з ОЗУ-буферів на диск (Фінальний залп)
                #     sc.save_to_disk()
                #     if sc.track_buffer_to_disk:
                #         dump_manager.append_batch_to_track_file(sc.track_buffer_to_disk)
                #         sc.track_buffer_to_disk = []
                #     print("test 1")
                #     # Зберігаємо легкі метадані (лінії А-В, гектари)
                #     dump_manager.save_lightweight_json(state)
                #     print("test 2")
                #     # Копіюємо робочі файли під новим іменем поля
                #     #import shutil
                #     try:
                #         new_json = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json")
                #         new_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt")
                #         new_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.wkb")
                        
                #         if os.path.exists(dump_manager.CURRENT_SESSION_FILE):
                #             shutil.copy2(dump_manager.CURRENT_SESSION_FILE, new_json)
                #         if os.path.exists(dump_manager.CURRENT_TRACK_FILE):
                #             shutil.copy2(dump_manager.CURRENT_TRACK_FILE, new_txt)
                        
                #         old_wkb = os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename)
                #         if os.path.exists(old_wkb):
                #             shutil.copy2(old_wkb, new_wkb)
                            
                #         state.current_file = field_name
                #         print(f"[Main_Engine] УСПІХ: Поле '{field_name}' успішно зафіксовано на eMMC!")
                #     except Exception as copy_err:
                #         print(f"[Main_Engine] Помилка копіювання файлів поля: {copy_err}")
                elif cmd == "save_field":
                    raw_name = cmd_data.get("filename", f"field_{int(time.time())}")
                    field_name = raw_name.replace(".json", "").replace(".txt", "").replace(".wkb", "").strip()
                    
                    print(f"[Main_Engine] Збереження поточного поля під іменем: {field_name}")
                    
                    # Примусово скидаємо залишки з ОЗУ-буферів на диск
                    sc.save_to_disk()
                    if sc.track_buffer_to_disk:
                        dump_manager.append_batch_to_track_file(sc.track_buffer_to_disk)
                        sc.track_buffer_to_disk = []
                    
                    # Тепер цей виклик відпрацює ідеально, бо імпорт глобальний!
                    dump_manager.save_lightweight_json(state)
                    
                    try:
                        new_json = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json")
                        new_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt")
                        new_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.wkb")
                        
                        if os.path.exists(dump_manager.CURRENT_SESSION_FILE):
                            shutil.copy2(dump_manager.CURRENT_SESSION_FILE, new_json)
                        if os.path.exists(dump_manager.CURRENT_TRACK_FILE):
                            shutil.copy2(dump_manager.CURRENT_TRACK_FILE, new_txt)
                        
                        old_wkb = os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename)
                        if os.path.exists(old_wkb):
                            shutil.copy2(old_wkb, new_wkb)
                            
                        state.current_file = field_name
                        print(f"[Main_Engine] УСПІХ: Поле '{field_name}' успішно зафіксовано на eMMC!")
                    except Exception as copy_err:
                        print(f"[Main_Engine] Помилка копіювання файлів поля: {copy_err}")


                elif cmd == "load_field":
                    raw_name = cmd_data.get("filename")
                    if raw_name:
                        # --- ЗАХИСТ ВІД ПОДВІЙНИХ РОЗШИРЕНЬ ---
                        field_name = raw_name.replace(".json", "").replace(".txt", "").replace(".wkb", "").strip()
                        
                        print(f"[Main_Engine] Завантаження архівного поля: {field_name}")
                        
                        # Повна зачистка поточного ОЗУ перед завантаженням старого поля
                        sc.reset()
                        state.path_history = []
                        state.area = 0.0
                        state.guidance_error = 0.0
                        
                        # Формуємо шляхи до архівного поля
                        src_json = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.json")
                        src_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.txt")
                        src_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_name}.wkb")
                        
                        # 1. Відновлюємо легкі змінні та лінії А-В
                        if os.path.exists(src_json):
                            dump_manager.load_session_dump(state, sc, filename=src_json)
                        else:
                            print(f"[Main_Engine Warning] Файл метаданих не знайдено: {src_json}")
                        
                        # 2. Відновлюємо бінарну карту покриття WKB для математики
                        if os.path.exists(src_wkb):
                            try:
                                all_chunks = []
                                with open(src_wkb, "rb") as f:
                                    while True:
                                        try:
                                            chunk = wkb.load(f)
                                            if chunk and not chunk.is_empty:
                                                all_chunks.append(chunk)
                                        except EOFError: break
                                        except Exception: break
                                if all_chunks:
                                    sc.covered_area = unary_union(all_chunks)
                                    print(f"[Main_Engine] УСПІХ: Архівна карта WKB відновлена ({len(all_chunks)} ешелонів).")
                                else:
                                    print("[Main_Engine] Попередження: Файл WKB порожній.")
                            except Exception as e:
                                print(f"[Main_Engine] Помилка читання архівного WKB: {e}")
                        else:
                            print(f"[Main_Engine Warning] Файл карти WKB не знайдено: {src_wkb}")
                        
                        # Копіюємо архівні файли в робочу сесію, щоб автозбереження працювало далі
                        #import shutil
                        try:
                            if os.path.exists(src_json): shutil.copy2(src_json, dump_manager.CURRENT_SESSION_FILE)
                            if os.path.exists(src_txt): shutil.copy2(src_txt, dump_manager.CURRENT_TRACK_FILE)
                            if os.path.exists(src_wkb): shutil.copy2(src_wkb, os.path.join(dump_manager.DUMP_DIR, sc.current_wkb_filename))
                            dump_manager.set_session_active()
                        except Exception as copy_err:
                            print(f"[Main_Engine] Помилка синхронізації з робочою сесією: {copy_err}")
                        
                        state.current_file = field_name

                
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

                elif cmd == "load_field" or cmd == "save_field":
                    # Повністю заглушили команди, карта завжди чиста!
                    state.current_file = "NEW"
                    print(
                        f"[Main_Engine] Команда {cmd} проігнорована. Працюємо на чистій карті."
                    )

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
        # main.py --- ЧАСТИНА 2.1 (РОЗРАХУНОК РЕЖИМІВ ТА ЗОН VRA В ОЗУ)
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
                # main.py --- ЧАСТИНА 2.2 (ЛІНІЇ А-В, СНІМШОТ ТА ЗАПУСК СИСТЕМИ)
                # =======================================================================

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


# =======================================================================
# main.py --- ФІНАЛЬНИЙ БЛОК ЗАПУСКУ З РОЗУМНИМ ВІДНОВЛЕННЯМ СЕСІЇ
# =======================================================================


# def start_flask_process(d_queue, c_queue):
#     """Запуск веб-сервера з автоматичним відновленням кешу треку"""
#     import dump_manager

#     logging.getLogger("werkzeug").setLevel(logging.ERROR)

#     # Перевіряємо, чи є активна сесія для відновлення
#     if dump_manager.is_session_active() and os.path.exists(
#         dump_manager.CURRENT_SESSION_FILE
#     ):
#         try:
#             with open(dump_manager.CURRENT_SESSION_FILE, "r", encoding="utf-8") as f:
#                 dump_data = json.load(f)

#             # Покроково відновлюємо текстову траєкторію для Canvas вебу
#             history = dump_manager.load_track_history()

#             web_server.WEB_CACHE["new_points"] = history
#             web_server.WEB_CACHE["total_count"] = len(history)
#             web_server.WEB_CACHE["area"] = dump_data.get("area", 0.0)
#             web_server.WEB_CACHE["current_file"] = "current_session"
#             web_server.WEB_CACHE["active_vra_file"] = dump_data.get(
#                 "active_vra_file", None
#             )
#             print(
#                 f"[Web_Server Autoload] УСПІХ: Відновлено {len(history)} точок треку для веб-інтерфейсу."
#             )
#         except Exception as e:
#             print(f"[Web_Server Autoload] Помилка відновлення кешу вебу: {e}")
#             # Дефолтний чистий старт при збої
#             web_server.WEB_CACHE["new_points"] = []
#             web_server.WEB_CACHE["total_count"] = 0
#             web_server.WEB_CACHE["area"] = 0.0
#             web_server.WEB_CACHE["current_file"] = "NEW"
#             web_server.WEB_CACHE["active_vra_file"] = None
#     else:
#         # Абсолютно чистий старт системи
#         web_server.WEB_CACHE["new_points"] = []
#         web_server.WEB_CACHE["total_count"] = 0
#         web_server.WEB_CACHE["area"] = 0.0
#         web_server.WEB_CACHE["current_file"] = "NEW"
#         web_server.WEB_CACHE["active_vra_file"] = None
#         print("[Web_Server Autoload] Чистий старт. Веб-кеш порожній.")


#     app = web_server.create_app(d_queue, c_queue)
#     app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)
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
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from shapely.geometry import MultiPolygon
    from shapely import wkb
    from shapely.ops import unary_union
    #import dump_manager

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

    # # 2. Запуск математичного ядра як звичайного потоку (прямий доступ до SharedState)
    # import threading

    # threading.Thread(target=main_calculation_loop, daemon=True).start()

    # # 3. Запуск Flask у СПРАВЖНЬОМУ ОКРЕМУ ПРОЦЕСІ на іншому ядрі CPU
    # flask_process = multiprocessing.Process(
    #     target=start_flask_process, args=(data_queue, cmd_queue), daemon=True
    # )
    # flask_process.start()

    # # Утримуємо головний потік системи
    # while True:
    #     time.sleep(1)
    # 2. Запуск математичного ядра як звичайного потоку
    import threading

    threading.Thread(target=main_calculation_loop, daemon=True).start()

    # 3. ПЕРЕДАЄМО ВІДНОВЛЕНИЙ ТРЕК У ФЛАКС ПРИ СТАРТІ:
    # Беремо state.path_history, який щойно успішно прочитався з диска
    history_to_flask = getattr(state, "path_history", [])
    #print(history_to_flask)

    # Запуск Flask в окремому процесі з передачею історії
    flask_process = multiprocessing.Process(
        target=start_flask_process,
        args=(data_queue, cmd_queue, history_to_flask),  # <-- Передаємо масив сюди!
        daemon=True,
    )
    flask_process.start()

    while True:
        time.sleep(1)
