import json
import os
import time

DUMP_DIR = os.path.abspath("fields")
CURRENT_SESSION_FILE = os.path.join(DUMP_DIR, "current_session.json")

def save_session_dump(state, sc, filename=None):
    """
    Робить повний злімок ОЗУ (state та sc) і пише на диск.
    Якщо filename не вказано, пише в поточну робочу сесію.
    """
    os.makedirs(DUMP_DIR, exist_ok=True)
    target_file = filename if filename else CURRENT_SESSION_FILE
    
    try:
        # Збираємо абсолютно всі критичні дані для відновлення екрану Canvas
        payload = {
            "timestamp": time.time(),
            "area": getattr(state, 'area', 0.0),
            "point_a": getattr(state, 'point_a', None),
            "point_b": getattr(state, 'point_b', None),
            "guidance_error": getattr(state, 'guidance_error', 0.0),
            "path_history": getattr(state, 'path_history', []),
            # Якщо всередині sc (SectionControl) є розраховані полігони, 
            # їх теж можна додати сюди (якщо вони серіалізуються в JSON)
        }
        
        # Атомарний запис у Linux для захисту від раптового відключення живлення
        temp_file = target_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(temp_file, target_file)
        return True
    except Exception as e:
        print(f"[DumpManager] Critical error writing dump: {e}")
        return False

def load_session_dump(state, sc, filename=None):
    """
    Завантажує дамп з диска та накатує його назад на живі об'єкти системи.
    """
    target_file = filename if filename else CURRENT_SESSION_FILE
    if not os.path.exists(target_file):
        return False
        
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            dump = json.load(f)
            
        # Накатуємо дані назад в ОЗУ об'єкта state
        state.area = dump.get("area", 0.0)
        state.point_a = dump.get("point_a")
        state.point_b = dump.get("point_b")
        state.guidance_error = dump.get("guidance_error", 0.0)
        state.path_history = dump.get("path_history", [])
        
        # Синхронізуємо двигун обчислення секцій
        sc.path_history = state.path_history
        
        print(f"[DumpManager] State successfully restored from file: {os.path.basename(target_file)}")
        return True
    except Exception as e:
        print(f"[DumpManager] Could not read dump: {e}")
        return False

def clear_current_dump():
    """Видаляє поточну сесію (викликається при Reset)"""
    if os.path.exists(CURRENT_SESSION_FILE):
        try:
            os.remove(CURRENT_SESSION_FILE)
        except:
            pass
