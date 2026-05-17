import os
import geopandas as gpd

# 1. Автоматически определяем папку, в которой лежит этот скрипт (SYS/geodata)
script_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Формируем точный абсолютный путь к вашему zip-архиву
zip_filename = "test_Shapefile.zip" # Укажите точное имя (регистр важен!)
absolute_zip_path = os.path.join(script_dir, zip_filename)

print(f"Ищем файл по пути: {absolute_zip_path}")

try:
    # Проверяем, существует ли файл физически перед тем как читать
    if not os.path.exists(absolute_zip_path):
        raise FileNotFoundError(f"Файл не найден по пути {absolute_zip_path}. Проверьте имя файла!")

    # Передаем geopandas правильный абсолютный URI для ZIP-архива
    # Важно: используем нормализованные слеши для GDAL
    uri = f"zip://{absolute_zip_path.replace(os.sep, '/')}"
    gdf = gpd.read_file(uri)
    
    print("\n--- УСПЕШНО НАЙДЕНО ПОЛЕ ---")
    print(f"Количество зон (полигонов): {len(gdf)}")
    print(f"Система координат (CRS): {gdf.crs}")
    print("\nДоступные колонки в вашей таблице:")
    print(list(gdf.columns))
    
    print("\nПервые 3 строки вашей карты:")
    print(gdf.head(3))

except Exception as e:
    print(f"\nОшибка чтения: {e}")
    print("Убедитесь, что внутри zip файлы (.shp, .dbf) лежат сразу в корне архива, а не запакованы внутри подпапки.")
