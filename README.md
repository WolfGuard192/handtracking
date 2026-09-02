# HandClose (Windows) — безопасный демон на основе веб-камеры

**Описание.** Программа отслеживает жест последовательности `OPEN -> FIST` (ладонь → сжатие) через веб-камеру с помощью MediaPipe. При распознавании (и при разрешении опций) аккуратно закрывает пользовательские приложения в Windows.

**Структура:**
- `main.py` — точка входа, CLI, логика state-machine, cooldown, поддержка USB/виртуальных камер и IP-потоков (DroidCam), `--list-cameras`, `--probe-url`.
- `hand_detector.py` — интерфейс к MediaPipe Hands + state-machine класс.
- `app_manager.py` — перечисление процессов/окон и корректное закрытие (WM_CLOSE → wait → terminate).
- `config.py` — параметры по умолчанию.
- `requirements.txt`
- `logs/` — лог-файлы (создаётся автоматически).
- `tests/` — пару простых pytest тестов.

---

## Требования
- Python 3.10.x (рекомендуется) или 3.11; Windows 64-bit
- Для IP-режима можно использовать DroidCam (Wi-Fi поток `http://<ip>:4747/video`, иногда `.../mjpegfeed`).
- Для виртуальной веб-камеры — установите клиент **DroidCam** с драйвером (отобразится устройство `DroidCam Source`).
- В Windows включите доступ к камере для настольных приложений (Параметры → Конфиденциальность → Камера).

Рекомендуется создать виртуальное окружение:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
"# handtracking" 
"# handtracking" 
