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
                "flow": state.flow_percents,  # [100, 120, 80, ...]
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
            }
        )

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

    return app
