import math
import pyproj
import os, time
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import wkt

class SectionControl:
    def __init__(self, cfg):
        self.off_timers = [0] * 100  # Таймеры для каждой секции
        self.cfg = cfg
        self.covered_area = MultiPolygon()
        self.transformer_to_m = None
        self.last_x, self.last_y, self.last_hdg = None, None, None
        self.path_history = []
        self.last_p1_list = []
        self.last_p2_list = []
        self.last_hdg = None
        self.last_time = None
        self.omega = 0.0 # Кутова швидкість (рад/сек)
        self.prev_heading = None
        self.total_turn = 0.0
        self.threshold = 0.1  # Чутливість (мінімальний рух у градусах)
        self.prev_percents = None

        # Загрузка сохранения геометрии
        save_file = cfg.get("SAVE_FILE", "coverage.wkt")
        if os.path.exists(save_file):
            try:
                with open(save_file, "r") as f:
                    content = f.read()
                    if content:
                        geom = wkt.loads(content)
                        self.covered_area = (
                            geom
                            if isinstance(geom, MultiPolygon)
                            else MultiPolygon([geom])
                        )
            except:
                pass
    
    # Curve Compensation (компенсация на поворотах)
    def update_1(self, current_speed, current_heading):
        import time
        now = time.time()
        
        if self.prev_heading is None:
            self.prev_heading = current_heading
            self.last_time = now
            return 0.0

        dt = now - self.last_time
        if dt < 0.05: dt = 0.1 # Захист від мікро-кроків

        # 1. Твій розрахунок різниці (найкоротший шлях) - ПРАВИЛЬНО
        diff = (current_heading - self.prev_heading + 180) % 360 - 180
        
        # 2. Перетворюємо різницю у ШВИДКІСТЬ (градуси за секунду)
        if abs(diff) > self.threshold:
            # Замість накопичення (+=), ми рахуємо миттєву кутову швидкість
            turn_rate = diff / dt
        else:
            # Рух зупинився — миттєво в нуль
            turn_rate = 0.0

        # Оновлюємо базу для наступного кроку
        self.prev_heading = current_heading
        self.last_time = now

        # Для дебагу: turn_rate покаже, наскільки "різко" ти крутиш
        print(f"RATE: {turn_rate:.2f} deg/s")

        # Ми вже маємо turn_rate (deg/s)
        # 1. Переводимо швидкість трактора в м/с
        v_tractor = current_speed / 3.6
        
        # 2. Переводимо turn_rate у радіани (для формули)
        omega_rad = math.radians(turn_rate)
        
        # 3. Рахуємо відсотки для кожної секції
        widths = self.cfg.get("SECTION_WIDTHS", [3.0]*7)
        total_w = sum(widths)
        current_pos = -total_w / 2
        percents = []
        
        for w in widths:
            dist_to_center = current_pos + w / 2
            
            if abs(turn_rate) < 0.1 or v_tractor < 0.2:
                # Якщо їдемо прямо або стоїмо — рівно 100%
                ratio = 100
            else:
                # Швидкість секції: V_sec = V_tr + (Omega * Dist)
                #v_section = v_tractor + (omega_rad * dist_to_center)
                v_section = v_tractor - (omega_rad * dist_to_center)
                ratio = (v_section / v_tractor) * 100
            # Обмежуємо адекватними рамками (напр. 50% - 150%)
            percents.append(int(max(20, min(150, ratio))))     
            current_pos += w
            # Совет: Можно добавить условие: 
            # if rtk_status < 4: return [100] * num_sections. 
            # Это будет значить: «Нет идеального сигнала — не рискуем химией, льем ровно».
        return percents

    #Curve Compensation (компенсация на поворотах)
    def curve_compensation_1(self, current_speed, current_heading, rtk_status=0):
        
        # Розрахунок компенсації виливу на поворотах.
        # current_speed: швидкість у км/год
        # current_heading: курс у градусах
        # rtk_status: статус якості GPS (4 = RTK Fix)
        
        now = time.time()
        
        # 1. Завантажуємо параметри з конфігу
        # (self.cfg оновлюється в gps_loop через config_manager.load_config())
        widths = self.cfg.get("SECTION_WIDTHS", [3.0] * 7)
        num_sections = len(widths)
        
        min_rtk = self.cfg.get("CURVE_COMP_MIN_RTK", 4)
        low_limit, high_limit = self.cfg.get("CURVE_COMP_LIMITS", [50, 150])
        threshold = self.cfg.get("CURVE_COMP_THRESHOLD", 0.1)

        # Якщо це перший запуск - ініціалізуємо змінні та повертаємо 100%
        if self.prev_heading is None:
            self.prev_heading = current_heading
            self.last_time = now
            return [100] * num_sections

        dt = now - self.last_time
        if dt < 0.05: dt = 0.1 # Захист від занадто частих викликів

        # 2. Розрахунок кутової швидкості (градуси/сек)
        # Шукаємо найкоротший шлях повороту через 360 градусів
        diff = (current_heading - self.prev_heading + 180) % 360 - 180
        turn_rate = diff / dt if abs(diff) > threshold else 0.0

        self.prev_heading = current_heading
        self.last_time = now

        # 3. Перевірка умов для застосування компенсації
        v_tractor = current_speed / 3.6 # Переводимо в м/с
        
        # Вимикаємо компенсацію (повертаємо 100%), якщо:
        # - Якість GPS низька (RTK status < порогового)
        # - Швидкість занадто мала (< 0.2 м/с)
        # - Ми їдемо практично прямо
        if rtk_status < min_rtk or v_tractor < 0.2 or abs(turn_rate) < 0.1:
            return [100] * num_sections

        # 4. Розрахунок відсотків для кожної секції
        omega_rad = math.radians(turn_rate) # Переводимо кутову швидкість у радіани
        total_w = sum(widths)
        
        # Починаємо з крайньої лівої точки штанги
        current_pos = -total_w / 2
        percents = []
        
        for w in widths:
            # Відстань від центру трактора до центру поточної секції
            dist_to_center = current_pos + w / 2
            
            # Формула: V_сектору = V_трактора - (Omega * Dist)
            # Знак мінус означає: при повороті вправо (omega > 0), 
            # ліві секції (dist < 0) прискорюються (мінус на мінус дає плюс)
            v_section = v_tractor - (omega_rad * dist_to_center)
            
            # Розраховуємо відношення швидкості секції до швидкості трактора
            ratio = (v_section / v_tractor) * 100
            
            # Обмежуємо лімітами з конфігу та перетворюємо в ціле число
            clamped_ratio = int(max(low_limit, min(high_limit, ratio)))
            # Обмежуємо адекватними рамками (напр. 50% - 150%)
    #       #percents.append(int(max(20, min(150, ratio))))   
            
            percents.append(clamped_ratio)
            
            # Переходимо до наступної секції
            current_pos += w

        return percents

    def curve_compensation_2(self, current_speed, current_heading, rtk_status=0):
        import time
        now = time.time()
        
        # --- 1. ЗАВАНТАЖЕННЯ ПАРАМЕТРІВ ---
        widths = self.cfg.get("SECTION_WIDTHS", [3.0] * 7)
        num_sections = len(widths)
        
        min_rtk = self.cfg.get("CURVE_COMP_MIN_RTK", 4)
        low_limit, high_limit = self.cfg.get("CURVE_COMP_LIMITS", [20, 150])
        threshold = self.cfg.get("CURVE_COMP_THRESHOLD", 0.1)
        smooth_factor = self.cfg.get("CURVE_COMP_SMOOTH", 0.3) # Читаємо з конфігу

            # Якщо це перший запуск або дані GPS тільки з'явилися
        if self.prev_heading is None:
            self.prev_heading = current_heading
            self.last_time = now
            # Ініціалізуємо внутрішній стан фільтра
            self.prev_percents = [100.0] * num_sections
            # Повертаємо список зі 100% для кожної секції
            return [100] * num_sections


        dt = now - self.last_time
        if dt < 0.05: dt = 0.1 

        # --- 2. РОЗРАХУНОК КУТОВОЇ ШВИДКОСТІ ---
        diff = (current_heading - self.prev_heading + 180) % 360 - 180
        turn_rate = diff / dt if abs(diff) > threshold else 0.0
        self.prev_heading = current_heading
        self.last_time = now

        v_tractor = current_speed / 3.6
        
        # --- 3. ОБЧИСЛЕННЯ НОВИХ ВІДСОТКІВ (Raw values) ---
        raw_percents = []
        
        # Якщо умови не виконуються — цільове значення 100%
        if rtk_status < min_rtk or v_tractor < 0.2 or abs(turn_rate) < 0.1:
            target_percents = [100.0] * num_sections
        else:
            omega_rad = math.radians(turn_rate)
            total_w = sum(widths)
            current_pos = -total_w / 2
            
            for w in widths:
                dist_to_center = current_pos + w / 2
                v_section = v_tractor - (omega_rad * dist_to_center)
                ratio = (v_section / v_tractor) * 100
                
                # Тимчасово обмежуємо, але ще не округлюємо
                clamped = max(low_limit, min(high_limit, ratio))
                raw_percents.append(clamped)
                current_pos += w
            target_percents = raw_percents

        # --- 4. LOW-PASS FILTER (ЗГЛАДЖУВАННЯ) ---
        # Якщо кількість секцій змінилася, скидаємо фільтр
        if self.prev_percents is None or len(self.prev_percents) != num_sections:
            self.prev_percents = [100.0] * num_sections

        filtered_percents = []
        for i in range(num_sections):
            # Формула: новий = старий + alpha * (ціль - старий)
            new_val = self.prev_percents[i] + smooth_factor * (target_percents[i] - self.prev_percents[i])
            filtered_percents.append(new_val)
        
        self.prev_percents = filtered_percents # Зберігаємо для наступного кроку

        # Повертаємо цілі числа для JSON
        return [int(round(x)) for x in filtered_percents]
    
    def process_1(self, lat, lon, heading_deg, speed):
        # Читаем актуальное состояние мастера
        master_on = self.cfg.get("MASTER_SW", False)
        section_widths = self.cfg.get("SECTION_WIDTHS", [])
        section_modes = self.cfg.get("SECTION_MODES", ["AUTO"] * len(section_widths))
        heading = math.radians(heading_deg)

        if not self.transformer_to_m:
            zone = int((lon + 180) / 6) + 1
            self.transformer_to_m = pyproj.Transformer.from_crs(
                "epsg:4326", f"epsg:326{zone}", always_xy=True
            )

        ux, uy = self.transformer_to_m.transform(lon, lat)

        # Порог движения (5 см)
        if self.last_x is not None:
            if math.sqrt((ux - self.last_x) ** 2 + (uy - self.last_y) ** 2) < 0.05:
                return [False] * len(section_widths)

        # Расчет Look Ahead (минимум 0.3м для низких скоростей)
        # dist_ahead = max((speed / 3.6) * self.cfg.get("LOOK_AHEAD", 0.5), 0.3)
        speed_ms = speed / 3.6
        dist_ahead = max(
            speed_ms * self.cfg.get("LOOK_AHEAD", 0.5), 0.6
        )  # Минимум 60 см
        if speed < 5:
            dist_ahead = max(
                dist_ahead, 0.8
            )  # На скорости < 5 км/ч гарантируем длину штанги минимум 0.8 метра
        else:
            dist_ahead = max(
                dist_ahead, 0.5
            )  # На большой скорости добавляем чуть больше выноса для стабильности

        pred_x = ux + dist_ahead * math.sin(heading)
        pred_y = uy + dist_ahead * math.cos(heading)

        res_states = []
        polys_to_save = []  # Только для реального внесения
        total_w = sum(section_widths)
        l_offset = -total_w / 2
        current_p1_list, current_p2_list = [], []

        for idx, w in enumerate(section_widths):
            mode = section_modes[idx] if idx < len(section_modes) else "AUTO"
            p1 = self.get_p(pred_x, pred_y, heading, l_offset)
            p2 = self.get_p(pred_x, pred_y, heading, l_offset + w)
            current_p1_list.append(p1)
            current_p2_list.append(p2)

            # Стыковка с прошлым шагом
            if self.last_p1_list and len(self.last_p1_list) > idx:
                p4, p3 = self.last_p1_list[idx], self.last_p2_list[idx]
            else:
                p4 = self.get_p(ux, uy, heading, l_offset)
                p3 = self.get_p(ux, uy, heading, l_offset + w)

            poly = Polygon([p1, p2, p3, p4])
            if not poly.is_valid:
                poly = poly.buffer(0)

            is_on = False
            # ПРОВЕРКА ПЕРЕКРЫТИЯ: Считаем только если Master ВКЛ
            if master_on:
                if mode == "ON":
                    is_on = True
                elif mode == "OFF":
                    is_on = False
                else:  # AUTO
                    # Уменьшаем буфер на низких скоростях
                    safety_buffer = -0.02 if speed < 3 else -0.08

                    if speed < 3:
                        safety_buffer = -0.15  # 15 см заступ на очень малой скорости
                    elif speed < 7:
                        safety_buffer = -0.10  # 10 см заступ для средней скорости
                    else:
                        safety_buffer = -0.05  # 5 см для высокой точности на скорости
                    # test_poly = poly.buffer(safety_buffer)
                    safety_buffer = -0.02
                    test_poly = poly.buffer(safety_buffer)
                    is_on = True
                    if not self.covered_area.is_empty and not test_poly.is_empty:
                        if self.covered_area.intersects(test_poly):
                            is_on = False

            # После того как посчитал is_on
            # if is_on == True:
            # # Если секция хочет включиться, проверяем, сколько времени она была выключена
            #     if time.time() - self.off_timers[idx] < 0.5: # Задержка 0.5 секунды
            #         is_on = False # Держим выключенной, чтобы не мерцала
            # else:
            #     self.off_timers[idx] = time.time() # Запоминаем время выключения

            res_states.append(is_on)

            # ВАЖНО: В память поля пишем только если мастер ВКЛ и секция ЛЬЕТ
            if master_on and is_on:
                polys_to_save.append(poly)
            l_offset += w

        # Пишем в историю для отрисовки ВСЕГДА (будет красный след при Master OFF)
        self.path_history.append([lat, lon, heading_deg, list(res_states)])
        if len(self.path_history) > 5000:
            self.path_history.pop(0)

        # Додаємо точку в історію
        # self.path_history.append([lat, lon, heading_deg, list(res_states)])
        # ОБМЕЖЕННЯ ПАМ'ЯТІ (Важливо!)
        # Якщо історія занадто велика, видаляємо стару точку.
        # Але пам'ятай: якщо ти видалиш точку з початку, індекси змістяться!
        # Тому краще тримати великий ліміт (наприклад, 10 000 точок)
        # if len(self.path_history) > 10000:
        #    self.path_history.pop(0)

        # Обновляем геометрию поля (только реальная работа)
        if polys_to_save:
            try:
                step_union = unary_union(polys_to_save)
                self.covered_area = self.covered_area.union(step_union)
                # ЗАПИСЬ Оптимизация раз в 50 шагов
                if len(self.path_history) % 50 == 0:
                    self.covered_area = self.covered_area.simplify(
                        0.05, preserve_topology=True
                    )
                    self.save_to_disk()
            except:
                pass

        self.last_x, self.last_y, self.last_hdg = ux, uy, heading
        self.last_p1_list, self.last_p2_list = current_p1_list, current_p2_list
        return res_states

    def curve_compensation(self, speed, heading_deg, rtk_status):
        now = time.time()
        widths = self.cfg.get("SECTION_WIDTHS", [3.0] * 7)
        num_sections = len(widths)
        
        # Параметри з конфігу
        limits = self.cfg.get("CURVE_COMP_LIMITS", [20, 150])
        smooth = self.cfg.get("CURVE_COMP_SMOOTH", 0.3)
        
        if self.prev_heading is None:
            self.prev_heading = heading_deg
            self.last_time = now
            self.prev_percents = [100.0] * num_sections
            return [100] * num_sections

        dt = max(now - self.last_time, 0.1)
        diff = (heading_deg - self.prev_heading + 180) % 360 - 180
        turn_rate = diff / dt if abs(diff) > self.cfg.get("CURVE_COMP_THRESHOLD", 0.1) else 0.0
        
        self.prev_heading, self.last_time = heading_deg, now
        v_tr = speed / 3.6

        # Розрахунок цільових значень
        targets = []
        if rtk_status < self.cfg.get("CURVE_COMP_MIN_RTK", 4) or v_tr < 0.2 or abs(turn_rate) < 0.1:
            targets = [100.0] * num_sections
        else:
            omega = math.radians(turn_rate)
            current_pos = -sum(widths) / 2
            for w in widths:
                v_sec = v_tr - (omega * (current_pos + w/2))
                ratio = (v_sec / v_tr) * 100 if v_tr > 0 else 100
                targets.append(max(limits[0], min(limits[1], ratio)))
                current_pos += w

        # Фільтр Low-pass
        if not self.prev_percents or len(self.prev_percents) != num_sections:
            self.prev_percents = [100.0] * num_sections
            
        filtered = []
        for i in range(num_sections):
            val = self.prev_percents[i] + smooth * (targets[i] - self.prev_percents[i])
            filtered.append(val)
        
        self.prev_percents = filtered
        return [int(round(x)) for x in filtered]

    def process(self, lat, lon, heading_deg, speed):
        master_on = self.cfg.get("MASTER_SW", False)
        widths = self.cfg.get("SECTION_WIDTHS", [])
        modes = self.cfg.get("SECTION_MODES", ["AUTO"] * len(widths))
        heading = math.radians(heading_deg)

        # Проекція координат
        if not self.transformer_to_m:
            zone = int((lon + 180) / 6) + 1
            self.transformer_to_m = pyproj.Transformer.from_crs("epsg:4326", f"epsg:326{zone}", always_xy=True)
        ux, uy = self.transformer_to_m.transform(lon, lat)

        # Поріг руху
        if self.last_x is not None:
            if math.sqrt((ux - self.last_x)**2 + (uy - self.last_y)**2) < 0.05:
                return [False] * len(widths)

        # Look Ahead
        speed_ms = speed / 3.6
        dist_ahead = max(speed_ms * self.cfg.get("LOOK_AHEAD_TIME", 0.6), self.cfg.get("MIN_LOOK_AHEAD_DIST", 0.5))
        pred_x, pred_y = ux + dist_ahead * math.sin(heading), uy + dist_ahead * math.cos(heading)

        res_states, polys_to_save = [], []
        l_offset = -sum(widths) / 2
        curr_p1, curr_p2 = [], []

        # Налаштування перекриття
        base_buf = self.cfg.get("AUTO_SECTION_BUFFER", -0.05)
        min_overlap = self.cfg.get("AUTO_SECTION_MIN_OVERLAP", 0.3)

        for i, w in enumerate(widths):
            p1 = self.get_p_new(pred_x, pred_y, heading, l_offset)
            p2 = self.get_p_new(pred_x, pred_y, heading, l_offset + w)
            curr_p1.append(p1); curr_p2.append(p2)

            # Формуємо полігон секції
            p4, p3 = (self.last_p1_list[i], self.last_p2_list[i]) if (self.last_p1_list and len(self.last_p1_list) > i) else (self.get_p(ux, uy, heading, l_offset), self.get_p(ux, uy, heading, l_offset + w))
            poly = Polygon([p1, p2, p3, p4])
            if not poly.is_valid: poly = poly.buffer(0)

            is_on = False
            if master_on:
                mode = modes[i]
                if mode == "ON": is_on = True
                elif mode == "OFF": is_on = False
                else: # AUTO
                    test_poly = poly.buffer(base_buf)
                    is_on = True
                    if not self.covered_area.is_empty and not test_poly.is_empty:
                        # Швидка перевірка перетину
                        if self.covered_area.intersects(test_poly):
                            # Точна перевірка відсотка площі перекриття
                            inter_area = self.covered_area.intersection(test_poly).area
                            if (inter_area / test_poly.area) > min_overlap:
                                is_on = False
            
            res_states.append(is_on)
            if master_on and is_on: polys_to_save.append(poly)
            l_offset += w

        # Історія шляху (завжди)
        self.path_history.append([lat, lon, heading_deg, list(res_states)])
        if len(self.path_history) > 10000: self.path_history.pop(0)

        # Оновлення карти поля
        if polys_to_save:
            try:
                self.covered_area = self.covered_area.union(unary_union(polys_to_save))
                if len(self.path_history) % 50 == 0:
                    self.covered_area = self.covered_area.simplify(0.05, preserve_topology=True)
            except: pass

        self.last_x, self.last_y, self.last_p1_list, self.last_p2_list = ux, uy, curr_p1, curr_p2
        return res_states

    def get_p_new(self, x, y, hdg, offset):
        return (x + offset * math.cos(hdg), y - offset * math.sin(hdg))    
    
    
    
    #************************************************************************************
    def get_area_ha(self):
        if self.covered_area.is_empty:
            return 0.0
        return round(self.covered_area.area / 10000.0, 4)
    
    def meters_to_gps(mx, my):
        # sc.transformer_to_m — это твой трансформер из 4326 в 326xx
        # Мы используем его в обратную сторону
        try:
            lon, lat = sc.transformer_to_m.transform(mx, my, direction=pyproj.enums.TransformDirection.INVERSE)
            return [lat, lon]
        except:
            return None

    def reset(self):
        from shapely.geometry import MultiPolygon

        self.covered_area = MultiPolygon()  # Саме так, а не None
        self.path_history = []
        self.last_x = self.last_y = self.last_hdg = None
        # Видаліть файл збереження, якщо він є
        save_file = self.cfg.get("SAVE_FILE", "coverage.wkt")
        if os.path.exists(save_file):
            os.remove(save_file)
        history_file = self.cfg.get("HISTORY_FILE", "history.json")
        if os.path.exists(history_file):
            os.remove(history_file)

    def save_to_disk(self):
        """Примусовий запис геометрії на диск"""
        try:
            save_file = self.cfg.get("SAVE_FILE", "coverage.wkt")
            # Обов'язково робимо simplify перед записом, щоб файл був легким
            simplified = self.covered_area.simplify(0.05, preserve_topology=True)
            with open(save_file, "w") as f:
                f.write(wkt.dumps(simplified, rounding_precision=3))
        except Exception as e:
            print(f"Force save error WKT: {e}")

    def get_p(self, tx, ty, th, lo):
        # Стандартная навигационная математика (0 - Север)
        bx = tx - self.cfg.get("OFFSET_BACK", 0) * math.sin(th)
        by = ty - self.cfg.get("OFFSET_BACK", 0) * math.cos(th)
        res_x = bx + lo * math.cos(th)
        res_y = by - lo * math.sin(th)
        return (res_x, res_y)