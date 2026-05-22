#include "BoomManager.h"

// Ініціалізуємо PCA9685 за стандартною адресою 0x40
BoomManager::BoomManager(ConfigManager *configMgr) : _pca(0x40)
{
    _configMgr = configMgr;
    _totalSections = 5;
    _hardwareMode = 0;
    
    // Обнуляємо масив станів при старті
    for(int i = 0; i < 16; i++) {
        _sectionStates[i] = 0;
    }
}

void BoomManager::begin()
{
    SystemConfig &cfg = _configMgr->getConfig();
    _totalSections = cfg.total_sections;
    _hardwareMode = cfg.hardware_mode; // 0 - локальні крани, 1 - сервоприводи

    DBG_OUTPUT_PORT.println(F("[BOOM] Starting I2C Bus for PCA9685..."));

    // Ручний запуск шини Wire на наших захищених пінах GPIO 1 та 2
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000); // Швидкість шини 400 кГц (Fast Mode)

    // Запуск самої плати PCA9685
    _pca.begin();

    if (_hardwareMode == 0)
    {
        // --- РЕЖИМ 0: ПРОСТІ КЛАПАНА (НАШ СТЕНД / MOSFET / РЕЛЕ) ---
        _pca.setPWMFreq(1600);
        DBG_OUTPUT_PORT.println(F("[BOOM] PCA9685 ready in Discrete MOSFET/Relay mode."));
    }
    else
    {
        // --- РЕЖИМ 1: СЕРВОПРИВОДИ (МОНСТРИ DS5160) ---
        _pca.setPWMFreq(50);
        DBG_OUTPUT_PORT.println(F("[BOOM] PCA9685 ready in 50Hz Servo Mode (DS5160 ready)."));
    }

    // При старті про всяк випадок жорстко закриваємо всю штангу
    shutDownAll();
}

void BoomManager::setSectionState(int sectionId, int state)
{
    // Захист від дурака: якщо ID прийшов від 1 до 8, переводимо його в індекс масиву (0..7)
    int channelIndex = sectionId - 1;

    // Перевірка коректності меж
    if (channelIndex < 0 || channelIndex >= _totalSections) return;

    // Зберігаємо стан у внутрішній масив
    _sectionStates[channelIndex] = state; 

    bool pinActive = (state == 1); // Базово: 1 - увімкнути вилив

    // Зчитуємо налаштування інверсії з конфігурації
    bool invert = _configMgr->getConfig().invertSections;

    if (invert)
    {
        pinActive = !pinActive; // Якщо NO клапан, то для виливу треба зняти 12В
    }

    // Керуємо конкретним каналом PCA9685 (0..7)
    if (pinActive)
    {
        _pca.setPWM(channelIndex, 0, 4095); // Повний логічний 1 (12В на котушку)
    }
    else
    {
        _pca.setPWM(channelIndex, 0, 0); // Повний логічний 0 (0В на котушку)
    }
}

void BoomManager::shutDownAll()
{
    bool invert = _configMgr->getConfig().invertSections;

    // Закриваємо всі активні канали відповідно до конфігурації
    for (int i = 0; i < _totalSections; i++)
    {
        _sectionStates[i] = 0; // Скидаємо стан в системі

        // Безпека: вилив має повністю зупинитися
        if (invert)
        {
            _pca.setPWM(i, 0, 4095); // NO клапани: подаємо 12В, щоб закрити їх
        }
        else
        {
            _pca.setPWM(i, 0, 0); // NC клапани: знеструмлюємо, щоб вони самі закрилися пружиною
        }
    }
    //DBG_OUTPUT_PORT.println(F("[BOOM] Emergency/Init shutdown: All sections CLOSED."));
}


// #include "BoomManager.h"

// // Ініціалізуємо PCA9685 за стандартною адресою 0x40
// BoomManager::BoomManager(ConfigManager *configMgr) : _pca(0x40)
// {
//     _configMgr = configMgr;
//     _totalSections = 5;
//     _hardwareMode = 0;
// }

// void BoomManager::begin()
// {
//     SystemConfig &cfg = _configMgr->getConfig();
//     _totalSections = cfg.total_sections;
//     _hardwareMode = cfg.hardware_mode; // 0 - локальні крани, 1 - сервоприводи

//     DBG_OUTPUT_PORT.println(F("[BOOM] Starting I2C Bus for PCA9685..."));

//     // Ручний запуск шини Wire на наших захищених пінах GPIO 1 та 2
//     Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000); // Швидкість шини 400 кГц (Fast Mode)

//     // Запуск самої плати PCA9685
//     _pca.begin();

//     if (_hardwareMode == 0)
//     {
//         // --- РЕЖИМ 0: ПРОСТІ КЛАПАНА (НАШ СТЕНД / MOSFET / РЕЛЕ) ---
//         // Для звичайних ключів ставимо максимальну частоту ШІМ модуля (1600 Гц),
//         // щоб виходи працювали фактично як чисті цифрові піни без пульсацій
//         _pca.setPWMFreq(1600);
//         DBG_OUTPUT_PORT.println(F("[BOOM] PCA9685 ready in Discrete MOSFET/Relay mode."));
//     }
//     else
//     {
//         // --- РЕЖИМ 1: СЕРВОПРИВОДИ (МОНСТРИ DS5160) ---
//         // Для сервомоторів потрібна сувора частота 50 Гц (період 20 мс)
//         _pca.setPWMFreq(50);
//         DBG_OUTPUT_PORT.println(F("[BOOM] PCA9685 ready in 50Hz Servo Mode (DS5160 ready)."));
//     }

//     // При старті про всяк випадок жорстко закриваємо всю штангу
//     shutDownAll();
// }
// // Приклад інтеграції в BoomManager.cpp
// // Припускаємо, що об'єкт pca (Adafruit_PWMServoDriver) вже ініціалізований у begin()

// void BoomManager::setSectionState(int id, int state)
// {
//     // Твоя існуюча логіка перевірки id і запису в масив станів
//     // ...

//     bool pinActive = (state == 1); // Базове налаштування: 1 - увімкнути секцію

//     // Зчитуємо налаштування інверсії з конфігурації
//     // (Припустимо, у тебе є вказівник на configManager або конфіг переданий сюди)
//     bool invert = cfg->getConfig().invertSections;

//     if (invert)
//     {
//         pinActive = !pinActive; // Якщо NO клапан, то для ВИЛИВУ (state=1) треба ЗНЯТИ 12В
//     }

//     // sectionPins[id] - це номер каналу на платі PCA9685 (0-15)
//     if (pinActive)
//     {
//         pca.setPWM(sectionPins[id], 0, 4095); // Повний логічний 1 (12В на котушку)
//     }
//     else
//     {
//         pca.setPWM(sectionPins[id], 0, 0); // Повний логічний 0 (0В на котушку)
//     }
// }

// void BoomManager::shutDownAll()
// {
//     bool invert = configManager->getConfig().invertSections;

//     for (int id = 1; id <= maxSectionsCount; id++)
//     {
//         // Записуємо внутрішній стан як вимкнено
//         // ...

//         // Для безпеки: вилив має повністю припинитися
//         if (invert)
//         {
//             pca.setPWM(sectionPins[id], 0, 4095); // NO клапани: подаємо 12В, щоб ЗАКРИТИ їх
//         }
//         else
//         {
//             pca.setPWM(sectionPins[id], 0, 0); // NC клапани: знеструмлюємо, щоб вони ЗАКРИЛИСЯ сами
//         }
//     }
// }

// void BoomManager::setSectionState(int sectionId, int state) {
//     // Переводимо агрономічний ID (1..8) в індекс каналу PCA9685 (0..7)
//     int channel = sectionId - 1;
//     if (channel < 0 || channel >= _totalSections) return;

//     if (_hardwareMode == 0) {
//         // --- КЕРУВАННЯ MOSFET-ОМ НА НАШОМУ СТЕНДІ (Варіант 1, Клапан NC) ---
//         // Регістри PCA9685 мають розрядність 12 біт (значення від 0 до 4095)
//         if (state == 1) {
//             // Увімкнути секцію: видаємо повні 5В на затвор MOSFET-а
//             // Передаємо (канал, час_увімкнення=0, час_вимкнення=4095) -> чисті 100% ШІМ
//             _pca.setPWM(channel, 0, 4095);
//         } else {
//             // Вимкнути секцію: притискаємо затвор до землі (0В)
//             _pca.setPWM(channel, 0, 0);
//         }
//     } else {
//         // --- КЕРУВАННЯ ПОТУЖНОЮ СЕРВОЮ (Майбутній замут з DS5160) ---
//         // Примітка: для сервоприводів на 50 Гц тривалість імпульсу 1мс - це 0°, а 2мс - це 180°
//         // У розрядності 12 біт (4095) це приблизно значення від 204 до 409.
//         if (state == 1) {
//             _pca.setPWM(channel, 0, 409); // Крутимо серву на повне відкриття заслінки TeeJet
//         } else {
//             _pca.setPWM(channel, 0, 204); // Повертаємо серву у нульове положення (кран перекритий)
//         }
//     }
// }

// void BoomManager::shutDownAll() {
//     // Проходимо циклом по всіх каналах і повністю гасимо ШІМ у нуль
//     for (int i = 0; i < _totalSections; i++) {
//         _pca.setPWM(i, 0, 0);
//     }
// }
