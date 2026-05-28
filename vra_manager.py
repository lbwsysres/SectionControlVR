import os
import geopandas as gpd
from shapely.geometry import Point
import math

class VRAManager:
    def __init__(self, cfg=None): # Додаємо cfg сюди
        self.cfg = cfg
        self.rate_data = None       # Хранилище геоданных карты
        self.rate_column = 'rate'   # Имя целевой колонки из Shapefile
        self.rate_default = 0.0   # Базовая норма, если карта не загружена

    def load_map_from_zip(self, zip_filename="test_Shapefile.zip"):
        """
        Загружает ZIP-карту из папки 'geodata', расположенной относительно рабочей директории.
        """
        try:
            root_dir = os.getcwd()
            absolute_zip_path = os.path.join(root_dir, "taskmaps", zip_filename)
            
            print(f"[VRA INFO]: Looking for map at: {absolute_zip_path}")
            
            if not os.path.exists(absolute_zip_path):
                print(f"[VRA ERROR]: Map file not found at {absolute_zip_path}")
                return False

            uri = f"zip://{absolute_zip_path.replace(os.sep, '/')}"
            self.rate_data = gpd.read_file(uri)
            
            self.spatial_index = self.rate_data.sindex 

            if self.rate_data.crs and self.rate_data.crs.to_epsg() != 4326:
                self.rate_data = self.rate_data.to_crs(epsg=4326)
            self.rate_default = self.cfg.get("VRA_RATE_DEFAULT", 99.0)
                
            print(f"[VRA SUCCESS]: Loaded {len(self.rate_data)} application zones.")
            return True
        except Exception as e:
            print(f"[VRA ERROR]: Failed to parse Shapefile: {e}")
            return False
    def get_target_rate(self, lon, lat):
        # 1. Захист: якщо карта не завантажена, віддаємо дефолт
        if self.rate_data is None:
            return self.rate_default

        from shapely.geometry import Point
        point = Point(lon, lat)
        
        try:
            # 2. Перевіряємо, чи створено індекс (sindex)
            spatial_index = getattr(self, 'spatial_index', None)
            
            if spatial_index is not None:
                # Швидкий C++ пошук через Bounding Box точки
                possible_idx = spatial_index.query(point)
                
                if len(possible_idx) > 0:
                    # Працюємо через суворий системний метод .iloc для зрізів
                    possible_matches = self.rate_data.iloc[possible_idx]
                    matched_zones = possible_matches[possible_matches.geometry.contains(point)]
                    
                    if not matched_zones.empty:
                        # Дістаємо значення колонки 'rate' без збою індексів таблиці
                        return float(matched_zones['rate'].values[0])
            
            # 3. НАДІЙНИЙ ФОЛБЕК: Якщо індекс збоїть або мовчить,
            # виконується ваш ОРИГІНАЛЬНИЙ, перевірений часом код:
            matched_zones = self.rate_data[self.rate_data.geometry.contains(point)]
            if not matched_zones.empty:
                return float(matched_zones.iloc[0]['rate'])
                
        except Exception as e:
            print(f"[VRA Error] Помилка індексу пошуку карти: {e}")
            
        return self.rate_default

    def get_target_rate_0(self, lon, lat):
        if self.rate_data is None or getattr(self, 'spatial_index', None) is None:
            return self.rate_default

        from shapely.geometry import Point
        point = Point(lon, lat)
        
        # 1. Индекс за микросекунды находит ID только тех зон, которые находятся прямо под точкой
        possible_matches_idx = self.spatial_index.query(point)
        
        if len(possible_matches_idx) == 0:
            return self.rate_default
            
        # 2. Берем из таблицы только эти найденные зоны (обычно это 1 зона)
        possible_matches = self.rate_data.iloc[possible_matches_idx]
        
        # 3. Ваша родная точная проверка входжения точки
        matched_zones = possible_matches[possible_matches.geometry.contains(point)]

        if not matched_zones.empty:
            return float(matched_zones.iloc.get('rate', self.rate_default))
            
        return self.rate_default


    def get_target_rate_1(self, lon, lat):
        """
        Принимает текущую GPS-координату секции/форсунки.
        Возвращает норму внесения из Shapefile.
        """
        if self.rate_data is None or self.rate_data.empty:
            return self.rate_default

        point = Point(lon, lat)
        matched_zones = self.rate_data[self.rate_data.geometry.contains(point)]
        
        if not matched_zones.empty:
            try:
                raw_val = float(matched_zones.iloc[0][self.rate_column])
            except (ValueError, TypeError):
                # Если в ячейке текст или битые данные — возвращаем дефолт
                return self.rate_default
            
            # Защита от NaN: если значение не определено, возвращаем базовую норму
            if math.isnan(raw_val):
                return self.rate_default # или 0.0, в зависимости от вашей логики (лучше дефолт, чтобы не отключить форсунки на ходу)
                
            return raw_val
        
        # Если трактор/опрыскиватель выехал за пределы карты поля
        return self.rate_default
    
    def get_target_rate_2(self, lon, lat):
        """
        Принимает текущую GPS-координату секции/форсунки.
        Возвращает норму внесения из Shapefile.
        """
        if self.rate_data is None:
            return self.rate_default

        point = Point(lon, lat)
        matched_zones = self.rate_data[self.rate_data.geometry.contains(point)]
        
        if not matched_zones.empty:
            # Безопасно вытягиваем ячейку по имени колонки 'rate' из первой совпавшей строки
            return float(matched_zones.iloc[0][self.rate_column])
        
        return 0.0
    def get_map_polygons(self):
        """
        Возвращает плоский массив полигонов с их рейтами, 
        минимальное и максимальное значение для Canvas-фронтенда.
        """
        if self.rate_data is None or self.rate_data.empty:
            return {"status": "no_map"}

        polygons_list = []
        
        # Перебираем все зоны на карте
        for _, row in self.rate_data.iterrows():
            try:
                raw_val = float(row[self.rate_column])
            except (ValueError, TypeError):
                raw_val = float('nan')

            # Фикс №1: Если NaN — ставимо 0.0, інакше — залишаємо значення
            rate_val = 0.0 if math.isnan(raw_val) else raw_val
            geom = row['geometry']
            
            # Извлекаем координаты внешней границы полигона
            if geom is None:
                continue
            elif geom.geom_type == 'Polygon':
                coords = list(geom.exterior.coords)
            elif geom.geom_type == 'MultiPolygon':
                coords = []
                # Итерируемся по внутренним полигонам MultiPolygon
                for poly in geom.geoms:
                    coords.extend(list(poly.exterior.coords))
            else:
                continue # Пропускаем линии или точки, если они есть на карте
            
            # Для твоего Canvas важен порядок [Lat, Lon]
            # В Shapefile координаты лежат как (X, Y) -> (Lon, Lat), меняем их местами:
            formatted_coords = [[pt[1], pt[0]] for pt in coords]
            
            polygons_list.append({
                "rate": rate_val,
                "points": formatted_coords
            })

        # Фикс №2: Безопасный расчет минимума и максимума без NaN
        # Сначала очищаем колонку от NaN во временной переменной для расчетов
        clean_rates = self.rate_data[self.rate_column].dropna()

        if not clean_rates.empty:
            min_rate = float(clean_rates.min())
            max_rate = float(clean_rates.max())
        else:
            # Если вся колонка состояла из NaN
            min_rate = 0.0
            max_rate = self.rate_default

        # Защита от одинаковых значений (чтобы не было деления на 0 на фронтенде)
        if min_rate == max_rate:
            min_rate = max_rate * 0.8 if max_rate != 0 else -1.0

        return {
            "status": "success",
            "min_rate": min_rate,
            "max_rate": max_rate,
            "rate_default": self.rate_default,
            "polygons": polygons_list
        }

    def get_map_polygons_1(self):
        """
        Возвращает плоский массив полигонов с их рейтами, 
        минимальное и максимальное значение для Canvas-фронтенда.
        """
        if self.rate_data is None:
            return {"status": "no_map"}

        polygons_list = []
        
        # Перебираем все зоны на карте
        for _, row in self.rate_data.iterrows():
            #rate_val = float(row[self.rate_column])
            raw_val = float(row[self.rate_column])
            # Якщо NaN — ставимо 0.0, інакше — залишаємо пораховане значення
            rate_val = 0.0 if math.isnan(raw_val) else raw_val
            geom = row['geometry']
            
            # Извлекаем координаты внешней границы полигона
            if geom.geom_type == 'Polygon':
                coords = list(geom.exterior.coords)
            elif geom.geom_type == 'MultiPolygon':
                coords = []
                # Итерируемся по внутренним полигонам MultiPolygon
                for poly in geom.geoms:
                    coords.extend(list(poly.exterior.coords))
            else:
                continue # Пропускаем линии или точки, если они есть на карте
            
            # Для твоего Canvas важен порядок [Lat, Lon]
            # В Shapefile координаты лежат как (X, Y) -> (Lon, Lat), меняем их местами:
            formatted_coords = [[pt[1], pt[0]] for pt in coords]
            
            polygons_list.append({
                "rate": rate_val,
                "points": formatted_coords
            })

        # Находим экстремумы для динамического градиента цветов на Canvas
        min_rate = float(self.rate_data[self.rate_column].min())
        max_rate = float(self.rate_data[self.rate_column].max())
        if min_rate == max_rate:
            min_rate = max_rate * 0.8

        return {
            "status": "success",
            "min_rate": min_rate,
            "max_rate": max_rate,
            "rate_default": self.rate_default,
            "polygons": polygons_list
        }
    def reset_manager(self):
            """
            Полностью выгружает карту из памяти и возвращает менеджер к дефолтному состоянию.
            """
            self.rate_data = None
            print("[VRA INFO]: Карта задач выгружена из памяти системы.")
    def deactivate_map(self):
        """
        [ФЕНШУЙ]: Повністю вивантажує карту з оперативної пам'яті.
        Рушій геометрії автоматично перейде на rate_default.
        """
        self.rate_data = None
        self.spatial_index = None  # Очищення ОЗУ
        print("[VRA INFO]: Карта завдань успішно вивантажена з пам'яті.")

    def activate_existing_map(self, zip_filename):
        """
        Потокобезпечно активує карту, яка вже лежать у папці geodata.
        """
        return self.load_map_from_zip(zip_filename)
