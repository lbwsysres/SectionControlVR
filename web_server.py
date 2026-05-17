from flask import (
    Flask,
    jsonify,
    render_template_string,
    request,
    redirect,
    render_template,
    Response,
)
import config_manager, os
import math
import pyproj
import dump_manager
import os
import serial.tools.list_ports
import datetime
import re
import geopandas as gpd

# def meters_to_gps(sc, mx, my):
#     if mx is None or my is None:
#         return None
#     try:
#         # Используем трансформер из переданного объекта sc
#         lon, lat = sc.transformer_to_m.transform(
#             mx, my,
#             direction=pyproj.enums.TransformDirection.INVERSE
#         )
#         return [lat, lon]
#     except Exception as e:
#         print(f"DEBUG: Error convert meters_to_gps : {e}")
#         return None
def meters_to_gps(sc, mx, my):
    if mx is None or my is None:
        return None

    # ЗАХИСТ: Якщо об'єкт проекції ще не ініціалізований (після завантаження дампу),
    # ми не викликаємо .transform(), щоб сервер на SBC не падав.
    if sc is None or getattr(sc, "transformer_to_m", None) is None:
        # Можна залишити лог для відладки, щоб бачити, коли це відбувається
        # print("DEBUG: meters_to_gps - трансформер ще не створено (чекаємо GPS референс)")
        return None

    try:
        # Тепер викликати метод абсолютно безпечно
        lon, lat = sc.transformer_to_m.transform(
            mx, my, direction=pyproj.enums.TransformDirection.INVERSE
        )
        return [lat, lon]
    except Exception as e:
        print(f"DEBUG: Error convert meters_to_gps : {e}")
        return None


def create_app(state, sc):
    app = Flask(__name__)

    @app.route("/")
    def index():
        cfg = config_manager.load_config()
        # return render_template_string(MAP_HTML, cfg=cfg)
        return render_template("board.html", cfg=cfg)

    @app.route("/map_data")
    def map_data():
        cfg = config_manager.load_config()

        try:
            last_idx = int(request.args.get("last", 0))
        except:
            last_idx = 0

        new_points = state.path_history[last_idx:]
        ab_gps_data = {
            "a": (
                meters_to_gps(sc, state.point_a[0], state.point_a[1])
                if state.point_a
                else None
            ),
            "b": (
                meters_to_gps(sc, state.point_b[0], state.point_b[1])
                if state.point_b
                else None
            ),
        }
        return jsonify(
            {
                "area": state.area,
                "states": state.current_states,
                "pos": [state.last_lat, state.last_lon],
                "ab_gps": ab_gps_data,
                "flow_percents": state.flow_percents,  # [100, 120, 80, ...]
                "vra_flows": state.vra_flows,
                "speed": round(state.speed, 1),
                "hdg": state.hdg,
                "rtk": state.rtk,
                "master": cfg.get("MASTER_SW", False),
                "modes": cfg.get("SECTION_MODES", ["AUTO"] * len(state.current_states)),
                # Рядок з "history" ВИДАЛЕНО
                "ab_line": {
                    "a": state.point_a,
                    "b": state.point_b,
                    "error": getattr(state, "guidance_error", 0),
                },
                "ux": sc.last_x,
                "uy": sc.last_y,
                "new_points": new_points,
                "total_count": len(state.path_history),
                "gps_mode": state.gps_mode,
                "gps_mode_text": state.gps_mode_text,
            }
        )
    @app.route("/panel_data")
    def panel_data():
        """
        Ультра-легкий роут для заліза (ESP32 / LVGL).
        Ніякої історії, мінімальний JSON, швидка відповідь.
        """
        cfg = config_manager.load_config()
        
        # Скорочуємо імена ключів, щоб ESP32 витрачала менше пам'яті на парсинг тексту
        return jsonify({
            "mo": cfg.get("SECTION_MODES", ["AUTO"] * len(state.current_states)),
            "st": state.current_states,  # [True, False, ...] — стани лампочок секцій
            "fl": state.flow_percents,   # [100, 120, ...] — відсотки виливу для екрану
            "sp": round(state.speed, 1), # Швидкість
            "hd": state.hdg,             # Курс для компаса LVGL
            "rt": state.rtk,             # Статус RTK
            "er": round(getattr(state, "guidance_error", 0), 2), # Відхилення А-Б у метрах
            "ar": state.area,            # Оброблена площа в га
            "m_g": state.gps_mode,       # Наш цифровий код стану (0, 1, 2, 3)
            "ms": cfg.get("MASTER_SW", False) # Головний тумблер
        })

    @app.route("/settings")
    def settings():
        cfg = config_manager.load_config()
        # widths готовим так же, как и раньше
        widths_str = ",".join(map(str, cfg["SECTION_WIDTHS"]))
        # render_template сам пойдет в папку /templates и найдет там файл
        return render_template("settings.html", cfg=cfg, widths=widths_str)

    # @app.route("/save_settings", methods=["POST"])
    # def save_settings():
    #     # Отримуємо JSON з тіла запиту (fetch шле саме його)
    #     data = request.get_json()
    #     if not data:
    #         return {"error": "No data received"}, 400

    #     # Завантажуємо поточний конфіг
    #     cfg = config_manager.load_config()

    #     # Оновлюємо значення, використовуючи ключі з JS
    #     if "SECTION_WIDTHS" in data:
    #         cfg["SECTION_WIDTHS"] = [float(x) for x in data["SECTION_WIDTHS"]]

    #     if "AUTO_SECTION_MIN_OVERLAP" in data:
    #         cfg["AUTO_SECTION_MIN_OVERLAP"] = float(data["AUTO_SECTION_MIN_OVERLAP"])

    #     if "LOOK_AHEAD_TIME" in data:
    #         cfg["LOOK_AHEAD"] = float(data["LOOK_AHEAD_TIME"])

    #     if "AUTO_SECTION_BUFFER" in data:
    #         cfg["AUTO_SECTION_BUFFER"] = float(data["AUTO_SECTION_BUFFER"])

    #     if "CURVE_COMP_SMOOTH" in data:
    #         cfg["CURVE_COMP_SMOOTH"] = float(data["CURVE_COMP_SMOOTH"])

    #     if "CURVE_COMP_MIN_RTK" in data:
    #         cfg["CURVE_COMP_MIN_RTK"] = int(data["CURVE_COMP_MIN_RTK"])

    #     if "DRAW_OFF_SECTIONS" in data:
    #         cfg["DRAW_OFF_SECTIONS"] = bool(data["DRAW_OFF_SECTIONS"])

    #     if "VISUAL_SCALE" in data:
    #         cfg["VISUAL_SCALE"] = float(data["VISUAL_SCALE"])

    #     if "OFFSET_BACK" in data:
    #         cfg["OFFSET_BACK"] = float(data["OFFSET_BACK"])

    #     if "UDP_PORT" in data:
    #         cfg["UDP_PORT"] = int(data["UDP_PORT"])
    #     if "MIN_SPEED" in data:
    #         cfg["MIN_SPEED"] = float(data["MIN_SPEED"])

    #     if "MIN_LOOK_AHEAD_DIST" in data:
    #         cfg["MIN_LOOK_AHEAD_DIST"] = float(data["MIN_LOOK_AHEAD_DIST"])

    #     # Збираємо ліміти назад у список [min, max]
    #     if "CURVE_LIMIT_LOW" in data and "CURVE_LIMIT_HIGH" in data:
    #         cfg["CURVE_COMP_LIMITS"] = [
    #             int(data["CURVE_LIMIT_LOW"]),
    #             int(data["CURVE_LIMIT_HIGH"])
    #         ]

    #     # Зберігаємо оновлений об'єкт через менеджер
    #     config_manager.save_config(cfg)

    #     # Повертаємо успішний статус для JS (response.ok буде true)
    #     return {"status": "success"}, 200

    @app.route("/save_settings", methods=["POST"])
    def save_settings():
        # Отримуємо JSON з тіла запиту сторінки налаштувань
        data = request.get_json()
        if not data:
            return {"error": "No data received"}, 400

        # 1. Завантажуємо актуальний конфіг із нашого оперативнішого RAM-кешу
        cfg = config_manager.load_config()

        # 2. Словник автоматичного мапінгу та приведення типів (JS Ключ -> Бекенд Ключ)
        key_mapping = {
            "SECTION_WIDTHS": ("SECTION_WIDTHS", lambda v: [float(x) for x in v]),
            "AUTO_SECTION_MIN_OVERLAP": ("AUTO_SECTION_MIN_OVERLAP", float),
            "LOOK_AHEAD_TIME": ("LOOK_AHEAD",float,),

            "LOOK_AHEAD_ON_TIME": ("LOOK_AHEAD_ON_TIME",float,),
            "LOOK_AHEAD_OFF_TIME": ("LOOK_AHEAD_OFF_TIME",float,),

            "AUTO_SECTION_BUFFER": ("AUTO_SECTION_BUFFER", float),
            "CURVE_COMP_SMOOTH": ("CURVE_COMP_SMOOTH", float),
            "CURVE_COMP_MIN_RTK": ("CURVE_COMP_MIN_RTK", int),
            "DRAW_OFF_SECTIONS": ("DRAW_OFF_SECTIONS", bool),
            "VISUAL_SCALE": ("VISUAL_SCALE", float),
            "OFFSET_BACK": ("OFFSET_BACK", float),
            "UDP_PORT": ("UDP_PORT", int),
            "MIN_SPEED": ("MIN_SPEED", float),
            "MIN_LOOK_AHEAD_DIST": ("MIN_LOOK_AHEAD_DIST", float),
            "CURVE_COMP_LIMITS": ("CURVE_COMP_LIMITS", lambda v: [int(x) for x in v]),
            # --- ПАРАМЕТРИ ПОРТІВ ТА ЗАЛІЗА (GPS) ---
            "GPS_ENABLE": ("GPS_ENABLE", bool),
            "GPS_PORT": ("GPS_PORT", lambda v: str(v).strip()),
            "GPS_PORT_SPEED": ("GPS_PORT_SPEED", int),
            "GPS_TIME_RECONNECT": ("GPS_TIME_RECONNECT", int),
            # --- ПАРАМЕТРИ ПОРТІВ ТА ЗАЛІЗА (ПЛАТА КЛАПАНІВ) ---
            "CONTROL_BOARD_ENABLE": ("CONTROL_BOARD_ENABLE", bool),
            "CONTROL_BOARD_PORT": ("CONTROL_BOARD_PORT", lambda v: str(v).strip()),
            "CONTROL_BOARD_PORT_SPEED": ("CONTROL_BOARD_PORT_SPEED", int),
            "CONTROL_BOARD_TIME_RECONNECT": ("CONTROL_BOARD_TIME_RECONNECT", int),
            "SMART_TURN_ENABLED": ("SMART_TURN_ENABLED", bool),
        }

        # 3. Елегантний динамічний цикл замість 20 штук операторів "if"
        for js_key, (cfg_key, type_converter) in key_mapping.items():
            if js_key in data and data[js_key] is not None:
                try:
                    cfg[cfg_key] = type_converter(data[js_key])
                except (ValueError, TypeError) as e:
                    print(f"[Web_Server] Помилка обробки параметра {js_key}: {e}")

        # 4. Зберігаємо оновлений об'єкт через менеджер (пише на диск + синхронізує RAM-кеш)
        config_manager.save_config(cfg)

        # Повертаємо успішний статус для JS (response.ok буде true)
        return {"status": "success"}, 200

    @app.route("/set_master/<int:val>")
    def set_master(val):
        cfg = config_manager.load_config()
        cfg["MASTER_SW"] = bool(val)
        config_manager.save_config(cfg)
        return "OK"

    @app.route("/set_mode/<int:idx>/<mode>")
    def set_mode(idx, mode):
        cfg = config_manager.load_config()
        if "SECTION_MODES" not in cfg:
            cfg["SECTION_MODES"] = ["AUTO"] * len(cfg.get("SECTION_WIDTHS", []))

        while len(cfg["SECTION_MODES"]) <= idx:
            cfg["SECTION_MODES"].append("AUTO")

        cfg["SECTION_MODES"][idx] = mode
        config_manager.save_config(cfg)
        return "OK"

    @app.route("/reset")
    def reset():
        state.reset_flag = True
        return "OK"

    @app.route("/emu_control", methods=["POST"])
    def emu_control():
        try:
            data = request.json
            state.emu_hdg = float(data.get("hdg", 0))
            state.emu_speed = float(data.get("spd", 0))
            state.emu_enabled = bool(data.get("enabled", False))
            return "OK"
        except:
            return "Error", 400

    @app.route("/reset_area")
    def reset_area():
        try:
            # sc.reset_area() # Викликаємо правильний метод з очищенням об'єктів
            # 2. Выгружаем карту предписаний из памяти запущенного движка
            vra = getattr(state, 'vra_manager', None)
            if vra:
                vra.reset_manager()
            state.reset_flag = True  # Виставляємо прапорець для gps_loop
            return jsonify({"status": "ok", "message": "Area cleared"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/set_point/<label>")
    def set_point(label):
        # 1. Сообщение о том, какой label пришел
        print(f"--- DEBUG: AB : {label} ---")

        if label == "a":
            state.point_a = (sc.last_x, sc.last_y)
            print(f"SET A: {state.point_a}")

        elif label == "b":
            state.point_b = (sc.last_x, sc.last_y)
            print(f"SET B: {state.point_b}")

        elif label == "reset":
            state.point_a = state.point_b = None
            print("RESET AB")

        elif label == "nudge":
            try:
                val = float(request.args.get("value", 0))
                print(f"NUDGE: {val} m")

                if state.point_a and state.point_b:
                    ax, ay = state.point_a
                    bx, by = state.point_b
                    dx, dy = bx - ax, by - ay
                    dist = math.sqrt(dx**2 + dy**2)

                    if dist > 0:
                        nx, ny = -dy / dist, dx / dist
                        state.point_a = (ax + nx * val, ay + ny * val)
                        state.point_b = (bx + nx * val, by + ny * val)
                        print(f"NEW POINT A: {state.point_a}")
                    else:
                        print("ERROR AB == 0!")
                else:
                    print("ERROR AB NOT SET")
            except Exception as e:
                print(f"CRITICAL Nudge: {e}")
        elif label == "manual_coords":
            try:
                lat = float(request.args.get("lat"))
                lon = float(request.args.get("lon"))
                target = request.args.get("label", "a")  # Куда пишем: в 'a' или 'b'

                # Конвертируем в метры UTM через ваш трансформер
                mx, my = sc.transformer_to_m.transform(lon, lat)

                if target == "a":
                    state.point_a = (mx, my)
                else:
                    state.point_b = (mx, my)

                print(
                    f"--- MANUAL SET {target.upper()}: {lat}, {lon} -> ({mx}, {my}) ---"
                )
            except Exception as e:
                print(f"Manual record error: {e}")
        return "OK"

    @app.route("/export_kml")
    def export_kml():
        if not state.path_history:
            return "История пуста", 400

        # Собираем координаты в одну строку через пробел
        # В KML формат: Долгота,Широта,Высота
        coords_list = []
        for pt in state.path_history:
            lat = pt[0]
            lon = pt[1]
            coords_list.append(f"{lon},{lat},0")

        coords_str = " ".join(coords_list)

        # Формируем XML ОДНИМ блоком без лишних пробелов в начале
        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://opengis.net">
    <Document>
    <name>MySection_Track</name>
    <Style id="path_style">
        <LineStyle>
        <color>7f00ffff</color>
        <width>4</width>
        </LineStyle>
    </Style>
    <Placemark>
        <name>Траектория</name>
        <styleUrl>#path_style</styleUrl>
        <LineString>
        <tessellate>1</tessellate>
        <coordinates>{coords_str}</coordinates>
        </LineString>
    </Placemark>
    </Document>
    </kml>""".strip()  # .strip() уберет случайные пустые строки в начале и конце

        return Response(
            kml_content,
            mimetype="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": "attachment;filename=track.kml"},
        )

    # =================================================================================
    @app.route("/api/save_field", methods=["POST"])
    def api_save_field():
        """Тракторист натиснув 'Зберегти поле' та ввів назву"""
        data = request.get_json() or {}
        field_name = data.get("field_name", "").strip()

        if not field_name:
            return {"error": "Назва поля не може бути порожньою"}, 400

        # Формуємо безпечне ім'я файлу без символів / або \
        secure_name = "".join(
            c for c in field_name if c.isalnum() or c in (" ", "_", "-")
        ).strip()
        filename = os.path.join(dump_manager.DUMP_DIR, f"{secure_name}.json")

        success = dump_manager.save_session_dump(state, sc, filename=filename)
        if success:
            return {
                "status": "success",
                "message": f"Поле {secure_name} збережено",
            }, 200
        return {"error": "Помилка при записі файлу"}, 500

    @app.route("/api/load_field", methods=["POST"])
    def api_load_field():
        """Тракторист вибрав старе поле зі списку"""
        data = request.get_json() or {}
        filename = data.get("filename", "")

        target_path = os.path.join(dump_manager.DUMP_DIR, os.path.basename(filename))
        if not os.path.exists(target_path):
            return {"error": "Файл поля не знайдено"}, 404

        success = dump_manager.load_session_dump(state, sc, filename=target_path)
        if success:
            # Також копіюємо його в поточну робочу сесію, щоб воно автозберігалося далі
            dump_manager.save_session_dump(state, sc)
            return {"status": "success"}, 200
        return {"error": "Не вдалося завантажити поле"}, 500

    # **************************************************************************************
    @app.route("/fields")
    def fields_page():
        """Показує окрему сторінку файлового менеджера (наша TFormFields)"""
        return render_template("fields.html")

    @app.route("/api/files", methods=["GET"])
    def list_files():
        """Повертає список файлів полів у форматі JSON"""
        import os, time
        import dump_manager

        files_list = []
        if os.path.exists(dump_manager.DUMP_DIR):
            for fname in os.listdir(dump_manager.DUMP_DIR):
                # Пропускаємо тимчасові файли та поточну робочу сесію
                if fname.endswith(".json") and fname != "current_session.json":
                    fpath = os.path.join(dump_manager.DUMP_DIR, fname)
                    stat = os.stat(fpath)
                    files_list.append(
                        {
                            "name": fname,
                            "size": round(stat.st_size / 1024, 1),
                            "date": time.strftime(
                                "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)
                            ),
                        }
                    )
        # Сортуємо: спочатку найновіші поля
        files_list.sort(key=lambda x: x["date"], reverse=True)
        return jsonify(files_list)

    @app.route("/api/delete_field", methods=["POST"])
    def api_delete_field():
        """Видалення файлу поля з диска"""
        import os
        import dump_manager

        data = request.get_json() or {}
        filename = os.path.basename(data.get("filename", ""))
        target_path = os.path.join(dump_manager.DUMP_DIR, filename)

        if os.path.exists(target_path):
            os.remove(target_path)
            return {"status": "success"}, 200
        return {"error": "Файл не знайдено"}, 404

    # @app.route('/api/status', methods=['GET'])
    # def get_status():
    #     # 1. Проверяем, запущен ли реальный поток GPS или мы крутим джойстик
    #     # Для этого смотрим, активен ли последовательный порт в воркере
    #     # (Для упрощения можно выставить флаг прямо из gps_worker.py в state.gps_connected)
    #     gps_hardware_connected = getattr(state, 'gps_connected', False)

    #     # 2. Проверяем, на связи ли плата реле/клапанов
    #     board_hardware_connected = getattr(state, 'board_connected', False)

    #     # 3. Собираем пакет для фронтенда
    #     status_pack = {
    #         "gps_connected": gps_hardware_connected,
    #         "emu_enabled": state.emu_enabled,
    #         "rtk_status": state.rtk,       # 0=No, 1=GPS, 4=RTK Fix, 5=Float
    #         "sats": getattr(state, 'gps_sats', 0), # Количество спутников
    #         "board_connected": board_hardware_connected,
    #         "speed": round(state.speed, 1),
    #         "hdg": round(state.hdg, 1)
    #     }

    #     return jsonify(status_pack), 200
    @app.route("/api/status", methods=["GET"])
    def get_status():
        # 1. Проверяем, запущен ли реальный поток GPS или мы крутим джойстик
        gps_hardware_connected = getattr(state, "gps_connected", False)

        # 2. Проверяем, на связи ли плата реле/клапанов
        board_hardware_connected = getattr(state, "board_connected", False)

        # 3. Собираем полный пакет данных для фронтенда с защитой от AttributeError
        status_pack = {
            "gps_connected": gps_hardware_connected,
            "emu_enabled": getattr(state, "emu_enabled", False),
            "rtk_status": getattr(state, "rtk", 0),  # 0=No, 1=GPS, 4=RTK Fix, 5=Float
            "sats": getattr(state, "gps_sats", 0),  # Количество спутников
            # Новые параметры геометрической точности (округляем до 2 знаков)
            "hdop": round(getattr(state, "hdop", 0.0), 2),
            "vdop": round(getattr(state, "vdop", 0.0), 2),
            "pdop": round(getattr(state, "pdop", 0.0), 2),
            "board_connected": board_hardware_connected,
            "speed": round(getattr(state, "speed", 0.0), 1),
            "hdg": round(getattr(state, "hdg", 0.0), 1),
            "file": getattr(state, "current_file", "NONE"),
        }

        return jsonify(status_pack), 200

    @app.route("/api/available_ports", methods=["GET"])
    def get_available_ports():
        ports_list = []
        # comports() автоматично збирає імена та описи на Windows та Linux
        for p in serial.tools.list_ports.comports():
            ports_list.append(
                {
                    "device": p.device,  # Для конфігу (наприклад, 'COM3' або '/dev/ttyUSB0')
                    "description": p.description,  # Для ПІПЛА (наприклад, 'USB-SERIAL CH340')
                }
            )

        # Якщо заліза взагалі немає, кидаємо заглушку, щоб інтерфейс не пустував
        if not ports_list:
            ports_list = [
                {"device": "com1", "description": "Демо-порт 1 (Заглушка)"},
                {"device": "/dev/ttyUSB0", "description": "Демо-порт Linux"},
            ]

        return jsonify(ports_list), 200

    # ********************************** VRA **********************************
    # *************************************************************************
    @app.route('/api/vra/map', methods=['GET'])
    def get_vra_map():
        vra = getattr(state, 'vra_manager', None)
        if not vra:
            return jsonify({"status": "no_map"})
        return jsonify(vra.get_map_polygons())
    # import os
    # import datetime
    # from flask import jsonify, request, render_code # або render_template, залежно від вашого імпорту
    # from werkzeug.utils import secure_filename
    # import geopandas as gpd

    # Припустимо, цей код інтегрується в архітектуру вашого створення маршрутів
    # state — це спільне сховище, де лежить state.vra_manager

    @app.route('/vra_control')
    def vra_control_page():
        """Відображає нову сторінку керування картами завдань (vra_maps.html)"""
        return render_template('vra_maps.html') # Саму сторінку зробимо наступним кроком


    # @app.route('/api/vra/list', methods=['GET'])
    # def get_vra_list():
    #     """
    #     1. СКАНУВАННЯ ПАПКИ geodata.
    #     Повертає список усіх ZIP-карт та показує, яка з них зараз активна в пам'яті.
    #     """
    #     vra = getattr(state, 'vra_manager', None)
    #     #active_file = state.get("active_vra_file", None) if state else None
    #     active_file = getattr(state, "active_vra_file", None)
        
    #     # Якщо карти в пам'яті фізично немає (була вивантажена), скидаємо статус активності
    #     if vra and vra.rate_data is None:
    #         active_file = None
    #         #if state: state.set("active_vra_file", None)
    #         if state: state.active_vra_file = None

    #     upload_dir = os.path.join(os.getcwd(), "geodata")
    #     if not os.path.exists(upload_dir):
    #         os.makedirs(upload_dir, exist_ok=True)

    #     # Збираємо всі .zip файли в папці
    #     files = [f for f in os.listdir(upload_dir) if f.endswith('.zip')]
        
    #     # Формуємо красиву таблицю для фронтенду
    #     maps_list = []
    #     for f in files:
    #         file_path = os.path.join(upload_dir, f)
    #         stat = os.stat(file_path)
    #         # Отримуємо дату створення файлу для виводу на екран
    #         created_time = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
            
    #         maps_list.append({
    #             "filename": f,
    #             "created": created_time,
    #             "is_active": (f == active_file)
    #         })

    #     return jsonify({
    #         "status": "ok",
    #         "active_file": active_file,
    #         "rate_default": vra.rate_default if vra else 100.0,
    #         "maps": maps_list
    #     })

    @app.route('/api/vra/list', methods=['GET'])
    def get_vra_list():
        vra = getattr(state, 'vra_manager', None)
        active_file = getattr(state, "active_vra_file", None)
        
        # Витягуємо свіжі залізні налаштування з config.json
        cfg = config_manager.load_config()

        upload_dir = os.path.join(os.getcwd(), "geodata")
        os.makedirs(upload_dir, exist_ok=True)
        files = [f for f in os.listdir(upload_dir) if f.endswith('.zip')]
        
        maps_list = []
        for f in files:
            file_path = os.path.join(upload_dir, f)
            stat = os.stat(file_path)
            created_time = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
            maps_list.append({
                "filename": f,
                "created": created_time,
                "is_active": (f == active_file)
            })

        return jsonify({
            "status": "ok",
            "active_file": active_file,
            # Передаємо актуальні дані з конфігу у фронтенд
            "rate_default": cfg.get("VRA_RATE_DEFAULT", 0.0),
            "calc_mode": cfg.get("VRA_CALC_MODE", "boom"),
            "maps": maps_list
        })
    
    @app.route('/api/vra/save_config', methods=['POST'])
    def save_vra_config():
        """
        Приймає залізні налаштування VRA з фронтенду,
        оновлює RAM-кеш та синхронізує файл config.json на диску.
        """
        data = request.get_json() or {}
        
        rate_default = data.get("rate_default")
        calc_mode = data.get("calc_mode")
        
        if calc_mode not in ["boom", "sections"]:
            return jsonify({"status": "error", "message": "Неверный режим вычислений"}), 400

        try:
            # Збираємо пачку для оновлення
            new_cfg_patch = {
                "VRA_RATE_DEFAULT": float(rate_default) if rate_default is not None else 0.0,
                "VRA_CALC_MODE": calc_mode
            }
            
            # Викликаємо твій фірмовий збережувач конфігу
            config_manager.save_config(new_cfg_patch)
            
            # Одразу синхронізуємо дефолтне значення в нашому менеджері карт, якщо він запущений
            vra = getattr(state, 'vra_manager', None)
            if vra:
                vra.rate_default = new_cfg_patch["VRA_RATE_DEFAULT"]

            return jsonify({"status": "ok", "message": "Налаштування заліза успішно збережені!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Помилка конфігуратора: {str(e)}"}), 500

    @app.route('/api/vra/upload', methods=['POST'])
    def upload_new_vra_map():
        """
        2. ЗАВАНТАЖИТИ НОВИЙ (Валідація + Штамп дати/часу при збігу імен)
        Приймає файл, перевіряє на "адекватність", копіює, але НЕ активує відразу.
        """
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "Файл не знайдено в запиті"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"status": "error", "message": "Файл не обрано"}), 400
            
        if not file.filename.endswith('.zip'):
            return jsonify({"status": "error", "message": "Дозволені лише .zip архіви Shapefile"}), 400

        upload_dir = os.path.join(os.getcwd(), "geodata")
        os.makedirs(upload_dir, exist_ok=True)

        # Очищаємо ім'я файлу від небезпечних системних символів
        #orig_filename = secure_filename(file.filename)
        # Безопасная очистка имени файла на чистом Python (вместо secure_filename)
        filename_cleaned = file.filename.replace(" ", "_") # Меняем пробелы на подчёркивания
        orig_filename = re.sub(r'[^a-zA-Z0-9_.-]', '', filename_cleaned) # Удаляем спецсимволы
        # Если после очистки имя стало пустым, даем дефолтное
        if not orig_filename or orig_filename in ['.zip', '..zip']:
            orig_filename = "uploaded_map.zip"

        name_part, ext_part = os.path.splitext(orig_filename)

        # ПЕРЕВІРКА НА ЗБІГ ІМЕН: якщо файл існує, додаємо штамп ДДММГГ_ЧЧММ [☍]
        target_filename = orig_filename
        name_was_changed = False
        if os.path.exists(os.path.join(upload_dir, target_filename)):
            timestamp = datetime.datetime.now().strftime("%d%m%y_%H%M")
            target_filename = f"{name_part}_{timestamp}{ext_part}"
            name_was_changed = True

        temp_path = os.path.join(upload_dir, f"temp_upload_{target_filename}")
        final_path = os.path.join(upload_dir, target_filename)

        try:
            # Зберігаємо тимчасово на диск для перевірки валідатором geopandas
            file.save(temp_path)
            
            # Перевірка "адекватності" (Валідація)
            uri = f"zip://{temp_path.replace(os.sep, '/')}"
            test_df = gpd.read_file(uri)
            
            # Шукаємо нашу головну колонку
            vra = getattr(state, 'vra_manager', None)
            rate_col = vra.rate_column if vra else 'rate'
            
            if rate_col not in test_df.columns:
                if os.path.exists(temp_path): os.remove(temp_path)
                return jsonify({
                    "status": "error", 
                    "message": f"Валідація провалена! У файлі відсутня обов'язкова колонка норми внеску '{rate_col}'."
                }), 422

            # Перейменовуємо тимчасовий файл у фінальний робочий архів
            os.rename(temp_path, final_path)
            
            msg = f"Файл успішно збережено як {target_filename}."
            if name_was_changed:
                msg = f"Увага! Таке ім'я вже було зайняте. Файл автоматично перейменовано у: {target_filename}"

            return jsonify({
                "status": "ok",
                "message": msg,
                "filename": target_filename
            }), 200

        except Exception as e:
            # Якщо geopandas впав — файл бітий, видаляємо сміття
            if os.path.exists(temp_path): os.remove(temp_path)
            return jsonify({
                "status": "error", 
                "message": f"Помилка читання архіву! Перевірте струкруту Shapefile. Деталі: {str(e)}"
            }), 400


    @app.route('/api/vra/activate', methods=['POST'])
    def activate_vra_map():
        """
        3. ЗАГРУЗИТЬ СУЩЕСТВУЮЩИЙ (Активація карти з архіву папки geodata)
        """
        data = request.get_json() or {}
        filename = data.get("filename")
        
        if not filename:
            return jsonify({"status": "error", "message": "Не вказано ім'я файлу"}), 400

        vra = getattr(state, 'vra_manager', None)
        if vra:
            # Атомарно та безпечно завантажуємо карту в пам'яті рушія
            success = vra.activate_existing_map(filename)
            if success:
                # Записуємо в state для DumpManager, щоб зберегти сесію
                #if state: state.set("active_vra_file", filename)
                if state: state.active_vra_file = filename
                return jsonify({"status": "ok", "message": f"Карта {filename} активована в роботу!"})
                
        return jsonify({"status": "error", "message": "Не вдалося активувати карту"}), 500


    @app.route('/api/vra/deactivate', methods=['POST'])
    def deactivate_vra_map():
        """
        4. ОТКЛЮЧИТЬ КАРТУ (Феншуйне вивантаження з ОЗУ)
        """
        vra = getattr(state, 'vra_manager', None)
        if vra:
            vra.deactivate_map()
            #if state: state.set("active_vra_file", None) # Очищаємо сесію
            if state: state.active_vra_file = None
            return jsonify({"status": "ok", "message": "Карту вивантажено. Система перейшла на базову норму."})
            
        return jsonify({"status": "error", "message": "Менеджер карт не ініціалізовано"}), 500
    
    @app.route('/api/vra/delete', methods=['POST'])
    def delete_vra_map_file():
        """
        5. ВИДАЛЕННЯ ФАЙЛУ З ДИСКА.
        Стирає ZIP-архив з папки geodata.
        """
        data = request.get_json() or {}
        filename = data.get("filename")
        
        if not filename:
            return jsonify({"status": "error", "message": "Не вказано ім'я файлу"}), 400

        # Захист: не дозволяємо видалити карту, яка зараз завантажена в ОЗУ
        active_file = getattr(state, "active_vra_file", None)
        if filename == active_file:
            return jsonify({"status": "error", "message": "Неможливо видалити карту, яка зараз працює в системі! Спочатку відключіть її."}), 422

        file_path = os.path.join(os.getcwd(), "geodata", filename)
        
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[VRA INFO]: Файл {filename} фізично видалено з диска.")
                return jsonify({"status": "ok", "message": "Файл успішно видалено."})
            else:
                return jsonify({"status": "error", "message": "Файл не знайдено на диску."}), 444
        except Exception as e:
            return jsonify({"status": "error", "message": f"Помилка доступу до диска: {str(e)}"}), 500



    # @app.route('/api/vra/upload', methods=['POST'])
    # def upload_vra_map():
    #     """
    #     Принимает ZIP-архив с Shapefile, сохраняет его в папку geodata/
    #     и мгновенно обновляет карту в работающем движке.
    #     """
    #     if 'file' not in request.files:
    #         return jsonify({"error": "Файл не найден в запросе"}), 400
            
    #     file = request.files['file']
    #     if file.filename == '':
    #         return jsonify({"error": "Файл не выбран"}), 400
            
    #     if file and file.filename.endswith('.zip'):
    #         filename = "test_Shapefile.zip" # Жестко перезаписываем рабочий файл карты
            
    #         # Путь к папке geodata в корне проекта
    #         upload_dir = os.path.join(os.getcwd(), "geodata")
    #         os.makedirs(upload_dir, exist_ok=True) # Создаем папку, если её нет
            
    #         file_path = os.path.join(upload_dir, filename)
    #         file.save(file_path)
            
    #         # Даем команду менеджеру мгновенно перечитать карту в памяти
    #         vra = getattr(state, 'vra_manager', None)
    #         if vra:
    #             success = vra.load_map_from_zip(filename)
    #             if success:
    #                 return jsonify({"message": "Карта успешно загружена и активирована!"}), 200
    #             else:
    #                 return jsonify({"error": "Архив загружен, но Shapefile внутри поврежден или неверного формата"}), 422
                    
    #         return jsonify({"error": "Системная ошибка: VRAManager не инициализирован"}), 500
            
    #     return jsonify({"error": "Допускаются только файлы .zip архивов Shapefile"}), 400










    return app
