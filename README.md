# MKVMerge GUI v2

PySide6-версия утилиты для пакетной обработки MKV-файлов (замена аудиодорожек через mkvmerge).

## Требования

- **Python 3.10+** — https://www.python.org/downloads/
  - При установке обязательно поставить галочку **"Add Python to PATH"**
- **PySide6** — графическая библиотека (Qt для Python)
- **mkvmerge** — должен быть установлен и путь прописан в конфиге
- **WinRAR** или **7-Zip** — для распаковки RAR архивов (опционально)

## Установка

1. Установить Python (если ещё не установлен):
   ```
   https://www.python.org/downloads/
   ```

2. Установить зависимости:
   ```
   pip install PySide6 pymediainfo
   ```
   `pymediainfo` — опционально, для отображения длительности видео. Требует установленного [MediaInfo](https://mediaarea.net/en/MediaInfo).

3. Для распаковки RAR архивов нужен **WinRAR** или **7-Zip**. Установка через PowerShell:
   ```powershell
   winget install RARLab.WinRAR
   ```
   или
   ```powershell
   winget install 7zip.7zip
   ```
   Программа автоматически ищет `UnRAR.exe` в `C:\Program Files\WinRAR\` и `7z.exe` в `C:\Program Files\7-Zip\`.

3. Убедиться, что `mkvmerge_gui_config.json` лежит в той же папке, что и `mkvmerge_gui_v2.py`.

## Запуск

```
python mkvmerge_gui_v2.py
```

Или двойной клик по файлу `mkvmerge_gui_v2.py` (если Python ассоциирован с `.py` файлами).

## Конфигурация

Файл `mkvmerge_gui_config.json` — общий для обеих версий (v1 и v2). Содержит:

- Пути к папкам (аудио, видео, выход, тест)
- Путь к `mkvmerge.exe`
- Настройки суффикса и имени дорожки
- Список маппингов (фильмов)

Если конфиг отсутствует, программа создаст его при первом запуске.

## Отличия от оригинала

- Используется **PySide6** (Qt) вместо Tkinter
- Скролл работает плавно при любом количестве записей
- Все кнопки и элементы управления идентичны оригиналу
- Тот же формат конфига — можно переключаться между версиями
