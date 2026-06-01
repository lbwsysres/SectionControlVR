# =======================================================================
# dump_manager.py --- РОЗУМНЕ ВІДНОВЛЕННЯ СЕСІЇ ТА ЗАХИСТ eMMC
# =======================================================================
import json
import os
import time
from pathlib import Path
from pprint import pprint
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
        
        print("save_lightweight_json:\n")
        #pprint(sc.__dict__)
        #print(sc.__dict__['cfg']['ACTIVE_IMPLEMENT_ID'])
        print(f"ACTIVE_TASKMAP_FILE: {sc.__dict__['cfg']['ACTIVE_TASKMAP_FILE']}")
        print(f"ACTIVE_IMPLEMENT_ID: {sc.__dict__['cfg']['ACTIVE_IMPLEMENT_ID']}")
        print(f"VRA_RATE_DEFAULT: {sc.__dict__['cfg']['VRA_RATE_DEFAULT']}")

        #pprint(sc.__dict__)
        

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
            lines.append(f"{p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[5]}\n")

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