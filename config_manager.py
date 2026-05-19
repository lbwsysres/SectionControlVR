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
    "SAVE_FILE": "coverage.wkb",
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
    "SMART_TURN_ENABLED": True,
    "LOOK_AHEAD_ON_TIME": 0.8,
    "LOOK_AHEAD_OFF_TIME": 0.3,
    # Дописуємо в DEFAULT_CONFIG всередині config_manager.py
    "VRA_RATE_DEFAULT": 0.0,  # Твоя захисна норма 0.0 за замовчуванням
    "VRA_CALC_MODE": "boom",  # Режим обчислення: "boom" (вся штанга) або "sections" (посекційно)
    "CONTROL_BOARD_TYPE": "udp",
    "CONTROL_BOARD_PORT_NUM": 5005

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

    # Якщо кешу ще немає (хоча це малоймовірно), завантажуємо його
    if _cached_config is None:
        _cached_config = load_config()

    # Зливаємо поточний повний кеш із новими змінами від користувача
    updated_config = {**_cached_config, **new_cfg}

    # Синхронізуємо кількість режимів із кількістю секцій перед збереженням
    if len(updated_config.get("SECTION_MODES", [])) != len(
        updated_config.get("SECTION_WIDTHS", [])
    ):
        updated_config["SECTION_MODES"] = ["AUTO"] * len(
            updated_config["SECTION_WIDTHS"]
        )

    # Оновлюємо глобальний RAM-кеш
    _cached_config = updated_config

    # Записуємо на диск
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(_cached_config, f, indent=4)
        print("[Config] Save config to disk and RAM successfully.")
    except Exception as e:
        print(f"[Config] Помилка збереження конфігу: {e}")


def save_config_1(new_cfg):
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
    # print(new_cfg)


def _read_from_disk():
    """Читає конфіг з диска та автоматично дописує нові параметри з DEFAULT_CONFIG"""
    current_disk_cfg = {}
    config_changed = False

    # 1. Спроба прочитати файл, якщо він є
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                current_disk_cfg = json.load(f)
        except Exception as e:
            print(f"[Config] Помилка читання файлу конфігу, створимо заново: {e}")
            current_disk_cfg = {}

    # 2. Магічне злиття: беремо дефолт, поверх накочуємо те, що вже було на диску
    # (так ми зберігаємо всі налаштування фермера і додаємо нові ключі з коду)
    final_config = {**DEFAULT_CONFIG, **current_disk_cfg}

    # 3. Синхронізація масивів секцій (ваша чудова логіка безпеки)
    if len(final_config.get("SECTION_MODES", [])) != len(
        final_config.get("SECTION_WIDTHS", [])
    ):
        final_config["SECTION_MODES"] = ["AUTO"] * len(final_config["SECTION_WIDTHS"])
        config_changed = True

    # 4. Перевіряємо, чи з'явилися нові ключі, яких не було на диску
    if set(final_config.keys()) != set(current_config_keys := current_disk_cfg.keys()):
        config_changed = True

    # 5. Якщо конфіг оновився — перезаписуємо його на диску
    if config_changed:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(final_config, f, indent=4)
            print(
                "[Config] Знайдено нові параметри! Файл config.json на диску успішно оновлено."
            )
        except Exception as e:
            print(f"[Config] Не вдалося оновити файл на диску: {e}")

    return final_config


def _read_from_disk_1():
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
