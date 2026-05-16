# config_manager.py
import json
import os

CONFIG_FILE = "config.json"

# Глобальний кеш для зберігання конфігурації в оперативній пам'яті (RAM)
_cached_config = None

DEFAULT_CONFIG = {
    "UDP_PORT": 9999,
    "SECTION_WIDTHS": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    "DRAW_OFF_SECTIONS": False,
    "LOOK_AHEAD": 0.1,
    "MIN_SPEED": 1.0,
    "VISUAL_SCALE": 1.0,
    "OFFSET_BACK": 0.0,
    "MASTER_SW": True,
    "SECTION_MODES": ["AUTO", "AUTO", "AUTO", "AUTO", "AUTO"],
    "SAVE_FILE": "coverage.wkt",
    "HISTORY_FILE": "history.json",
    "LOOK_AHEAD_TIME": 0.6,
    "MIN_LOOK_AHEAD_DIST": 0.5,
    "AUTO_SECTION_BUFFER": -0.05,
    "AUTO_SECTION_MIN_OVERLAP": 0.3,
    "CURVE_COMP_MIN_RTK": 4,
    "CURVE_COMP_LIMITS": [50, 150],
    "CURVE_COMP_THRESHOLD": 0.1,
    "CURVE_COMP_SMOOTH": 0.3,
    "GPS_PORT": "com1",
    "GPS_PORT_SPEED": 115200,
    "GPS_TIME_RECONNECT": 5000,
    "GPS_ENABLE": False,
    "CONTROL_BOARD_PORT": "com2",
    "CONTROL_BOARD_PORT_SPEED": 115200,
    "CONTROL_BOARD_TIME_RECONNECT": 5000,
    "CONTROL_BOARD_ENABLE": False,
    "LOOK_AHEAD_ON_TIME": 0.8,
    "LOOK_AHEAD_OFF_TIME": 0.3,
}


def load_config():
    """Повертає конфігурацію з оперативної пам'яті (без дискового I/O)"""
    global _cached_config

    # Якщо це перший запуск — читаємо з диска
    if _cached_config is None:
        _cached_config = _read_from_disk()

    return _cached_config


def save_config(new_cfg):
    """Оновлює кеш в RAM та одночасно записує дані на диск"""
    global _cached_config

    # Синхронізуємо кількість режимів із кількістю секцій перед збереженням
    if len(new_cfg.get("SECTION_MODES", [])) != len(new_cfg.get("SECTION_WIDTHS", [])):
        new_cfg["SECTION_MODES"] = ["AUTO"] * len(new_cfg["SECTION_WIDTHS"])

    # Оновлюємо глобальний RAM-кеш
    _cached_config = {**DEFAULT_CONFIG, **new_cfg}

    # Записуємо на диск в асинхронному стилі (один раз)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(_cached_config, f, indent=4)
    print("[Config] Save congif disk and RAM.")
    #print(new_cfg)


def _read_from_disk():
    """Внутрішня функція для первинного читання файлу з диска"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                cfg = json.load(f)
                if len(cfg.get("SECTION_MODES", [])) != len(
                    cfg.get("SECTION_WIDTHS", [])
                ):
                    cfg["SECTION_MODES"] = ["AUTO"] * len(cfg["SECTION_WIDTHS"])
                return {**DEFAULT_CONFIG, **cfg}
            except Exception as e:
                print(f"[Config] Помилка читання JSON, використано default: {e}")
                return DEFAULT_CONFIG
    return DEFAULT_CONFIG
