# =======================================================================
# section_engine.py --- ЧАСТИНА 2 З 4 (ОЗУ-БУФЕРИЗАЦІЯ ТА ЗАХИСТ eMMC)
# =======================================================================
import math
import pyproj
import os
import time
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import wkb
import struct


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

        # --- ОЗУ-БУФЕРИ ДЛЯ ЗАХИСТУ ВІД ЗНОСУ eMMC ---
        self.buffer_to_disk = []  # Сюди збираємо полігони
        self.track_buffer_to_disk = []  # Сюди збираємо точки треку [lat, lon, hdg]

        # ==========================================
        # ІНІЦІАЛІЗАЦІЯ СИСТЕМИ ЧАНКІВ
        # ==========================================
        self.CHUNK_SIZE_METERS = 400.0  # 400 метрів (при zoom=10 це 4000 пікселів текстури PixiJS)
        self.base_field_x = None        # Базова координата X найпершої точки поля (для відносного відліку)
        self.base_field_y = None        # Базова координата Y найпершої точки поля

    def get_chunk_key(self, tx, ty):
        """
        Рахує унікальний локальний ключ чанка поля.
        Якщо базової точки ще немає — поточна позиція фіксується як старт поля (0_0).
        """
        if self.base_field_x is None or self.base_field_y is None:
            self.base_field_x = tx
            self.base_field_y = ty
            print(f"[CHUNKS CORE] Базу локальних чанків встановлено: X={tx:.1f}м, Y={ty:.1f}м")
            
        # Рахуємо чисті відносні метри всередині нашого поля
        local_x = tx - self.base_field_x
        local_y = ty - self.base_field_y
        
        # Цілочисельне ділення дає індекс квадрата (може бути і від'ємним, це нормально)
        chunk_x = int(local_x // self.CHUNK_SIZE_METERS)
        chunk_y = int(local_y // self.CHUNK_SIZE_METERS)
        
        return f"{chunk_x}_{chunk_y}"



    def get_section_point(self, tx, ty, th_rad, offset):
        """Розрахунок координат конкретної форсунки з урахуванням винесення штанги назад."""
        offset_back = self.cfg.get("OFFSET_BACK", 0.0)
        bx = tx - offset_back * math.sin(th_rad)
        by = ty - offset_back * math.cos(th_rad)
        res_x = bx + offset * math.cos(th_rad)
        res_y = by - offset * math.sin(th_rad)
        return (res_x, res_y)

    def save_to_disk_old(self):
        """
        ЕТАЛОННИЙ ЗАПИС ЕШЕЛОНУ: Пакує буфер ОЗУ в чистий MultiPolygon.
        Один швидкий бінарний запис захищає eMMC від зносу.
        """
        print("[save_to_disk] Start.")
        if not hasattr(self, "buffer_to_disk") or not self.buffer_to_disk:
            return
        import dump_manager
        wkb_path = os.path.join(dump_manager.DUMP_DIR, self.current_wkb_filename)

        try:
            # Фільтруємо тільки повністю валідні полігони проходів
            valid_polys = [
                p for p in self.buffer_to_disk if p.is_valid and not p.is_empty
            ]

            if valid_polys:
                # Пакуємо в монолітний MultiPolygon, щоб уникнути склеювання байтів
                chunk_multipoly = MultiPolygon(valid_polys)

                # Дозаписуємо в кінець файлу (Режим "ab")
                with open(wkb_path, "ab") as f:
                    wkb.dump(chunk_multipoly, f, hex=False)

                # Очищаємо оперативний буфер, пакет успішно зафіксовано на eMMC
                self.buffer_to_disk = []
        except Exception as e:
            print(f"[SectionControl eMMC-Save Error] Помилка запису ешелону WKB: {e}")

    def save_to_disk(self):
        """
        ШВИДКИЙ БІНАРНИЙ ДОЗАПИС (Стиль C++/Delphi).
        Формат на диску: [4 байти довжини блока (Big-Endian uint32)] + [Самі байти WKB].
        Ідеально для частоти 10 Гц: миттєво, без читання диска, захищає eMMC.
        """
        if not hasattr(self, "buffer_to_disk") or not self.buffer_to_disk:
            return
            
        import dump_manager
        wkb_path = os.path.join(dump_manager.DUMP_DIR, self.current_wkb_filename)

        try:
            # Фільтруємо тільки повністю валідні полігони
            valid_polys = [p for p in self.buffer_to_disk if p.is_valid and not p.is_empty]
            if not valid_polys:
                return

            # Пакуємо пачку в один MultiPolygon для цього блоку
            chunk_multipoly = MultiPolygon(valid_polys)
            
            # Перетворюємо геометрію в бінарну строку в пам'яті (ОЗУ)
            wkb_bytes = wkb.dumps(chunk_multipoly, hex=False)
            bytes_len = len(wkb_bytes)

            # Відкриваємо файл на дозапис ("ab")
            with open(wkb_path, "ab") as f:
                # Записуємо заголовок довжини (4 байти, unsigned int)
                f.write(struct.pack(">I", bytes_len))
                # Дописуємо тіло геометрії
                f.write(wkb_bytes)
                # Примусово виштовхуємо буфери ОС на флешку (захист від збою живлення трактора)
                f.flush()
                os.fsync(f.fileno()) 

            # Очищаємо буфер, пачка успішно пішла на eMMC
            self.buffer_to_disk = []

        except Exception as e:
            print(f"[SectionControl eMMC-Save Error] Помилка дозапису блоку WKB: {e}")



    def reset(self):
        """Повне очищення поточної сесії в ОЗУ"""
        self.covered_area = MultiPolygon()
        self.path_history = []
        self.buffer_to_disk = []
        self.track_buffer_to_disk = []
        self.last_x = self.last_y = None
        self.last_p1_list = []
        self.last_p2_list = []
        self.base_field_x = None
        self.base_field_y = None

        print("[SectionControl] Карта покриття та ОЗУ-буфери очищені.")

    # =======================================================================
    # section_engine.py --- ЧАСТИНА 3 З 4 (МАТЕМАТИКА ПОВОРОТІВ ТА LOOK AHEAD)
    # =======================================================================

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
                v_sec = v_tr - (omega * (current_pos + w / 2))
                ratio = (v_sec / v_tr) * 100 if v_tr > 0 else 100
                targets.append(max(limits[0], min(limits[1], ratio)))
                current_pos += w

        if not self.prev_percents or len(self.prev_percents) != num_sections:
            self.prev_percents = [100.0] * num_sections

        filtered = []
        for i in range(num_sections):
            val = self.prev_percents[i] + smooth * (targets[i] - self.prev_percents[i])
            filtered.append(val)

        self.last_turn_rate = turn_rate
        self.prev_percents = filtered
        return [int(round(x)) for x in filtered]

    #def process(self, lat, lon, heading_deg, speed):
    # Було: def process(self, lat, lon, heading_deg, speed_kmh, master_on):
    # Стане:
    #def process(self, lat, lon, heading_deg, speed, master_on, chunk_key="0_0"):
    def process(self, lat, lon, heading_deg, speed, chunk_key="0_0"):

        # LBW - переделать вызов master_on widths modes - из main
        """Головна логіка секційного контролю"""
        master_on = self.cfg.get("MASTER_SW", False)
        widths = self.cfg.get("SECTION_WIDTHS", [])
        modes = self.cfg.get("SECTION_MODES", ["AUTO"] * len(widths))
        heading = math.radians(heading_deg)

        # Захист від зміни конфігурації штанги на ходу
        current_boom_width = sum(widths)
        if not hasattr(self, "_last_boom_width"):
            self._last_boom_width = current_boom_width

        if (self.last_p1_list and len(self.last_p1_list) != len(widths)) or (
            self._last_boom_width != current_boom_width
        ):
            self.last_p1_list = []
            self.last_p2_list = []
            self.last_x = None
            self.last_y = None
            self._last_boom_width = current_boom_width
            print(
                f"[SectionControl] Штангу змінено ({current_boom_width}м). Пам'ять осей скинуто!"
            )

        # 1. Проекція координат WGS84 у метри (UTM)
        if not self.transformer_to_m:
            zone = int((lon + 180) / 6) + 1
            self.transformer_to_m = pyproj.Transformer.from_crs(
                "epsg:4326", f"epsg:326{zone}", always_xy=True
            )

        ux, uy = self.transformer_to_m.transform(lon, lat)

        # 2. Двосторонній захист від шуму та GPS-телепорту
        if self.last_x is not None:
            distance_from_last_step = math.sqrt(
                (ux - self.last_x) ** 2 + (uy - self.last_y) ** 2
            )
            if distance_from_last_step < 0.05:
                return (
                    [mode == "ON" for mode in modes]
                    if master_on
                    else [False] * len(widths)
                )

            if distance_from_last_step > 50.0:
                print(
                    f"[SectionControl] КРИТИЧНИЙ GPS СТРИБОК: {round(distance_from_last_step, 1)} м. Скидаємо штангу!"
                )
                self.last_p1_list = []
                self.last_p2_list = []
                self.last_x = ux
                self.last_y = uy
                return (
                    [mode == "ON" for mode in modes]
                    if master_on
                    else [False] * len(widths)
                )

        # 3. РОЗДІЛЬНИЙ LOOK AHEAD ТА ПЕРЕМИКАЧ "РОЗУМНИЙ РОЗВОРОТ"
        is_any_section_active = any(self.last_p1_list)
        if is_any_section_active:
            time_ahead = self.cfg.get("LOOK_AHEAD_OFF_TIME", 0.4)
        else:
            time_ahead = self.cfg.get("LOOK_AHEAD_ON_TIME", 0.8)

        speed_ms = speed / 3.6
        dist_ahead = max(
            speed_ms * time_ahead, self.cfg.get("MIN_LOOK_AHEAD_DIST", 0.5)
        )
        smart_turn_enabled = self.cfg.get("SMART_TURN_ENABLED", True)
        turn_rate = getattr(self, "last_turn_rate", 0.0)

        if smart_turn_enabled and abs(turn_rate) > 0.5 and speed_ms > 0.2:
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
            pred_x = ux + dist_ahead * math.sin(heading)
            pred_y = uy + dist_ahead * math.cos(heading)
            look_ahead_heading = heading
        # =======================================================================
        # section_engine.py --- ЧАСТИНА 4 З 4 (ЗАЛПОВИЙ ЗАПИС ТА СИНХРОНІЗАЦІЯ)
        # =======================================================================

        # 4. ПЕРЕВІРКА ПЕРЕКРИТТІВ ТА ФОРМУВАННЯ ПОЛІГОНІВ СЕКЦІЙ
        res_states, polys_to_save = [], []
        l_offset = -sum(widths) / 2
        curr_p1, curr_p2 = [], []
        base_buf = self.cfg.get("AUTO_SECTION_BUFFER", -0.05)
        min_overlap = self.cfg.get("AUTO_SECTION_MIN_OVERLAP", 0.3)

        for i, w in enumerate(widths):
            p1 = self.get_section_point(pred_x, pred_y, look_ahead_heading, l_offset)
            p2 = self.get_section_point(
                pred_x, pred_y, look_ahead_heading, l_offset + w
            )
            curr_p1.append(p1)
            curr_p2.append(p2)

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
                else:
                    # Динамічний буфер для захисту від схлопування полігонів
                    current_step_m = speed_ms * 0.1
                    if current_step_m > 0:
                        max_safe_buf = -(current_step_m * 0.4)
                        dynamic_buf = max(base_buf, max_safe_buf)
                    else:
                        dynamic_buf = base_buf

                    test_poly = poly.buffer(dynamic_buf)
                    is_on = True

                    if not self.covered_area.is_empty and not test_poly.is_empty:
                        if self.covered_area.intersects(test_poly):
                            inter_area = self.covered_area.intersection(test_poly).area
                            if (inter_area / test_poly.area) > min_overlap:
                                is_on = False

            res_states.append(is_on)
            if master_on and is_on:
                polys_to_save.append(poly)
            l_offset += w


        # ==============================================================================
        # МОДЕРНІЗОВАНИЙ ЗАПИС ІСТОРІЇ З КЛЮЧЕМ ЧАНКА
        # ==============================================================================
        # 5. Запис історії для PixiJS на фронтенд (чистий плоский масив масивів)
        self.path_history.append(
            [chunk_key, lat, lon, heading_deg, list(res_states), list(widths)]
        )

        if len(self.path_history) > 100000:
            self.path_history.pop(0)

        # Перетворюємо масиви в рядки для текстового логу треку
        states_str = "-".join(["1" if s else "0" for s in res_states])
        widths_str = "-".join([str(w) for w in widths])

        # Кладемо в ОЗУ-буфер текстового треку
        self.track_buffer_to_disk.append([chunk_key, lat, lon, heading_deg, states_str, widths_str])

        # 6. ОНОВЛЕННЯ ТОЧНОЇ КАРТИ В ОЗУ
        if polys_to_save:
            try:
                for p in polys_to_save:
                    if p.is_valid and not p.is_empty:
                        self.buffer_to_disk.append(p)

                # Робоча карта в ОЗУ для логіки перекриттів (завжди 100% точна, БЕЗ simplify)
                self.covered_area = self.covered_area.union(unary_union(polys_to_save))
            except Exception as e:
                print(f"[SectionControl RAM Error] Помилка об’єднання карт в ОЗУ: {e}")

        # --- СИНХРОННЕ ПАКЕТНЕ ЗБЕРЕЖЕННЯ (ЗАХИСТ eMMC) ---
        # На столі тестуємо через % 30, на полі міняємо на % 300 (раз на 30 сек при 10 Гц)
        if len(self.path_history) % 30 == 0:
            try:
        #         # Оптимізуємо моноліт в пам'яті, щоб інтерфейс вебу не гальмував
        #         self.covered_area = self.covered_area.simplify(
        #             0.05, preserve_topology=True
        #         )
               
                # А) Скидаємо бінарні полігони покриття новим методом фіксованої довжини
                if self.buffer_to_disk:
                    self.save_to_disk()

                # Б) Скидаємо текстові точки треку одним махом
                import dump_manager
                if self.track_buffer_to_disk:
                    dump_manager.append_batch_to_track_file(self.track_buffer_to_disk)
                    self.track_buffer_to_disk = []  # Очищаємо ОЗУ-буфер треку

                print(f"[SectionControl eMMC-Safe] Пачка успішно зафіксована на диск. Буфери чисті.")
            except Exception as e:
                print(f"[SectionControl Sync Error] Помилка синхронізації з диском: {e}")


        # 5. Запис історії для відмальовки сліду на Canvas (в ОЗУ)
        # self.path_history.append(
        #     [chunk_key, lat, lon, heading_deg, list(res_states), list(widths)]
        # )

        # # LBW 
        # if len(self.path_history) > 100000:
        #     self.path_history.pop(0)
        # # --- ЗБЕРІГАЄМО ПОВНУ 5-ЕЛЕМЕНТНУ СТРУКТУРУ ДЛЯ ВЕБ-CANVAS ---
        # # Перетворюємо масив станів [True, False...] у рядок "1-0-1..."
        # states_str = "-".join(["1" if s else "0" for s in res_states])
        # # Перетворюємо ширини [0.8, 0.7...] у рядок "0.8-0.7..."
        # widths_str = "-".join([str(w) for w in widths])

        # # Кладемо в ОЗУ-буфер для залпового скидання на диск
        # self.track_buffer_to_disk.append([chunk_key,lat, lon, heading_deg, states_str, widths_str])
        # # 6. ОНОВЛЕННЯ КАРТИ В ОЗУ ТА ЗАЛПОВИЙ ЗАПИС НА ДИСК (Кожні 300 точок)
        # if polys_to_save:
        #     try:
        #         for p in polys_to_save:
        #             if p.is_valid and not p.is_empty:
        #                 self.buffer_to_disk.append(p)
        #         # Синхронна монолітна карта в ОЗУ для логіки перекриттів
        #         self.covered_area = self.covered_area.union(unary_union(polys_to_save))
        #     except Exception as e:
        #         print(f"[SectionControl RAM Error] Помилка об’єднання карт в ОЗУ: {e}")

        # # --- СИНХРОННЕ ПАКЕТНЕ ЗБЕРЕЖЕННЯ (ЗАХИСТ eMMC) ---
        # if len(self.path_history) % 30 == 0:
        #     try:
        #         # Оптимізуємо моноліт в пам'яті, щоб інтерфейс вебу не гальмував
        #         self.covered_area = self.covered_area.simplify(
        #             0.05, preserve_topology=True
        #         )
        #         # А) Скидаємо бінарні полігони покриття одним махом
        #         if self.buffer_to_disk:
        #             self.save_to_disk()
        #         # Б) Скидаємо 300 текстових точок треку одним махом
        #         import dump_manager
        #         if self.track_buffer_to_disk:
        #             dump_manager.append_batch_to_track_file(self.track_buffer_to_disk)
        #             self.track_buffer_to_disk = []  # Очищаємо ОЗУ-буфер треку
        #         print(
        #             f"[SectionControl eMMC-Safe] Пачка з 300 точок успішно зафіксована на диск."
        #         )
        #     except Exception as e:
        #         print(
        #             f"[SectionControl Sync Error] Помилка синхронізації з диском: {e}"
        #         )

        self.last_x, self.last_y = ux, uy
        self.last_p1_list, self.last_p2_list = curr_p1, curr_p2
        return res_states

    def get_area_ha(self):
        """Розрахунок площі з ОЗУ"""
        if self.covered_area.is_empty:
            return 0.0
        return round(self.covered_area.area / 10000.0, 4)
