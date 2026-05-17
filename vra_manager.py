import os
import geopandas as gpd
from shapely.geometry import Point

class VRAManager:
    def __init__(self):
        self.rate_data = None       # Хранилище геоданных карты
        self.rate_column = 'rate'   # Имя целевой колонки из Shapefile
        self.rate_default = 100.0   # Базовая норма, если карта не загружена

    def load_map_from_zip(self, zip_filename="test_Shapefile.zip"):
        """
        Загружает ZIP-карту из папки 'geodata', расположенной относительно рабочей директории.
        """
        try:
            root_dir = os.getcwd()
            absolute_zip_path = os.path.join(root_dir, "geodata", zip_filename)
            
            print(f"[VRA INFO]: Looking for map at: {absolute_zip_path}")
            
            if not os.path.exists(absolute_zip_path):
                print(f"[VRA ERROR]: Map file not found at {absolute_zip_path}")
                return False

            uri = f"zip://{absolute_zip_path.replace(os.sep, '/')}"
            self.rate_data = gpd.read_file(uri)
            
            if self.rate_data.crs and self.rate_data.crs.to_epsg() != 4326:
                self.rate_data = self.rate_data.to_crs(epsg=4326)
                
            print(f"[VRA SUCCESS]: Loaded {len(self.rate_data)} application zones.")
            return True
        except Exception as e:
            print(f"[VRA ERROR]: Failed to parse Shapefile: {e}")
            return False

    def get_target_rate(self, lon, lat):
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
        if self.rate_data is None:
            return {"status": "no_map"}

        polygons_list = []
        
        # Перебираем все зоны на карте
        for _, row in self.rate_data.iterrows():
            rate_val = float(row[self.rate_column])
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
        print("[VRA INFO]: Карта завдань успішно вивантажена з пам'яті.")

    def activate_existing_map(self, zip_filename):
        """
        Потокобезпечно активує карту, яка вже лежать у папці geodata.
        """
        return self.load_map_from_zip(zip_filename)
