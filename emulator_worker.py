# emulator_worker.py
import math
import time
import threading

class EmulatorWorker(threading.Thread):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.running = True
        self.dt = 0.1 # Працюємо на 10 Гц (як реальний GPS)

    def run(self):
        print("[Emu_Unit] Tread is Run.")
        while self.running:
            # Працюємо ТІЛЬКИ якщо емулятор увімкнено на фронтенді та є швидкість
            if self.state.emu_enabled and self.state.emu_speed > 0:
                import math
                current_time = time.time()
                    
                # Кожні 30 секунд трактор буде закладати плавний розворот,
                # імітуючи рух по великому полю та перетин кордонів чанків
                self.state.emu_angle = 15.0 * math.sin(current_time / 10.0)
                
                # 1. Читаємо кут коліс з нашого нового квадратного пада (-30...+30)
                wheel_angle = self.state.emu_hdg
                
                # Жорстка "мертва зона" для керма, щоб курс міг ЗАВМЕРТИ
                if abs(wheel_angle) < 0.1:
                    turn_rate = 0.0
                else:
                    # Чим вища швидкість і більший кут — тим швидше міняється курс
                    turn_rate = (wheel_angle * (self.state.emu_speed / 20.0)) * 0.8 * self.dt
                
                # 2. Оновлюємо курс трактора (Compass Heading)
                if turn_rate != 0:
                    self.state.hdg = (self.state.hdg + turn_rate) % 360
                
                # 3. Рахуємо рух вперед
                dist = (self.state.emu_speed / 3.6) * self.dt # Шлях за 100мс у метрах
                rad = math.radians(self.state.hdg)
                
                # Оновлюємо віртуальні GPS координати в SharedState
                self.state.last_lat += (dist * math.cos(rad)) / 111320
                self.state.last_lon += (dist * math.sin(rad)) / (
                    111320 * math.cos(math.radians(self.state.last_lat))
                )
                
                # Емулятор повністю імітує роботу залізяки для математичного ядра
                self.state.speed = self.state.emu_speed
                self.state.rtk = 4 # Імітуємо ідеальний RTK Fix для тестування компенсації на поворотах
                
            time.sleep(self.dt) # Чіткий крок у 100 мс

    def stop(self):
        self.running = False
