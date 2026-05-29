# web_sever.py
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
import json
import time

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
    "ux": 0.0,
    "uy": 0.0,
}
import logging
logger = logging.getLogger("WebServer")


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

            # 🛠️ ІНЖЕНЕРНИЙ ПЕРЕХВАТ ПАКЕТУ З ОЗУ МАТЕМАТИКИ
            if isinstance(snap, dict) and snap.get("type") == "live_state_dump":
                global LIVE_SHARED_STATE_CACHE
                # Записуємо відфільтровані змінні класу SharedState в окремий глобальний кеш
                LIVE_SHARED_STATE_CACHE = snap.get("variables", {})
                continue  # Миттєво йдемо на наступну ітерацію черги, не чіпаючи твій оригінальний код нижче

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

    base_sys_dir = os.path.dirname(os.path.abspath(__file__))
    implements_dir = os.path.join(base_sys_dir, "implements")

    # Запускаем поток обновления кеша внутри веб-сервера
    t = threading.Thread(target=cache_updater_loop, args=(data_queue,), daemon=True)
    t.start()


    # region  RENDER TAMPLATE
    @app.route("/")
    def view_navigation_hub_1():
        cfg = config_manager.load_config()
        return render_template("index.html", cfg=cfg)
        #return render_template("index.html")
    
    @app.route("/hub")
    def view_navigation_hub():
        return render_template("hub.html")

    
    @app.route("/settings")
    def settings():
        cfg = config_manager.load_config()
        widths_str = ",".join(map(str, cfg["SECTION_WIDTHS"]))
        return render_template("settings.html", cfg=cfg, widths=widths_str)


    @app.route("/map")
    def index():
        cfg = config_manager.load_config()
        return render_template("board.html", cfg=cfg)

    @app.route("/fields")
    def fields_page():
        """Показує сторінку файлового менеджера полів"""
        return render_template("fields.html")

    @app.route("/vra_control")
    def vra_control_page():
        return render_template("vra_maps.html")



    @app.route("/implement_manager") #МЕНЕДЖЕРА ЗНАРЯДЬ
    def view_implement_manager():
        # Завантажуємо базовий порожній конфіг, щоб шаблонізатор не вилітав (якщо потрібно)
        return render_template("implement_manager.html")
    
    
    @app.route("/taskmaps_manager")
    def view_taskmaps_manager():
        return render_template("taskmaps_manager.html")
    # endregion

    # region  МЕНЕДЖЕРА ЗНАРЯДЬ (IMPLEMENT MANAGER API)
    # =======================================================================
    # СЕКЦІЯ МЕНЕДЖЕРА ЗНАРЯДЬ (IMPLEMENT MANAGER API)
    # =======================================================================
    BASE_SYS_DIR = os.path.dirname(os.path.abspath(__file__))
    IMPLEMENTS_DIR = os.path.join(BASE_SYS_DIR, "implements")

    if not os.path.exists(IMPLEMENTS_DIR):
        os.makedirs(IMPLEMENTS_DIR, exist_ok=True)

    # @app.route("/implement_manager")
    # def view_implement_manager():
    #     # Завантажуємо базовий порожній конфіг, щоб шаблонізатор не вилітав (якщо потрібно)
    #     return render_template("implement_manager.html")

    # --- 1. ОТРИМАННЯ СПИСКУ ВСІХ ЗНАРЯДЬ ---
    @app.route("/api/implements/list", methods=["GET"])
    def api_get_implements_list():
        try:
            implements_list = []
            # Скануємо папку на наявність конфігів
            for fname in os.listdir(IMPLEMENTS_DIR):
                if fname.endswith(".json"):
                    fpath = os.path.join(IMPLEMENTS_DIR, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            implements_list.append(data)
                    except Exception as e:
                        print(f"[eMMC Error] Не вдалося прочитати файл {fname}: {e}")

            # Сортуємо за назвою, щоб список не стрибав на екрані
            implements_list.sort(key=lambda x: x.get("name", "").lower())
            return jsonify(implements_list)

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- 2. ЗБЕРЕЖЕННЯ АБО ОНОВЛЕННЯ ЗНАРЯДДЯ НА eMMC ---
    @app.route("/api/implements/save", methods=["POST"])
    def api_save_implement():
        try:
            req_data = request.get_json()
            if not req_data or "id" not in req_data:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Некоректні дані: відсутній ID знаряддя",
                        }
                    ),
                    400,
                )

            impl_id = req_data["id"]
            # Формуємо безпечне ім'я файлу на основі його унікального ID
            filename = f"{impl_id}.json"
            fpath = os.path.join(IMPLEMENTS_DIR, filename)

            # Атомарно записуємо структурований JSON на eMMC
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(req_data, f, ensure_ascii=False, indent=4)

            print(
                f"[eMMC Save] Успішно записано знаряддя: ID={impl_id}, Ім'я={req_data.get('name')}"
            )
            return jsonify({"status": "success"})

        except Exception as e:
            print(f"[eMMC Save Error] Збій запису на диск: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- 3. ПОВНЕ ВИДАЛЕННЯ ФАЙЛУ ЗНАРЯДДЯ З ДИСКА ---
    @app.route("/api/implements/delete", methods=["POST"])
    def api_delete_implement():
        try:
            req_data = request.get_json()
            if not req_data or "id" not in req_data:
                return (
                    jsonify(
                        {"status": "error", "message": "Некоректні дані: відсутній ID"}
                    ),
                    400,
                )

            impl_id = req_data["id"]
            filename = f"{impl_id}.json"
            fpath = os.path.join(IMPLEMENTS_DIR, filename)

            # Перевіряємо, чи фізично існує такий файл перед видаленням
            if os.path.exists(fpath):
                os.remove(fpath)
                print(
                    f"[eMMC Delete] Файл знаряддя {filename} успішно видалено з диска."
                )
                return jsonify({"status": "success"})
            else:
                return (
                    jsonify({"status": "error", "message": "Файл не знайдено на eMMC"}),
                    404,
                )

        except Exception as e:
            print(f"[eMMC Delete Error] Збій видалення з диска: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # endregion

    # region  СЕКЦІЯ МЕНЕДЖЕРА VRA (VRA MANAGER API)
    # =======================================================================
    # СЕКЦІЯ МЕНЕДЖЕРА VRA (VRA MANAGER API)
    # =======================================================================
    # Визначаємо нову ізольовану папку на eMMC
    TASKMAPS_DIR = os.path.join(os.getcwd(), "taskmaps")
    os.makedirs(TASKMAPS_DIR, exist_ok=True)

    # Маршрут для відкриття самої сторінки менеджера карт
    # @app.route("/taskmaps_manager")
    # def view_taskmaps_manager():
    #     return render_template("taskmaps_manager.html")

    # --- 1. ОТРИМАННЯ СПИСКУ ЗАВАНТАЖЕНИХ КАРТ TASKMAPS ---
    @app.route("/api/taskmaps/list", methods=["GET"])
    def get_taskmaps_list():
        try:
            cfg = config_manager.load_config()
            # Зчитуємо тільки .zip файли з нашої нової папки
            files = [f for f in os.listdir(TASKMAPS_DIR) if f.endswith(".zip")]

            maps_list = []
            for f in files:
                fpath = os.path.join(TASKMAPS_DIR, f)
                maps_list.append(
                    {
                        "filename": f,
                        "created": datetime.datetime.fromtimestamp(
                            os.stat(fpath).st_mtime
                        ).strftime("%d.%m.%Y %H:%M"),
                        # Перевіряємо за системним конфигом, чи активна ця карта зараз у полі
                        "is_active": (f == cfg.get("ACTIVE_TASKMAP_FILE", "")),
                    }
                )

            # Сортуємо від нових до старих
            maps_list.sort(key=lambda x: x["created"], reverse=True)
            return jsonify({"status": "ok", "maps": maps_list})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- 2. ЗАВАНТАЖЕННЯ НОВОЇ КАРТИ (ZIP С ЗБЕРЕЖЕННЯМ ІМЕНІ АГРОНОМА) ---
    @app.route("/api/taskmaps/upload", methods=["POST"])
    def upload_taskmap_file():
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

        # Очищаємо ім'я файлу від пробілів та спецсимволів за вашим фірмовим алгоритмом
        filename_cleaned = file.filename.replace(" ", "_")
        orig_filename = re.sub(r"[^a-zA-Z0-9_.-]", "", filename_cleaned)
        if not orig_filename or orig_filename in [".zip", "..zip"]:
            orig_filename = "uploaded_taskmap.zip"

        name_part, ext_part = os.path.splitext(orig_filename)
        target_filename = orig_filename

        # Якщо агроном завантажує карту з ім'ям, яке вже є — авто-додаємо мітку часу
        if os.path.exists(os.path.join(TASKMAPS_DIR, target_filename)):
            timestamp = datetime.datetime.now().strftime("%d%m%y_%H%M")
            target_filename = f"{name_part}_{timestamp}{ext_part}"

        final_path = os.path.join(TASKMAPS_DIR, target_filename)

        try:
            # Тимчасово зберігаємо для валідації Geopandas
            temp_path = os.path.join(TASKMAPS_DIR, f"temp_{target_filename}")
            file.save(temp_path)

            # Перевіряємо силами Geopandas, чи всередині валідний Shapefile
            uri = f"zip://{temp_path.replace(os.sep, '/')}"
            test_df = gpd.read_file(uri)

            # Перевіряємо наявність вашої обов'язкової робочої колонки 'rate'
            if "rate" not in test_df.columns:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Валідація провалена: відсутня колонка 'rate' у Shapefile!",
                        }
                    ),
                    422,
                )

            # Якщо все відмінно — перейменовуємо в чистий фінальний файл
            os.rename(temp_path, final_path)
            print(
                f"[eMMC TaskMap] Успішно завантажено та перевірено карту: {target_filename}"
            )
            return jsonify({"status": "ok", "filename": target_filename})

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Помилка структури Shapefile: {str(e)}",
                    }
                ),
                400,
            )

    # --- 3. ПАРСИНГ ТА ГЕНЕРАЦІЯ ДАНИХ ДЛЯ ЖИВОГО ПРЕВ'Ю КАРТИ ---
    @app.route("/api/taskmaps/preview", methods=["GET"])
    def get_taskmap_preview():
        filename = request.args.get("filename")
        if not filename:
            return (
                jsonify({"status": "error", "message": "Не вказано ім'я файлу карти"}),
                400,
            )

        file_path = os.path.join(TASKMAPS_DIR, filename)
        if not os.path.exists(file_path):
            return (
                jsonify(
                    {"status": "error", "message": "Файл карти не знайдено на eMMC"}
                ),
                404,
            )

        try:
            # Зчитуємо Shapefile безпосередньо з потрібного ZIP-архіву
            uri = f"zip://{file_path.replace(os.sep, '/')}"
            rate_data = gpd.read_file(uri)

            if rate_data.empty:
                return jsonify({"status": "error", "message": "Карта порожня"}), 400

            polygons_list = []
            rate_column = "rate"  # Стандарт вашого Shapefile

            # =======================================================================
            # ВАША РІДНА ЛОГІКА ПАРСИНГУ КООРДИНАТ ДЛЯ CANVAS (ОДИН В ОДИН)
            # =======================================================================
            for _, row in rate_data.iterrows():
                try:
                    raw_val = float(row[rate_column])
                except (ValueError, TypeError):
                    raw_val = float("nan")

                # Якщо NaN — ставимо 0.0, інакше — залишаємо оригінальне значення
                rate_val = 0.0 if math.isnan(raw_val) else raw_val
                geom = row["geometry"]

                if geom is None:
                    continue
                elif geom.geom_type == "Polygon":
                    coords = list(geom.exterior.coords)
                elif geom.geom_type == "MultiPolygon":
                    coords = []
                    for poly in geom.geoms:
                        coords.extend(list(poly.exterior.coords))
                else:
                    continue  # Пропускаємо точки та лінії

                # Зміна порядку з (Lon, Lat) на [Lat, Lon] для вашого Canvas
                formatted_coords = [[pt[1], pt[0]] for pt in coords]
                polygons_list.append({"rate": rate_val, "points": formatted_coords})

            # Безпечний розрахунок мінімуму та максимуму для колірного градієнта
            clean_rates = rate_data[rate_column].dropna()
            cfg = config_manager.load_config()
            rate_default = cfg.get("VRA_RATE_DEFAULT", 0.0)

            if not clean_rates.empty:
                min_rate = float(clean_rates.min())
                max_rate = float(clean_rates.max())
            else:
                min_rate = 0.0
                max_rate = rate_default

            # Захист від однакових значень (щоб не було ділення на 0 на фронтенді)
            if min_rate == max_rate:
                min_rate = max_rate * 0.8 if max_rate != 0 else -1.0

            # Повертаємо чистий JSON-пакет для інтерактивного вікна прев'ю
            return jsonify(
                {
                    "status": "success",
                    "filename": filename,
                    "min_rate": min_rate,
                    "max_rate": max_rate,
                    "rate_default": rate_default,
                    "polygons": polygons_list,
                }
            )

        except Exception as e:
            print(f"[TaskMap Preview Error] Збій парсингу {filename}: {e}")
            return (
                jsonify(
                    {"status": "error", "message": f"Помилка читання картки: {str(e)}"}
                ),
                500,
            )

    # --- 4. ПОВНЕ ВИДАЛЕННЯ ФАЙЛУ КАРТИ З НАКОПИЧУВАЧА ---
    @app.route("/api/taskmaps/delete", methods=["POST"])
    def delete_taskmap_file():
        try:
            req_data = request.get_json() or {}
            filename = req_data.get("filename")
            if not filename:
                return (
                    jsonify({"status": "error", "message": "Не вказано ім'я файлу"}),
                    400,
                )

            fpath = os.path.join(TASKMAPS_DIR, filename)
            if os.path.exists(fpath):
                os.remove(fpath)
                print(f"[eMMC TaskMap] Файл карти {filename} успішно видалено з диска.")
                return jsonify({"status": "success"})
            else:
                return (
                    jsonify({"status": "error", "message": "Файл не знайдено на eMMC"}),
                    404,
                )

        except Exception as e:
            print(f"[TaskMap Delete Error] Збій видалення з диска: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    @app.route("/api/taskmaps/map", methods=["GET"]) # Загрузка на ФРОНТЭНД
    def get_vra_map_1():
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
            if (
                not hasattr(app, "_vra_polygons_cache")
                or getattr(app, "_last_polys_file", None) != active_file
            ):
                #upload_dir = os.path.join(os.getcwd(), "geodata")
                upload_dir = os.path.join(os.getcwd(), "taskmaps")
                file_path = os.path.join(upload_dir, active_file)

                if not os.path.exists(file_path):
                    return jsonify({"status": "no_map"})

                # Зчитуємо Shapefile силами процесу веб-сервера
                uri = f"zip://{file_path.replace(os.sep, '/')}"
                rate_data = gpd.read_file(uri)

                if rate_data.empty:
                    return jsonify({"status": "no_map"})

                polygons_list = []
                rate_column = "rate"  # Стандарт вашого Shapefile

                # =======================================================================
                # ВАША РІДНА ЛОГІКА ПАРСИНГУ КООРДИНАТ ДЛЯ CANVAS (ОДИН В ОДИН)
                # =======================================================================
                for _, row in rate_data.iterrows():
                    try:
                        raw_val = float(row[rate_column])
                    except (ValueError, TypeError):
                        raw_val = float("nan")

                    # Фікс №1: Якщо NaN — ставимо 0.0, інакше — залишаємо значення
                    rate_val = 0.0 if math.isnan(raw_val) else raw_val
                    geom = row["geometry"]

                    if geom is None:
                        continue
                    elif geom.geom_type == "Polygon":
                        coords = list(geom.exterior.coords)
                    elif geom.geom_type == "MultiPolygon":
                        coords = []
                        for poly in geom.geoms:
                            coords.extend(list(poly.exterior.coords))
                    else:
                        continue  # Пропускаємо лінії або точки

                    # Зміна порядку з (Lon, Lat) на [Lat, Lon] для Canvas
                    formatted_coords = [[pt[1], pt[0]] for pt in coords]

                    polygons_list.append({"rate": rate_val, "points": formatted_coords})

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
                    "polygons": polygons_list,
                }
                app._last_polys_file = active_file

            # 3. Віддаємо JavaScript-планшету готовий валідний JSON-пакет із кешу ОЗУ
            return jsonify(app._vra_polygons_cache)

        except Exception as e:
            print(f"[Web VRA Map Parser Error]: {e}")
            return jsonify({"status": "error", "message": str(e)})

    # endregion

    # region 🌾 НОВИЙ ХАБ СЕСІЙ ПОЛІВ (HUB_SESSION)
    # =======================================================================
    # СЕКЦІЯ НОВИЙ ХАБ СЕСІЙ ПОЛІВ (HUB_SESSION)
    # =======================================================================
    # --- 1. ОТРИМАННЯ СПИСКУ ПОЛІВ З АВТО-ПІДТЯГУВАННЯМ ПАРАМЕТРІВ ---
    # Роут для відкриття сторінки самого Навігаційного Хабу
    @app.route("/")
    # def view_navigation_hub_1():
    #     cfg = config_manager.load_config()
    #     return render_template("index.html", cfg=cfg)
    #     #return render_template("index.html")
    # @app.route("/hub")
    # def view_navigation_hub():
    #     return render_template("hub.html")

    @app.route("/api/hub_session/fields", methods=["GET"])
    def api_get_hub_fields():
        try:
            # Використовуємо твою системну директорію дампів полів
            fields_dir = dump_manager.DUMP_DIR
            if not os.path.exists(fields_dir):
                return jsonify({"status": "ok", "fields": []})

            fields_list = []
            # Шукаємо всі індивідуальні JSON конфіги полів
            for fname in os.listdir(fields_dir):
                if fname.endswith(".json") and fname != "current_session.json":
                    fpath = os.path.join(fields_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            f_data = json.load(f)

                        # Перевіряємо, чи є в полі лінія АВ
                        has_ab = False
                        if f_data.get("point_a") and f_data.get("point_b"):
                            has_ab = True

                        fields_list.append(
                            {
                                "id": fname.replace(".json", ""),
                                "name": fname.replace(
                                    ".json", ""
                                ),  # Ім'я файлу для плитки
                                "area": float(f_data.get("area", 0.0)),
                                "has_line_ab": has_ab,
                                # Наші нові мультипрофільні прив'язки
                                "active_implement_id": f_data.get(
                                    "active_implement_id", ""
                                ),
                                "active_taskmap_file": f_data.get(
                                    "active_vra_file", ""
                                ),
                                "target_rate_default": float(
                                    f_data.get("target_rate_default", 200.0)
                                ),
                                # Зчитуємо мітку часу для правильного сортування
                                "mtime": os.stat(fpath).st_mtime,
                            }
                        )
                    except Exception as e:
                        print(f"[Hub Error] Не вдалося прочитати поле {fname}: {e}")

            # СОРТУВАННЯ: Останнє поле, де працював трактор — завжди перше під пальцем!
            fields_list.sort(key=lambda x: x["mtime"], reverse=True)
            return jsonify({"status": "ok", "fields": fields_list})

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- 2. СТВОРЕННЯ НОВОГО ЧИСТОГО ПОЛЯ З ТАЧ-КЛАВІАТУРИ ---
    @app.route("/api/hub_session/create_field", methods=["POST"])
    def api_create_hub_field():
        try:
            req_data = request.get_json() or {}
            raw_name = req_data.get("name", "").strip()

            if not raw_name:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Назва поля не може бути порожньою!",
                        }
                    ),
                    400,
                )

            # Очищаємо назву поля від пробілів та небезпечних символів
            filename_cleaned = raw_name.replace(" ", "_")
            safe_name = re.sub(r"[^a-zA-Z0-9_А-Яа-яІіЄєЇїҐґ.-]", "", filename_cleaned)

            if not safe_name:
                safe_name = f"Field_{int(time.time())}"

            fpath = os.path.join(dump_manager.DUMP_DIR, f"{safe_name}.json")

            # Захист: якщо таке поле вже є, не затираємо його, а повертаємо попередження
            if os.path.exists(fpath):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Поле з назвою '{safe_name}' вже існує на eMMC!",
                        }
                    ),
                    422,
                )

            # Формуємо чисту структуру нового поля під розширений мультипрофіль
            new_field_data = {
                "timestamp": time.time(),
                "area": 0.0,
                "point_a": None,
                "point_b": None,
                "guidance_error": 0.0,
                "active_implement_id": "",  # Поки без знаряддя
                "active_vra_file": "",  # Поки ручний вилив
                "target_rate_default": 200.0,  # Стандартна дефолтна норма
            }

            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(new_field_data, f, ensure_ascii=False, indent=4)

            print(f"[Hub eMMC] Створено нове чисте поле: {safe_name}.json")
            return jsonify({"status": "ok", "id": safe_name})

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- 3. ЗАЛІЗОБЕТОННИЙ ЗАПУСК СТАРТУ (РУБІЖ ЗАХИСТУ №1) ---
    @app.route("/api/hub_session/start", methods=["POST"])
    def api_start_hub_session():
        try:
            req_data = request.get_json() or {}
            field_id = req_data.get("field_id")
            impl_id = req_data.get("implement_id")
            taskmap_file = req_data.get("taskmap_file")
            target_rate = req_data.get("target_rate", 200.0)
            action_type = req_data.get(
                "action_type", "run"
            )  # <-- Наш новий параметр (run або save)

            if not field_id:
                return (
                    jsonify(
                        {"status": "error", "message": "Не вибрано поле для запуску!"}
                    ),
                    400,
                )

            # Перевірка 1: Чи існує саме поле
            field_path = os.path.join(dump_manager.DUMP_DIR, f"{field_id}.json")
            if not os.path.exists(field_path):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Помилка: Файл самого поля зник з eMMC!",
                        }
                    ),
                    404,
                )

            # Перевірка 2: ЗАХИСТ ВІД ВИДАЛЕННЯ ЗНАРЯДДЯ (Оприскувача)
            if impl_id:
                impl_path = os.path.join(os.getcwd(), "implements", f"{impl_id}.json")
                if not os.path.exists(impl_path):
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": "🚨 АВАРІЯ: Вибраний профіль обприскувача/сівалки був видалений з пам'яті! Будь ласка, виберіть інше знаряддя.",
                            }
                        ),
                        422,
                    )

            # Перевірка 3: ЗАХИСТ ВІД ВИДАЛЕННЯ КАРТИ ЗАВДАНЬ VRA
            if taskmap_file:
                taskmap_path = os.path.join(os.getcwd(), "taskmaps", taskmap_file)
                if not os.path.exists(taskmap_path):
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": f"🚨 АВАРІЯ: Файл карти VRA '{taskmap_file}' не знайдено в папці taskmaps! Можливо, витягли флешку.",
                            }
                        ),
                        422,
                    )

            # СИНХРОНІЗАЦІЯ: Оновлюємо внутрішній JSON поля на eMMC, щоб воно назавжди запам'ятало налаштування
            try:
                with open(field_path, "r", encoding="utf-8") as f:
                    field_data = json.load(f)

                field_data["active_implement_id"] = impl_id if impl_id else ""
                field_data["active_vra_file"] = taskmap_file if taskmap_file else ""
                field_data["target_rate_default"] = float(target_rate)

                with open(field_path, "w", encoding="utf-8") as f:
                    json.dump(field_data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[Hub Error] Не вдалося оновити прив'язки в JSON поля: {e}")

            # ДИФЕРЕНЦІАЦІЯ ДІЇ ЗАЛЕЖНО ВІД ТИПУ ВИКЛИКУ
            if action_type == "run":
                # ПОВНИЙ ЗАПУСК: Надсилаємо команду в ядро математики для ініціалізації поля та скидання ОЗУ
                cmd_queue.put(
                    {
                        "cmd": "load_hub_session",
                        "filename": f"{field_id}.json",
                        "implement_id": impl_id,
                        "taskmap_file": taskmap_file,
                        "target_rate": float(target_rate),
                    }
                )
                print(
                    f"[Hub Session] РЕЖИМ RUN: Команду load_hub_session відправлено в ядро для поля '{field_id}'"
                )
            else:
                # РЕЖИМ SAVE: Просто зафіксували зміни на диску eMMC, ядро поки не смикаємо (не ламаємо поточну роботу)
                print(
                    f"[Hub Session] РЕЖИМ SAVE: Налаштування для поля '{field_id}' успішно оновлено на eMMC.",
                    flush=True,
                )
            
            return jsonify({"status": "ok"})

        except Exception as e:
            print(f"[Hub Start Error] Глобальний збій запуску сесії: {e}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Внутрішня помилка сервера: {str(e)}",
                    }
                ),
                500,
            )

    # @app.route('/api/hub_session/start', methods=['POST'])
    # def api_start_hub_session():
    #     try:
    #         req_data = request.get_json() or {}
    #         field_id = req_data.get("field_id")
    #         impl_id = req_data.get("implement_id")
    #         taskmap_file = req_data.get("taskmap_file")
    #         target_rate = req_data.get("target_rate", 200.0)

    #         if not field_id:
    #             return jsonify({"status": "error", "message": "Не вибрано поле для запуску!"}), 400

    #         # Перевірка 1: Чи існує саме поле
    #         field_path = os.path.join(dump_manager.DUMP_DIR, f"{field_id}.json")
    #         if not os.path.exists(field_path):
    #             return jsonify({"status": "error", "message": "Помилка: Файл самого поля зник з eMMC!"}), 404

    #         # Перевірка 2: ЗАХИСТ ВІД ВИДАЛЕННЯ ЗНАРЯДДЯ (Оприскувача)
    #         if impl_id:
    #             impl_path = os.path.join(os.getcwd(), "implements", f"{impl_id}.json")
    #             if not os.path.exists(impl_path):
    #                 return jsonify({
    #                     "status": "error",
    #                     "message": "🚨 АВАРІЯ: Вибраний профіль обприскувача/сівалки був видалений з пам'яті! Будь ласка, виберіть інше знаряддя."
    #                 }), 422

    #         # Перевірка 3: ЗАХИСТ ВІД ВИДАЛЕННЯ КАРТИ ЗАВДАНЬ VRA
    #         if taskmap_file:
    #             taskmap_path = os.path.join(os.getcwd(), "taskmaps", taskmap_file)
    #             if not os.path.exists(taskmap_path):
    #                 return jsonify({
    #                     "status": "error",
    #                     "message": f"🚨 АВАРІЯ: Файл карти VRA '{taskmap_file}' не знайдено в папці taskmaps! Можливо, витягли флешку."
    #                 }), 422

    #         # СИНХРОНІЗАЦІЯ: Оновлюємо внутрішній JSON поля на eMMC, щоб воно назавжди запам'ятало налаштування
    #         try:
    #             with open(field_path, "r", encoding="utf-8") as f:
    #                 field_data = json.load(f)

    #             field_data["active_implement_id"] = impl_id if impl_id else ""
    #             field_data["active_taskmap_file"] = taskmap_file if taskmap_file else ""
    #             field_data["target_rate_default"] = float(target_rate)

    #             with open(field_path, "w", encoding="utf-8") as f:
    #                 json.dump(field_data, f, ensure_ascii=False, indent=4)
    #         except Exception as e:
    #             print(f"[Hub Error] Не вдалося оновити прив'язки в JSON поля: {e}")

    #         # НАДСИЛАННЯ КОМАНДИ В ЯДРО МАТЕМАТИКИ (Через твою чергу команд c_queue/cmd_queue)
    #         # Використовуємо нашу нову, повністю паралельну команду, про яку домовилися
    #         cmd_queue.put({
    #             "cmd": "load_hub_session",
    #             "filename": f"{field_id}.json",
    #             "implement_id": impl_id,
    #             "taskmap_file": taskmap_file,
    #             "target_rate": float(target_rate)
    #         })

    #         print(f"[Hub Session] Команду load_hub_session успішно відправлено в ядро для поля '{field_id}'")
    #         return jsonify({"status": "ok"})

    #     except Exception as e:
    #         print(f"[Hub Start Error] Глобальний збій запуску сесії: {e}")
    #         return jsonify({"status": "error", "message": f"Внутрішня помилка сервера: {str(e)}"}), 500
    # endregion

    # region 🕵️‍♂️ ІНЖЕНЕРНИЙ ІНСПЕКТОР СТАНУ ОЗУ (STATE INSPECTOR)
    # Оголошуємо пустий словник при старті сервера
    LIVE_SHARED_STATE_CACHE = {}

    @app.route("/api/system/state_inspector", methods=["GET"])
    def api_system_state_inspector():
        try:
            global LIVE_SHARED_STATE_CACHE

            # 1. Зчитуємо свіжий системний конфіг заліза з диска eMMC
            cfg = config_manager.load_config()

            # Створюємо фінальний об'єднаний словник діагностики
            merged_dump = {}

            # 2. Додаємо налаштування з config.json (CFG_)
            if cfg and isinstance(cfg, dict):
                for cfg_key, cfg_val in cfg.items():
                    # Захист: пропускаємо великі масиви (наприклад, дефолтні SECTION_WIDTHS)
                    # щоб не забивати таблицю довгими списками координат
                    if isinstance(cfg_val, (list, dict, tuple)):
                        continue
                    merged_dump[f"CFG_{cfg_key}"] = cfg_val

            # 3. Додаємо "живі" змінні з ОЗУ SharedState (RAM_)
            if LIVE_SHARED_STATE_CACHE:
                for ram_key, ram_val in LIVE_SHARED_STATE_CACHE.items():
                    merged_dump[f"RAM_{ram_key}"] = ram_val

            # Якщо черга ще пуста і ядро не встигло кинути дані
            if not merged_dump:
                return jsonify(
                    {
                        "status": "warning",
                        "message": "Чекаємо дані з ОЗУ... Переконайтеся, що головний цикл main.py запущено.",
                    }
                )

            # СОРТУВАННЯ: Розставляємо всі імена від А до Я для зручного пошуку пальцем
            # Тепер у тебе спочатку красиво підуть всі CFG_, а потім всі RAM_
            sorted_dump = dict(sorted(merged_dump.items()))

            return jsonify(
                {
                    "status": "ok",
                    "class_name": "SharedState (RAM) + config.json (Disk)",
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                    "variables": sorted_dump,
                }
            )

        except Exception as e:
            print(f"[State Inspector Error] Збій склеювання RAM + CFG: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # endregion

    # =======================================================================

    # @app.route("/map")
    # def index():
    #     cfg = config_manager.load_config()
    #     return render_template("board.html", cfg=cfg)

    # #     return render_template("hub.html", cfg=cfg)

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
                "ux": WEB_CACHE["ux"],  # Заглушка, фронтенд использует pos
                "uy": WEB_CACHE["uy"],
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

    # @app.route("/settings")
    # def settings():
    #     cfg = config_manager.load_config()
    #     widths_str = ",".join(map(str, cfg["SECTION_WIDTHS"]))
    #     return render_template("settings.html", cfg=cfg, widths=widths_str)

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
        raw_filename = os.path.basename(data.get("filename", ""))

        if not raw_filename:
            return {"error": "Не вказано ім'я файлу"}, 400

        # --- ЗАХИСТ ВІД РОЗШИРЕНЬ ---
        # Витягуємо чисте базове ім'я поля (наприклад, з "field_1.json" робимо "field_1")
        field_base_name = (
            raw_filename.replace(".json", "")
            .replace(".txt", "")
            .replace(".wkb", "")
            .strip()
        )

        # Формуємо шляхи до всієї трійки файлів цього поля
        target_json = os.path.join(dump_manager.DUMP_DIR, f"{field_base_name}.json")
        target_txt = os.path.join(dump_manager.DUMP_DIR, f"{field_base_name}.txt")
        target_wkb = os.path.join(dump_manager.DUMP_DIR, f"{field_base_name}.wkb")

        deleted_any = False
        errors = []

        # Зачищаємо всі три хвости на eMMC
        for file_path in [target_json, target_txt, target_wkb]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_any = True
                except Exception as e:
                    errors.append(
                        f"Не вдалося видалити {os.path.basename(file_path)}: {e}"
                    )

        if deleted_any:
            print(
                f"[Web_Server] Повне видалення архівного поля '{field_base_name}' (JSON+TXT+WKB) виконано."
            )
            return {
                "status": "success",
                "removed_field": field_base_name,
                "errors": errors,
            }, 200

        return {"error": f"Файли поля '{field_base_name}' не знайдено на диску"}, 404

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

    # @app.route("/fields")
    # def fields_page():
    #     """Показує сторінку файлового менеджера полів"""
    #     return render_template("fields.html")

    @app.route("/api/files", methods=["GET"])
    def list_files():
        """Повертає список збережених JSON-файлів полів із внутрішніми метаданими для UI хабу"""
        import time
        import json

        # Ініціалізуємо список на самому початку, щоб він ЗАВЖДИ був визначений
        files_list = []

        if os.path.exists(dump_manager.DUMP_DIR):
            for fname in os.listdir(dump_manager.DUMP_DIR):
                # Ігноруємо поточну сесію та тимчасові файли
                if fname.endswith(".json") and fname != "current_session.json":
                    fpath = os.path.join(dump_manager.DUMP_DIR, fname)
                    try:
                        stat = os.stat(fpath)

                        # Дефолтні значення для метаданих
                        area = 0.0
                        has_ab = False
                        active_vra = None

                        # Безпечно читаємо вміст JSON-файлу поля
                        with open(fpath, "r", encoding="utf-8") as f:
                            field_data = json.load(f)
                            area = field_data.get("area", 0.0)
                            active_vra = field_data.get(
                                "active_vra_file", None
                            )  # Виправлено на None

                            # Перевіряємо точки лінії AB
                            pt_a = field_data.get("point_a")
                            pt_b = field_data.get("point_b")
                            if pt_a and pt_b:
                                has_ab = True

                    except Exception as e:
                        # Якщо файл порожній або пошкоджений, беремо базовий stat
                        print(
                            f"[Hub Router Error] Не вдалося зчитати метадані {fname}: {e}"
                        )
                        stat = os.stat(fpath)

                    # Додаємо об'єкт до списку
                    files_list.append(
                        {
                            "name": fname,
                            "size": round(stat.st_size / 1024, 1),
                            "date": time.strftime(
                                "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)
                            ),
                            "area": round(area, 4),
                            "has_ab": has_ab,
                            "active_vra": active_vra,
                        }
                    )

        # Тепер сортування відпрацює ідеально, бо список гарантовано існує
        files_list.sort(key=lambda x: x["date"], reverse=True)
        return jsonify(files_list)

    @app.route("/api/files_1", methods=["GET"])
    def list_files_1():
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

    # region СТАРЫЙ СЕКЦІЯ МЕНЕДЖЕРА ЗНАРЯДЬ (IMPLEMENT MANAGER API)
    # =======================================================================
    # СЕКЦІЯ МЕНЕДЖЕРА ЗНАРЯДЬ (IMPLEMENT MANAGER API)
    # =======================================================================
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
            if (
                not hasattr(app, "_vra_polygons_cache")
                or getattr(app, "_last_polys_file", None) != active_file
            ):
                upload_dir = os.path.join(os.getcwd(), "geodata")
                #upload_dir = os.path.join(os.getcwd(), "taskmaps")
                file_path = os.path.join(upload_dir, active_file)

                if not os.path.exists(file_path):
                    return jsonify({"status": "no_map"})

                # Зчитуємо Shapefile силами процесу веб-сервера
                uri = f"zip://{file_path.replace(os.sep, '/')}"
                rate_data = gpd.read_file(uri)

                if rate_data.empty:
                    return jsonify({"status": "no_map"})

                polygons_list = []
                rate_column = "rate"  # Стандарт вашого Shapefile

                # =======================================================================
                # ВАША РІДНА ЛОГІКА ПАРСИНГУ КООРДИНАТ ДЛЯ CANVAS (ОДИН В ОДИН)
                # =======================================================================
                for _, row in rate_data.iterrows():
                    try:
                        raw_val = float(row[rate_column])
                    except (ValueError, TypeError):
                        raw_val = float("nan")

                    # Фікс №1: Якщо NaN — ставимо 0.0, інакше — залишаємо значення
                    rate_val = 0.0 if math.isnan(raw_val) else raw_val
                    geom = row["geometry"]

                    if geom is None:
                        continue
                    elif geom.geom_type == "Polygon":
                        coords = list(geom.exterior.coords)
                    elif geom.geom_type == "MultiPolygon":
                        coords = []
                        for poly in geom.geoms:
                            coords.extend(list(poly.exterior.coords))
                    else:
                        continue  # Пропускаємо лінії або точки

                    # Зміна порядку з (Lon, Lat) на [Lat, Lon] для Canvas
                    formatted_coords = [[pt[1], pt[0]] for pt in coords]

                    polygons_list.append({"rate": rate_val, "points": formatted_coords})

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
                    "polygons": polygons_list,
                }
                app._last_polys_file = active_file

            # 3. Віддаємо JavaScript-планшету готовий валідний JSON-пакет із кешу ОЗУ
            return jsonify(app._vra_polygons_cache)

        except Exception as e:
            print(f"[Web VRA Map Parser Error]: {e}")
            return jsonify({"status": "error", "message": str(e)})

    # @app.route("/vra_control")
    # def vra_control_page():
    #     return render_template("vra_maps.html")

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

    # endregion

    return app
