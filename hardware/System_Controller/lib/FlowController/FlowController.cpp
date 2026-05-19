#include "FlowController.h"
#include "driver/pulse_cnt.h" // Підключаємо новий апаратний драйвер лічильника для ядра 3.х

// Глобальний хендл для нашого апаратного лічильника
pcnt_unit_handle_t pcnt_unit = nullptr;
// Додаємо змінні для накопичення імпульсів на початку файлу або всередині класу
//int pulse_history[10] = {0}; // Буфер на 10 тактів (10 * 50мс = 500мс)
//int history_idx = 0;
int pulse_history[20] = {0}; 
int history_idx = 0;

FlowController::FlowController(ConfigManager* configMgr, VraNetworkManager* netMgr) {
    _configMgr = configMgr;
    _netMgr = netMgr;
    _targetFlow = 0.0f;
    _currentFlow = 0.0f;
    _virtualPressure = 0.0f;
    _currentPwm = 0;
    
    // ГРАНАТА ЗНЕШКОДЖЕНА: Перемикаємося на РЕАЛЬНУ ВОДУ з відра!
    _emulationMode = false; 
    
    _Kp = 1.8f;  // Трохи піднімемо жорсткість для реального насоса
    _Ki = 0.25f;
    _integral = 0.0f;
}

void FlowController::begin() {
    SystemConfig& cfg = _configMgr->getConfig();
    
    // 1. Налаштування апаратного ШІМ для драйвера BTS7960
    ledcAttach(PUMP_R_PWM_PIN, PUMP_PWM_FREQ, PUMP_PWM_RES);
    ledcAttach(PUMP_L_PWM_PIN, PUMP_PWM_FREQ, PUMP_PWM_RES);
    ledcWrite(PUMP_R_PWM_PIN, 0);
    ledcWrite(PUMP_L_PWM_PIN, 0);
    


    // 2. ІНІЦІАЛІЗАЦІЯ АПАРАТНОГО ЛІЧИЛЬНИКА ІМПУЛЬСІВ (PCNT) ДЛЯ ЯДРА 3.х
    // Конфігурація самого юніта лічильника
    pcnt_unit_config_t unit_config = {
        .low_limit = -32000,
        .high_limit = 32000,
        .flags = { .accum_count = true } // Дозволяємо намотувати імпульси безперервно
    };
    pcnt_new_unit(&unit_config, &pcnt_unit);

    // Конфігурація вхідного піна для датчика Холла (Витратомір G1/2" на GPIO 4)
    pcnt_chan_config_t chan_config = {
        .edge_gpio_num = 4,            // Наш сигнальний пін витратоміра
        .level_gpio_num = -1,          // Напрямок рахунку не міняється, ставимо -1
        .flags = { .io_loop_back = false }
    };
    pcnt_channel_handle_t pcnt_chan = nullptr;
    pcnt_new_channel(pcnt_unit, &chan_config, &pcnt_chan);

    // Налаштовуємо дію: рахувати кожен позитивний фронт імпульсу (росте вгору)
    //pcnt_channel_set_edge_action(pcnt_chan, PCNT_EDGE_ACT_INCREMENT, PCNT_EDGE_ACT_NONE);
    pcnt_channel_set_edge_action(pcnt_chan, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // ЗАХИСТ ВІД НАВЕДЕНЬ ТА ШУМІВ (Апаратний Glitch Фільтр):
    // Ігноруємо будь-які імпульси, коротші за 1000 тактів процесора (захищає від іскор мотора)
    pcnt_glitch_filter_config_t filter_config = {
        .max_glitch_ns = 1000,
    };
    pcnt_unit_set_glitch_filter(pcnt_unit, &filter_config);

    // Вмикаємо та запускаємо наш залізничний лічильник у роботу
    pcnt_unit_enable(pcnt_unit);
    pcnt_unit_clear_count(pcnt_unit);
    pcnt_unit_start(pcnt_unit);

    DBG_OUTPUT_PORT.println(F("[FLOW] Hardware PCNT Pulse Counter started on GPIO 4."));
}

void FlowController::setTargetFlow(float flow) {
    _targetFlow = flow;
    if (_targetFlow < 0.1f) _targetFlow = 0.0f;
}

void FlowController::update(bool isEmergency, int activeSectionsCount) {
    if (isEmergency || activeSectionsCount == 0 || _targetFlow <= 0.05f) {
        _currentPwm = 0;
        ledcWrite(PUMP_R_PWM_PIN, 0);
        ledcWrite(PUMP_L_PWM_PIN, 0);
        _integral = 0.0f;
        _currentFlow = 0.0f;
        _virtualPressure = 0.0f;
        pcnt_unit_clear_count(pcnt_unit);
        memset(pulse_history, 0, sizeof(pulse_history)); 
        return;
    }

    // 1. Зчитуємо імпульси з залізничного лічильника
    int raw_pulse_count = 0;
    pcnt_unit_get_count(pcnt_unit, &raw_pulse_count);
    pcnt_unit_clear_count(pcnt_unit);
    if (raw_pulse_count < 0) raw_pulse_count = 0;

    // Зчитуємо свіжі налаштування користувача з пам'яті
    SystemConfig& cfg = _configMgr->getConfig();
    
    // Захист від дурня: вікно не може бути менше 1 і більше нашого ліміту 20
    int window_size = cfg.flow_window;
    if (window_size < 1) window_size = 1;
    if (window_size > 20) window_size = 20;

    // 2. ДИНАМІЧНЕ КІЛЬЦЕВЕ НАКОПИЧЕННЯ
    pulse_history[history_idx] = raw_pulse_count;
    history_idx = (history_idx + 1) % window_size; // Індекс крутиться чітко під розмір вікна

    // Рахуємо суму імпульсів строго по динамічному вікну користувача
    int total_pulses = 0;
    for (int i = 0; i < window_size; i++) {
        total_pulses += pulse_history[i];
    }

    // Універсальна математична формула часу:
    // Один такт триває 50мс (0.05 сек). Повне вікно триває (window_size * 0.05) секунд.
    // Щоб перевести суму імпульсів у хвилину (60 сек), множимо її на коефіцієнт:
    // time_factor = 60.0 / (window_size * 0.05) -> що математично дорівнює (1200.0 / window_size)
    if (total_pulses > 0) {
        float time_factor = 1200.0f / (float)window_size;
        _currentFlow = ((float)total_pulses * time_factor) / (float)cfg.flow_pulses;
    } else {
        _currentFlow = 0.0f;
    }

    // Розрахунок віртуального тиску
    _virtualPressure = (_currentFlow / (float)activeSectionsCount) * 0.6f;

    // 3. РОБОТА ПІД-РЕГУЛЯТОРА
    float error = _targetFlow - _currentFlow;
    float allowedError = _targetFlow * ((float)cfg.deadband / 100.0f);
    
    if (abs(error) > allowedError) {
        _integral += error * 0.05f;
        if (_integral > 400.0f) _integral = 400.0f;
        if (_integral < -400.0f) _integral = -400.0f;
        
        float controlSignal = (error * _Kp) + (_integral * _Ki);
        _currentPwm += (int)controlSignal;
    }

    int userMaxPwm = (cfg.pwm_max * 1023) / 100;
    int userMinPwm = (cfg.pwm_min * 1023) / 100;
    
    if (_currentPwm > userMaxPwm) _currentPwm = userMaxPwm;
    if (_currentPwm < userMinPwm) _currentPwm = userMinPwm;

    ledcWrite(PUMP_R_PWM_PIN, _currentPwm);
    ledcWrite(PUMP_L_PWM_PIN, 0);
}

/*
void FlowController::update(bool isEmergency, int activeSectionsCount) {
    if (isEmergency || activeSectionsCount == 0 || _targetFlow <= 0.05f) {
        _currentPwm = 0;
        ledcWrite(PUMP_R_PWM_PIN, 0);
        ledcWrite(PUMP_L_PWM_PIN, 0);
        _integral = 0.0f;
        _currentFlow = 0.0f;
        _virtualPressure = 0.0f;
        pcnt_unit_clear_count(pcnt_unit);
        memset(pulse_history, 0, sizeof(pulse_history)); // Очищаємо історію
        return;
    }

    // 1. Зчитуємо імпульси за поточні 50 мс
    int raw_pulse_count = 0;
    pcnt_unit_get_count(pcnt_unit, &raw_pulse_count);
    pcnt_unit_clear_count(pcnt_unit);

    // Захист від від'ємних значень лічильника
    if (raw_pulse_count < 0) raw_pulse_count = 0;

    // 2. ОНОВЛЮЄМО КОВЗНИЙ БУФЕР (Згладжування потоку)
    pulse_history[history_idx] = raw_pulse_count;
    history_idx = (history_idx + 1) % 10; // Крутимо індекс від 0 до 9

    // Рахуємо суму імпульсів за останні 500 мілісекунд
    int total_pulses_500ms = 0;
    for (int i = 0; i < 10; i++) {
        total_pulses_500ms += pulse_history[i];
    }

    SystemConfig& cfg = _configMgr->getConfig();
    
    // Нова точна формула перерахунку:
    // Оскільки ми взяли імпульси за 0.5 секунди, то щоб отримати хвилину, множимо на 120.
    // CurrentFlow = (total_pulses_500ms * 120.0) / cfg.flow_pulses
    if (total_pulses_500ms > 0) {
        _currentFlow = ((float)total_pulses_500ms * 120.0f) / (float)cfg.flow_pulses;
    } else {
        _currentFlow = 0.0f;
    }

    // Розрахунок віртуального тиску на основі згладженого потоку
    _virtualPressure = (_currentFlow / (float)activeSectionsCount) * 0.6f;

    // 3. РОБОТА ПІД-РЕГУЛЯТОРА (Працює на плавному потоці)
    float error = _targetFlow - _currentFlow;
    float allowedError = _targetFlow * ((float)cfg.deadband / 100.0f);
    
    if (abs(error) > allowedError) {
        _integral += error * 0.05f;
        if (_integral > 400.0f) _integral = 400.0f;
        if (_integral < -400.0f) _integral = -400.0f;
        
        float controlSignal = (error * _Kp) + (_integral * _Ki);
        _currentPwm += (int)controlSignal;
    }

    int userMaxPwm = (cfg.pwm_max * 1023) / 100;
    int userMinPwm = (cfg.pwm_min * 1023) / 100;
    
    if (_currentPwm > userMaxPwm) _currentPwm = userMaxPwm;
    if (_currentPwm < userMinPwm) _currentPwm = userMinPwm;

    ledcWrite(PUMP_R_PWM_PIN, _currentPwm);
    ledcWrite(PUMP_L_PWM_PIN, 0);
}
*/
/*
void FlowController::update(bool isEmergency, int activeSectionsCount) {
    // Якщо аварія, або закриті всі секції, або Питон просить нуль
    if (isEmergency || activeSectionsCount == 0 || _targetFlow <= 0.05f) {
        _currentPwm = 0;
        ledcWrite(PUMP_R_PWM_PIN, 0);
        ledcWrite(PUMP_L_PWM_PIN, 0);
        _integral = 0.0f;
        _currentFlow = 0.0f;
        _virtualPressure = 0.0f;
        pcnt_unit_clear_count(pcnt_unit); // Скидаємо імпульси в нуль, поки стоїмо
        return;
    }

    // 2. ЗЧИТУВАННЯ РЕАЛЬНОГО ВИТРАТОМІРА ЗА ДОПОМОГОЮ АПАРАТНОГО PCNT
    int pulse_count = 0;
    // Миттєво заглядаємо в залізничний регістр і забираємо кількість накопичених імпульсів
    pcnt_unit_get_count(pcnt_unit, &pulse_count);
    pcnt_unit_clear_count(pcnt_unit); // Одразу очищаємо регістр для наступного такту

    SystemConfig& cfg = _configMgr->getConfig();
    
    // Перераховуємо імпульси в літри на хвилину. 
    // Наш такт викликається 20 разів на секунду (кожні 50 мс), тому множимо на 20, щоб отримати секунди, 
    // і на 60, щоб отримати хвилини: (pulse_count * 20 * 60) / cfg.flow_pulses
    if (pulse_count > 0) {
        _currentFlow = ((float)pulse_count * 1200.0f) / (float)cfg.flow_pulses;
    } else {
        _currentFlow = 0.0f;
    }

    // Розрахунок реалістичного віртуального тиску (поки немає залізничного манометра)
    // Тиск залежить від опору відкритих форсунок штанги та поточного виливу
    _virtualPressure = (_currentFlow / (float)activeSectionsCount) * 0.6f;

    // 3. РОБОТА БОЙОВОГО ПІД-РЕГУЛЯТОРА (PID)
    float error = _targetFlow - _currentFlow;
    float allowedError = _targetFlow * ((float)cfg.deadband / 100.0f);
    
    if (abs(error) > allowedError) {
        _integral += error * 0.05f;
        if (_integral > 400.0f) _integral = 400.0f;   // Рамки анти-намотування
        if (_integral < -400.0f) _integral = -400.0f;
        
        float controlSignal = (error * _Kp) + (_integral * _Ki);
        _currentPwm += (int)controlSignal;
    }

    // Обмеження потужності з Веб-конфігу користувача
    int userMaxPwm = (cfg.pwm_max * 1023) / 100;
    int userMinPwm = (cfg.pwm_min * 1023) / 100;
    
    if (_currentPwm > userMaxPwm) _currentPwm = userMaxPwm;
    if (_currentPwm < userMinPwm) _currentPwm = userMinPwm;

    // 4. ВИДАЧА СИГНАЛУ НА ДРАЙВЕР BTS7960
    ledcWrite(PUMP_R_PWM_PIN, _currentPwm);
    ledcWrite(PUMP_L_PWM_PIN, 0);
}
*/