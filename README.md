# MKVMerge GUI v2

PySide6-версия утилиты для пакетной обработки MKV-файлов (замена аудиодорожек через mkvmerge).

## Требования

- **Python 3.10+**
- **PySide6** — графическая библиотека (Qt для Python)
- **mkvmerge** — должен быть установлен и путь прописан в настройках
- **WinRAR** или **7-Zip** — для распаковки RAR архивов (опционально)

## Установка

1. Установить Python (если ещё не установлен):
   ```powershell
   winget install Python.Python.3.13
   ```

2. Установить зависимости:
   ```
   pip install PySide6 pymediainfo
   ```
   `pymediainfo` — опционально, для отображения длительности видео. Требует установленного [MediaInfo](https://mediaarea.net/en/MediaInfo).

3. Для распаковки RAR архивов нужен **WinRAR** или **7-Zip**:
   ```powershell
   winget install RARLab.WinRAR
   ```
   или
   ```powershell
   winget install 7zip.7zip
   ```
   Программа автоматически ищет `UnRAR.exe` в `C:\Program Files\WinRAR\` и `7z.exe` в `C:\Program Files\7-Zip\`.

## Запуск

```
python mkvmerge_gui_v2.pyw
```

Или двойной клик по файлу `mkvmerge_gui_v2.pyw`.

## Конфигурация

При первом запуске программа создаст папки `config_films/` и `config_settings/` с настройками. Конфиг содержит:

- Пути к папкам (аудио, видео, выход, тест)
- Путь к `mkvmerge.exe`
- Настройки суффикса и имени дорожки
- Список маппингов (фильмов)
