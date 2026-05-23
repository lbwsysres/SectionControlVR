from flask import Flask, jsonify, render_template, request, Response
import config_manager
import os
import math
import pyproj
import dump_manager
import serial.tools.list_ports
import datetime
import re
import geopandas as gpd
import threading

# Глобальный RAM-буфер для хранения последнего снимка состояния системы
# Глобальний RAM-буфер для зберігання останнього знімка стану системи
WEB_CACHE = {
    "area": 0.0,
    "states": [],
    "pos": [49.7604988, 29.0021806],
    "flow_percents": [],
    "vra_flows": [],
    "speed": 0.0,
    "hdg": 0.0,
    "rtk": 0,
    "guidance_error": 0.0,
    "gps_mode": 0,
    "gps_mode_text": "Initializing...",
    "point_a": None,
    "point_b": None,
    "ab_gps": {"a": None, "b": None},
    "new_points": [],
    "total_count": 0,
    "gps_connected": False,
    "board_connected": False,
    "gps_sats": 0,
    "hdop": 0.0,
    "vdop": 0.0,
    "pdop": 0.0,
    "current_file": "NEW",
    "esp_current_flow": 0.0,
    "esp_pressure": 0.0,
    "esp_pwm": 0,
    "active_vra_file": None,
    # ОБО'В'ЯЗКОВО ДОДАЄМО ЦЕЙ КЛЮЧ (Він викликав KeyError у /api/status)
    "emu_enabled": False,
}


# Внутренний трансформер веб-сервера для разгрузки главного процесса
_web_transformer = None


def meters_to_gps_local(mx, my, ref_lon=29.0):
    """Безопасный инверсный трансформер прямо на стороне веб-сервера"""
    global _web_transformer
    if mx is None or my is None:
        return None
    try:
        if _web_transformer is None:
            zone = int((ref_lon + 180) / 6) + 1
            _web_transformer = pyproj.Transformer.from_crs(
                "epsg:4326", f"epsg:326{zone}", always_xy=True
            )
        lon, lat = _web_transformer.transform(
            mx, my, direction=pyproj.enums.TransformDirection.INVERSE
        )
        return [lat, lon]
    except:
        return None


def cache_updater_loop(data_queue):
    """Поток внутри Flask, который забирает данные из межпроцессной очереди"""
    global WEB_CACHE
    while True:
        try:
            # Ждем свежий снимок от математики
            snap = data_queue.get()
            if snap is None:
                break

            # Атомарно обновляем наш локальный кеш
            for key, val in snap.items():
                if key in WEB_CACHE:
                    WEB_CACHE[key] = val

            # Считаем GPS координаты точек А-Б прямо здесь, чтобы не грузить ядро расчетов
            ref_lon = WEB_CACHE["pos"][1] if WEB_CACHE["pos"][1] != 0 else 29.0
            WEB_CACHE["ab_gps"] = {
                "a": (
                    meters_to_gps_local(
                        WEB_CACHE["point_a"][0], WEB_CACHE["point_a"][1], ref_lon
                    )
                    if WEB_CACHE["point_a"]
                    else None
                ),
                "b": (
                    meters_to_gps_local(
                        WEB_CACHE["point_b"][0], WEB_CACHE["point_b"][1], ref_lon
                    )
                    if WEB_CACHE["point_b"]
                    else None
                ),
            }
        except:
            pass


def create_app(data_queue, cmd_queue):
    """Инициализация фабрики Flask. Объекты state и sc больше НЕ НУЖНЫ."""
    app = Flask(__name__)

    # Запускаем поток обновления кеша внутри веб-сервера
    t = threading.Thread(target=cache_updater_loop, args=(data_queue,), daemon=True)
    t.start()

    @app.route("/")
    def index():
        cfg = config_manager.load_config()
        return render_template("board.html", cfg=cfg)

    @app.route("/map_data")
    def map_data():
        cfg = config_manager.load_config()
        try:
            last_idx = int(request.args.get("last", 0))
        except:
            last_idx = 0

        # Забираем срез точек из локального кеша
        new_points = (
            WEB_CACHE["new_points"][last_idx:]
            if last_idx < len(WEB_CACHE["new_points"])
            else []
        )

        return jsonify(
            {
                "area": WEB_CACHE["area"],
                "states": WEB_CACHE["states"],
                "pos": WEB_CACHE["pos"],
                "ab_gps": WEB_CACHE["ab_gps"],
                "flow_percents": WEB_CACHE["flow_percents"],
                "vra_flows": WEB_CACHE["vra_flows"],
                "speed": round(WEB_CACHE["speed"], 1),
                "hdg": WEB_CACHE["hdg"],
                "rtk": WEB_CACHE["rtk"],
                "master": cfg.get("MASTER_SW", False),
                "modes": cfg.get("SECTION_MODES", ["AUTO"] * len(WEB_CACHE["states"])),
                "ab_line": {
                    "a": WEB_CACHE["point_a"],
                    "b": WEB_CACHE["point_b"],
                    "error": WEB_CACHE["guidance_error"],
                },
                "ux": WEB_CACHE["pos"][1],  # Заглушка, фронтенд использует pos
                "uy": WEB_CACHE["pos"][0],
                "new_points": new_points,
                "total_count": WEB_CACHE["total_count"],
                "gps_mode": WEB_CACHE["gps_mode"],
                "gps_mode_text": WEB_CACHE["gps_mode_text"],
            }
        )

    @app.route("/panel_data")
    def panel_data():
        cfg = config_manager.load_config()
        return jsonify(
            {
                "mo": cfg.get("SECTION_MODES", ["AUTO"] * len(WEB_CACHE["states"])),
                "st": WEB_CACHE["states"],
                "fl": WEB_CACHE["flow_percents"],
                "sp": round(WEB_CACHE["speed"], 1),
                "hd": WEB_CACHE["hdg"],
                "rt": WEB_CACHE["rtk"],
                "er": round(WEB_CACHE["guidance_error"], 2),
                "ar": WEB_CACHE["area"],
                "m_g": WEB_CACHE["gps_mode"],
                "ms": cfg.get("MASTER_SW", False),
            }
        )

    @app.route("/settings")
    def settings():
        cfg = config_manager.load_config()
        widths_str = ",".join(map(str, cfg["SECTION_WIDTHS"]))
        return render_template("settings.html", cfg=cfg, widths=widths_str)

    @app.route("/save_settings", methods=["POST"])
    def save_settings():
        data = request.get_json()
        if not data:
            return {"error": "No data received"}, 400
        cfg = config_manager.load_config()

        # Ваш шикарный маппинг типов (оставляем без изменений)
        key_mapping = {
            "SECTION_WIDTHS": ("SECTION_WIDTHS", lambda v: [float(x) for x in v]),
            "AUTO_SECTION_MIN_OVERLAP": ("AUTO_SECTION_MIN_OVERLAP", float),
            "LOOK_AHEAD_ON_TIME": ("LOOK_AHEAD_ON_TIME", float),
            "LOOK_AHEAD_OFF_TIME": ("LOOK_AHEAD_OFF_TIME", float),
            "AUTO_SECTION_BUFFER": ("AUTO_SECTION_BUFFER", float),
            "CURVE_COMP_SMOOTH": ("CURVE_COMP_SMOOTH", float),
            "DRAW_OFF_SECTIONS": ("DRAW_OFF_SECTIONS", bool),
            "UDP_PORT": ("UDP_PORT", int),
            "MIN_SPEED": ("MIN_SPEED", float),
            "CONTROL_BOARD_ENABLE": ("CONTROL_BOARD_ENABLE", bool),
            "CONTROL_BOARD_PORT": ("CONTROL_BOARD_PORT", lambda v: str(v).strip()),
            "CONTROL_BOARD_PORT_SPEED": ("CONTROL_BOARD_PORT_SPEED", int),
            "SMART_TURN_ENABLED": ("SMART_TURN_ENABLED", bool),
        }
        for js_key, (cfg_key, type_converter) in key_mapping.items():
            if js_key in data and data[js_key] is not None:
                try:
                    cfg[cfg_key] = type_converter(data[js_key])
                except:
                    pass
        config_manager.save_config(cfg)

        # Отправляем команду в главное ядро, что конфиг обновился
        cmd_queue.put({"cmd": "reload_config"})
        return {"status": "success"}, 200

    @app.route("/set_master/<int:val>")
    def set_master(val):
        cfg = config_manager.load_config()
        cfg["MASTER_SW"] = bool(val)
        config_manager.save_config(cfg)
        cmd_queue.put({"cmd": "reload_config"})
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
        cmd_queue.put({"cmd": "reload_config"})
        return "OK"

    @app.route("/reset")
    def reset():
        cmd_queue.put({"cmd": "reset"})
        return "OK"

    @app.route("/emu_control", methods=["POST"])
    def emu_control():
        try:
            data = request.json
            cmd_queue.put(
                {
                    "cmd": "emu_control",
                    "hdg": float(data.get("hdg", 0)),
                    "spd": float(data.get("spd", 0)),
                    "enabled": bool(data.get("enabled", False)),
                }
            )
            return "OK"
        except:
            return "Error", 400

    @app.route("/reset_area")
    def reset_area():
        cmd_queue.put({"cmd": "reset_area"})
        return jsonify({"status": "ok", "message": "Area cleared"})

    @app.route("/set_point/<label>")
    def set_point(label):
        val = request.args.get("value", 0)
        lat = request.args.get("lat")
        lon = request.args.get("lon")
        cmd_queue.put(
            {"cmd": "set_point", "label": label, "value": val, "lat": lat, "lon": lon}
        )
        return "OK"

    @app.route("/api/load_field", methods=["POST"])
    def api_load_field():
        data = request.get_json() or {}
        filename = data.get("filename", "")
        cmd_queue.put({"cmd": "load_field", "filename": filename})
        return {"status": "success"}, 200

    @app.route("/api/delete_field", methods=["POST"])
    def api_delete_field():
        data = request.get_json() or {}
        filename = os.path.basename(data.get("filename", ""))
        target_path = os.path.join(dump_manager.DUMP_DIR, filename)
        if os.path.exists(target_path):
            os.remove(target_path)
            return {"status": "success"}, 200
        return {"error": "Файл не знайдено"}, 404

    @app.route("/api/status", methods=["GET"])
    def get_status():
        """Повертає поточний статус заліза та системних допусків з RAM-кешу"""
        return (
            jsonify(
                {
                    "gps_connected": WEB_CACHE["gps_connected"],
                    "emu_enabled": WEB_CACHE["emu_enabled"],
                    "rtk_status": WEB_CACHE["rtk"],
                    "sats": WEB_CACHE["gps_sats"],
                    "hdop": round(WEB_CACHE["hdop"], 2),
                    "vdop": round(WEB_CACHE["vdop"], 2),
                    "pdop": round(WEB_CACHE["pdop"], 2),
                    "board_connected": WEB_CACHE["board_connected"],
                    "speed": round(WEB_CACHE["speed"], 1),
                    "hdg": round(WEB_CACHE["hdg"], 1),
                    "file": WEB_CACHE["current_file"],
                    "esp_current_flow": round(WEB_CACHE["esp_current_flow"], 1),
                    "esp_pressure": round(WEB_CACHE["esp_pressure"], 1),
                    "esp_pwm": WEB_CACHE["esp_pwm"],
                }
            ),
            200,
        )

    @app.route("/api/available_ports", methods=["GET"])
    def get_available_ports():
        """Сканує системні COM/tty порти ОС для сторінки налаштувань"""
        ports_list = [
            {"device": p.device, "description": p.description}
            for p in serial.tools.list_ports.comports()
        ]
        if not ports_list:
            ports_list = [
                {"device": "com1", "description": "Демо-порт 1 (Заглушка)"},
                {"device": "/dev/ttyUSB0", "description": "Демо-порт Linux"},
            ]
        return jsonify(ports_list), 200

    @app.route("/fields")
    def fields_page():
        """Показує сторінку файлового менеджера полів"""
        return render_template("fields.html")

    @app.route("/api/files", methods=["GET"])
    def list_files():
        """Повертає список збережених JSON-файлів полів для UI менеджера"""
        import time

        files_list = []
        if os.path.exists(dump_manager.DUMP_DIR):
            for fname in os.listdir(dump_manager.DUMP_DIR):
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
        files_list.sort(key=lambda x: x["date"], reverse=True)
        return jsonify(files_list)

    @app.route("/api/save_field", methods=["POST"])
    def api_save_field():
        """Тракторист ввів ім'я поля — відправляємо команду на заморозку сесії"""
        data = request.get_json() or {}
        field_name = data.get("field_name", "").strip()
        if not field_name:
            return {"error": "Назва поля не може бути порожньою"}, 400

        secure_name = "".join(
            c for c in field_name if c.isalnum() or c in (" ", "_", "-")
        ).strip()
        # Даємо команду ядру зробити іменований злімок
        cmd_queue.put({"cmd": "save_field", "filename": f"{secure_name}.json"})
        return {
            "status": "success",
            "message": f"Запит на збереження поля {secure_name} надіслано",
        }, 200

    @app.route("/export_kml")
    def export_kml():
        """Генерація KML-файлу для Google Earth прямо з локального веб-кешу"""
        if not WEB_CACHE["new_points"]:
            return "Історія порожня", 400
        coords_list = [f"{pt[1]},{pt[0]},0" for pt in WEB_CACHE["new_points"]]
        coords_str = " ".join(coords_list)
        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://opengis.net">
<Document>
<name>MySection_Track</name>
<Style id="path_style"><LineStyle><color>7f00ffff</color><width>4</width></LineStyle></Style>
<Placemark>
<name>Траєкторія</name>
<styleUrl>#path_style</styleUrl>
<LineString><tessellate>1</tessellate><coordinates>{coords_str}</coordinates></LineString>
</Placemark>
</Document>
</kml>""".strip()
        return Response(
            kml_content,
            mimetype="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": "attachment;filename=track.kml"},
        )

    # ********************************** VRA СЕКЦІЯ **********************************
    @app.route("/api/vra/map", methods=["GET"])
    def get_vra_map():
        """
        Рідний роут карт VRA з вашим фірмовим парсингом [Lat, Lon] для Canvas.
        Адаптовано під ізольовану роботу Flask на окремому ядрі CPU.
        """
        # 1. Дізнаємося з міжпроцесного кешу, який файл зараз активний у ядрі математики
        active_file = WEB_CACHE.get("active_vra_file")
        cfg = config_manager.load_config()
        rate_default = cfg.get("VRA_RATE_DEFAULT", 0.0)
        
        if not active_file:
            return jsonify({"status": "no_map"})

        try:
            # 2. Швидке ОЗУ-кешування сліду карти, щоб не мучити процесор читанням ZIP-файлу при кожному оновленні
            if not hasattr(app, '_vra_polygons_cache') or getattr(app, '_last_polys_file', None) != active_file:
                upload_dir = os.path.join(os.getcwd(), "geodata")
                file_path = os.path.join(upload_dir, active_file)
                
                if not os.path.exists(file_path):
                    return jsonify({"status": "no_map"})
                    
                # Зчитуємо Shapefile силами процесу веб-сервера
                uri = f"zip://{file_path.replace(os.sep, '/')}"
                rate_data = gpd.read_file(uri)
                
                if rate_data.empty:
                    return jsonify({"status": "no_map"})

                polygons_list = []
                rate_column = "rate" # Стандарт вашого Shapefile

                # =======================================================================
                # ВАША РІДНА ЛОГІКА ПАРСИНГУ КООРДИНАТ ДЛЯ CANVAS (ОДИН В ОДИН)
                # =======================================================================
                for _, row in rate_data.iterrows():
                    try:
                        raw_val = float(row[rate_column])
                    except (ValueError, TypeError):
                        raw_val = float('nan')

                    # Фікс №1: Якщо NaN — ставимо 0.0, інакше — залишаємо значення
                    rate_val = 0.0 if math.isnan(raw_val) else raw_val
                    geom = row['geometry']
                    
                    if geom is None:
                        continue
                    elif geom.geom_type == 'Polygon':
                        coords = list(geom.exterior.coords)
                    elif geom.geom_type == 'MultiPolygon':
                        coords = []
                        for poly in geom.geoms:
                            coords.extend(list(poly.exterior.coords))
                    else:
                        continue # Пропускаємо лінії або точки
                    
                    # Зміна порядку з (Lon, Lat) на [Lat, Lon] для Canvas
                    formatted_coords = [[pt[1], pt[0]] for pt in coords]
                    
                    polygons_list.append({
                        "rate": rate_val,
                        "points": formatted_coords
                    })

                # Фікс №2: Безпечний розрахунок мінімуму і максимума без NaN
                clean_rates = rate_data[rate_column].dropna()

                if not clean_rates.empty:
                    min_rate = float(clean_rates.min())
                    max_rate = float(clean_rates.max())
                else:
                    min_rate = 0.0
                    max_rate = rate_default

                # Захист від однакових значень (делення на 0)
                if min_rate == max_rate:
                    min_rate = max_rate * 0.8 if max_rate != 0 else -1.0

                # Зберігаємо сформований результат у локальну ОЗУ-змінну процесу Flask
                app._vra_polygons_cache = {
                    "status": "success",
                    "min_rate": min_rate,
                    "max_rate": max_rate,
                    "rate_default": rate_default,
                    "polygons": polygons_list
                }
                app._last_polys_file = active_file

            # 3. Віддаємо JavaScript-планшету готовий валідний JSON-пакет із кешу ОЗУ
            return jsonify(app._vra_polygons_cache)

        except Exception as e:
            print(f"[Web VRA Map Parser Error]: {e}")
            return jsonify({"status": "error", "message": str(e)})

    @app.route("/vra_control")
    def vra_control_page():
        return render_template("vra_maps.html")

    @app.route("/api/vra/list", methods=["GET"])
    def get_vra_list():
        cfg = config_manager.load_config()
        upload_dir = os.path.join(os.getcwd(), "geodata")
        os.makedirs(upload_dir, exist_ok=True)
        files = [f for f in os.listdir(upload_dir) if f.endswith(".zip")]

        maps_list = [
            {
                "filename": f,
                "created": datetime.datetime.fromtimestamp(
                    os.stat(os.path.join(upload_dir, f)).st_mtime
                ).strftime("%d.%m.%Y %H:%M"),
                "is_active": (f == WEB_CACHE["active_vra_file"]),
            }
            for f in files
        ]

        return jsonify(
            {
                "status": "ok",
                "active_file": WEB_CACHE["active_vra_file"],
                "rate_default": cfg.get("VRA_RATE_DEFAULT", 0.0),
                "calc_mode": cfg.get("VRA_CALC_MODE", "boom"),
                "maps": maps_list,
            }
        )

    @app.route("/api/vra/save_config", methods=["POST"])
    def save_vra_config():
        data = request.get_json() or {}
        rate_default = data.get("rate_default")
        calc_mode = data.get("calc_mode")
        if calc_mode not in ["boom", "sections"]:
            return (
                jsonify({"status": "error", "message": "Неправильний режим обчислень"}),
                400,
            )
        try:
            new_cfg_patch = {
                "VRA_RATE_DEFAULT": (
                    float(rate_default) if rate_default is not None else 0.0
                ),
                "VRA_CALC_MODE": calc_mode,
            }
            config_manager.save_config(new_cfg_patch)
            cmd_queue.put({"cmd": "reload_config"})
            return jsonify(
                {"status": "ok", "message": "Налаштування заліза успішно збережені!"}
            )
        except Exception as e:
            return (
                jsonify(
                    {"status": "error", "message": f"Помилка конфігуратора: {str(e)}"}
                ),
                500,
            )

    @app.route("/api/vra/upload", methods=["POST"])
    def upload_new_vra_map():
        """Завантаження та первинна швидка валідація ZIP-архіву Shapefile"""
        if "file" not in request.files:
            return (
                jsonify({"status": "error", "message": "Файл не знайдено в запиті"}),
                400,
            )
        file = request.files["file"]
        if file.filename == "" or not file.filename.endswith(".zip"):
            return (
                jsonify({"status": "error", "message": "Дозволені лише .zip архіви"}),
                400,
            )

        upload_dir = os.path.join(os.getcwd(), "geodata")
        os.makedirs(upload_dir, exist_ok=True)

        filename_cleaned = file.filename.replace(" ", "_")
        orig_filename = re.sub(r"[^a-zA-Z0-9_.-]", "", filename_cleaned)
        if not orig_filename or orig_filename in [".zip", "..zip"]:
            orig_filename = "uploaded_map.zip"

        name_part, ext_part = os.path.splitext(orig_filename)
        target_filename = orig_filename
        name_was_changed = False

        if os.path.exists(os.path.join(upload_dir, target_filename)):
            timestamp = datetime.datetime.now().strftime("%d%m%y_%H%M")
            target_filename = f"{name_part}_{timestamp}{ext_part}"
            name_was_changed = True

        temp_path = os.path.join(upload_dir, f"temp_upload_{target_filename}")
        final_path = os.path.join(upload_dir, target_filename)

        try:
            file.save(temp_path)
            uri = f"zip://{temp_path.replace(os.sep, '/')}"
            test_df = gpd.read_file(uri)

            # Перевіряємо наявність колонки 'rate' за замовчуванням
            if "rate" not in test_df.columns:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Валідація провалена! Відсутня колонка 'rate'.",
                        }
                    ),
                    422,
                )

            os.rename(temp_path, final_path)
            msg = f"Файл збережено як {target_filename}."
            if name_was_changed:
                msg = (
                    f"Увага! Ім'я зайняте. Файл авто-перейменовано в: {target_filename}"
                )
            return (
                jsonify({"status": "ok", "message": msg, "filename": target_filename}),
                200,
            )
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Помилка читання архіву Shapefile: {str(e)}",
                    }
                ),
                400,
            )

    @app.route("/api/vra/activate", methods=["POST"])
    def activate_vra_map():
        data = request.get_json() or {}
        filename = data.get("filename")
        if not filename:
            return jsonify({"status": "error", "message": "Не вказано ім'я файлу"}), 400
        cmd_queue.put({"cmd": "activate_vra", "filename": filename})
        return jsonify(
            {
                "status": "ok",
                "message": f"Карта {filename} відправлена на активацію в ядро!",
            }
        )

    @app.route("/api/vra/deactivate", methods=["POST"])
    def deactivate_vra_map():
        cmd_queue.put({"cmd": "deactivate_vra"})
        return jsonify({"status": "ok", "message": "Карту вивантажено з ОЗУ."})

    return app
