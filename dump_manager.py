# =======================================================================
# dump_manager.py --- РОЗУМНЕ ВІДНОВЛЕННЯ СЕСІЇ ТА ЗАХИСТ eMMC
# =======================================================================
import json
import os
import time
from pathlib import Path
from pprint import pprint
import struct
from shapely import wkb
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

# ЖОРСТКА КОРЕНЕВА ПРИВ'ЯЗКА ДО ПАПКИ СКРИПТА
BASE_SYS_DIR = os.path.dirname(os.path.abspath(__file__)) # папка SYS
DUMP_DIR = os.path.join(BASE_SYS_DIR, "fields") # СТРОГО SYS/fields/

CURRENT_SESSION_FILE = os.path.join(DUMP_DIR, "current_session.json")
CURRENT_TRACK_FILE = os.path.join(DUMP_DIR, "current_session.txt")
STATUS_FILE = os.path.join(DUMP_DIR, "session_status.txt")



def set_session_active():
    """Ставить маркер, що сесія активна і її треба відновлювати при перезапуску"""
    try:
        os.makedirs(DUMP_DIR, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write("ACTIVE")
    except:
        pass

def is_session_active():
    """Перевіряє, чи була активна сесія до перезавантаження"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return f.read().strip() == "ACTIVE"
        except:
            return False
    return False

def save_lightweight_json(state, sc, filename=None):
    """Зберігає ТІЛЬКИ налаштування (лінії А-В, гектари). Запис атомарний."""
    #print(f"[RESET] " + "="*58)
    print(f"[DumpManager] save_lightweight_json")
    print(f"[DumpManager] Зберігає ТІЛЬКИ налаштування (лінії А-В, гектари). Запис атомарний.")
    os.makedirs(DUMP_DIR, exist_ok=True)
    target_file = filename if filename else CURRENT_SESSION_FILE

    try:
        payload = {
            "timestamp": time.time(),
            "area": getattr(state, "area", 0.0),
            "point_a": getattr(state, "point_a", None),
            "point_b": getattr(state, "point_b", None),
            "guidance_error": getattr(state, "guidance_error", 0.0),
            # "active_vra_file": getattr(sc, "ACTIVE_TASKMAP_FILE", ""),
            # "active_implement_id": getattr(sc, "ACTIVE_IMPLEMENT_ID", ""),
            # "target_rate_default": getattr(sc, "TARGET_RATE_DEFAULT", 0.0),
            
            # Пряме звернення до вкладеного словника
            "active_vra_file": getattr(sc, "cfg", {}).get("ACTIVE_TASKMAP_FILE", ""),
            "active_implement_id": getattr(sc, "cfg", {}).get("ACTIVE_IMPLEMENT_ID", ""),
            "target_rate_default": getattr(sc, "cfg", {}).get("VRA_RATE_DEFAULT", 0.0),
        }
        
        # print("save_lightweight_json:\n")
        # print(f"ACTIVE_TASKMAP_FILE: {sc.__dict__['cfg']['ACTIVE_TASKMAP_FILE']}")
        # print(f"ACTIVE_IMPLEMENT_ID: {sc.__dict__['cfg']['ACTIVE_IMPLEMENT_ID']}")
        # print(f"VRA_RATE_DEFAULT: {sc.__dict__['cfg']['VRA_RATE_DEFAULT']}")


        temp_file = target_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, target_file)

        # Активуємо маркер, бо пішли перші збереження
        if not filename:
            set_session_active()
        return True
    except Exception as e:
        print(f"[DumpManager] Помилка запису JSON: {e}")
        return False

def append_batch_to_track_file(points_batch, filename=None):
    """ЗАЛПОВИЙ ЗАПИС ТРЕКУ: Зберігає 5 елементів точки (Координати + Секції + Ширини)"""
    if not points_batch:
        return True

    os.makedirs(DUMP_DIR, exist_ok=True)
    target_track = filename.replace(".json", ".txt") if filename else CURRENT_TRACK_FILE

    try:
        lines = []
        for p in points_batch:
            # p тепер це [lat, lon, hdg, states_str, widths_str]
            lines.append(f"{p[0]},{p[1]:.8f},{p[2]:.8f},{p[3]:.2f},{p[4]},{p[5]}\n")

        with open(target_track, "a", encoding="utf-8") as f:
            f.writelines(lines)

        if not filename:
            set_session_active()
        return True
    except Exception as e:
        print(f"[DumpManager] Помилка пакетного запису 5-ел. треку: {e}")
        return False

def load_track_history(filename=None):
    """Покроково вичитує трек і повністю відновлює 5-елементну структуру для Canvas вебу"""
    target_track = filename.replace(".json", ".txt") if filename else CURRENT_TRACK_FILE
    restored_track = []
    print(f"[DumpManager] Покроково вичитує трек і повністю відновлює ")
    print(filename)
    if os.path.exists(target_track):
        try:
            with open(target_track, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            # Розбиваємо рядок на 5 частин
                            chunk_key,lat_s, lon_s, hdg_s, states_s, widths_s = line.split(",")

                            # 1. Відновлюємо масив станів секцій pt[3]
                            boolean_states = [
                                char == "1" for char in states_s.split("-")
                            ]

                            # 2. Відновлюємо масив ширин кожної секції pt[4]
                            float_widths = [float(w) for w in widths_s.split("-")]

                            # Збираємо ПОВНОЦІННУ точку для JS-скрипту updateFieldMap
                            restored_track.append(
                                [
                                    chunk_key,
                                    float(lat_s),
                                    float(lon_s),
                                    float(hdg_s),
                                    boolean_states,
                                    float_widths,
                                ]
                            )
                        except Exception as parse_err:
                            continue
        except Exception as e:
            print(f"[DumpManager] Помилка читання текстового треку: {e}")

    return restored_track

def clear_current_dump():
    """Повне очищення сесії та скидання маркера в NEW (при натисканні RESET)"""
    for path in [CURRENT_SESSION_FILE, CURRENT_TRACK_FILE, STATUS_FILE]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write("NEW")
    except:
        pass

def load_session_dump(state, sc, filename=None):
    """
    НЕВБИВАНЕ ЗАВАНТАЖЕННЯ СЕСІЇ:
    Намагається прочитати JSON, але якщо його немає — все одно 
    гарантовано завантажує текстовий трек .txt для вебу!
    """
    target_file = filename if filename else CURRENT_SESSION_FILE
    print(f"[DumpManager] Спроба завантаження метаданих з: {target_file}")
    
    # 1. Намагаємося прочитати легкі налаштування з JSON
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                dump = json.load(f)
                
            state.area = dump.get("area", 0.0)
            state.point_a = dump.get("point_a")
            state.point_b = dump.get("point_b")
            state.guidance_error = dump.get("guidance_error", 0.0)
            state.active_vra_file = dump.get("active_vra_file", None)
            print("[DumpManager] Налаштування поля та лінії А-В успішно відновлено.")
        except Exception as json_err:
            print(f"[DumpManager] Файл JSON знайдено, але сталася помилка читання: {json_err}")
    else:
        print("[DumpManager] Файл налаштувань .json відсутній (перший проїзд). Працюємо за замовчуванням.")

    # Фіксуємо чисте ім'я для інтерфейсу (беремо ліву частину кортежу)
    state.current_file = os.path.splitext(os.path.basename(target_file))[0]

    # 2. ГАРАНТОВАНО ВИКЛИКАЄМО ЧИТАННЯ ТЕКСТОВОГО ТРЕКУ ДЛЯ ВЕБУ
    # Навіть якщо JSON немає, файл .txt з точками вже точно на диску!
    try:
        restored_track = load_track_history(filename)
        
        # Накатуємо відновлений 5-елементний трек в ОЗУ системи
        state.path_history = restored_track
        sc.path_history = state.path_history  # Синхронізуємо з двигуном штанги
        
        print(f"[DumpManager] УСПІХ: Траєкторія відновлена. Зчитано {len(restored_track)} точок для Canvas вебу.")
        return True
    except Exception as track_err:
        print(f"[DumpManager] Критична помилка відновлення треку: {track_err}")
        return False
    
def load_wkb_geometry_safely_old(filepath):
    """
    Безопасный потоковый парсер "слоеного пирога" WKB.
    Выкачивает ВСЕ сохраненные MultiPolygon'ы до конца файла.
    """
    import os
    from shapely import wkb
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union

    print(f"[WKB_PARSER] [START] Попытка чтения геометрии из: {filepath}")
    
    if not os.path.exists(filepath):
        print(f"[WKB_PARSER] [WARN] Файл не найден: {filepath}. Возвращаем пустой MultiPolygon.")
        return MultiPolygon()

    # Проверяем, не пустой ли файл на диске
    file_size = os.path.getsize(filepath)
    print(f"[WKB_PARSER] [INFO] Размер файла на диске: {file_size} байт.")
    if file_size == 0:
        print("[WKB_PARSER] [WARN] Файл имеет нулевой размер. Возвращаем пустой MultiPolygon.")
        return MultiPolygon()

    all_chunks = []
    chunks_count = 0

    try:
        with open(filepath, "rb") as f:
            while True:
                try:
                    # Читаем очередной блок геометрии
                    chunk = wkb.load(f)
                    if chunk and not chunk.is_empty:
                        all_chunks.append(chunk)
                        chunks_count += 1
                        # Логируем каждые 50 блоков, чтобы не забивать консоль, но видеть прогресс
                        if chunks_count % 50 == 0:
                            print(f"[WKB_PARSER] [PROGRESS] Успешно прочитано блоков: {chunks_count}...")
                except EOFError:
                    print(f"[WKB_PARSER] [SUCCESS] Достигнут конец файла (EOF). Всего блоков найдено: {chunks_count}")
                    break
                except Exception as chunk_err:
                    # Если один блок побит, логируем и пытаемся читать дальше, если это возможно
                    print(f"[WKB_PARSER] [ERROR] Сбой чтения блока №{chunks_count + 1}: {chunk_err}")
                    break # Прерываем, так как битый бинарный поток обычно не восстановить в рамках одной сессии
    except Exception as file_err:
        print(f"[WKB_PARSER] [CRITICAL] Не удалось открыть или прочитать файл: {file_err}")
        return MultiPolygon()

    # Сшиваем все пачки полигонов в один монолит
    if all_chunks:
        print(f"[WKB_PARSER] [UNION] Запуск объединения (unary_union) для {len(all_chunks)} элементов...")
        try:
            merged_geometry = unary_union(all_chunks)
            print(f"[WKB_PARSER] [UNION_SUCCESS] Геометрия успешно объединена в ОЗУ. Тип: {merged_geometry.geom_type}")
            return merged_geometry
        except Exception as union_err:
            print(f"[WKB_PARSER] [UNION_CRITICAL] Ошибка сшивания shapely полигонов: {union_err}")
            return MultiPolygon()
    else:
        print("[WKB_PARSER] [INFO] Валидных геометрических блоков в файле не обнаружено.")
        return MultiPolygon()

def load_wkb_geometry_safely(filepath):
    """
    Безпечний потоковий парсер блоків фіксованої довжини.
    Зчитує геометрію покроково. Гарантовано повертає MultiPolygon.
    Якщо файл частково побитий, врятує та завантажить усі вцілілі блоки.
    """
    print(f"[WKB_PARSER] [START] Читання геометрії з: {filepath}")
    
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        print(f"[WKB_PARSER] [WARN] Файл порожній або відсутній. Повертаємо порожній MultiPolygon.")
        return MultiPolygon()

    all_chunks = []
    chunks_count = 0

    try:
        with open(filepath, "rb") as f:
            while True:
                # 1. Читаємо спочатку 4 байти заголовка довжини
                len_bytes = f.read(4)
                if not len_bytes or len(len_bytes) < 4:
                    # Чистий і коректний кінець файлу (EOF)
                    break
                
                # Розпаковуємо довжину наступного WKB-блоку
                block_len = struct.unpack(">I", len_bytes)[0]
                
                # 2. Викушуємо з потоку суворо block_len байтів
                wkb_bytes = f.read(block_len)
                if len(wkb_bytes) < block_len:
                    print(f"[WKB_PARSER] [WARN] Файл раптово обірвався на блоці №{chunks_count + 1}. Хвіст пошкоджено.")
                    break # Що встигли прочитати раніше — те врятовано!
                
                try:
                    # Розпаковуємо геометрію суворо з цього масиву байт
                    chunk = wkb.loads(wkb_bytes)
                    if chunk and not chunk.is_empty:
                        all_chunks.append(chunk)
                        chunks_count += 1
                except Exception as chunk_err:
                    # Якщо блок всередині бітий, ми знаємо його довжину, тому просто переступаємо його!
                    print(f"[WKB_PARSER] [ERROR] Пропуск бітого блоку №{chunks_count + 1}: {chunk_err}")
                    continue

        print(f"[WKB_PARSER] [SUCCESS] Читання завершено. Валідних блоків знайдено: {chunks_count}")

    except Exception as file_err:
        print(f"[WKB_PARSER] [CRITICAL] Помилка файлової системи: {file_err}")
        return MultiPolygon()

    # Зшиваємо блоки в один моноліт один раз при завантаженні програми
    if all_chunks:
        print(f"[WKB_PARSER] [UNION] Об'єднання {len(all_chunks)} елементів в ОЗУ...")
        try:
            merged_geometry = unary_union(all_chunks)
            print(f"[WKB_PARSER] [UNION_SUCCESS] Тип завантаженої карти: {merged_geometry.geom_type}")
            
            # Стандартизуємо вихідний тип до суворого MultiPolygon
            if isinstance(merged_geometry, Polygon):
                return MultiPolygon([merged_geometry])
            elif isinstance(merged_geometry, MultiPolygon):
                return merged_geometry
            else:
                polygons = [geom for geom in merged_geometry.geoms if isinstance(geom, Polygon)]
                return MultiPolygon(polygons)
        except Exception as union_err:
            print(f"[WKB_PARSER] [UNION_CRITICAL] Помилка сшивания shapely: {union_err}")
            return MultiPolygon()
    
    return MultiPolygon()

def log_multipolygon_details(mp: MultiPolygon):
    """
    Аналізує та виводить у лог детальну структуру об'єкта MultiPolygon.
    """
    if not mp or mp.is_empty:
        print("[LOG_REPORT] MultiPolygon порожній. Немає даних для аналізу.")
        return

    # Загальна кількість окремих полігонів (островів/кілець)
    polygons_count = len(mp.geoms)
    
    total_interiors = 0  # Кількість "дірок" у полігонах
    total_vertices = 0   # Загальна кількість точок (координат) на карті

    holes_areas = [Polygon(hole).area for poly in mp.geoms for hole in poly.interiors]
    micro_holes = [a for a in holes_areas if a < 1.0] # Дірки менше 1 кв.м.

    for polygon in mp.geoms:
        # Рахуємо внутрішні контури ("дірки")
        total_interiors += len(polygon.interiors)
        
        # Рахуємо вершини зовнішньої межі
        total_vertices += len(polygon.exterior.coords)
        
        # Додаємо вершини всіх внутрішніх контурів
        for interior in polygon.interiors:
            total_vertices += len(interior.coords)

    # Виводимо підсумковий звіт
    print("=" * 50)
    print("[LOG_REPORT] СТАТИСТИКА ЗАВАНТАЖЕНОЇ ГЕОМЕТРІЇ:")
    print(f" 🔹 Загальний тип: {mp.geom_type}")
    print(f" 🔹 Кількість окремих полігонів: {polygons_count}")
    print(f" 🔹 Кількість внутрішніх вирізів (дірок): {total_interiors}")
    print(f" 🔹 Загальна кількість точок (вершин): {total_vertices:,}")
    print(f" 🔹 Сумарна площа (в одиницях проєкції): {mp.area:,.2f}")
    print(f" 🔹 Загальний периметр контурів: {mp.length:,.2f}")
    print(f" 🔹 Максимальна дірка: {max(holes_areas):.2f} кв.м.")
    print(f" 🔹 Середня площа дірки: {sum(holes_areas)/len(holes_areas):.2f} кв.м.")
    print(f" 🔹 Кількість мікро-пропусків <1 кв.м.: {len(micro_holes)} підозрілі брязкання секцій")
    
    # Опціонально: межі всієї карти (Bounding Box)
    minx, miny, maxx, maxy = mp.bounds
    print(f" 🔹 Охоплюючий прямокутник (Bounds): [{minx:.4f}, {miny:.4f}] -> [{maxx:.4f}, {maxy:.4f}]")
    print("=" * 50)

def check_sections_stability(track_file):
    with open(track_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    section_changes = [0] * 8  # Лічильники перемикань для кожної з 8 секцій
    last_states = None
    total_records = 0

    for line in lines:
        parts = line.strip().split(',')
        if len(parts) < 6:
            continue
        
        total_records += 1
        # Розпаршуємо рядок секцій: '0-0-0-1-0-0-0-0' -> [0, 0, 0, 1, 0, 0, 0, 0]
        current_states = [int(x) for x in parts[4].split('-')]
        
        if last_states is not None:
            for i in range(8):
                if current_states[i] != last_states[i]:
                    section_changes[i] += 1
                    
        last_states = current_states

    print(f"=== ФІНАЛЬНИЙ АНАЛІЗ РОБОТИ SECTION CONTROL ===")
    print(f"Всього точок записано: {total_records}")
    print("Кількість перемикань по кожній секції (1..8):")
    for idx, changes in enumerate(section_changes):
        status = "СТАБІЛЬНО" if changes < total_records * 0.05 else "БРЯЗКАННЯ (Часті перемикання!)"
        print(f"  🔹 Секція №{idx+1}: {changes} разів змінила стан ({status})")
    print("==============================================")

# Запуск тесту перед релізом:
# check_sections_stability("your_track_file.txt")

def save_multipolygon_to_kml(mp: MultiPolygon, output_kml_path: str):
    """
    Конвертує об'єкт MultiPolygon (з урахуванням усіх 185 дірок) у файл KML.
    """
    if not mp or mp.is_empty:
        print("[KML_EXPORT] MultiPolygon порожній. Скасування запису.")
        return False

    kml_header = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://opengis.net">
  <Document>
    <name>Карта покриття обприскувача</name>
    <Style id="sprayer_coverage">
      <LineStyle>
        <color>ff0000ff</color> <!-- Червона межа -->
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>7f00ff00</color> <!-- Напівпрозорий зелений слід (50% альфа) -->
      </PolyStyle>
    </Style>
    <Placemark>
      <name>Фактичний слід обробки</name>
      <styleUrl>#sprayer_coverage</styleUrl>
      <MultiGeometry>
"""

    kml_footer = """      </MultiGeometry>
    </Placemark>
  </Document>
</kml>
"""

    try:
        with open(output_kml_path, "w", encoding="utf-8") as f:
            f.write(kml_header)

            for polygon in mp.geoms:
                f.write("        <Polygon>\n")
                
                # 1. Записуємо зовнішній контур (Exterior)
                f.write("          <outerBoundaryIs>\n            <LinearRing>\n              <coordinates>\n")
                # У KML координати йдуть у форматі: Довгота,Широта,Висота (Lon,Lat,0)
                ext_coords = " ".join([f"{lon},{lat},0" for lon, lat in polygon.exterior.coords])
                f.write(f"                {ext_coords}\n")
                f.write("              </coordinates>\n            </LinearRing>\n          </outerBoundaryIs>\n")

                # 2. Записуємо всі 185 внутрішніх вирізів (Interiors / Дірки)
                for interior in polygon.interiors:
                    f.write("          <innerBoundaryIs>\n            <LinearRing>\n              <coordinates>\n")
                    int_coords = " ".join([f"{lon},{lat},0" for lon, lat in interior.coords])
                    f.write(f"                {int_coords}\n")
                    f.write("              </coordinates>\n            </LinearRing>\n          </innerBoundaryIs>\n")

                f.write("        </Polygon>\n")

            f.write(kml_footer)
        print(f"[KML_EXPORT] Карта покриття успішно збережена у: {output_kml_path}")
        return True
    except Exception as e:
        print(f"[KML_EXPORT] Помилка запису KML карти: {e}")
        return False

import math

def calculate_offset_point(lat, lon, heading, distance_meters):
    """Розраховує зміщення точки по перпендикуляру до курсу руху."""
    R = 6378137.0
    dn = distance_meters * math.cos(heading)
    de = distance_meters * math.sin(heading)
    
    dLat = dn / R
    dLon = de / (R * math.cos(math.radians(lat)))
    
    return lat + math.degrees(dLat), lon + math.degrees(dLon)

def save_dynamic_sections_to_kml(track_txt_path: str, output_kml_path: str):
    # Кольори KML у форматі AABBGGRR (Альфа, Blue, Green, Red)
    # 7f00ff00 -> 50% прозорості, зелений (працює)
    # 7f0000ff -> 50% прозорості, червоний (вимкнено)
    kml_header = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://opengis.net">
  <Document>
    <name>Мапа роботи секцій обприскувача</name>
    <Style id="sec_active">
      <LineStyle><width>0</width></LineStyle>
      <PolyStyle><color>7f00ff00</color></PolyStyle> 
    </Style>
    <Style id="sec_disabled">
      <LineStyle><width>0</width></LineStyle>
      <PolyStyle><color>7f0000ff</color></PolyStyle>
    </Style>
"""
    kml_footer = """  </Document>
</kml>
"""

    try:
        with open(track_txt_path, "r", encoding="utf-8") as f:
            lines = [line.strip().split(',') for line in f if line.strip()]

        kml_polygons = []
        
        for idx in range(len(lines) - 1):
            p1, p2 = lines[idx], lines[idx + 1]
            if len(p1) < 6 or len(p2) < 6:
                continue
                
            try:
                lat1, lon1, hdg1 = float(p1[1]), float(p1[2]), float(p1[3])
                states1 = [int(x) for x in p1[4].split('-')]
                widths1 = [float(x) for x in p1[5].split('-')]
                
                lat2, lon2, hdg2 = float(p2[1]), float(p2[2]), float(p2[3])
                states2 = [int(x) for x in p2[4].split('-')]
                widths2 = [float(x) for x in p2[5].split('-')]
            except (ValueError, IndexError):
                continue

            # Динамічно визначаємо кількість секцій у поточному рядку
            sections_count = min(len(states1), len(widths1), len(states2), len(widths2))
            if sections_count == 0:
                continue

            perp_angle1 = math.radians(hdg1 + 90)
            perp_angle2 = math.radians(hdg2 + 90)
            
            # Розрахунок початкового зміщення від лівого краю штанги
            total_width = sum(widths1[:sections_count])
            current_offset1 = -total_width / 2.0
            current_offset2 = -total_width / 2.0
            
            for s_idx in range(sections_count):
                sec_w1 = widths1[s_idx]
                
                start_offset1 = current_offset1
                end_offset1 = current_offset1 + sec_w1
                start_offset2 = current_offset2
                end_offset2 = current_offset2 + sec_w1
                
                current_offset1 = end_offset1
                current_offset2 = end_offset2
                
                # Секція активна, якщо вона увімкнена хоча б на одному кроці
                is_active = (states1[s_idx] == 1 or states2[s_idx] == 1)
                style_url = "#sec_active" if is_active else "#sec_disabled"
                status_text = "АКТИВНА" if is_active else "ВИМКНЕНА"

                # Координати 4 кутів полігона для цієї секції
                l1_lat, l1_lon = calculate_offset_point(lat1, lon1, perp_angle1, start_offset1)
                r1_lat, r1_lon = calculate_offset_point(lat1, lon1, perp_angle1, end_offset1)
                r2_lat, r2_lon = calculate_offset_point(lat2, lon2, perp_angle2, end_offset2)
                l2_lat, l2_lon = calculate_offset_point(lat2, lon2, perp_angle2, start_offset2)
                
                poly_xml = f"""    <Placemark>
      <name>Секція {s_idx+1} ({status_text})</name>
      <styleUrl>{style_url}</styleUrl>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              {l1_lon:.8f},{l1_lat:.8f},0
              {r1_lon:.8f},{r1_lat:.8f},0
              {r2_lon:.8f},{r2_lat:.8f},0
              {l2_lon:.8f},{l2_lat:.8f},0
              {l1_lon:.8f},{l1_lat:.8f},0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
"""
                kml_polygons.append(poly_xml)

        with open(output_kml_path, "w", encoding="utf-8") as f:
            f.write(kml_header)
            f.writelines(kml_polygons)
            f.write(kml_footer)
            
        print(f"[READY] Універсальний KML успішно згенеровано: {output_kml_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Помилка генерації KML: {e}")
        return False

