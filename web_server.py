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

SETTINGS_HTML_1 = """
<!DOCTYPE html>
<html>
<head>
    <title>Settings</title>
    <style>
        body { background: #111; color: white; font-family: sans-serif; padding: 20px; }
        .box { background: #222; padding: 15px; border-radius: 12px; max-width: 400px; margin: auto; border: 1px solid #333; }
        input { background: #333; border: 1px solid #555; color: white; padding: 12px; width: 80%; margin-bottom: 20px; border-radius: 6px; }
        label { color: #2ecc71; display: block; margin-bottom: 8px; font-weight: bold; }
        .btn { background: #2ecc71; color: black; border: none; padding: 15px; width: 100%; cursor: pointer; font-weight: bold; border-radius: 6px; font-size: 16px; }
        select,input{background:#222;border:1px solid #444;color:#fff;padding:10px;width:90%;border-radius:6px;outline:none;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://w3.org' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%232ecc71' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;cursor:pointer;font-family:inherit}select:focus,input:focus{border-color:var(--neon-green)}
    </style>
</head>
<body>
    <div class="box">
        <h2>⚙ Настройки MySection</h2>
        <form action="/save_settings" method="POST">
            <label>Секции (метры, через запятую):</label>
            <input name="widths" value="{{ widths }}">
            <label>Рисовать выключенные секции?</label>
            <select name="draw_off">
                <option value="true" {{ 'selected' if cfg.DRAW_OFF_SECTIONS }}>ДА (Показывать красным)</option>
                <option value="false" {{ 'selected' if not cfg.DRAW_OFF_SECTIONS }}>НЕТ (Только чистое поле)</option>
            </select>
            <label>Визуальный масштаб (напр. 1.0):</label>
            <input type="number" step="0.1" name="visual_scale" value="{{ cfg.VISUAL_SCALE }}">
            <label>Look Ahead (сек):</label>
            <input type="number" step="0.1" name="look_ahead" value="{{ cfg.LOOK_AHEAD }}">
            <label>Offset Back (вынос штанги, м):</label>
            <input type="number" step="0.1" name="offset_back" value="{{ cfg.OFFSET_BACK }}">
            <label>UDP Порт (AgIO):</label>
            <input type="number" name="port" value="{{ cfg.UDP_PORT }}">
            <button type="submit" class="btn">СОХРАНИТЬ И ПРИМЕНИТЬ</button>
        </form>
        <br><a href="/" style="color: #666; text-decoration: none; display: block; text-align: center;">← Назад</a>
    </div>
</body>
</html>
"""
def meters_to_gps(sc, mx, my):
    if mx is None or my is None:
        return None
    try:
        # Используем трансформер из переданного объекта sc
        lon, lat = sc.transformer_to_m.transform(
            mx, my, 
            direction=pyproj.enums.TransformDirection.INVERSE
        )
        return [lat, lon]
    except Exception as e:
        print(f"DEBUG: Ошибка конвертации: {e}")
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
            last_idx = int(request.args.get('last', 0))
        except:
            last_idx = 0

        new_points = state.path_history[last_idx:]
        ab_gps_data = {
            "a": meters_to_gps(sc, state.point_a[0], state.point_a[1]) if state.point_a else None,
            "b": meters_to_gps(sc, state.point_b[0], state.point_b[1]) if state.point_b else None
        }
        # if state.speed is None or state.hdg is None:
        #     flow_percents = [100] * len(sc.cfg.get("SECTION_WIDTHS", [1.0]*7))
        # else:
        #     # Викликаємо твій робочий метод
        #     #flow_percents = sc.get_curve_compensation(state.speed / 3.6, state.hdg)
        #     flow_percents = sc.update(state.speed, state.hdg)

        #flow_percents = [100] * len(sc.cfg.get("SECTION_WIDTHS", [1.0]*7))
        #omega = sc.calculate_omega(state.hdg)
        #head = sc.update(state.hdg)
        return jsonify(
            {
                "area": state.area,
                "states": state.current_states,
                "pos": [state.last_lat, state.last_lon],
                "ab_gps": ab_gps_data,
                "flow": state.flow_percents,           # [100, 120, 80, ...]
                "speed": round(state.speed, 1),
                "hdg": state.hdg,
                "rtk": state.rtk,
                "master": cfg.get("MASTER_SW", False),
                "modes": cfg.get("SECTION_MODES", ["AUTO"] * len(state.current_states)),
                # Рядок з "history" ВИДАЛЕНО
                "ab_line": {
                    "a": state.point_a,
                    "b": state.point_b,
                    "error": getattr(state, 'guidance_error', 0)
                },
                "ux": sc.last_x, 
                "uy": sc.last_y,
                "new_points": new_points, 
                "total_count": len(state.path_history)
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
    #     cfg = config_manager.load_config()

    #     # Используем .get(), чтобы сервер не падал, если поле не пришло
    #     if "widths" in request.form:
    #         cfg["SECTION_WIDTHS"] = [
    #             float(x) for x in request.form["widths"].split(",")
    #         ]

    #     if "min_speed" in request.form:
    #         cfg["MIN_SPEED"] = float(request.form["min_speed"])

    #     if "visual_scale" in request.form:
    #         cfg["VISUAL_SCALE"] = float(request.form["visual_scale"])

    #     if "look_ahead" in request.form:
    #         cfg["LOOK_AHEAD"] = float(request.form["look_ahead"])

    #     if "offset_back" in request.form:
    #         cfg["OFFSET_BACK"] = float(request.form["offset_back"])

    #     if "port" in request.form:
    #         cfg["UDP_PORT"] = int(request.form["port"])

    #     # Добавляем сохранение новой настройки отрисовки
    #     if "draw_off" in request.form:
    #         cfg["DRAW_OFF_SECTIONS"] = request.form["draw_off"] == "true"

    #     config_manager.save_config(cfg)
    #     return redirect("/")
    @app.route("/save_settings", methods=["POST"])
    def save_settings():
        # Отримуємо JSON з тіла запиту (fetch шле саме його)
        data = request.get_json()
        if not data:
            return {"error": "No data received"}, 400

        # Завантажуємо поточний конфіг
        cfg = config_manager.load_config()

        # Оновлюємо значення, використовуючи ключі з JS
        if "SECTION_WIDTHS" in data:
            cfg["SECTION_WIDTHS"] = [float(x) for x in data["SECTION_WIDTHS"]]

        if "AUTO_SECTION_MIN_OVERLAP" in data:
            cfg["AUTO_SECTION_MIN_OVERLAP"] = float(data["AUTO_SECTION_MIN_OVERLAP"])

        if "LOOK_AHEAD_TIME" in data:
            cfg["LOOK_AHEAD"] = float(data["LOOK_AHEAD_TIME"])

        if "AUTO_SECTION_BUFFER" in data:
            cfg["AUTO_SECTION_BUFFER"] = float(data["AUTO_SECTION_BUFFER"])

        if "CURVE_COMP_SMOOTH" in data:
            cfg["CURVE_COMP_SMOOTH"] = float(data["CURVE_COMP_SMOOTH"])

        if "CURVE_COMP_MIN_RTK" in data:
            cfg["CURVE_COMP_MIN_RTK"] = int(data["CURVE_COMP_MIN_RTK"])

        if "DRAW_OFF_SECTIONS" in data:
            cfg["DRAW_OFF_SECTIONS"] = bool(data["DRAW_OFF_SECTIONS"])

        if "VISUAL_SCALE" in data:
            cfg["VISUAL_SCALE"] = float(data["VISUAL_SCALE"])

        if "OFFSET_BACK" in data:
            cfg["OFFSET_BACK"] = float(data["OFFSET_BACK"])

        if "UDP_PORT" in data:
            cfg["UDP_PORT"] = int(data["UDP_PORT"])
        if "MIN_SPEED" in data:
            cfg["MIN_SPEED"] = float(data["MIN_SPEED"])
        
        if "MIN_LOOK_AHEAD_DIST" in data:
            cfg["MIN_LOOK_AHEAD_DIST"] = float(data["MIN_LOOK_AHEAD_DIST"])
        
        # Збираємо ліміти назад у список [min, max]
        if "CURVE_LIMIT_LOW" in data and "CURVE_LIMIT_HIGH" in data:
            cfg["CURVE_COMP_LIMITS"] = [
                int(data["CURVE_LIMIT_LOW"]), 
                int(data["CURVE_LIMIT_HIGH"])
            ]


        # Зберігаємо оновлений об'єкт через менеджер
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

    @app.route('/reset_area')
    def reset_area():
        try:
            #sc.reset_area() # Викликаємо правильний метод з очищенням об'єктів
            state.reset_flag = True # Виставляємо прапорець для gps_loop
            return jsonify({"status": "ok", "message": "Area cleared"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/set_point/<label>')
    def set_point(label):
        # 1. Сообщение о том, какой label пришел
        print(f"--- DEBUG: AB : {label} ---")

        if label == 'a':
            state.point_a = (sc.last_x, sc.last_y)
            print(f"SET A: {state.point_a}")
            
        elif label == 'b':
            state.point_b = (sc.last_x, sc.last_y)
            print(f"SET B: {state.point_b}")
            
        elif label == 'reset':
            state.point_a = state.point_b = None
            print("RESET AB")
            
        elif label == 'nudge':
            try:
                val = float(request.args.get('value', 0))
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
        elif label == 'manual_coords':
                try:
                    lat = float(request.args.get('lat'))
                    lon = float(request.args.get('lon'))
                    target = request.args.get('label', 'a') # Куда пишем: в 'a' или 'b'
                    
                    # Конвертируем в метры UTM через ваш трансформер
                    mx, my = sc.transformer_to_m.transform(lon, lat)
                    
                    if target == 'a':
                        state.point_a = (mx, my)
                    else:
                        state.point_b = (mx, my)
                        
                    print(f"--- MANUAL SET {target.upper()}: {lat}, {lon} -> ({mx}, {my}) ---")
                except Exception as e:
                    print(f"Manual record error: {e}")      
        return "OK"

    @app.route('/export_kml')
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
    </kml>""".strip() # .strip() уберет случайные пустые строки в начале и конце

        return Response(
            kml_content,
            mimetype='application/vnd.google-earth.kml+xml',
            headers={'Content-Disposition': 'attachment;filename=track.kml'}
        )



    # =================================================================================



    return app
