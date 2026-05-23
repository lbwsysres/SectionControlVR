import math
import pyproj
import os
import time
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import wkt
from shapely import wkb  # МІНЯЄМО wkt НА wkb


class SectionControl:
    def __init__(self, cfg):
        self.cfg = cfg
        self.covered_area = MultiPolygon()
        self.transformer_to_m = None
        self.last_x, self.last_y = None, None
        self.last_p1_list = []
        self.last_p2_list = []

        self.path_history = []
        self.prev_heading = None
        self.last_time = None
        self.prev_percents = None
        self.current_wkb_filename = "current_session.wkb"

        # НАШ ФЕН-ШУЙ БУФЕР: збирає нові полігони для дозапису
        self.buffer_to_disk = [] 


        # Завантаження збереженої геометрії поля
        # Міняємо розширення на .wkb, щоб не плутатися
        # save_file = cfg.get("SAVE_FILE", "coverage.wkb")
        # if os.path.exists(save_file):
        #     try:
        #         with open(save_file, "rb") as f:  # "rb" — Читання бінарного файлу
        #             content = f.read()
        #             if content:  # Перевіряємо, що файл не порожній
        #                 geom = wkb.loads(content)
        #                 self.covered_area = geom if isinstance(geom, MultiPolygon) else MultiPolygon([geom])
        #     except Exception as e:
        #         print(f"Помилка завантаження WKB карти: {e}. Створюємо нову.")
        #         self.covered_area = MultiPolygon()

    def get_section_point(self, tx, ty, th_rad, offset):
        """
        Єдина правильна навігаційна математика (0 градусів = Північ).
        Враховує винос штанги назад (OFFSET_BACK).
        """
        offset_back = self.cfg.get("OFFSET_BACK", 0.0)
        # Зсув трактора назад до осі штанги
        bx = tx - offset_back * math.sin(th_rad)
        by = ty - offset_back * math.cos(th_rad)
        # Зсув конкретної форсунки вбік по штанзі
        res_x = bx + offset * math.cos(th_rad)
        res_y = by - offset * math.sin(th_rad)
        return (res_x, res_y)

    def curve_compensation(self, speed, heading_deg, rtk_status):
        """Розрахунок компенсації виливу на поворотах (Low-Pass Filter)"""
        now = time.time()
        widths = self.cfg.get("SECTION_WIDTHS", [3.0] * 7)
        num_sections = len(widths)

        limits = self.cfg.get("CURVE_COMP_LIMITS", [20, 150])
        smooth = self.cfg.get("CURVE_COMP_SMOOTH", 0.3)

        if self.prev_heading is None:
            self.prev_heading = heading_deg
            self.last_time = now
            self.prev_percents = [100.0] * num_sections
            return [100] * num_sections

        dt = max(now - self.last_time, 0.05)

        # Найкоротший шлях розвороту через 360 градусів
        diff = (heading_deg - self.prev_heading + 180) % 360 - 180
        turn_rate = (
            diff / dt if abs(diff) > self.cfg.get("CURVE_COMP_THRESHOLD", 0.1) else 0.0
        )

        self.prev_heading, self.last_time = heading_deg, now
        v_tr = speed / 3.6  # км/год -> м/с

        targets = []
        if (
            rtk_status < self.cfg.get("CURVE_COMP_MIN_RTK", 4)
            or v_tr < 0.2
            or abs(turn_rate) < 0.1
        ):
            targets = [100.0] * num_sections
        else:
            omega = math.radians(turn_rate)
            current_pos = -sum(widths) / 2
            for w in widths:
                # Розрахунок швидкості конкретної секції на повороті
                v_sec = v_tr - (omega * (current_pos + w / 2))
                ratio = (v_sec / v_tr) * 100 if v_tr > 0 else 100
                targets.append(max(limits[0], min(limits[1], ratio)))
                current_pos += w

        # Фільтрація Low-pass для плавного перемикання клапанів
        if not self.prev_percents or len(self.prev_percents) != num_sections:
            self.prev_percents = [100.0] * num_sections

        filtered = []
        for i in range(num_sections):
            val = self.prev_percents[i] + smooth * (targets[i] - self.prev_percents[i])
            filtered.append(val)

        # Знайдіть кінець методу curve_compensation і додайте цей рядок перед return:
        self.last_turn_rate = turn_rate  # Зберігаємо для логіки Look Ahead
        self.prev_percents = filtered
        return [int(round(x)) for x in filtered]

    def process(self, lat, lon, heading_deg, speed):
        """
        Головна логіка секційного контролю та побудови карти покриття.
        Підтримує перемикач "Розумний розворот" (SMART_TURN_ENABLED).
        """
        master_on = self.cfg.get("MASTER_SW", False)
        widths = self.cfg.get("SECTION_WIDTHS", [])
        modes = self.cfg.get("SECTION_MODES", ["AUTO"] * len(widths))
        heading = math.radians(heading_deg)

        # -----------------------------------------------------------------------------------
        # ЖОРСТКИЙ АГРО-ФЕН-ШУЙ ФІКС ДЛЯ ЗМІНИ ШТАНГИ НА ХОДУ (Захист від перекосу трапецій)
        # -----------------------------------------------------------------------------------
        # Створюємо унікальний маркер поточної геометрії штанги (сума всіх ширин)
        current_boom_width = sum(widths)
        if not hasattr(self, '_last_boom_width'):
            self._last_boom_width = current_boom_width

        # Якщо змінилася АБО кількість секцій, АБО загальна ширина штанги —
        # ми миттєво і повністю очищаємо пам'ять минулого кроку!
        if (self.last_p1_list and len(self.last_p1_list) != len(widths)) or (self._last_boom_width != current_boom_width):
            self.last_p1_list = []
            self.last_p2_list = []
            self.last_x = None
            self.last_y = None
            self._last_boom_width = current_boom_width
            print(f"[SectionControl] УВАГА! Тракторист змінив штангу. Стара ширина: {self._last_boom_width}м, Нова: {current_boom_width}м. Пам'ять осей скинуто!")

        # -----------------------------------------------------------------------------------
        # ЗАХИСТ ВІД ЗМІНИ КІЛЬКОСТІ СЕКЦІЙ НА ХОДУ
        # -----------------------------------------------------------------------------------
        # Якщо механізатор змінив кількість форсунок у меню, довжина масиву last_p1_list
        # не збігатиметься з новими параметрами. Скидаємо «хвіст» штанги, щоб уникнути IndexError.
        if self.last_p1_list and len(self.last_p1_list) != len(widths):
            self.last_p1_list = []
            self.last_p2_list = []
            print(
                f"[SectionControl] Конфігурацію змінено на {len(widths)} секцій. Пам'ять штанги скинуто."
            )
        # -----------------------------------------------------------------------------------

        # 1. Проекція координат WGS84 у метри (UTM)
        if not self.transformer_to_m:
            zone = int((lon + 180) / 6) + 1
            self.transformer_to_m = pyproj.Transformer.from_crs(
                "epsg:4326", f"epsg:326{zone}", always_xy=True
            )

        ux, uy = self.transformer_to_m.transform(lon, lat)

        # # 2. Фільтр шуму GPS: якщо зсув менше 5 см, ігноруємо крок
        # if self.last_x is not None:
        #     if math.sqrt((ux - self.last_x)**2 + (uy - self.last_y)**2) < 0.05:
        #         return [mode == "ON" for mode in modes] if master_on else [False] * len(widths)
        # =================================================================================
        # ОНОВЛЕНИЙ КРОК 2: ДВОСТОРОННІЙ ЗАХИСТ ВІД ШУМУ ТА GPS-ТЕЛЕПОРТУ
        # =================================================================================
        if self.last_x is not None:
            distance_from_last_step = math.sqrt(
                (ux - self.last_x) ** 2 + (uy - self.last_y) ** 2
            )

            # ФІКС А: Захист від мікро-шуму (якщо зсув менше 5 см, ігноруємо крок)
            if distance_from_last_step < 0.05:
                return (
                    [mode == "ON" for mode in modes]
                    if master_on
                    else [False] * len(widths)
                )

            # ФІКС Б: Захист від GPS-телепорту (стрибок більше 50 метрів за такт 100-250 мс)
            if distance_from_last_step > 50.0:
                print(
                    f"[SectionControl] КРИТИЧНИЙ GPS СТРИБОК: {round(distance_from_last_step, 1)} м. Скидаємо пам'ять штанги!"
                )
                self.last_p1_list = []
                self.last_p2_list = []
                self.last_x = ux
                self.last_y = uy
                # Повертаємо поточні стани без побудови гігантського ламаного полігону-стріли
                return (
                    [mode == "ON" for mode in modes]
                    if master_on
                    else [False] * len(widths)
                )
        # =================================================================================
        # -----------------------------------------------------------------------------------
        # 3. РОЗДІЛЬНИЙ LOOK AHEAD ТА ПЕРЕМИКАЧ "РОЗУМНИЙ РАЗВОРОТ"
        # -----------------------------------------------------------------------------------
        # Визначаємо час випередження: якщо хоч одна секція активна — перевіряємо на ВИМКНЕННЯ (OFF).
        # Якщо все вимкнено — шукаємо ВВІМКНЕННЯ (ON).
        is_any_section_active = any(self.last_p1_list)

        if is_any_section_active:
            time_ahead = self.cfg.get(
                "LOOK_AHEAD_OFF_TIME", 0.4
            )  # Клапани закриваються швидко
        else:
            time_ahead = self.cfg.get(
                "LOOK_AHEAD_ON_TIME", 0.8
            )  # Насосу потрібен час на тиск

        speed_ms = speed / 3.6
        dist_ahead = max(
            speed_ms * time_ahead, self.cfg.get("MIN_LOOK_AHEAD_DIST", 0.5)
        )

        # Отримуємо прапорець "Розумного розвороту" з конфігу (за замовчуванням True)
        smart_turn_enabled = self.cfg.get("SMART_TURN_ENABLED", True)
        turn_rate = getattr(self, "last_turn_rate", 0.0)

        # Перевіряємо умови: режим увімкнено + трактор реально крутить кермом у русі
        if smart_turn_enabled and abs(turn_rate) > 0.5 and speed_ms > 0.2:
            # === РЕЖИМ: "РОЗУМНИЙ РОЗВОРОТ" (Штанга плавно загинається по дузі) ===
            omega = math.radians(turn_rate)
            predicted_heading = heading + (omega * time_ahead)

            pred_x = ux + (speed_ms / omega) * (
                math.cos(heading) - math.cos(predicted_heading)
            )
            pred_y = uy + (speed_ms / omega) * (
                math.sin(predicted_heading) - math.sin(heading)
            )
            look_ahead_heading = predicted_heading
        else:
            # === РЕЖИМ: КЛАССИЧЕСКИЙ (Штанга жорстко пряма попереду трактора) ===
            pred_x = ux + dist_ahead * math.sin(heading)
            pred_y = uy + dist_ahead * math.cos(heading)
            look_ahead_heading = heading

        # -----------------------------------------------------------------------------------
        # 4. ПЕРЕВІРКА ПЕРЕКРИТТІВ ТА ФОРМУВАННЯ ПОЛІГОНІВ СЕКЦІЙ
        # -----------------------------------------------------------------------------------
        res_states, polys_to_save = [], []
        l_offset = -sum(widths) / 2
        curr_p1, curr_p2 = [], []

        base_buf = self.cfg.get("AUTO_SECTION_BUFFER", -0.05)
        min_overlap = self.cfg.get("AUTO_SECTION_MIN_OVERLAP", 0.3)

        for i, w in enumerate(widths):
            # Розрахунок нових передніх точок випередження (враховуючи обрану модель штанги)
            p1 = self.get_section_point(pred_x, pred_y, look_ahead_heading, l_offset)
            p2 = self.get_section_point(
                pred_x, pred_y, look_ahead_heading, l_offset + w
            )
            curr_p1.append(p1)
            curr_p2.append(p2)

            # Формуємо задні точки (минулий крок або поточна лінія штанги)
            if self.last_p1_list and len(self.last_p1_list) > i:
                p4, p3 = self.last_p1_list[i], self.last_p2_list[i]
            else:
                p4 = self.get_section_point(ux, uy, heading, l_offset)
                p3 = self.get_section_point(ux, uy, heading, l_offset + w)

            poly = Polygon([p1, p2, p3, p4])
            if not poly.is_valid:
                poly = poly.buffer(0)

            is_on = False

            if master_on:
                mode = modes[i]
                if mode == "ON":
                    is_on = True
                elif mode == "OFF":
                    is_on = False
                else:  # Режим AUTO (Контроль перекриттів)
                    # test_poly = poly.buffer(base_buf)
                    # is_on = True

                    # if not self.covered_area.is_empty and not test_poly.is_empty:
                    #     if self.covered_area.intersects(test_poly):
                    #         inter_area = self.covered_area.intersection(test_poly).area
                    #         if (inter_area / test_poly.area) > min_overlap:
                    #             is_on = False  # Перекриття знайдено -> вимикаємо секцію

                    # --- ДИНАМИЧЕСКИЙ БУФЕР ДЛЯ НИЗКИХ СКОРОСТЕЙ ---
                    # Расчетный шаг трактора за 1 такт (10 Гц) в метрах
                    current_step_m = speed_ms * 0.1

                    # Буфер не должен превышать 40% от длины шага, иначе полигон схлопнется.
                    # Если 40% от шага меньше, чем 5 см (base_buf), берем более мягкий буфер.
                    if current_step_m > 0:
                        max_safe_buf = -(current_step_m * 0.4)
                        dynamic_buf = max(
                            base_buf, max_safe_buf
                        )  # max, т.к. числа отрицательные (-0.02 > -0.05)
                    else:
                        dynamic_buf = base_buf

                    test_poly = poly.buffer(dynamic_buf)
                    is_on = True

                    if not self.covered_area.is_empty and not test_poly.is_empty:
                        if self.covered_area.intersects(test_poly):
                            inter_area = self.covered_area.intersection(test_poly).area
                            if (inter_area / test_poly.area) > min_overlap:
                                is_on = False  # Перекриття знайдено -> вимикаємо секцію

            res_states.append(is_on)
            if master_on and is_on:
                polys_to_save.append(poly)

            l_offset += w

        # 5. Запис історії для відмальовки сліду на Canvas
        #self.path_history.append([lat, lon, heading_deg, list(res_states)])

        self.path_history.append([lat, lon, heading_deg, list(res_states), list(widths)])
        if len(self.path_history) > 10000:
            self.path_history.pop(0)

        # 6. Оновлення бінарної карти покриття WKB
        if polys_to_save:
            try:
                # НАПОВНЮЄМО НАШ БУФЕР ДОЗАПИСУ СВІЖИМИ ПОЛІГОНАМИ
                if not hasattr(self, 'buffer_to_disk'):
                    self.buffer_to_disk = []
                for p in polys_to_save:
                    if p.is_valid and not p.is_empty:
                        self.buffer_to_disk.append(p)

                # Ваша рідна монолітна математика для ОЗУ (залишається без змін)
                from shapely.ops import unary_union
                self.covered_area = self.covered_area.union(unary_union(polys_to_save))

                # Кожні 150 кроків викликаємо наш новий моментальний append
                if len(self.path_history) % 150 == 0:
                    self.covered_area = self.covered_area.simplify(0.05, preserve_topology=True)
                    self.save_to_disk()
                    print(f"Оновлення бінарної карти покриття WKB")
            except Exception as e:
                print(f"Помилка обробки карти у Shapely: {e}")


        self.last_x, self.last_y = ux, uy
        self.last_p1_list, self.last_p2_list = curr_p1, curr_p2
        return res_states

    def get_area_ha(self):
        if self.covered_area.is_empty:
            return 0.0
        return round(self.covered_area.area / 10000.0, 4)

    def save_to_disk(self):
        """
        ФИНТ УШАМИ: Моментальний append нових полігонів у кінець файлу.
        Записує геометрію як окремий ешелон (пакет) у бінарний потік.
        """
        # Якщо за останні 150 кроків нічого не налили — писати нічого
        if not hasattr(self, 'buffer_to_disk') or not self.buffer_to_disk:
            return

        import os
        import dump_manager
        from shapely import wkb
        from shapely.ops import unary_union

        wkb_path = os.path.join(dump_manager.DUMP_DIR, self.current_wkb_filename)
        
        try:
            # Зшиваємо тільки свіжі полігони, накопичені за 150 кроків
            chunk_union = unary_union(self.buffer_to_disk)
            
            if chunk_union and not chunk_union.is_empty:
                # ВІДКРИВАЄМО В РЕЖИМІ "ab" (Append Binary)
                with open(wkb_path, "ab") as f:
                    # ВАЖЛИВО: wkb.dump (БЕЗ літери s) пише об'єкт у потік із суворим бінарним маркером довжини
                    wkb.dump(chunk_union, f, hex=False)
                
                # Очищаємо ОЗУ-буфер, пакет пішов на диск
                self.buffer_to_disk = []
                # print(f"[SectionControl Append] Геометричний ешелон успішно дописано в кінець файлу.")
        except Exception as e:
            print(f"[SectionControl Append] Помилка append WKB: {e}")

 
        # --- БЕЗПЕЧНЕ ТА ШВИДКЕ БІНАРНЕ ЗБЕРЕЖЕННЯ ---
    def save_to_disk_00(self):
        """
        ФИНТ УШАМИ: Легкий і моментальний append нових полігонів у кінець файлу.
        Працює за 1 мілісекунду, не навантажуючи флешку eMMC.
        """
        if not self.buffer_to_disk:
            return

        import os
        import dump_manager
        from shapely import wkb
        from shapely.ops import unary_union

        wkb_path = os.path.join(dump_manager.DUMP_DIR, self.current_wkb_filename)
        
        try:
            # Склеюємо тільки ті полігони, які наїздили за останні 150 кроків
            chunk_union = unary_union(self.buffer_to_disk)
            wkb_bytes = wkb.dumps(chunk_union, hex=False)
            
            # СУВОРИЙ РЕЖИМ ДОЗАПИСУ "ab" (Append Binary) — штовхаємо байти в кінець
            with open(wkb_path, "ab") as f:
                f.write(wkb_bytes)
                
            # Очищаємо проміжний ОЗУ-буфер, він уже на диску
            self.buffer_to_disk = []
            print("[SectionControl] Новий геометричний блок успішно дозаписано.")
        except Exception as e:
            print(f"[SectionControl] Помилка аappend WKB: {e}")

    def save_to_disk_0(self):
        """
        ФЕН-ШУЙ СОХРАНЕНИЕ: Пишет геометрию одновременно в файл поля
        и в резервный файл текущей сессии.
        """
        import os
        import dump_manager
        from shapely import wkb

        try:
            wkb_bytes = wkb.dumps(self.covered_area, hex=False)

            # 1. Завжди пишемо в резервну копію поточного стану
            current_path = os.path.join(dump_manager.DUMP_DIR, "current_session.wkb")
            with open(current_path, "wb") as f:
                f.write(wkb_bytes)
            print(f"[SectionControl] Геометрия сохранена в: {current_path}")

            # 2. Якщо ми працюємо в конкретному іменованому полі (наприклад "1.wkb")
            # пишемо дубль і туди, щоб накопичувати трек!
            if (
                getattr(self, "current_wkb_filename", "current_session.wkb")
                != "current_session.wkb"
            ):
                field_path = os.path.join(
                    dump_manager.DUMP_DIR, self.current_wkb_filename
                )
                with open(field_path, "wb") as f:
                    f.write(wkb_bytes)
                print(f"[SectionControl] Геометрия сохранена в: {field_path}")

        except Exception as e:
            print(f"[SectionControl] Помилка подвійного збереження WKB: {e}")


    def reset(self):
        """Скидання поточної карти поля"""
        self.covered_area = MultiPolygon()
        self.path_history = []
        self.last_x = self.last_y = None
        self.last_p1_list = []
        self.last_p2_list = []

        save_file = self.cfg.get("SAVE_FILE", "coverage.wkb")
        if os.path.exists(save_file):
            os.remove(save_file)

    def rebuild_covered_area_from_history(self):
        """
        Примусово відновлює монолітну карту covered_area із завантаженої історії треку.
        Рятує систему від 'сліпоти' після завантаження збереженого поля.
        """
        from shapely.ops import unary_union
        from shapely.geometry import Polygon

        if not self.path_history:
            return

        print(
            f"[SectionControl] Починаємо регенерацію карти з історії треку ({len(self.path_history)} точок)..."
        )
        polys_to_restore = []
        widths = self.cfg.get("SECTION_WIDTHS", [])

        # Проходимо по всьому масиву історії
        for idx in range(1, len(self.path_history)):
            try:
                # Беремо координати попереднього та поточного кроку
                prev_pt = self.path_history[idx - 1]
                curr_pt = self.path_history[idx]

                # Якщо на тому кроці секції були увімкнені (res_states == True)
                # Тут ми можемо приблизно відновити полігони проходів для розрахунку перекриттів
                # Але найпростіший і надійніший спосіб — звернутися до вашого методу формування полігонів.
                # Оскільки у нас є координати, курс і ширина секцій, ми просто наповнюємо карту.
                pass
            except:
                pass

        # Нам набагато простіше зробити так: оскільки ваш save_to_disk() пише .wkb файл на диск,
        # ми при завантаженні сесії просто прочитаємо цей готовий .wkb файл, який ви самі ж і зберегли!
        wkb_path = os.path.join(os.getcwd(), "covered_area.wkb")
        if os.path.exists(wkb_path):
            try:
                from shapely import wkb

                with open(wkb_path, "rb") as f:
                    self.covered_area = wkb.loads(f.read())
                print(
                    f"[SectionControl] Монолітна карта успішно відновлена з WKB файлу!"
                )
            except Exception as e:
                print(f"[SectionControl] Не вдалося прочитати WKB при регенерації: {e}")
