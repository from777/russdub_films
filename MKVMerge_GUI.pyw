#!/usr/bin/env python3
"""
MKVMerge GUI v2 — PySide6 (QTableWidget)
Быстрая версия с точным повторением всех кнопок оригинала.
Использует тот же mkvmerge_gui_config.json.
Открытый исходный код.
"""

import sys
import os

# Скрыть консольное окно СРАЗУ до тяжёлых импортов (PySide6 грузится долго)
if sys.platform == "win32":
    import ctypes
    _console = ctypes.windll.kernel32.GetConsoleWindow()
    if _console:
        ctypes.windll.user32.ShowWindow(_console, 0)

import ctypes
import ctypes.wintypes
import json
import re
import subprocess
import threading
import shutil
import webbrowser
import urllib.request
import urllib.parse
import urllib.error
import traceback
from datetime import datetime

# Опционально: pymediainfo для определения длительности видео
# Ленивый импорт чтобы не создавать окна при старте
HAS_MEDIAINFO = False
MediaInfo = None

def _init_mediainfo():
    global HAS_MEDIAINFO, MediaInfo
    if MediaInfo is not None:
        return
    try:
        from pymediainfo import MediaInfo as MI
        MediaInfo = MI
        HAS_MEDIAINFO = True
    except ImportError:
        HAS_MEDIAINFO = False

# PyInstaller --onefile распаковывает во временную папку — __file__ указывает туда.
# sys.executable указывает на сам .exe, поэтому конфиги ищем рядом с ним.
if getattr(sys, 'frozen', False):
    _SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_SCRIPT_DIR, "mkvmerge_gui_config.json")  # Оригинал (только миграция)
_SETTINGS_DIR = os.path.join(_SCRIPT_DIR, "config_settings")
_FILMS_DIR = os.path.join(_SCRIPT_DIR, "config_films")
SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.json")
FILMS_FILE = os.path.join(_FILMS_DIR, "films.json")

# ─── Проверка PySide6 ───
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QLineEdit, QPushButton, QHeaderView,
        QTextEdit, QPlainTextEdit, QFileDialog, QMessageBox, QSplitter,
        QComboBox, QMenu, QAbstractItemView, QInputDialog, QDialog,
        QGridLayout, QCheckBox, QTableWidget, QTableWidgetItem, QSpinBox,
        QSizePolicy, QAbstractScrollArea, QTabWidget, QTabBar, QScrollArea, QFrame, QStackedWidget,
        QProgressDialog, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QSplashScreen
    )
    from PySide6.QtCore import Qt, QTimer, Signal, QSize, QEvent, QObject, QSortFilterProxyModel, QByteArray, QBuffer, QIODevice, QPoint
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QAction, QPixmap, QShortcut, QKeySequence, QTextDocument, QIcon, QPalette, QPainter, QPen, QBrush, QIntValidator, QScreen
except ImportError:
    print("=" * 55)
    print("  ОШИБКА: PySide6 не установлен!")
    print("=" * 55)
    print()
    print("  Установи командой:")
    print("    pip install PySide6")
    print()
    print("=" * 55)
    try:
        input("\nНажми Enter чтобы закрыть...")
    except EOFError:
        pass
    sys.exit(1)

# ─── Константы ───
AUDIO_EXTS = ('.thd', '.ac3', '.dts', '.dtshd', '.eac3', '.flac', '.mka', '.thd+ac3', '.truehd')
VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.m2ts')

COLOR_READY = "#c8ffc8"
COLOR_ERROR = "#ffc8c8"
COLOR_TXT_WARN = "#fff3cd"
COLOR_TO_PROCESS = "#cce5ff"
COLOR_IN_TEST = "#ffe4b5"
COLOR_VIDEO_PENDING = "#e8d0ff"
COLOR_NEW = "#ffd699"
COLOR_ROW_EVEN = "#ffffff"
COLOR_ROW_ODD = "#f0f0f0"
COLOR_HEADER = "#4a4a4a"
COLOR_HIGHLIGHT = "#c5d5e8"

HEADERS = ["", "📁", "Дата создания", "♪ Папка", "♪ Аудио дорожка", "Пароль", "▶ Видео файл (источник)", "♪ Задержка",
           "Аффикс выходного файла", "▶ Выходной файл (результат)", "Название", "Год",
           "txt", "♪ Т.", "▶ Торрент источника видео", "Форум russdub", "Статус", "Дата обработки",
           "Абонемент", "Кинопоиск", "Действия"]

def shorten_russdub_url(url: str) -> str:
    """Сокращает ссылку russdub, убирая лишние параметры.
    https://russdub.ru:22223/viewtopic.php?f=19&t=3193&p=153225&hilit=...#p153225
    -> https://russdub.ru:22223/viewtopic.php?f=19&t=3193
    """
    if not url:
        return url
    # Проверяем что это ссылка на russdub viewtopic
    if "russdub.ru" not in url or "viewtopic.php" not in url:
        return url
    try:
        # Убираем якорь (#p...)
        if "#" in url:
            url = url.split("#")[0]
        # Парсим URL
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        # Оставляем только значимые параметры: f, t, или p (post ID)
        new_params = {}
        if "f" in params:
            new_params["f"] = params["f"][0]
        if "t" in params:
            new_params["t"] = params["t"][0]
        if "p" in params and "t" not in params:
            # Ссылка по ID поста (viewtopic.php?p=143621) — оставляем p
            new_params["p"] = params["p"][0]
        # Собираем обратно
        new_query = urllib.parse.urlencode(new_params)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"
    except Exception:
        return url


def validate_url_field(edit):
    """Проверяет URL-поле: пустое — ОК, иначе должно начинаться с http(s)://.
    Невалидное — красная рамка + tooltip. Возвращает True/False."""
    text = edit.text().strip()
    if not text:
        edit.setStyleSheet("")
        tip = edit.property("_orig_tooltip")
        if tip:
            edit.setToolTip(tip)
        return True
    if text.startswith("http://") or text.startswith("https://"):
        edit.setStyleSheet("")
        tip = edit.property("_orig_tooltip")
        if tip:
            edit.setToolTip(tip)
        return True
    edit.setStyleSheet("border: 2px solid red;")
    edit.setToolTip("⚠ Ссылка должна начинаться с http:// или https://")
    return False


def setup_url_validation(edit):
    """Подключает валидацию URL к QLineEdit через editingFinished."""
    edit.setProperty("_orig_tooltip", edit.toolTip())
    edit.editingFinished.connect(lambda e=edit: validate_url_field(e))


def setup_year_validation(edit):
    """Настраивает поле года: только цифры 1800–2099, макс 4 символа."""
    edit.setValidator(QIntValidator(1800, 2099))
    edit.setMaxLength(4)


COL_SELECT = 0
COL_OPEN = 1
COL_DATE_CREATED = 2
COL_FOLDER = 3
COL_AUDIO = 4
COL_PASSWORD = 5
COL_VIDEO = 6
COL_DELAY = 7
COL_SUFFIX = 8
COL_OUTPUT = 9
COL_TITLE = 10
COL_YEAR = 11
COL_INFO = 12
COL_TOR_A = 13
COL_TOR_V = 14
COL_FORUM = 15
COL_STATUS = 16
COL_DATE = 17
COL_SUB = 18
COL_KP = 19
COL_ACTIONS = 20
NUM_COLS = 21

_MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
_SUB_YEARS = [str(y) for y in range(2019, 2032)]

BTN_FONT = QFont("Arial", 8)
SMALL_BTN = "padding:1px 4px;"

def _exe_icon(exe_path: str, size: int = 16) -> QIcon:
    """Извлечь оригинальную иконку приложения из .exe файла."""
    from PySide6.QtWidgets import QFileIconProvider
    from PySide6.QtCore import QFileInfo
    if os.path.isfile(exe_path):
        icon = QFileIconProvider().icon(QFileInfo(exe_path))
        if not icon.isNull():
            return icon
    return QIcon()


def _make_emoji_icon(emoji: str, size: int = 18) -> QIcon:
    """Создать QIcon из эмодзи с заданным размером."""
    from PySide6.QtGui import QPainter, QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setFont(QFont("Segoe UI Emoji", size - 4))
    p.drawText(pm.rect(), Qt.AlignCenter, emoji)
    p.end()
    return QIcon(pm)


def _make_two_notes_icon(size: int = 18) -> QIcon:
    """Создать иконку ♫ (две ноты с перемычкой) для кнопок файла звуковой дорожки."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#222222")
    p.setPen(QPen(c, 1))
    p.setBrush(c)
    # Головки нот
    p.drawEllipse(1, 12, 5, 4)
    p.drawEllipse(9, 10, 5, 4)
    # Штили
    p.setPen(QPen(c, 1.2))
    p.drawLine(6, 14, 6, 3)
    p.drawLine(14, 12, 14, 1)
    # Перемычка
    p.setPen(QPen(c, 2))
    p.drawLine(6, 3, 14, 1)
    p.end()
    return QIcon(pm)


class _ArchiveProxyModel(QSortFilterProxyModel):
    """Фильтр для QFileDialog: показывает только архивы (.rar, .7z, .zip) и файлы без расширения."""
    _ARCHIVE_EXT = {'rar', '7z', 'zip'}

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        if model.isDir(idx):
            return True
        name = model.fileName(idx)
        if '.' not in name:
            return True
        ext = name.rsplit('.', 1)[-1].lower()
        if ext in self._ARCHIVE_EXT:
            return True
        # Файлы с "ненастоящим расширением" (пробелы или длиннее 10 символов)
        # Например: "Captain America. Brave New World" — ext="brave new world"
        if ' ' in ext or len(ext) > 10:
            return True
        return False


def _open_archive_dialog(parent, title, start_dir=""):
    """Открыть диалог выбора архива: показывает только .rar/.7z/.zip и файлы без расширения."""
    dlg = QFileDialog(parent, title, start_dir)
    dlg.setOption(QFileDialog.DontUseNativeDialog, True)
    dlg.setFileMode(QFileDialog.ExistingFile)
    dlg.setNameFilter("Архивы и файлы без расширения (*)")
    dlg.setProxyModel(_ArchiveProxyModel(dlg))
    if dlg.exec():
        files = dlg.selectedFiles()
        if files:
            return files[0]
    return ""


def _make_del_video_icon(size: int = 128) -> QIcon:
    """Создать иконку ✖📽️ для кнопок удаления видео."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    # Две иконки рядом — каждая size x size
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Крестик ✖ — красный, чуть опущен (y + 8)
    p.setPen(QColor("red"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 8, size, size, Qt.AlignCenter, "✖")
    # Видео иконка 📽️ — чуть поднята (y - 8)
    p.setFont(QFont("Segoe UI Emoji", size - 16))
    p.drawText(size, -8, size, size, Qt.AlignCenter, "📽️")
    p.end()
    return QIcon(pm)


def _make_del_audio_icon(size: int = 128) -> QIcon:
    """Создать иконку ✖♫ для кнопок удаления аудио вариантов."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Крестик ✖ — красный, чуть опущен (y + 8)
    p.setPen(QColor("red"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 8, size, size, Qt.AlignCenter, "✖")
    # Нота ♫ — чуть поднята (y - 8)
    p.setPen(QColor("#222222"))
    p.setFont(QFont("Segoe UI Emoji", size - 16))
    p.drawText(size, -8, size, size, Qt.AlignCenter, "♫")
    p.end()
    return QIcon(pm)


def _format_file_size_gb(path: str) -> str:
    """Вернуть размер файла в ГБ, например '1.2 ГБ'. Если файл не существует — пустая строка."""
    try:
        if path and os.path.isfile(path):
            size_bytes = os.path.getsize(path)
            size_gb = size_bytes / (1024 ** 3)
            if size_gb >= 0.01:
                return f"{size_gb:.2f} ГБ"
            else:
                size_mb = size_bytes / (1024 ** 2)
                return f"{size_mb:.0f} МБ"
    except:
        pass
    return ""


def _format_bytes_size(size_bytes: int) -> str:
    """Форматировать размер в байтах в строку ГБ/МБ."""
    if size_bytes > 0:
        size_gb = size_bytes / (1024 ** 3)
        if size_gb >= 0.01:
            return f"{size_gb:.2f} ГБ"
        else:
            size_mb = size_bytes / (1024 ** 2)
            return f"{size_mb:.0f} МБ"
    return ""


def _make_del_archive_icon(size: int = 128) -> QIcon:
    """Создать иконку ✖🎵 для кнопок удаления архива."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Крестик ✖ — красный
    p.setPen(QColor("red"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "✖")
    # Нота 🎵 — уменьшенный шрифт чтобы влезла
    p.setFont(QFont("Segoe UI Emoji", size - 56))
    p.drawText(size, 0, size, size, Qt.AlignCenter, "🎵")
    p.end()
    return QIcon(pm)


def _make_rename_icon(size: int = 128) -> QIcon:
    """Создать иконку ✏️📁 для кнопки переименования папки."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setFont(QFont("Segoe UI Emoji", size - 32))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "✏")
    p.drawText(size, 0, size, size, Qt.AlignCenter, "📁")
    p.end()
    return QIcon(pm)


def _make_copy_icon(size: int = 128) -> QIcon:
    """Создать иконку 🗐📁 для кнопки копирования папки."""
    from PySide6.QtGui import QPainter, QPixmap
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setFont(QFont("Segoe UI Emoji", size - 32))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "\U0001F5D0")
    p.drawText(size, 0, size, size, Qt.AlignCenter, "\U0001F4C1")
    p.end()
    return QIcon(pm)


def _make_rmdir_icon(size: int = 128) -> QIcon:
    """Создать иконку ✖📁 для кнопки удаления папки."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor("red"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "✖")
    p.setFont(QFont("Segoe UI Emoji", size - 32))
    p.drawText(size, 0, size, size, Qt.AlignCenter, "📁")
    p.end()
    return QIcon(pm)


def _make_to_result_icon(size: int = 128) -> QIcon:
    """Создать иконку ➜ 📽️ для кнопки В результат (с разрывом между стрелкой и иконкой)."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size * 2, size)  # Размер как было
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Стрелка ➜ — зелёная (сдвинута влево для создания промежутка)
    p.setPen(QColor("#228B22"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(-12, 0, size, size, Qt.AlignCenter, "➜")
    # Видео иконка 📽️ (как было)
    p.setFont(QFont("Segoe UI Emoji", size - 16))
    p.drawText(size, -8, size, size, Qt.AlignCenter, "📽️")
    p.end()
    return QIcon(pm)


def _make_unrar_icon(size: int = 128) -> QIcon:
    """Создать иконку 🔓🎵 (открытый замок + нота) для кнопки Распаковать."""
    from PySide6.QtGui import QPainter, QPixmap
    pm = QPixmap(size * 2, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Замок 🔓 и Нота 🎵 — уменьшенный шрифт чтобы влезли
    p.setFont(QFont("Segoe UI Emoji", size - 56))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "🔓")
    p.drawText(size, 0, size, size, Qt.AlignCenter, "🎵")
    p.end()
    return QIcon(pm)


def _make_play_icon(size: int = 128) -> QIcon:
    """Создать иконку ▶ для кнопки Обработать."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # Треугольник ▶ — синий
    p.setPen(QColor("#1E90FF"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "▶")
    p.end()
    return QIcon(pm)


def _make_download_icon(size: int = 128) -> QIcon:
    """Создать иконку ⬇ для кнопки Скачать."""
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor("#2196F3"))
    p.setFont(QFont("Arial", size - 16, QFont.Bold))
    p.drawText(0, 0, size, size, Qt.AlignCenter, "⬇")
    p.end()
    return QIcon(pm)


def _make_eye_icon(size: int = 64, color: str = "#333333") -> QIcon:
    """Создать красивую иконку глаза для кнопки предпросмотра."""
    from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QBrush, QPainterPath
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    cx, cy = size // 2, size // 2
    # Миндалевидная форма глаза
    eye_w = size * 0.75
    eye_h = size * 0.4

    # Внешний контур глаза (миндаль)
    path = QPainterPath()
    path.moveTo(cx - eye_w / 2, cy)
    path.quadTo(cx, cy - eye_h, cx + eye_w / 2, cy)
    path.quadTo(cx, cy + eye_h, cx - eye_w / 2, cy)

    p.setPen(QPen(QColor(color), size * 0.06))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawPath(path)

    # Радужка (круг)
    iris_r = size * 0.18
    p.setBrush(QBrush(QColor("#4488cc")))
    p.setPen(QPen(QColor("#336699"), size * 0.03))
    p.drawEllipse(int(cx - iris_r), int(cy - iris_r), int(iris_r * 2), int(iris_r * 2))

    # Зрачок (маленький чёрный круг)
    pupil_r = size * 0.08
    p.setBrush(QBrush(QColor("#111111")))
    p.setPen(Qt.NoPen)
    p.drawEllipse(int(cx - pupil_r), int(cy - pupil_r), int(pupil_r * 2), int(pupil_r * 2))

    # Блик (маленький белый кружок)
    highlight_r = size * 0.04
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(int(cx - pupil_r * 0.5), int(cy - pupil_r * 0.8), int(highlight_r * 2), int(highlight_r * 2))

    p.end()
    return QIcon(pm)


def _make_kp_search_icon(icon_path: str, size: int = 24, mag_scale: float = 0.55) -> QIcon:
    """Создать иконку Кинопоиска с маленькой лупой 🔍 в правом нижнем углу.
    mag_scale: размер лупы относительно иконки (0.3-0.6)."""
    from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QBrush
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # Основная иконка Кинопоиска
    kp_pm = QPixmap(icon_path)
    if not kp_pm.isNull():
        p.drawPixmap(0, 0, size, size, kp_pm)
    # Лупа в правом нижнем углу
    mag_size = size * mag_scale
    mx = size - mag_size
    my = size - mag_size
    # Белая подложка-круг для контраста
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(255, 255, 255, 200)))
    p.drawEllipse(int(mx), int(my), int(mag_size), int(mag_size))
    # Кольцо лупы
    ring_cx = mx + mag_size * 0.42
    ring_cy = my + mag_size * 0.42
    ring_r = mag_size * 0.28
    p.setPen(QPen(QColor("#333333"), mag_size * 0.12))
    p.setBrush(QBrush(QColor(200, 220, 255, 120)))
    p.drawEllipse(int(ring_cx - ring_r), int(ring_cy - ring_r), int(ring_r * 2), int(ring_r * 2))
    # Ручка лупы
    handle_pen = QPen(QColor("#333333"), mag_size * 0.14)
    handle_pen.setCapStyle(Qt.RoundCap)
    p.setPen(handle_pen)
    hx1 = ring_cx + ring_r * 0.7
    hy1 = ring_cy + ring_r * 0.7
    hx2 = mx + mag_size * 0.88
    hy2 = my + mag_size * 0.88
    p.drawLine(int(hx1), int(hy1), int(hx2), int(hy2))
    p.end()
    return QIcon(pm)


def _make_checkbox_header_icon(size: int = 64) -> QIcon:
    """Нарисовать аккуратный квадрат с галочкой внутри (галка не касается рамки)."""
    from PySide6.QtGui import QPainter, QPixmap, QColor, QPen
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # Рамка квадрата — белая с тонкой обводкой
    margin = int(size * 0.12)
    box = margin, margin, size - margin * 2, size - margin * 2
    p.setPen(QPen(QColor("#ffffff"), size * 0.07))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(*box, size * 0.08, size * 0.08)
    # Галочка — внутри квадрата с отступом от рамки
    inner = int(size * 0.25)  # отступ от края pixmap до начала галки
    pen = QPen(QColor("#ffffff"), size * 0.09)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    # Три точки галочки: левая, нижняя, правая верхняя
    x1, y1 = inner, int(size * 0.52)              # левый конец
    x2, y2 = int(size * 0.42), int(size * 0.72)   # нижний угол
    x3, y3 = size - inner, int(size * 0.28)        # правый верхний конец
    p.drawLine(x1, y1, x2, y2)
    p.drawLine(x2, y2, x3, y3)
    p.end()
    return QIcon(pm)


VIDEO_ICON = None  # Инициализируется позже после запуска QApplication

class AspectRatioLabel(QLabel):
    """QLabel для постера — масштабирует в paintEvent с актуальными размерами, прижат к верху-право."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._orig_pixmap = None
        self._scaled_cache = None  # (w, h, scaled_pixmap)

    def setOriginalPixmap(self, pm):
        self._orig_pixmap = pm
        self._scaled_cache = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scaled_cache = None
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        if not self._orig_pixmap or self._orig_pixmap.isNull():
            return
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        # Масштабируем с кешем (пересчёт только при смене размеров)
        if self._scaled_cache and self._scaled_cache[0] == w and self._scaled_cache[1] == h:
            scaled = self._scaled_cache[2]
        else:
            scaled = self._orig_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._scaled_cache = (w, h, scaled)
        p = QPainter(self)
        x = w - scaled.width()
        p.drawPixmap(x, 0, scaled)
        p.end()

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)


class _BoldPartDelegate(QStyledItemDelegate):
    """Делегат: текст между ▶ и ◀ рисуется жирным шрифтом. Остальные элементы — стандартно."""

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole) or ""
        if "\u25b6" not in text:                         # ▶ — маркер жирной части
            super().paint(painter, option, index)
            return

        painter.save()

        # --- Фон ---
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            bg = index.data(Qt.BackgroundRole)
            if bg is not None:
                painter.fillRect(option.rect, bg if isinstance(bg, (QColor, QBrush)) else QColor(bg))
            else:
                painter.fillRect(option.rect, option.palette.base())

        # --- Разделяем текст на 3 части: до ▶, между ▶◀ (жирный), после ◀ ---
        before, rest = text.split("\u25b6", 1)
        if "\u25c0" in rest:                             # ◀
            mid, after = rest.split("\u25c0", 1)
        else:
            mid, after = rest, ""

        normal_font = QFont(option.font)
        bold_font = QFont(option.font)
        bold_font.setBold(True)

        fm_n = QFontMetrics(normal_font)
        fm_b = QFontMetrics(bold_font)

        rect = option.rect.adjusted(4, 0, -2, 0)
        y = rect.top() + (rect.height() + fm_n.ascent() - fm_n.descent()) // 2
        x = rect.left()

        # --- Цвет текста ---
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        # 1) до маркера + сам ▶
        part1 = before + "\u25b6"
        painter.setFont(normal_font)
        painter.drawText(x, y, part1)
        x += fm_n.horizontalAdvance(part1)

        # 2) жирная часть
        painter.setFont(bold_font)
        painter.drawText(x, y, mid)
        x += fm_b.horizontalAdvance(mid)

        # 3) ◀ + остаток
        part3 = "\u25c0" + after
        painter.setFont(normal_font)
        painter.drawText(x, y, part3)

        painter.restore()

    def sizeHint(self, option, index):
        return super().sizeHint(option, index)


class NoScrollComboBox(QComboBox):
    """QComboBox без реакции на скролл колёсиком мыши — скролл идёт в таблицу."""
    def wheelEvent(self, event):
        event.ignore()


HEADER_TOOLTIPS = [
    "Выбрать строки для массовых операций\nКлик по заголовку — выбрать/снять все",
    "Открыть папку в проводнике",
    "Дата создания папки аудио\nБерётся из файловой системы",
    "Подпапка из «Папка аудио дорожек»\nКаждая подпапка = одна строка в таблице",
    "Аудио дорожка для замены\nИсточник: подпапка из «Папка аудио дорожек»",
    "Пароль от архива с аудио дорожкой\nИспользуется при распаковке RAR архива",
    "Видео файл (исходник)\nИсточник: «Папка видео»\n... — выбрать вручную\n⏳ — пометить что видео скачивается",
    "♪ Задержка аудио дорожки\nКоличество задержек и статус подтверждения\n✓ — есть подтверждённая, ✗ — нет\nРедактирование на вкладке фильма",
    "Префикс и суффикс имени выходного файла\nПо умолчанию берётся из настроек «Аффикс выходного файла»",
    "Имя выходного файла\nСохраняется в «Папка тест» при обработке,\nзатем перемещается в «Папка результата»",
    "Название фильма (для справки)\nХранится в конфиге",
    "Год выпуска\nХранится в конфиге",
    "TXT файл с описанием фильма\nИсточник: подпапка из «Папка аудио дорожек»\nФайл находится рядом с аудио дорожкой",
    "♪ Т. — Торрент файл аудио дорожки\nОткрывает .torrent файл из папки аудио дорожки в торрент-клиенте\nИсточник: подпапка из «Папка аудио дорожек»",
    "Ссылка на торрент с исходным видео\nХранится в конфиге",
    "Ссылка на тему форума russdub\nХранится в конфиге\nПоиск: «название фильма завершен» на russdub.ru:22223/search.php",
    "Статус обработки\nПроверяет файлы в «Папка видео», «Папка тест», «Папка результата»",
    "Дата и время последней обработки\nХранится в конфиге",
    "Абонемент (год и месяц)\nХранится в конфиге для каждого фильма\nКлик — сортировка по году и месяцу (пустые — внизу)",
    "Кинопоиск — ссылка или поиск\nЕсть ссылка → открыть\nНет ссылки → поиск по названию и году",
    ""  # COL_ACTIONS — колонка скрыта
]


# ═══════════════════════════════════════════════
#  Главное окно
# ═══════════════════════════════════════════════
class MKVMergeApp(QMainWindow):
    # Сигналы для потокобезопасного доступа к UI из рабочего потока
    _sig_log = Signal(str)
    _sig_read_ui = Signal()
    _sig_set_date = Signal(str, str)
    _sig_processing_done = Signal()
    _sig_file_done = Signal(str)  # folder_name — один файл обработан
    _sig_unrar_done = Signal(str, bool, str)  # folder_name, success, error
    _sig_unrar_progress = Signal(str, str)  # folder_name, progress_text
    _sig_poster_loaded = Signal(object, object)  # QLabel, QPixmap
    _sig_poster_error = Signal(object, str)  # status_label, error_text

    def __init__(self, readonly=False):
        super().__init__()
        self._readonly = readonly  # Режим только чтение — запрет autosave (--no-save)
        _title = f"MKVMerge GUI — обновлено {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        if readonly:
            _title += "  [ТОЛЬКО ЧТЕНИЕ — сохранение отключено]"
        self.setWindowTitle(_title)
        # Иконка приложения (заголовок окна + панель задач)
        _app_icon = os.path.join(_SCRIPT_DIR, "icons", "MKVMerge_GUI.ico")
        if os.path.isfile(_app_icon):
            self.setWindowIcon(QIcon(_app_icon))

        self.audio_folders = []
        self.video_files = []
        self.available_videos = []
        self.rows = []
        self._loading = True  # Блокировка autosave до полной загрузки

        self.current_txt_path = None
        self.txt_last_content = ""
        self.sort_column = None
        self.sort_reverse = False

        self.config = self._default_config()
        self._load_config()
        self.sort_column = self.config.get("sort_column") or None
        self.sort_reverse = self.config.get("sort_reverse", False)

        # Восстановить геометрию окна из конфига (или дефолт 98% экрана)
        _sw = self.config.get("window_width", 0)
        _sh = self.config.get("window_height", 0)
        _sx = self.config.get("window_x")
        _sy = self.config.get("window_y")
        screen = QApplication.primaryScreen()
        if _sw > 200 and _sh > 200:
            self.resize(_sw, _sh)
            if _sx is not None and _sy is not None and screen:
                sg = screen.availableGeometry()
                # Проверить что окно попадает на экран (хотя бы частично)
                if (_sx + _sw > sg.x() and _sx < sg.x() + sg.width() and
                        _sy < sg.y() + sg.height() and _sy + 50 > sg.y()):
                    self.move(_sx, _sy)
                else:
                    self.move((sg.width() - _sw) // 2 + sg.x(),
                              (sg.height() - _sh) // 2 + sg.y())
            elif _sx is not None and _sy is not None:
                self.move(_sx, _sy)
        elif screen:
            sg = screen.availableGeometry()
            w = min(int(sg.width() * 0.98), 3100)
            h = min(int(sg.height() * 0.95), 1100)
            self.resize(w, h)
            self.move((sg.width() - w) // 2 + sg.x(),
                      (sg.height() - h) // 2 + sg.y())
        else:
            self.resize(1600, 900)

        self._build_ui()
        _tmp = QLineEdit(); self._btn_h = _tmp.sizeHint().height(); del _tmp  # высота кнопок = высота инпута

        # Сигналы для потокобезопасного доступа к UI из рабочего потока
        self._sig_log.connect(self.log)
        self._sig_read_ui.connect(self._on_sig_read_ui)
        self._sig_set_date.connect(self._set_row_date)
        self._sig_processing_done.connect(self._check_all_statuses)
        self._sig_file_done.connect(self._on_file_done)
        self._sig_unrar_done.connect(self._on_unrar_done)
        self._sig_unrar_progress.connect(self._on_unrar_progress)
        self._sig_poster_loaded.connect(self._on_poster_loaded)
        self._sig_poster_error.connect(self._on_poster_error)
        self._read_result = {}
        self._read_event = threading.Event()
        self._pending_read_fn = ""

        # Восстановить свёрнутое состояние секции путей
        if self.config.get("paths_collapsed"):
            self._toggle_paths_section()

        # Открытые вкладки записей
        self._open_tabs = {}  # folder_name → {"tab_index": int, "widgets": {...}, "connections": [...]}
        # Глобальная ширина сплиттера (форма | txt) — единая для всех вкладок фильмов
        self._tab_splitter_sizes = self.config.get("tab_splitter_sizes", [450, 350])
        # Подсвеченная строка в таблице (ссылка на row dict)
        self._highlighted_row = None
        # TXT панель внизу — активная кнопка и folder_name
        self._active_txt_btn = None
        self._active_txt_fn = None

        # Автосохранение конфига
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._do_autosave)

        # Автосохранение txt
        self._txt_timer = QTimer(self)
        self._txt_timer.setInterval(2000)
        self._txt_timer.timeout.connect(self._txt_autosave_tick)
        self._txt_timer.start()

        # _initial_load вызывается из main() ДО show() чтобы не мелькали виджеты

    # ──────────────────────────────────
    #  Конфиг
    # ──────────────────────────────────
    @staticmethod
    def _default_config():
        return {
            "audio_path": "", "video_path": "", "output_path": "",
            "test_path": "",
            "mkvmerge_path": r"C:\Program Files\MKVToolNix\mkvmerge.exe",
            "unrar_path": "",
            "track_name": "ATMOS", "file_suffix": "_ATMOS", "file_prefix": "",
            "mappings": [], "sort_column": "", "sort_reverse": False
        }

    def _load_config(self):
        """Загрузить конфиг из новых файлов, или мигрировать из старого."""
        loaded_settings = False
        loaded_films = False
        # Новые файлы
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
                loaded_settings = True
            except Exception:
                pass
        if os.path.exists(FILMS_FILE):
            try:
                with open(FILMS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config["mappings"] = data.get("mappings", [])
                loaded_films = True
            except Exception:
                pass
        # Миграция из оригинального конфига
        if not loaded_settings or not loaded_films:
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    if not loaded_settings:
                        for k, v in old.items():
                            if k != "mappings":
                                self.config[k] = v
                    if not loaded_films:
                        self.config["mappings"] = old.get("mappings", [])
                except Exception:
                    pass

    def _backup_file(self, path):
        """Ротация бэкапов .bak1-.bakN для указанного файла."""
        if not os.path.exists(path):
            return
        n = self._get_backup_setting("bak_count", 5)
        try:
            for i in range(n, 1, -1):
                src = path + f".bak{i-1}"
                dst = path + f".bak{i}"
                if os.path.exists(src):
                    shutil.copy2(src, dst)
            shutil.copy2(path, path + ".bak1")
        except Exception:
            pass

    def _save_config(self):
        if self._readonly:
            return  # --no-save: полная блокировка сохранения
        self._save_settings()
        self._save_films()

    def _save_settings(self):
        """Сохранить общие настройки приложения."""
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        self._backup_file(SETTINGS_FILE)
        data = {
            "audio_path": self.audio_path_edit.text(),
            "download_path": self.download_path_edit.text(),
            "video_path": self.video_path_edit.text(),
            "output_path": self.output_path_edit.text(),
            "test_path": self.test_path_edit.text(),
            "mkvmerge_path": self.mkvmerge_path_edit.text(),
            "unrar_path": self.unrar_path_edit.text(),
            "track_name": self.track_name_edit.text(),
            "file_prefix": self.file_prefix_edit.text(),
            "file_suffix": self.file_suffix_edit.text(),
            "sort_column": self.sort_column,
            "sort_reverse": self.sort_reverse,
            "column_widths": [self.table.columnWidth(i) for i in range(NUM_COLS)],
            "column_order": [self.table.horizontalHeader().visualIndex(i) for i in range(NUM_COLS)],
            "hidden_columns": self.config.get("hidden_columns", []),
            "open_tabs": list(self._open_tabs.keys()),
            "backup_settings": self.config.get("backup_settings", {}),
            "paths_collapsed": not self._paths_group.isVisible(),
            "window_width": self.width(),
            "window_height": self.height(),
            "window_x": self.x(),
            "window_y": self.y(),
            "tab_splitter_sizes": self._tab_splitter_sizes,
            "short_link_default": self.short_link_default_cb.isChecked() if hasattr(self, 'short_link_default_cb') else True,
            "hidden_status_buttons": self.config.get("hidden_status_buttons", []),
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # Обновить self.config для совместимости
        self.config.update(data)

    # Поля, потеря которых сигнализирует о коррупции данных
    _SCORE_FIELDS = ("title", "year", "poster_url", "torrent_url",
                     "forum_url", "kinopoisk_url", "archive_password")
    _DAILY_PREFIX = ".daily_"   # films.json.daily_20260206_143000
    _DAILY_KEEP = 10            # 10 самых свежих (≈5 дней × 2)
    _DAILY_INTERVAL = 12 * 3600 # 12 часов в секундах

    @staticmethod
    def _calc_data_score(mappings):
        """Посчитать количество маппингов с хотя бы одним заполненным важным полем."""
        score = 0
        for m in mappings:
            if any(m.get(f) for f in MKVMergeApp._SCORE_FIELDS):
                score += 1
        return score

    def _daily_backup(self):
        """Бэкап по дням: интервал и лимит берутся из настроек бэкапов."""
        if not os.path.isfile(FILMS_FILE):
            return
        interval = self._get_backup_setting("daily_interval_hours", 12) * 3600
        keep = self._get_backup_setting("daily_keep", 10)

        prefix = os.path.basename(FILMS_FILE) + self._DAILY_PREFIX
        daily_dir = os.path.dirname(FILMS_FILE) or "."
        try:
            daily_files = sorted(
                [f for f in os.listdir(daily_dir) if f.startswith(prefix)],
                key=lambda f: os.path.getmtime(os.path.join(daily_dir, f)),
                reverse=True,
            )
        except Exception:
            daily_files = []

        if daily_files:
            newest = os.path.join(daily_dir, daily_files[0])
            try:
                age = datetime.now().timestamp() - os.path.getmtime(newest)
            except Exception:
                age = interval + 1
            if age < interval:
                return  # Ещё рано

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(daily_dir, prefix + stamp)
        try:
            shutil.copy2(FILMS_FILE, dst)
        except Exception:
            return

        daily_files.insert(0, os.path.basename(dst))
        for old in daily_files[keep:]:
            try:
                os.remove(os.path.join(daily_dir, old))
            except Exception:
                pass

    def _save_films(self):
        """Сохранить базу данных фильмов (маппинги) с защитой от коррупции."""
        self._daily_backup()
        os.makedirs(_FILMS_DIR, exist_ok=True)
        mappings = []
        for r in self.rows:
            mappings.append({
                "folder": r["folder_name"],
                "audio": self._audio_filename(r),
                "starter_audio": self._starter_filename(r),
                "ender_audio": self._ender_filename(r),
                "video": r["video_combo"].currentText(),
                "video_full_path": r.get("video_full_path", ""),
                "video_manual": r.get("video_manual", False),
                "delay": r.get("delay_value", "0"),
                "delay_confirmed": r.get("delay_confirmed", False),
                "delays": r.get("delays", [{"value": "0", "confirmed": False}]),
                "output": r["output_entry"].text(),
                "title": r["title_entry"].text(),
                "year": r["year_entry"].text(),
                "custom_prefix_enabled": r["prefix_cb"].isChecked(),
                "custom_prefix": r["prefix_entry"].text(),
                "custom_suffix_enabled": r["suffix_cb"].isChecked(),
                "custom_suffix": r["suffix_entry"].text(),
                "custom_track_name_enabled": r.get("custom_track_name_enabled", False),
                "custom_track_name": r.get("custom_track_name", ""),
                "torrent_url": r["torrent_entry"].text(),
                "forum_url": r["forum_entry"].text(),
                "sort_priority": r.get("sort_priority", 1),
                "processed_date": r.get("processed_date", ""),
                "video_pending": r.get("video_pending", False),
                "_password_error": r.get("_password_error", False),
                "archive_password": r["password_entry"].text(),
                "poster_url": r.get("poster_url", ""),
                "kinopoisk_url": r.get("kinopoisk_url", ""),
                "audio_torrent_url": r.get("audio_torrent_url", ""),
                "selected_txt": r.get("selected_txt", ""),
                "sub_year": r["sub_year"].currentText(),
                "sub_month": r["sub_month"].currentText(),
                "selected_audio_tracks": r.get("selected_audio_tracks"),
                "is_new": r.get("is_new", False),
                "video_duration": r["video_dur_lbl"].text(),
                "extra_audio_variants": r.get("extra_audio_variants", []),
                "extra_videos": r.get("extra_videos", []),
                "video_fps": r.get("video_fps", "авто"),
                "right_tab_idx": self._get_open_tab_right_idx(r),
                "torrent_confirmed": r.get("torrent_confirmed", False),
                "extra_torrent_urls": self._get_extra_torrent_urls(r),
            })

        # ── Защита от коррупции ──
        new_score = self._calc_data_score(mappings)
        new_videos = sum(1 for m in mappings if m.get("video"))
        old_score = 0
        old_videos = 0
        if os.path.isfile(FILMS_FILE):
            try:
                with open(FILMS_FILE, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                old_mappings = old_data.get("mappings", [])
                old_score = self._calc_data_score(old_mappings)
                old_videos = sum(1 for m in old_mappings if m.get("video"))
            except Exception:
                pass

        # ЖЁСТКАЯ БЛОКИРОВКА: записи есть но все данные пропали — это баг, НЕ сохранять.
        # Если записей мало (пустая папка / переезд) — сохранять нормально.
        if old_videos > 10 and new_videos == 0 and len(mappings) > 10:
            self.log(f"[ЗАЩИТА] БЛОКИРОВКА: video {old_videos}→0 при {len(mappings)} записях. Данные НЕ перезаписаны.")
            return

        lost = old_score - new_score
        threshold_pct = self._get_backup_setting("safe_threshold_pct", 20) / 100.0
        if old_score > 0 and lost > 3 and lost > old_score * threshold_pct:
            safe_name = FILMS_FILE + ".safe_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                shutil.copy2(FILMS_FILE, safe_name)
            except Exception:
                pass
            # Чистим старые .safe_ — оставляем safe_keep самых свежих
            safe_keep = self._get_backup_setting("safe_keep", 5)
            safe_prefix = os.path.basename(FILMS_FILE) + ".safe_"
            safe_dir = os.path.dirname(FILMS_FILE) or "."
            try:
                safe_files = sorted(
                    [f for f in os.listdir(safe_dir) if f.startswith(safe_prefix)],
                    key=lambda f: os.path.getmtime(os.path.join(safe_dir, f)),
                    reverse=True,
                )
                for old in safe_files[safe_keep:]:
                    try:
                        os.remove(os.path.join(safe_dir, old))
                    except Exception:
                        pass
            except Exception:
                pass

        self._backup_file(FILMS_FILE)
        self.config["mappings"] = mappings
        try:
            with open(FILMS_FILE, "w", encoding="utf-8") as f:
                json.dump({"mappings": mappings}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # Сохранить _meta.json в каждую папку фильма
        self._save_meta_to_folders(mappings)

    def _get_open_tab_right_idx(self, r):
        """Получить индекс активной правой вкладки (txt/Данные) для фильма."""
        fn = r["folder_name"]
        if fn in self._open_tabs:
            return self._open_tabs[fn]["widgets"].get("_right_tab_idx", 0)
        return r.get("right_tab_idx", 0)

    def _get_extra_torrent_urls(self, r):
        """Получить список доп. торрент-ссылок из виджетов вкладки или из данных."""
        fn = r["folder_name"]
        if fn in self._open_tabs:
            widgets = self._open_tabs[fn]["widgets"].get("extra_torrent_widgets", [])
            return [{"url": w["input"].text(), "confirmed": w["confirmed"]}
                    for w in widgets if w["input"].text().strip()]
        return r.get("extra_torrent_urls", [])

    def _save_meta_to_folders(self, mappings):
        """Сохранить _meta.json в папку каждого фильма (бэкап данных)."""
        for m in mappings:
            r = None
            for row in self.rows:
                if row["folder_name"] == m.get("folder"):
                    r = row
                    break
            if not r:
                continue
            folder_path = r.get("folder_path", "")
            if not folder_path or not os.path.isdir(folder_path):
                continue
            meta_path = os.path.join(folder_path, "_meta.json")
            meta_data = dict(m)
            meta_data["_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Если на диске есть данные а новые пустые — ротация бэкапов _meta.json.safe_N
            new_has = any(meta_data.get(f) for f in self._SCORE_FIELDS)
            if not new_has and os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        old_meta = json.load(f)
                    if any(old_meta.get(f) for f in self._SCORE_FIELDS):
                        keep = self._get_backup_setting("meta_safe_keep", 3)
                        # Ротация: .safe_3 → удалить, .safe_2 → .safe_3, .safe_1 → .safe_2, текущий → .safe_1
                        for i in range(keep, 1, -1):
                            src = os.path.join(folder_path, f"_meta.json.safe_{i-1}")
                            dst = os.path.join(folder_path, f"_meta.json.safe_{i}")
                            if os.path.exists(src):
                                shutil.copy2(src, dst)
                        shutil.copy2(meta_path, os.path.join(folder_path, "_meta.json.safe_1"))
                except Exception:
                    pass
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # Поля для сравнения при детекции расхождений _meta.json
    _META_COMPARE_FIELDS = [
        "title", "year", "forum_url", "torrent_url", "audio_torrent_url",
        "poster_url", "kinopoisk_url", "delay", "delays", "archive_password",
        "sub_year", "sub_month", "selected_audio_tracks",
        "custom_prefix", "custom_prefix_enabled", "custom_suffix", "custom_suffix_enabled",
        "custom_track_name", "custom_track_name_enabled",
        "is_new", "processed_date", "video_pending", "sort_priority",
        "video_fps",
    ]

    def _load_meta_from_folder(self, folder_path):
        """Загрузить _meta.json из папки фильма. Возвращает dict или None."""
        meta_path = os.path.join(folder_path, "_meta.json")
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _load_meta_backup_from_folder(self, folder_path):
        """Загрузить _meta_backup.json из папки фильма. Возвращает dict или None."""
        backup_path = os.path.join(folder_path, "_meta_backup.json")
        if not os.path.isfile(backup_path):
            return None
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _normalize_meta_val(val):
        """Нормализовать значение для сравнения: None, False, '', '—' → ''."""
        if val is None:
            return ""
        if val is False:
            return ""
        if val is True:
            return "True"
        s = str(val)
        if s in ("False", "None", "—"):
            return ""
        return s

    def _compare_meta(self, data_a, data_b):
        """Сравнить два набора данных по ключевым полям. True = одинаковые."""
        for field in self._META_COMPARE_FIELDS:
            va = self._normalize_meta_val(data_a.get(field, ""))
            vb = self._normalize_meta_val(data_b.get(field, ""))
            if va != vb:
                return False
        return True

    def _get_current_field_value(self, r, key):
        """Получить текущее строковое значение поля из строки таблицы."""
        if key == "title": return r["title_entry"].text()
        elif key == "year": return r["year_entry"].text()
        elif key == "delay": return r.get("delay_value", "0")
        elif key == "forum_url": return r["forum_entry"].text()
        elif key == "torrent_url": return r["torrent_entry"].text()
        elif key == "archive_password": return r["password_entry"].text()
        elif key == "sub_year":
            w = r.get("sub_year")
            return w.currentText() if hasattr(w, 'currentText') else str(w or "")
        elif key == "sub_month":
            w = r.get("sub_month")
            return w.currentText() if hasattr(w, 'currentText') else str(w or "")
        elif key == "custom_prefix_enabled":
            w = r.get("prefix_cb")
            return str(w.isChecked()) if hasattr(w, 'isChecked') else str(r.get(key, ""))
        elif key == "custom_suffix_enabled":
            w = r.get("suffix_cb")
            return str(w.isChecked()) if hasattr(w, 'isChecked') else str(r.get(key, ""))
        elif key == "custom_prefix": return r["prefix_entry"].text()
        elif key == "custom_suffix": return r["suffix_entry"].text()
        else:
            return str(r.get(key, ""))

    def _resolve_meta_conflict(self, folder_path, config_data, meta_data):
        """Разрешить конфликт: побеждает более новый, проигравший → _meta_backup.json."""
        config_time = config_data.get("_saved_at", "")
        meta_time = meta_data.get("_saved_at", "")
        # Побеждает более новый по _saved_at
        if meta_time > config_time:
            # _meta.json новее — он побеждает, config_data → бэкап
            loser = dict(config_data)
        else:
            # config_data новее или равен — он побеждает, meta_data → бэкап
            loser = dict(meta_data)
        # Сохранить проигравшего как бэкап
        backup_path = os.path.join(folder_path, "_meta_backup.json")
        loser["_backup_reason"] = "расхождение данных"
        loser["_backup_created"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(loser, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # Возвращаем победителя
        if meta_time > config_time:
            return meta_data
        else:
            return config_data

    # Названия месяцев на русском для дат бэкапов
    _MONTHS_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]

    def _move_backup_to_archive(self, folder_path):
        """Переместить _meta_backup.json в папку backup/ с ротацией (макс 5 копий)."""
        backup_path = os.path.join(folder_path, "_meta_backup.json")
        if not os.path.isfile(backup_path):
            return
        backup_dir = os.path.join(folder_path, "backup")
        os.makedirs(backup_dir, exist_ok=True)
        # Имя архивного файла с датой
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_name = f"_meta_backup_{ts}.json"
        archive_path = os.path.join(backup_dir, archive_name)
        try:
            shutil.move(backup_path, archive_path)
        except Exception as e:
            self.log(f"[BACKUP] Ошибка перемещения бэкапа в архив: {e}")
            return
        # Ротация: оставить макс 5 файлов, удалить самые старые
        self._rotate_old_backups(backup_dir, max_count=5)

    def _rotate_old_backups(self, backup_dir, max_count=5):
        """Оставить не более max_count файлов в папке backup/, удалить самые старые."""
        if not os.path.isdir(backup_dir):
            return
        files = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("_meta_backup_") and f.endswith(".json")],
            reverse=True  # Новейшие первыми (по имени = по дате)
        )
        for old_file in files[max_count:]:
            try:
                os.remove(os.path.join(backup_dir, old_file))
            except Exception:
                pass

    def _list_old_backups(self, folder_path):
        """Получить список старых бэкапов из папки backup/.
        Возвращает [(filename, date_str_ru, data_dict), ...] — новейший первый.
        """
        backup_dir = os.path.join(folder_path, "backup")
        if not os.path.isdir(backup_dir):
            return []
        files = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("_meta_backup_") and f.endswith(".json")],
            reverse=True
        )
        result = []
        for fname in files:
            fpath = os.path.join(backup_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            # Парсить дату из имени файла: _meta_backup_2026-02-05_15-51-25.json
            date_str_ru = fname
            try:
                date_part = fname.replace("_meta_backup_", "").replace(".json", "")
                dt = datetime.strptime(date_part, "%Y-%m-%d_%H-%M-%S")
                day = dt.day
                month_ru = self._MONTHS_RU[dt.month]
                year = dt.year
                time_str = dt.strftime("%H:%M")
                date_str_ru = f"{day} {month_ru} {year}, {time_str}"
            except Exception:
                pass
            result.append((fname, date_str_ru, data))
        return result

    def schedule_autosave(self):
        if self._loading:
            return  # Не сохранять до полной загрузки
        self._autosave_timer.start(1000)

    def _do_autosave(self):
        self._save_config()

    def closeEvent(self, event):
        if not self._readonly:
            self._save_current_txt()
            self._save_config()
        event.accept()

    # ──────────────────────────────────
    #  UI
    # ──────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(6, 6, 6, 6)
        ml.setSpacing(3)

        # === ПУТИ (сворачиваемая секция) ===
        self._paths_header = QWidget()
        paths_header = self._paths_header
        paths_header_l = QHBoxLayout(paths_header)
        paths_header_l.setContentsMargins(2, 0, 2, 0)
        paths_header_l.setSpacing(6)
        self._paths_toggle_btn = QPushButton("▲ Скрыть настройки")
        self._paths_toggle_btn.setStyleSheet(
            "QPushButton{border:none; text-align:left; font-size:9pt; color:#555; padding:2px 4px;}"
            "QPushButton:hover{color:#222; text-decoration:underline;}")
        self._paths_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._paths_toggle_btn.setToolTip("Свернуть/развернуть секцию настроек:\nпути к папкам, имя дорожки, аффиксы файлов")
        self._paths_toggle_btn.clicked.connect(self._toggle_paths_section)
        self._paths_summary_lbl = QLabel("")
        self._paths_summary_lbl.setStyleSheet("color: #666; font-size: 9pt;")
        self._paths_summary_lbl.setVisible(False)
        paths_header_l.addWidget(self._paths_toggle_btn)
        paths_header_l.addWidget(self._paths_summary_lbl, 1)
        ml.addWidget(paths_header)

        pg = QGroupBox()
        self._paths_group = pg
        self._paths_collapsed = False
        gl = QGridLayout(pg)
        gl.setSpacing(4)

        self.audio_path_edit = self._path_row(gl, 0, "🎵 Основная папка аудио дорожек:", self.config["audio_path"])
        _tip = "Основная папка с аудио дорожками для фильмов.\nКаждая подпапка = один фильм (одна строка в таблице).\nВ подпапке: аудио файл, архив, торрент, .txt описание."
        gl.itemAtPosition(0, 0).widget().setToolTip(_tip)
        self.audio_path_edit.setToolTip(_tip)
        self.audio_count_lbl = QLabel(""); gl.addWidget(self.audio_count_lbl, 0, 4)

        self.download_path_edit = self._path_row(gl, 1, "🎵 Папка куда скачиваются аудио дорожки:", self.config.get("download_path", ""))
        _tip = "Папка куда торрент-клиент скачивает архивы с аудио дорожками.\n\nНужна только если НЕ используется qBittorrent API.\nЕсли API включён — торренты скачиваются прямо в папку фильма,\nи эта папка не используется.\n\nТакже используется как начальная папка в диалоге выбора архива."
        gl.itemAtPosition(1, 0).widget().setToolTip(_tip)
        self.download_path_edit.setToolTip(_tip)

        self.video_path_edit = self._path_row(gl, 2, "📽️ Папка видео (источник):", self.config["video_path"])
        _tip = "Папка с исходными видео файлами (.mkv, .mp4, .avi, .m2ts).\nИз этой папки выбирается видео для объединения с аудио дорожкой.\nФайлы отображаются в выпадающем списке «Видео файл (источник)»."
        gl.itemAtPosition(2, 0).widget().setToolTip(_tip)
        self.video_path_edit.setToolTip(_tip)
        self.video_count_lbl = QLabel(""); gl.addWidget(self.video_count_lbl, 2, 4)
        self.show_used_videos_cb = None  # Создаётся ниже в настройках

        self.output_path_edit = self._path_row(gl, 3, "📽️ Папка результата:", self.config["output_path"])
        _tip = "Папка для готовых MKV файлов (результат объединения видео + аудио).\nСюда перемещаются файлы из папки «Тест» кнопкой «В Результат»."
        gl.itemAtPosition(3, 0).widget().setToolTip(_tip)
        self.output_path_edit.setToolTip(_tip)
        self.output_count_lbl = QLabel(""); gl.addWidget(self.output_count_lbl, 3, 4)

        self.test_path_edit = self._path_row(gl, 4, "📽️ Папка тест:", self.config["test_path"])
        _tip = "Папка для тестовых MKV файлов.\nmkvmerge сохраняет результат сюда для проверки перед переносом в «Результат»."
        gl.itemAtPosition(4, 0).widget().setToolTip(_tip)
        self.test_path_edit.setToolTip(_tip)
        self.test_count_lbl = QLabel(""); gl.addWidget(self.test_count_lbl, 4, 4)

        self.mkvmerge_path_edit = self._path_row(gl, 5, "mkvmerge.exe:", self.config["mkvmerge_path"], file_mode=True)
        _tip = "Путь к mkvmerge.exe из пакета MKVToolNix.\nОсновной инструмент для объединения видео и аудио дорожек в MKV."
        gl.itemAtPosition(5, 0).widget().setToolTip(_tip)
        self.mkvmerge_path_edit.setToolTip(_tip)
        # Иконки приложений из exe-файлов (оригинальные иконки MKVToolNix / WinRAR)
        def _set_exe_icon_label(grid_row, exe_path, label_text, margin_left=0):
            """Установить оригинальную иконку приложения в лейбл строки путей."""
            icon = _exe_icon(exe_path)
            if icon.isNull():
                return
            lbl_widget = gl.itemAtPosition(grid_row, 0).widget()
            pm = icon.pixmap(16, 16)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            pm.save(buf, "PNG")
            buf.close()
            import base64 as _b64
            img_b64 = _b64.b64encode(ba.data()).decode()
            lbl_widget.setTextFormat(Qt.RichText)
            if margin_left:
                lbl_widget.setStyleSheet(f"padding-left: {margin_left}px;")
            lbl_widget.setText(
                f'<span style="font-size:14pt">'
                f'<img src="data:image/png;base64,{img_b64}" width="16" height="16"'
                f' style="vertical-align:middle">'
                f'</span>&nbsp; {label_text}')

        _mkv_exe = self.config.get("mkvmerge_path", "")
        if _mkv_exe:
            _set_exe_icon_label(5, _mkv_exe, "mkvmerge.exe:", margin_left=3)

        self.unrar_path_edit = self._path_row(gl, 6, "WinRAR:", self.config.get("unrar_path", ""), file_mode=True)
        self.unrar_path_edit.setPlaceholderText("авто: C:\\Program Files\\WinRAR\\UnRAR.exe")
        _tip = ("Путь к UnRAR.exe (входит в комплект WinRAR) для распаковки архивов.\n"
                "Обычно: C:\\Program Files\\WinRAR\\UnRAR.exe\n\n"
                "Если пусто — ищет автоматически в Program Files и PATH.\n"
                "Также поддерживается 7z.exe (7-Zip).")
        self.unrar_path_edit.setToolTip(_tip)
        gl.itemAtPosition(6, 0).widget().setToolTip(_tip)
        _rar_exe = os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"), "WinRAR", "WinRAR.exe")
        _set_exe_icon_label(6, _rar_exe, "WinRAR:", margin_left=3)
        # Автосохранение, Справка, Настройки бэкапов — справа в блоке Пути
        self._adjust_path_widths()

        # --- Настройки по умолчанию (col 5-8, сразу после счётчиков) ---
        _sep = QFrame()
        _sep.setFrameShape(QFrame.VLine)
        _sep.setStyleSheet("color: #ccc;")
        gl.addWidget(_sep, 0, 5, 7, 1)  # Разделитель на всю высоту
        # Строка 0: Заголовок
        _hdr = QLabel("<b>Настройки по умолчанию для всех</b>")
        _hdr.setStyleSheet("color: #444;")
        _hdr.setToolTip("Глобальные настройки применяемые ко всем фильмам.\nМожно переопределить для каждого фильма на его вкладке.")
        gl.addWidget(_hdr, 0, 6, 1, 3)
        # Строка 1: Имя новой дорожки
        _tn_lbl = QLabel("Имя новой дорожки:")
        _tn_lbl.setToolTip("Имя аудио дорожки которое будет записано в MKV файл\n(параметр --track-name для mkvmerge)\nМожно переопределить на вкладке каждого фильма")
        gl.addWidget(_tn_lbl, 1, 6)
        self.track_name_edit = QLineEdit(self.config["track_name"])
        self.track_name_edit.setMinimumWidth(120)
        self.track_name_edit.setToolTip("Имя аудио дорожки которое будет записано в MKV файл\n(параметр --track-name для mkvmerge)")
        gl.addWidget(self.track_name_edit, 1, 7, 1, 2)
        # Строка 2: Аффикс — настройки по умолчанию для всех выходных видео файлов
        _lbl_prefix = QLabel("Аффикс по умолчанию для всех выходных видео файлов:")
        _lbl_prefix.setToolTip("Аффикс (префикс/суффикс) добавляемый к имени выходного видео файла по умолчанию.\nМожно переопределить для каждого файла отдельно на вкладке фильма.")
        gl.addWidget(_lbl_prefix, 2, 6)
        _affix_start_w = QWidget()
        _affix_start_l = QHBoxLayout(_affix_start_w)
        _affix_start_l.setContentsMargins(0, 0, 0, 0)
        _affix_start_l.setSpacing(4)
        _lbl_prefix_in = QLabel("в начале:")
        _lbl_prefix_in.setToolTip("Этот текст будет добавлен В НАЧАЛО имени выходного файла")
        _affix_start_l.addWidget(_lbl_prefix_in)
        self.file_prefix_edit = QLineEdit(self.config.get("file_prefix", ""))
        self.file_prefix_edit.setMinimumWidth(60)
        self.file_prefix_edit.setToolTip("Префикс добавляемый ПЕРЕД именем выходного файла\n(например: ATMOS_ → ATMOS_фильм.mkv)")
        _affix_start_l.addWidget(self.file_prefix_edit)
        gl.addWidget(_affix_start_w, 2, 7)
        _affix_end_w = QWidget()
        _affix_end_l = QHBoxLayout(_affix_end_w)
        _affix_end_l.setContentsMargins(0, 0, 0, 0)
        _affix_end_l.setSpacing(4)
        _lbl_suffix = QLabel("в конце:")
        _lbl_suffix.setToolTip("Этот текст будет добавлен В КОНЕЦ имени выходного файла (перед расширением)")
        _affix_end_l.addWidget(_lbl_suffix)
        self.file_suffix_edit = QLineEdit(self.config["file_suffix"])
        self.file_suffix_edit.setMinimumWidth(60)
        self.file_suffix_edit.setToolTip("Суффикс добавляемый ПОСЛЕ имени выходного файла\n(например: _ATMOS → фильм_ATMOS.mkv)")
        _affix_end_l.addWidget(self.file_suffix_edit)
        gl.addWidget(_affix_end_w, 2, 8)
        # Пересчёт выходных имён при изменении аффикса
        self.file_prefix_edit.textChanged.connect(lambda: self._on_global_affix_changed())
        self.file_suffix_edit.textChanged.connect(lambda: self._on_global_affix_changed())
        # Чекбокс "Показать занятые видео" — перенесён в блок "Видео файл (источник)" на вкладке фильма
        self.show_used_videos_cb = QCheckBox("Показать занятые видео в селекте Видео файл (источник)")
        self.show_used_videos_cb.setToolTip("Показать в выпадающих списках «Видео файл (источник)»\n"
                                            "файлы, уже назначенные другим записям.\n"
                                            "Они выделены цветом и подписаны папкой-владельцем (не кликабельны).\n"
                                            "Выключить — в списках только свободные файлы.")
        self.show_used_videos_cb.toggled.connect(lambda: self._update_all_video_combos())

        # Короткий линк для форума russdub (глобальная настройка по умолчанию)
        self.short_link_default_cb = QCheckBox("Короткий линк для форума russdub")
        self.short_link_default_cb.setChecked(self.config.get("short_link_default", True))
        self.short_link_default_cb.setToolTip("Автоматически сокращать ссылки russdub в таблице при вставке.\n"
                                              "Убирает лишние параметры (&p=...&hilit=...#p...).\n"
                                              "На вкладке фильма — своя независимая настройка.")
        self.short_link_default_cb.toggled.connect(lambda: self.schedule_autosave())
        gl.addWidget(self.short_link_default_cb, 3, 6, 1, 3)

        # --- Stretch + кнопки справа (как было) ---
        gl.setColumnStretch(9, 1)  # Stretch отталкивает кнопки вправо
        autosave_lbl = QLabel("💾 Автосохранение: 1 сек")
        autosave_lbl.setStyleSheet("color: #666; font-size: 9pt;")
        autosave_lbl.setToolTip("Все изменения автоматически сохраняются через 1 секунду.\nРучное сохранение не требуется.")
        autosave_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gl.addWidget(autosave_lbl, 0, 10)
        _right_btns = QWidget()
        _right_btns_l = QHBoxLayout(_right_btns)
        _right_btns_l.setContentsMargins(0, 0, 0, 0)
        _right_btns_l.setSpacing(4)
        backup_cfg_btn = QPushButton("Настройки бэкапов")
        backup_cfg_btn.clicked.connect(self._show_backup_settings)
        backup_cfg_btn.setToolTip("Настроить количество и интервалы резервных копий:\nдневные бэкапы, аварийные копии, _meta.json.safe в папках фильмов")
        _right_btns_l.addWidget(backup_cfg_btn)
        legend_btn = QPushButton("Справка")
        legend_btn.clicked.connect(self._show_status_legend)
        legend_btn.setToolTip("Показать модальное окно с описанием всех статусов:\nкак определяется каждый статус и что он означает")
        _right_btns_l.addWidget(legend_btn)
        gl.addWidget(_right_btns, 1, 10)
        ml.addWidget(pg)

        # === КНОПКА СОЗДАНИЯ ПАПКИ ===
        create_folder_btn = QPushButton("Создать папку для аудио дорожки")
        create_folder_btn.clicked.connect(self._create_audio_folder)
        create_folder_btn.setToolTip("Создать папку для аудио дорожки внутри папки заданной в «Папка аудио дорожек»")
        create_folder_btn.setStyleSheet("QPushButton{background-color: #4CAF50; color: white; font-weight: bold;}")
        create_btn_layout = QHBoxLayout()
        create_btn_layout.addWidget(create_folder_btn)
        self.scan_all_btn = QPushButton("👀 Сканировать все папки")
        self.scan_all_btn.clicked.connect(self._check_all_statuses)
        self.scan_all_btn.setToolTip("Сканирует все 4 папки:\n• Папка аудио дорожек — проверяет аудио файлы\n• Папка видео (источник) — обновляет список видео\n• Папка тест — ищет обработанные файлы\n• Папка результата — ищет готовые файлы\nОбновляет статусы всех строк")
        create_btn_layout.addWidget(self.scan_all_btn)
        # Кнопка "Выровнять ширину колонок"
        self.fit_cols_btn = QPushButton("↔ Выровнять колонки")
        self.fit_cols_btn.setToolTip("Подогнать ширину всех колонок таблицы\nпод максимально широкий контент в каждой колонке")
        self.fit_cols_btn.clicked.connect(self._fit_columns_to_content)
        create_btn_layout.addWidget(self.fit_cols_btn)
        create_btn_layout.addStretch()
        # --- Кнопки для вкладки фильма (видны только при открытом фильме, прижаты вправо) ---
        self.tab_old_backups_btn = QPushButton("Старые бекапы")
        self.tab_old_backups_btn.setStyleSheet("QPushButton{background-color:#e8e0f0; padding:4px 8px;} QPushButton:hover{background-color:#d0c0e8;} QPushButton:disabled{background-color:#f0f0f0; color:#999;}")
        self.tab_old_backups_btn.setToolTip("Просмотр архива старых бэкапов настроек из папки backup/ в каталоге фильма")
        self.tab_old_backups_btn.setVisible(False)
        self.tab_old_backups_btn.clicked.connect(self._on_tab_old_backups_click)
        create_btn_layout.addWidget(self.tab_old_backups_btn)
        self.tab_copy_btn = QPushButton()
        self.tab_copy_btn.setIcon(_make_copy_icon())
        self.tab_copy_btn.setIconSize(QSize(32, 16))
        self.tab_copy_btn.setStyleSheet("QPushButton{background-color:#e0e8ff;} QPushButton:hover{background-color:#c0d0ff;}")
        self.tab_copy_btn.setToolTip("Копировать папку — создать копию с теми же настройками")
        self.tab_copy_btn.clicked.connect(self._on_tab_copy_click)
        self.tab_copy_btn.setVisible(False)
        create_btn_layout.addWidget(self.tab_copy_btn)
        self.tab_rename_btn = QPushButton()
        self.tab_rename_btn.setIcon(_make_rename_icon())
        self.tab_rename_btn.setIconSize(QSize(32, 16))
        self.tab_rename_btn.setStyleSheet("QPushButton{background-color:#e0e8ff;} QPushButton:hover{background-color:#c0d0ff;}")
        self.tab_rename_btn.setToolTip("Переименовать папку текущего фильма")
        self.tab_rename_btn.clicked.connect(self._on_tab_rename_click)
        self.tab_rename_btn.setVisible(False)
        create_btn_layout.addWidget(self.tab_rename_btn)
        self.tab_delfolder_btn = QPushButton()
        self.tab_delfolder_btn.setIcon(_make_rmdir_icon())
        self.tab_delfolder_btn.setIconSize(QSize(32, 16))
        self.tab_delfolder_btn.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        self.tab_delfolder_btn.setToolTip("Безвозвратно удалить папку текущего фильма")
        self.tab_delfolder_btn.clicked.connect(self._on_tab_delfolder_click)
        self.tab_delfolder_btn.setVisible(False)
        create_btn_layout.addWidget(self.tab_delfolder_btn)
        ml.addLayout(create_btn_layout)

        # (Настройки по умолчанию перенесены в правую часть блока путей выше)

        # === ПОИСК И ФИЛЬТРАЦИЯ ===
        fg = QGroupBox("Поиск и фильтрация")
        self.filter_group = fg
        fl = QHBoxLayout(fg); fl.setSpacing(8)
        fl.addWidget(QLabel("Папка:"))
        self.filter_folder = QLineEdit()
        self.filter_folder.setPlaceholderText("имя папки...")
        self.filter_folder.setMaximumWidth(200)
        fl.addWidget(self.filter_folder)
        fl.addWidget(QLabel("Название:"))
        self.filter_title = QLineEdit()
        self.filter_title.setPlaceholderText("название фильма...")
        self.filter_title.setMaximumWidth(200)
        fl.addWidget(self.filter_title)
        fl.addWidget(QLabel("Год:"))
        self.filter_year = QLineEdit()
        self.filter_year.setPlaceholderText("год...")
        self.filter_year.setMaximumWidth(60)
        fl.addWidget(self.filter_year)
        fl.addWidget(QLabel("Абонемент:"))
        self.filter_sub_year = QComboBox()
        self.filter_sub_year.addItem("—")
        self.filter_sub_year.addItems(_SUB_YEARS)
        self.filter_sub_year.setMaximumWidth(80)
        fl.addWidget(self.filter_sub_year)
        self.filter_sub_month = QComboBox()
        self.filter_sub_month.addItem("—")
        self.filter_sub_month.addItems(_MONTHS_RU)
        self.filter_sub_month.setMaximumWidth(120)
        fl.addWidget(self.filter_sub_month)
        self.filter_btn = QPushButton("Поиск")
        self.filter_btn.setToolTip("Отфильтровать записи по введённым критериям")
        self.filter_btn.clicked.connect(self._apply_filter)
        fl.addWidget(self.filter_btn)
        self.filter_reset_btn = QPushButton("Сбросить")
        self.filter_reset_btn.setToolTip("Сбросить все фильтры (поиск + статусы) и показать все записи")
        self.filter_reset_btn.clicked.connect(self._reset_filter)
        fl.addWidget(self.filter_reset_btn)
        self.rows_count_lbl = QLabel("")
        self.rows_count_lbl.setToolTip("Количество видимых записей в таблице (с учётом фильтра)")
        fl.addWidget(self.rows_count_lbl)
        fl.addStretch()
        # filter_group добавляется ниже — под таблицей, над статусами

        # === ПАНЕЛЬ ФИЛЬТРАЦИИ ПО СТАТУСУ ===
        self.status_bar_widget = QWidget()
        status_bar = QHBoxLayout(self.status_bar_widget)
        status_bar.setContentsMargins(0, 0, 0, 0)
        status_bar.setSpacing(2)
        status_bar_lbl = QLabel("Статусы:")
        status_bar_lbl.setToolTip("Фильтрация по статусу записи.\nНажмите кнопку — отобразятся только записи с этим статусом.\nПовторный клик — сброс фильтра.")
        status_bar.addWidget(status_bar_lbl)
        # Все кнопки фильтрации в едином dict: ключ = строка
        # "new" → is_new, "text:XXX" → status_lbl.text()==XXX, "sp:N" → sort_priority==N, "custom:XXX" → произвольный фильтр
        self._status_filter_btns = {}
        def _add_filter_btn(key, label, bg_color, text_color, tooltip=None):
            sb = QPushButton(f"{label} (0)")
            sb.setCheckable(True)
            sb.setToolTip(tooltip or self._STATUS_TOOLTIPS.get(label, f"Показать записи со статусом «{label}»"))
            sb.setStyleSheet(
                f"QPushButton{{background-color:{bg_color}; color:{text_color};}}"
                f"QPushButton:hover{{border:2px solid {text_color};}}"
                f"QPushButton:checked{{border:3px solid #cc3300;}}")
            sb.clicked.connect(lambda checked, k=key: self._on_status_filter(k))
            status_bar.addWidget(sb)
            self._status_filter_btns[key] = sb
        # --- Индивидуальные статусы (то что пишется в колонке «Статус») ---
        _add_filter_btn("new",                   "NEW",               COLOR_NEW,            "#006600")
        _add_filter_btn("text:К обработке",      "К обработке",       COLOR_TO_PROCESS,     "blue")
        _add_filter_btn("text:Готово",           "Готово",            COLOR_READY,           "green")
        _add_filter_btn("text:В тесте",          "В тесте",           COLOR_IN_TEST,        "#b37400")
        _add_filter_btn("text:Нет аудио",        "Нет аудио",         COLOR_ERROR,          "red")
        _add_filter_btn("text:Нет видео",        "Нет видео",         COLOR_ERROR,          "red")
        _add_filter_btn("text:TXT!",             "TXT!",              COLOR_TXT_WARN,       "orange")
        _add_filter_btn("text:Видео в процессе", "Видео в процессе",  COLOR_VIDEO_PENDING,  "#8e44ad")
        _add_filter_btn("text:Неверный пароль",  "Неверный пароль",   COLOR_ERROR,          "red")
        _add_filter_btn("text:Ожидает видео",    "Ожидает видео",     "#e8e8e8",            "#cc6600")
        _add_filter_btn("text:Ожидает аудио",    "Ожидает аудио",     "#e8e8e8",            "#cc6600")
        _add_filter_btn("text:Нет файлов",       "Нет файлов",        "#e8e8e8",            "gray")
        _add_filter_btn("text:Чудовищная ошибка","Чудовищная ошибка",  "#ffe0e0",           "#cc0000")
        # --- Разделитель: группы статусов ---
        _sep1 = QFrame(); _sep1.setFrameShape(QFrame.VLine); _sep1.setStyleSheet("color: #aaa;")
        status_bar.addWidget(_sep1)
        _add_filter_btn("sp:3", "Ошибка",   COLOR_ERROR, "red",
                         "Группа: «Нет аудио» + «Нет видео»\nФайл выбран, но не найден на диске")
        _add_filter_btn("sp:1", "Ожидание", "#e8e8e8",   "#555",
                         "Группа: «Ожидает видео» + «Ожидает аудио» + «Нет файлов» + «Чудовищная ошибка»")
        # --- Разделитель: произвольные фильтры ---
        _sep2 = QFrame(); _sep2.setFrameShape(QFrame.VLine); _sep2.setStyleSheet("color: #aaa;")
        status_bar.addWidget(_sep2)
        _add_filter_btn("custom:no_audio_no_archive", "Нет аудио и архива", "#fff0e0", "#996600",
                         "Показать записи без аудио файла (>1 ГБ) и без архива")
        _add_filter_btn("custom:no_forum_url",        "Нет ссылки russdub", "#f0e0ff", "#660099",
                         "Показать записи без ссылки на форум russdub")
        # Выровнять высоту всех кнопок фильтрации
        _filter_btn_h = list(self._status_filter_btns.values())[0].sizeHint().height() if self._status_filter_btns else 22
        for _fb in self._status_filter_btns.values():
            _fb.setFixedHeight(_filter_btn_h)
        # Кнопка ⚙ настройки видимости кнопок
        self._status_settings_btn = QPushButton("⚙")
        self._status_settings_btn.setFixedSize(_filter_btn_h, _filter_btn_h)
        self._status_settings_btn.setToolTip("Настроить видимость кнопок фильтрации по статусам")
        self._status_settings_btn.clicked.connect(self._show_status_filter_settings)
        status_bar.addWidget(self._status_settings_btn)
        # Восстановить видимость кнопок из настроек
        # При первом запуске (нет настройки) — показать только основные кнопки
        _hidden = self.config.get("hidden_status_buttons", None)
        if _hidden is None:
            # Первый запуск — скрыть детальные статусы, показать основные + группы
            _hidden = [
                "text:Нет аудио", "text:Нет видео",            # детали → есть группа «Ошибка»
                "text:TXT!",                                    # редкий
                "text:Неверный пароль",                         # редкий
                "text:Ожидает видео", "text:Ожидает аудио",    # детали → есть группа «Ожидание»
                "text:Нет файлов", "text:Чудовищная ошибка",   # детали → есть группа «Ожидание»
                "custom:no_audio_no_archive",                   # кастомный
                "custom:no_forum_url",                          # кастомный
            ]
        for key, btn in self._status_filter_btns.items():
            if key in _hidden:
                btn.setVisible(False)
        status_bar.addStretch()
        # status_bar_widget добавляется ниже — под таблицей, над логом

        # === ТАБЛИЦА ===
        tg = QGroupBox("Отображаемые колонки")
        tl = QVBoxLayout(tg)
        tl.setContentsMargins(3, 3, 3, 3)

        self.table = QTableWidget(0, NUM_COLS)
        self.table.setHorizontalHeaderLabels(HEADERS)
        # Иконка-чекбокс для заголовка колонки выбора (вместо текстовой ☑)
        self._checkbox_header_icon = _make_checkbox_header_icon()
        hitem = self.table.horizontalHeaderItem(COL_SELECT)
        if hitem:
            hitem.setIcon(self._checkbox_header_icon)
        # Иконка Кинопоиска для заголовка колонки КП
        _kp_logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_logo.png")
        if os.path.isfile(_kp_logo):
            _kp_hitem = self.table.horizontalHeaderItem(COL_KP)
            if _kp_hitem:
                _kp_hitem.setIcon(QIcon(_kp_logo))
                _kp_hitem.setText("")  # Только иконка
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionsMovable(True)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        hdr = self.table.horizontalHeader()
        hdr.setMinimumSectionSize(30)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Перемещение колонок перетаскиванием
        hdr.setSectionsMovable(True)
        self._LOCKED_COLS = {COL_SELECT, COL_OPEN}
        hdr.sectionMoved.connect(self._on_section_moved)
        #        ☑  X  📁 Созд Папка Аудио       Видео Задерж Суфф Выход Назв Год Инфо T.A Торр.В Форум Стат Дата Абон Действ
        #        ☑  📁 Созд Папка Дорожка Видео Задерж Суфф Выход Назв Год Инфо Т. Торр.В Форум Стат Дата Абон Действ
        col_w = [28, 54, 130, 150, 120, 120, 90, 140, 400, 400, 65, 80, 35, 200, 200, 155, 130, 160, 260]
        for i, w in enumerate(col_w):
            self.table.setColumnWidth(i, w)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        # Колонка Действия: скрыта (кнопки только на вкладке фильма)
        self.table.setColumnHidden(COL_ACTIONS, True)

        # Клик по ячейке таблицы — загрузить txt этой строки
        self.table.cellClicked.connect(self._on_cell_clicked)

        # Сортировка по клику на заголовок
        hdr.sectionClicked.connect(self._on_header_clicked)
        # Правый клик на заголовке — меню видимости колонок
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._show_column_menu)
        # Автосохранение ширин колонок при изменении пользователем
        hdr.sectionResized.connect(lambda: self.schedule_autosave())
        # Стиль заголовка
        hdr.setStyleSheet(
            f"QHeaderView::section {{ background-color: {COLOR_HEADER}; color: white;"
            f" font-weight: bold; font-size: 9pt; padding: 3px; border: 1px solid #666; }}")
        self._set_header_tooltips()

        # === ЧЕКБОКСЫ ВИДИМОСТИ КОЛОНОК ===
        col_vis_layout = QHBoxLayout()
        col_vis_layout.setSpacing(2)
        col_vis_layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Колонки:")
        lbl.setFont(QFont("Arial", 8))
        lbl.setToolTip("Включить/выключить видимость колонок в таблице")
        col_vis_layout.addWidget(lbl, 0, Qt.AlignVCenter)
        self._col_checkboxes = []
        # Короткие названия для чекбоксов
        short_names = ["☑", "📁", "Создана", "♪Папка", "♪Дорожка", "Пароль", "▶Источник", "♪Задержка",
                       "Пре/Суфф", "▶Выходной", "Название", "Год",
                       "txt", "♪Т.", "▶Торрент", "Форум", "Статус", "Дата", "Абон.", "КП", "Действия"]
        for i in range(NUM_COLS):
            if i == COL_ACTIONS:
                # Колонка скрыта навсегда — чекбокс не нужен
                self._col_checkboxes.append(None)
                continue
            name = short_names[i]
            # Для иконок ♪ и ▶ создаём виджет с увеличенной иконкой
            if "♪" in name or "▶" in name:
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(0)
                cb = QCheckBox()
                cb.setFont(QFont("Arial", 7))
                hl.addWidget(cb, 0, Qt.AlignVCenter)
                if "♪" in name:
                    text_part = name.replace("♪", "")
                    note_lbl = QLabel("♪")
                    note_lbl.setFont(QFont("Arial", 11))
                    note_lbl.setContentsMargins(1, 0, 1, 0)
                    note_lbl.mousePressEvent = lambda e, c=cb: c.toggle()
                    hl.addWidget(note_lbl, 0, Qt.AlignVCenter)
                    txt_lbl = QLabel(text_part)
                    txt_lbl.setFont(QFont("Arial", 7))
                    txt_lbl.mousePressEvent = lambda e, c=cb: c.toggle()
                    hl.addWidget(txt_lbl, 0, Qt.AlignVCenter)
                else:
                    # ▶ — отдельный лейбл (крупный) + текст (7pt), каждый VCenter независимо
                    text_part = name.replace("▶", "")
                    tri_lbl = QLabel("▶")
                    tri_lbl.setFont(QFont("Arial", 11))
                    tri_lbl.setContentsMargins(1, 0, 1, 0)
                    tri_lbl.mousePressEvent = lambda e, c=cb: c.toggle()
                    hl.addWidget(tri_lbl, 0, Qt.AlignVCenter)
                    txt_lbl = QLabel(text_part)
                    txt_lbl.setFont(QFont("Arial", 7))
                    txt_lbl.mousePressEvent = lambda e, c=cb: c.toggle()
                    hl.addWidget(txt_lbl, 0, Qt.AlignVCenter)
                col_vis_layout.addWidget(w, 0, Qt.AlignVCenter)
            else:
                cb = QCheckBox(name)
                cb.setFont(QFont("Arial", 7))
                col_vis_layout.addWidget(cb, 0, Qt.AlignVCenter)
            cb.setChecked(True)
            cb.setToolTip(f"Показать/скрыть колонку «{HEADERS[i]}»")
            if i == COL_FOLDER or i == COL_SELECT:
                cb.setEnabled(False)  # Нельзя скрыть
            cb.toggled.connect(lambda checked, idx=i: self._toggle_column(idx, checked))
            self._col_checkboxes.append(cb)
        col_vis_layout.addStretch()
        tl.addLayout(col_vis_layout)

        # QStackedWidget: страница 0 = таблица, страница 1 = лейбл загрузки
        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(self.table)          # index 0
        self._loading_label = QLabel("Загрузка...")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._loading_label.setStyleSheet(
            "font-size: 48px; font-weight: bold; color: #336699; padding: 80px;")
        self._table_stack.addWidget(self._loading_label)  # index 1
        self._table_stack.setCurrentIndex(0)
        tl.addWidget(self._table_stack)

        # === ПАНЕЛЬ ДЕЙСТВИЙ ДЛЯ ВЫБРАННЫХ (QGroupBox с рамкой, 2 строки) ===
        self.batch_bar_widget = QGroupBox("Действия для выбранных:")
        self.batch_bar_widget.setStyleSheet(
            "QGroupBox { border: 1px solid #999; border-radius: 4px; margin-top: 6px; padding-top: 14px; font-weight: bold; }"
            " QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        self.batch_bar_widget.setToolTip("Действия для строк, выбранных чекбоксами ☑ в первой колонке.\nКлик по заголовку ☑ — выбрать/снять все.")
        _batch_vbox = QVBoxLayout(self.batch_bar_widget)
        _batch_vbox.setContentsMargins(4, 2, 4, 2)
        _batch_vbox.setSpacing(2)
        # Строка 1
        _batch_row1 = QHBoxLayout()
        _batch_row1.setSpacing(4)
        # Строка 2
        _batch_row2 = QHBoxLayout()
        _batch_row2.setSpacing(4)
        # Лейбл — для setText при переключении вкладка/таблица
        self.batch_lbl = QLabel("")
        self.batch_lbl.setVisible(False)  # текст теперь в заголовке QGroupBox
        # icon_type: "play", "unrar", "archive", "to_result", "video"
        _batch_defs = [
            ("batch_process_btn", "Обработать", "#cce5ff", "btn_play", self._process_single,
             "Запустить mkvmerge для всех выбранных строк со статусом «К обработке»", "play"),
            ("batch_download_btn", "Скачать", "#e0f0ff", "btn_download", self._action_download,
             "Скачать аудио дорожки: торрент-файл → торрент-клиент, ссылка → браузер", "download"),
            ("batch_to_res_btn", "В Результат", "#ccffcc", "btn_to_res", self._action_to_result,
             "Переместить тестовые файлы в результат для всех выбранных строк", "to_result"),
            ("batch_unrar_btn", "Архив", "#ffe4c4", "btn_unrar", self._action_unrar,
             "Распаковать архивы для всех выбранных строк с архивом", "unrar"),
            ("batch_del_archive_btn", "Архив", "#ffcccc", "btn_del_archive", self._action_del_archive,
             "Удалить архивы для всех выбранных строк где аудио уже распаковано", "archive"),
            ("batch_del_test_btn", "Тест", "#ffcccc", "btn_del_test", self._action_del_test,
             "Удалить тестовые видео файлы для всех выбранных строк", "video"),
            ("batch_del_src_btn", "Источник", "#ffcccc", "btn_del_src", self._action_del_source,
             "Удалить видео источники для всех выбранных строк", "video"),
            ("batch_del_res_btn", "Результат", "#ffcccc", "btn_del_res", self._action_del_result,
             "Удалить видео результаты для всех выбранных строк", "video"),
        ]
        self.batch_btns = {}
        self.batch_preview_btns = {}
        self._batch_labels = {}
        self._batch_actions = {}
        self._batch_colors = {}
        # Кнопки строки 1: btn_play (+ чекбоксы)
        # Кнопки строки 2: btn_to_res и далее
        _row2_keys = {"btn_to_res", "btn_unrar", "btn_del_archive", "btn_del_test", "btn_del_src", "btn_del_res"}
        for item in _batch_defs:
            icon_type = item[6] if len(item) > 6 else None
            attr, label, bg_color, bk, action_fn, tooltip = item[:6]
            target_row = _batch_row2 if bk in _row2_keys else _batch_row1
            btn_container = QWidget()
            btn_layout = QHBoxLayout(btn_container)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(0)
            b = QPushButton(label)
            if icon_type == "play":
                b.setIcon(_make_play_icon())
                b.setIconSize(QSize(16, 16))
            elif icon_type == "unrar":
                b.setIcon(_make_unrar_icon())
                b.setIconSize(QSize(32, 16))
            elif icon_type == "archive":
                b.setIcon(_make_del_archive_icon())
                b.setIconSize(QSize(32, 16))
            elif icon_type == "to_result":
                b.setIcon(_make_to_result_icon())
                b.setIconSize(QSize(32, 16))
            elif icon_type == "video":
                b.setIcon(_make_del_video_icon())
                b.setIconSize(QSize(32, 16))
            elif icon_type == "download":
                _dl_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "qbittorrent_icon.png")
                if os.path.isfile(_dl_icon_path):
                    b.setIcon(QIcon(_dl_icon_path))
                    b.setIconSize(QSize(16, 16))
            if bg_color == "#ffcccc":
                hover_bg = "#ff9999"
            elif bg_color == "#ccffcc":
                hover_bg = "#99ff99"
            elif bg_color == "#ffe4c4":
                hover_bg = "#ffc896"
            else:
                hover_bg = "#99ccff"
            b.setStyleSheet(f"QPushButton{{background-color:{bg_color};}} QPushButton:hover{{background-color:{hover_bg};}} QPushButton:disabled{{background-color:{bg_color};}}")
            b.setEnabled(False)
            b.setToolTip(tooltip)
            b.clicked.connect(lambda _, k=bk, a=action_fn: self._batch_action(k, a))
            btn_layout.addWidget(b)
            preview_btn = QPushButton()
            preview_btn.setIcon(_make_eye_icon())
            preview_btn.setIconSize(QSize(16, 16))
            preview_btn.setFixedWidth(24)
            preview_btn.setCheckable(True)
            preview_btn.setToolTip(f"Показать список записей для действия «{label}»")
            preview_btn.setStyleSheet(f"QPushButton{{background-color:{bg_color}; border-left:1px solid #888;}} QPushButton:hover{{background-color:{hover_bg};}} QPushButton:checked{{background-color:#ff8c00; border:3px solid #cc3300; border-radius:2px;}}")
            preview_btn.clicked.connect(lambda checked=False, k=bk: self._show_batch_preview(k))
            preview_btn.hide()
            btn_layout.addWidget(preview_btn)
            self.batch_preview_btns[bk] = preview_btn
            target_row.addWidget(btn_container)
            setattr(self, attr, b)
            self.batch_btns[bk] = b
            self._batch_labels[bk] = label
            self._batch_actions[bk] = action_fn
            self._batch_colors[bk] = bg_color
            # Чекбоксы после кнопки Обработать — в первую строку
            if bk == "btn_play":
                self.batch_del_audio_cb = QCheckBox("Удалить родные аудио дорожки")
                self.batch_del_audio_cb.setToolTip(
                    "При обработке: удалить ВСЕ существующие аудио дорожки\n"
                    "из оригинального видео файла (--no-audio).\n"
                    "Видео, субтитры и главы остаются.")
                _batch_row1.addWidget(self.batch_del_audio_cb)
                self.batch_best_track_cb = QCheckBox("Только большая аудио дорожка")
                self.batch_best_track_cb.setChecked(True)
                self.batch_best_track_cb.setToolTip(
                    "При обработке: автоматически сканировать аудио файл\n"
                    "и оставлять только самую крупную дорожку (например TrueHD).\n"
                    "Мелкие дорожки (например встроенный AC3) исключаются.")
                _batch_row1.addWidget(self.batch_best_track_cb)
        # Кнопка "Сбросить NEW" — в конце строки 2
        reset_new_container = QWidget()
        reset_new_layout = QHBoxLayout(reset_new_container)
        reset_new_layout.setContentsMargins(0, 0, 0, 0)
        reset_new_layout.setSpacing(0)
        self.reset_new_btn = QPushButton("📌 Сбросить NEW")
        self.reset_new_btn.clicked.connect(self._reset_new_flags)
        self.reset_new_btn.setToolTip("Убрать пометку NEW со всех строк\nи вернуть обычную подсветку статусов")
        self.reset_new_btn.setEnabled(False)
        reset_new_layout.addWidget(self.reset_new_btn)
        self.reset_new_preview_btn = QPushButton()
        self.reset_new_preview_btn.setIcon(_make_eye_icon())
        self.reset_new_preview_btn.setIconSize(QSize(16, 16))
        self.reset_new_preview_btn.setFixedWidth(24)
        self.reset_new_preview_btn.setCheckable(True)
        self.reset_new_preview_btn.setToolTip("Показать список NEW записей")
        self.reset_new_preview_btn.setStyleSheet("QPushButton:checked{background-color:#ff8c00; border:3px solid #cc3300; border-radius:2px;}")
        self.reset_new_preview_btn.clicked.connect(self._show_new_preview)
        self.reset_new_preview_btn.hide()
        reset_new_layout.addWidget(self.reset_new_preview_btn)
        _batch_row2.addWidget(reset_new_container)
        _batch_row1.addStretch()
        _batch_row2.addStretch()
        _batch_vbox.addLayout(_batch_row1)
        _batch_vbox.addLayout(_batch_row2)

        # === ВКЛАДКИ: таблица + записи ===
        self.tab_widget = QTabWidget(central)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_record_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.addTab(tg, "Таблица")
        # Первую вкладку нельзя закрыть
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)
        self.tab_widget.tabBar().setTabButton(0, QTabBar.LeftSide, None)
        # Кнопка "Закрыть все вкладки" в углу QTabWidget
        _close_all_btn = QPushButton("✕ Закрыть все")
        _close_all_btn.setToolTip("Закрыть все вкладки с фильмами\nВкладка «Таблица» останется открытой")
        _close_all_btn.setStyleSheet("QPushButton{padding:2px 8px; font-size:11px;} QPushButton:hover{color:red;}")
        _close_all_btn.clicked.connect(self._close_all_record_tabs)
        self.tab_widget.setCornerWidget(_close_all_btn, Qt.TopRightCorner)
        # Кнопка "Выбрать открытые" — прямо после последней вкладки (child tab_widget, не tabBar — чтобы не обрезалось)
        self._select_open_btn = QPushButton("☑", self.tab_widget)
        self._select_open_btn.setToolTip("Отметить/снять чекбоксы всех строк,\nу которых открыта вкладка")
        self._select_open_btn.setStyleSheet(
            "QPushButton{padding:2px 6px; font-size:12px; border:1px solid #aaa; border-radius:3px;"
            " background:#e0e8ff;} QPushButton:hover{background:#c0d0ff;}")
        self._select_open_btn.clicked.connect(self._select_open_tabs)
        self._select_open_btn.setVisible(False)
        self._select_open_btn.setFixedHeight(24)
        # Репозиционировать при изменении размера tabBar
        self.tab_widget.tabBar().installEventFilter(self)

        # === TXT панель (показывается при клике на кнопку txt) ===
        self.txt_group = QGroupBox("Содержимое txt")
        self.txt_group.setVisible(False)
        txl = QVBoxLayout(self.txt_group)
        txt_top = QHBoxLayout()
        self.txt_status_lbl = QLabel(""); self.txt_status_lbl.setStyleSheet("color:green;")
        txt_top.addStretch(); txt_top.addWidget(self.txt_status_lbl)
        txl.addLayout(txt_top)
        self.txt_edit = QTextEdit(); self.txt_edit.setFont(QFont("Consolas", 10))
        txl.addWidget(self.txt_edit)

        # === ЛОГ (внизу) ===
        log_g = QGroupBox("Лог")
        lgl = QVBoxLayout(log_g)
        self.log_text = QPlainTextEdit(); self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9)); self.log_text.setMaximumBlockCount(2000)
        lgl.addWidget(self.log_text)

        ml.addWidget(self.batch_bar_widget)

        # Контейнер: таблица/вкладки сверху + статусы снизу
        table_container = QWidget()
        _tc_layout = QVBoxLayout(table_container)
        _tc_layout.setContentsMargins(0, 0, 0, 0)
        _tc_layout.setSpacing(0)
        _tc_layout.addWidget(self.tab_widget, 1)
        _tc_layout.addWidget(fg)
        _tc_layout.addWidget(self.status_bar_widget)

        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.bottom_splitter.addWidget(log_g)
        self.bottom_splitter.addWidget(self.txt_group)
        self.txt_group.setVisible(False)

        splitter = QSplitter(Qt.Vertical, central)
        splitter.addWidget(table_container)
        splitter.addWidget(self.bottom_splitter)
        splitter.setSizes([600, 250])
        ml.addWidget(splitter, 1)

        # Ctrl+S
        self.txt_edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.txt_edit and event.type() == event.Type.KeyPress:
            if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_S:
                self._save_current_txt(); return True
        # Репозиционировать кнопку "Выбрать открытые" при изменении tabBar
        if obj is self.tab_widget.tabBar() and event.type() in (
                event.Type.Resize, event.Type.LayoutRequest, event.Type.Paint):
            self._reposition_select_open_btn()
        return super().eventFilter(obj, event)

    def _toggle_paths_section(self):
        """Свернуть/развернуть секцию настроек."""
        collapsed = self._paths_group.isVisible()
        self._paths_collapsed = collapsed  # Запомнить для восстановления при переключении вкладок
        self._paths_group.setVisible(not collapsed)
        if collapsed:
            self._paths_toggle_btn.setText("▼ Показать настройки")
            self._update_paths_summary()
            self._paths_summary_lbl.setVisible(True)
        else:
            self._paths_toggle_btn.setText("▲ Скрыть настройки")
            self._paths_summary_lbl.setVisible(False)
        self.schedule_autosave()

    def _update_paths_summary(self):
        """Обновить краткую сводку счётчиков для свёрнутой секции путей."""
        if not hasattr(self, '_paths_summary_lbl') or self._paths_summary_lbl.isHidden():
            return
        parts = []
        for lbl in [self.audio_count_lbl, self.video_count_lbl,
                     self.output_count_lbl, self.test_count_lbl]:
            t = lbl.text().strip()
            if t:
                parts.append(t)
        self._paths_summary_lbl.setText("   |   ".join(parts) if parts else "")

    def _path_row(self, grid, row, label, value, file_mode=False):
        lbl = QLabel(label)
        # Увеличить иконки эмодзи через HTML
        if "🎵" in label or "📽️" in label:
            html_label = label.replace("🎵", "<span style='font-size:14pt'>🎵</span>")
            html_label = html_label.replace("📽️", "<span style='font-size:14pt'>📽️</span>")
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(html_label)
        grid.addWidget(lbl, row, 0)
        e = QLineEdit(value); e.setMinimumWidth(300); grid.addWidget(e, row, 1)
        if not hasattr(self, '_path_edits'):
            self._path_edits = []
        self._path_edits.append(e)
        e.textChanged.connect(lambda: self._adjust_path_widths())
        b = QPushButton("..."); b.setMaximumWidth(30)
        b.setToolTip("Выбрать файл" if file_mode else "Выбрать папку")
        if file_mode:
            b.clicked.connect(lambda: self._browse_file(e))
        else:
            b.clicked.connect(lambda: self._browse_dir(e))
        grid.addWidget(b, row, 2)
        # 📁 сразу после "..."
        if not file_mode:
            bf = QPushButton("📁"); bf.setFixedWidth(30)
            bf.setToolTip("Открыть папку в проводнике")
            bf.clicked.connect(lambda: self._open_folder(e))
            grid.addWidget(bf, row, 3)
        return e

    def _setup_auto_width(self, widget, base_w=300):
        """Настроить авто-ширину поля ввода под содержимое.
        base_w — минимальная ширина, далее растёт под текст, макс 50% экрана.
        Для QComboBox — ширина по самому длинному элементу в списке."""
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            cap = int(screen_w * 0.5)
        except Exception:
            cap = 800
        def adjust(text=""):
            fm = widget.fontMetrics()
            if isinstance(widget, QComboBox):
                # Ширина по самому длинному элементу
                max_tw = 0
                for i in range(widget.count()):
                    tw = fm.horizontalAdvance(widget.itemText(i))
                    if tw > max_tw:
                        max_tw = tw
                text_w = max_tw + 50  # +50 для стрелки и отступов
            else:
                text_w = fm.horizontalAdvance(widget.text()) + 30
            w = max(base_w, min(text_w, cap))
            widget.setMinimumWidth(w)
            widget.setMaximumWidth(w)
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(adjust)
        else:
            widget.textChanged.connect(adjust)
        adjust()

    def _adjust_path_widths(self):
        """Подогнать ширину всех полей путей под самый длинный путь."""
        if not hasattr(self, '_path_edits'):
            return
        max_w = 300
        for e in self._path_edits:
            fm = e.fontMetrics()
            text_w = fm.horizontalAdvance(e.text()) + 30
            if text_w > max_w:
                max_w = text_w
        # Ограничить максимум — не шире 70% экрана
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            cap = int(screen_w * 0.7)
        except Exception:
            cap = 1200
        if max_w > cap:
            max_w = cap
        for e in self._path_edits:
            e.setMinimumWidth(max_w)
            e.setMaximumWidth(max_w)

    def _browse_dir(self, edit):
        p = QFileDialog.getExistingDirectory(self, "Выбрать папку")
        if p: edit.setText(p)

    def _browse_file(self, edit):
        p, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", "", "Executable (*.exe)")
        if p: edit.setText(p)

    def _open_folder(self, edit):
        """Открыть папку из указанного поля в проводнике."""
        p = edit.text()
        if p and os.path.isdir(p): os.startfile(p)

    # ──────────────────────────────────
    #  Сканирование
    # ──────────────────────────────────
    @staticmethod
    def _is_audio(fn):
        lo = fn.lower()
        return lo.endswith(AUDIO_EXTS) or '.thd' in lo

    @staticmethod
    def _is_archive_by_magic(filepath):
        """Определить архив по magic bytes (сигнатуре файла) — работает для файлов без расширения."""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(8)
            if not header:
                return False
            # RAR: 'Rar!' (52 61 72 21)
            if header[:4] == b'Rar!':
                return True
            # 7z: 37 7A BC AF 27 1C
            if header[:6] == b'7z\xbc\xaf\x27\x1c':
                return True
            # ZIP/PK: 50 4B 03 04
            if header[:4] == b'PK\x03\x04':
                return True
            return False
        except OSError:
            return False

    def _format_audio_size(self, folder_path, filename):
        """Форматировать имя аудио файла с размером: 'file.ac3  [125 МБ]'"""
        try:
            size = os.path.getsize(os.path.join(folder_path, filename))
            if size >= 1024**3:
                s = f"{size / 1024**3:.1f} ГБ"
            elif size >= 1024**2:
                s = f"{size / 1024**2:.0f} МБ"
            else:
                s = f"{size / 1024:.0f} КБ"
            return f"{filename}  [{s}]"
        except OSError:
            return filename

    def _audio_filename(self, r):
        """Получить чистое имя аудио файла из комбобокса (без размера)."""
        combo = r["audio_combo"]
        data = combo.currentData(Qt.UserRole)
        return data if data else combo.currentText()

    def _starter_filename(self, r):
        """Получить чистое имя стартового аудио файла (или '' если не выбран)."""
        combo = r.get("starter_combo")
        if not combo or not combo.isEnabled():
            return ""
        data = combo.currentData(Qt.UserRole)
        return data if data else ""

    def _ender_filename(self, r):
        """Получить чистое имя конечного аудио файла (или '' если не выбран)."""
        combo = r.get("ender_combo")
        if not combo or not combo.isEnabled():
            return ""
        data = combo.currentData(Qt.UserRole)
        return data if data else ""

    _AUDIO_MAIN_THRESHOLD = 1024 ** 3  # 1 ГБ — порог для основной аудио дорожки

    def _has_main_audio(self, r):
        """True если в папке есть хотя бы один аудио файл >= 1 ГБ (основная дорожка).
        Маленькие файлы (< 1 ГБ) — стартовые/финальные, НЕ считаются основной дорожкой."""
        fp = r.get("folder_path", "")
        for fn in r.get("audio_files", []):
            try:
                if os.path.getsize(os.path.join(fp, fn)) >= self._AUDIO_MAIN_THRESHOLD:
                    return True
            except OSError:
                pass
        return False

    def _populate_audio_combo(self, combo, files, folder_path):
        """Заполнить комбобокс основных аудио файлов (ТОЛЬКО файлы >= 1 ГБ)."""
        combo.clear()
        for fn in files:
            try:
                sz = os.path.getsize(os.path.join(folder_path, fn))
            except OSError:
                sz = 0
            if sz >= self._AUDIO_MAIN_THRESHOLD:
                display = self._format_audio_size(folder_path, fn)
                combo.addItem(display, fn)  # userData = чистое имя файла

    def _populate_starter_combo(self, combo, files, folder_path, exclude_file=""):
        """Заполнить starter/ender комбобокс (ТОЛЬКО файлы < 1 ГБ). Первый пункт '— нет —'. exclude_file — str или list."""
        combo.clear()
        combo.addItem("— нет —", "")
        if isinstance(exclude_file, str):
            excludes = {exclude_file} if exclude_file else set()
        else:
            excludes = set(f for f in exclude_file if f)
        for fn in files:
            if fn in excludes:
                continue
            try:
                sz = os.path.getsize(os.path.join(folder_path, fn))
            except OSError:
                sz = 0
            if sz < self._AUDIO_MAIN_THRESHOLD:
                display = self._format_audio_size(folder_path, fn)
                combo.addItem(display, fn)

    def _sync_audio_combos(self, r):
        """Перекрёстная синхронизация аудио селектов — выбранный файл исключается из других."""
        main_file = r["audio_combo"].currentData(Qt.UserRole) or ""
        starter_file = r["starter_combo"].currentData(Qt.UserRole) or ""
        ender_file = r["ender_combo"].currentData(Qt.UserRole) or ""

        # Обновить starter: исключить main + ender
        sc = r["starter_combo"]
        sc.blockSignals(True)
        self._populate_starter_combo(sc, r["audio_files"], r["folder_path"],
                                     exclude_file=[main_file, ender_file])
        if starter_file and starter_file not in (main_file, ender_file):
            for i in range(sc.count()):
                if sc.itemData(i, Qt.UserRole) == starter_file:
                    sc.setCurrentIndex(i)
                    break
        sc.setEnabled(len(r["audio_files"]) > 1)
        sc.blockSignals(False)

        # Обновить ender: исключить main + starter
        ec = r["ender_combo"]
        ec.blockSignals(True)
        self._populate_starter_combo(ec, r["audio_files"], r["folder_path"],
                                     exclude_file=[main_file, starter_file])
        if ender_file and ender_file not in (main_file, starter_file):
            for i in range(ec.count()):
                if ec.itemData(i, Qt.UserRole) == ender_file:
                    ec.setCurrentIndex(i)
                    break
        ec.setEnabled(len(r["audio_files"]) > 1)
        ec.blockSignals(False)

        # Синхронизировать вкладку если открыта
        fn = r["folder_name"]
        if fn in self._open_tabs:
            tw = self._open_tabs[fn]["widgets"]
            for key in ("starter_combo", "ender_combo"):
                src = r.get(key)
                dst = tw.get(key)
                if src and dst:
                    dst.blockSignals(True)
                    dst.clear()
                    for i in range(src.count()):
                        dst.addItem(src.itemText(i), src.itemData(i, Qt.UserRole))
                    dst.setCurrentIndex(src.currentIndex())
                    dst.setEnabled(src.isEnabled())
                    dst.blockSignals(False)

    def _find_audio_folders(self, path, result):
        try:
            items = os.listdir(path)
        except OSError:
            return
        af = [f for f in items if os.path.isfile(os.path.join(path, f)) and self._is_audio(f)]
        if af:
            result.append({"name": os.path.basename(path), "path": path, "files": af})
        else:
            # Папка без аудио — если есть .txt, значит создана для аудио дорожки
            has_txt = any(f.lower().endswith('.txt') for f in items
                         if os.path.isfile(os.path.join(path, f)))
            if has_txt:
                result.append({"name": os.path.basename(path), "path": path, "files": []})
            else:
                for it in items:
                    ip = os.path.join(path, it)
                    if os.path.isdir(ip):
                        self._find_audio_folders(ip, result)

    def _scan_audio_silent(self):
        p = self.audio_path_edit.text()
        if not p or not os.path.isdir(p): return
        self.audio_folders = []
        self._find_audio_folders(p, self.audio_folders)
        self.audio_folders.sort(key=lambda x: x["name"])
        total = sum(len(f["files"]) for f in self.audio_folders)
        self.audio_count_lbl.setText(f"Папок: {len(self.audio_folders)}, аудио файлов: {total}")

    def _scan_video_silent(self):
        p = self.video_path_edit.text()
        if not p or not os.path.isdir(p): return
        self.video_files = [f for f in os.listdir(p) if f.lower().endswith(VIDEO_EXTS)]
        self.available_videos = self.video_files.copy()
        self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")

    # ──────────────────────────────────
    #  Таблица — построение
    # ──────────────────────────────────
    def _build_table(self, skip_status_check=False):
        self.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self.rows = []
        self.available_videos = self.video_files.copy()
        n = len(self.audio_folders)
        self.table.setRowCount(n)
        for i, folder in enumerate(self.audio_folders):
            self._create_row(i, folder, skip_status=skip_status_check, skip_insert=True)
        self.setUpdatesEnabled(True)
        self._update_archive_btn_count()
        self._update_batch_buttons()
        # Переподключить открытые вкладки к новым строкам
        self._reconnect_open_tabs()
        self._update_rows_count()
        self.log(f"Создано строк: {len(self.rows)}")

    def _create_row(self, idx, folder, cached=None, insert_at=None, skip_status=False, skip_insert=False):
        """cached — кэшированные данные (folder_created, archive_file) чтобы не делать I/O заново.
        skip_insert — строка уже создана через setRowCount(), не вызывать insertRow()."""
        if not skip_insert:
            self.table.insertRow(idx)
        self.table.setRowHeight(idx, 30)
        base_color = COLOR_ROW_EVEN if idx % 2 == 0 else COLOR_ROW_ODD

        # --- 0: Select (чекбокс выбора) ---
        select_cb = QCheckBox(self.table)
        select_cb.setToolTip("Выбрать для массовых операций")
        sw = QWidget(self.table); sl = QHBoxLayout(sw); sl.setContentsMargins(0,0,0,0)
        sl.setAlignment(Qt.AlignCenter); sl.addWidget(select_cb)
        self.table.setCellWidget(idx, COL_SELECT, sw)

        # --- 1: Open folder ---
        open_w = QWidget(self.table)
        open_l = QHBoxLayout(open_w); open_l.setContentsMargins(1,1,1,1); open_l.setSpacing(1)
        open_btn = QPushButton("📁", self.table); open_btn.setFont(BTN_FONT); open_btn.setFixedWidth(24)
        open_btn.setToolTip(f"Открыть папку «{folder['name']}» в проводнике")
        tab_btn = QPushButton("📋", self.table); tab_btn.setFont(BTN_FONT); tab_btn.setFixedWidth(24)
        tab_btn.setToolTip("Открыть во вкладке для редактирования")
        open_l.addWidget(open_btn); open_l.addWidget(tab_btn)
        self.table.setCellWidget(idx, COL_OPEN, open_w)

        # --- 2: Folder ---
        fi = QTableWidgetItem(folder["name"])
        fi.setToolTip(f"Папка: {folder['path']}")
        fi.setFlags(fi.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(idx, COL_FOLDER, fi)

        # --- 3: Audio data widgets (без parent — данные хранятся в row dict, не отображаются) ---
        audio_combo = NoScrollComboBox(); audio_combo.setFont(BTN_FONT)
        if folder["files"]:
            self._populate_audio_combo(audio_combo, folder["files"], folder["path"])
            audio_combo.setCurrentIndex(0)
            audio_combo.setToolTip("Основной аудио файл — будет вставлен в видео при обработке\nРазмер файла показан в скобках")
        else:
            audio_combo.addItem("⚠ Нет аудио файлов", "")
            audio_combo.setEnabled(False)
            audio_combo.setToolTip("В папке нет аудио файлов — добавьте аудио дорожку")
            audio_combo.setStyleSheet("color: red;")
        # Стартовый аудио файл (воспроизводится перед основным)
        starter_combo = NoScrollComboBox(); starter_combo.setFont(BTN_FONT)
        if folder["files"] and len(folder["files"]) > 1:
            self._populate_starter_combo(starter_combo, folder["files"], folder["path"],
                                          exclude_file=audio_combo.currentData(Qt.UserRole) or "")
            starter_combo.setToolTip("Стартовый аудио файл — воспроизводится ДО основного\n"
                                     "Используется для intro/заставок\n"
                                     "mkvmerge: starter + main (append)")
        else:
            starter_combo.addItem("— нет —", "")
            starter_combo.setEnabled(False)
            starter_combo.setToolTip("Стартовый файл недоступен — нужно 2+ аудио файла в папке")
        # Конечный аудио файл (воспроизводится после основного)
        ender_combo = NoScrollComboBox(); ender_combo.setFont(BTN_FONT)
        if folder["files"] and len(folder["files"]) > 1:
            self._populate_starter_combo(ender_combo, folder["files"], folder["path"],
                                          exclude_file=audio_combo.currentData(Qt.UserRole) or "")
            ender_combo.setToolTip("Конечный аудио файл — воспроизводится ПОСЛЕ основного\n"
                                    "Используется для outro/финальных титров\n"
                                    "mkvmerge: main + ender (append)")
        else:
            ender_combo.addItem("— нет —", "")
            ender_combo.setEnabled(False)
            ender_combo.setToolTip("Конечный файл недоступен — нужно 2+ аудио файла в папке")
        # Пароль от архива с аудио дорожкой
        password_entry = QLineEdit(""); password_entry.setFont(BTN_FONT)
        password_entry.setPlaceholderText("пароль...")
        password_entry.setToolTip("Пароль от архива с аудио дорожкой (для расшифровки RAR архива)")
        move_archive_btn = QPushButton("📦"); move_archive_btn.setFont(BTN_FONT)
        move_archive_btn.setFixedWidth(28)
        move_archive_btn.setToolTip("Переместить архив с аудио дорожкой в эту папку")
        # Виджеты данных
        audio_summary = QLabel("", self.table)
        audio_summary.setFont(BTN_FONT)
        audio_summary.setTextFormat(Qt.RichText)
        audio_summary.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(idx, COL_AUDIO, audio_summary)
        self.table.setCellWidget(idx, COL_PASSWORD, password_entry)

        # --- 3: Video — виджеты данных (скрыты) + summary label + кнопка ⏳ ---
        video_combo = NoScrollComboBox(); video_combo.setFont(BTN_FONT)
        video_combo.setItemDelegate(_BoldPartDelegate(video_combo))
        video_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        video_combo.setToolTip("Видео файл")
        video_btn = QPushButton("..."); video_btn.setFont(BTN_FONT); video_btn.setFixedWidth(28)
        video_btn.setToolTip("Выбрать видео вручную")
        video_dur_lbl = QLabel(""); video_dur_lbl.setFont(QFont("Arial", 8, QFont.Bold))
        video_dur_lbl.setStyleSheet("color:#333;"); video_dur_lbl.setToolTip("Длительность видео")
        video_pending_btn = QPushButton("⏳", self.table); video_pending_btn.setFont(BTN_FONT); video_pending_btn.setFixedWidth(28)
        video_pending_btn.setToolTip("Пометить: видео ещё скачивается")
        video_summary = QLabel("", self.table)
        video_summary.setFont(BTN_FONT); video_summary.setTextFormat(Qt.RichText)
        vw = QWidget(self.table); vl = QHBoxLayout(vw); vl.setContentsMargins(2,1,2,1); vl.setSpacing(2)
        vl.addWidget(video_summary, 1); vl.addWidget(video_pending_btn)
        self.table.setCellWidget(idx, COL_VIDEO, vw)

        # --- 4: Delay info (только отображение, редактирование — на вкладке фильма) ---
        dw = QWidget(self.table); dl = QHBoxLayout(dw); dl.setContentsMargins(2,1,2,1); dl.setSpacing(2)
        delay_lbl = QLabel('1 <span style="color:red">✗</span>', self.table)
        delay_lbl.setFont(BTN_FONT)
        delay_lbl.setTextFormat(Qt.RichText)
        delay_lbl.setToolTip("Количество задержек и статус подтверждения\nРедактирование на вкладке фильма")
        dl.addWidget(delay_lbl)
        self.table.setCellWidget(idx, COL_DELAY, dw)
        _delay_value = "0"

        # --- 5: Prefix/Suffix checkboxes + entries ---
        sw = QWidget(self.table); sll = QHBoxLayout(sw); sll.setContentsMargins(2,1,2,1); sll.setSpacing(1)
        prefix_cb = QCheckBox(self.table); prefix_cb.setToolTip("Включить кастомный префикс (в начале имени файла)")
        prefix_entry = QLineEdit(self.table); prefix_entry.setFont(BTN_FONT); prefix_entry.setEnabled(False)
        prefix_entry.setToolTip("Кастомный префикс — добавляется ПЕРЕД именем выходного файла")
        prefix_entry.setPlaceholderText("начало")
        suffix_cb = QCheckBox(self.table); suffix_cb.setToolTip("Включить кастомный суффикс (в конце имени файла)")
        suffix_entry = QLineEdit(self.table); suffix_entry.setFont(BTN_FONT); suffix_entry.setEnabled(False)
        suffix_entry.setToolTip("Кастомный суффикс — добавляется ПОСЛЕ имени выходного файла")
        suffix_entry.setPlaceholderText("конец")
        sll.addWidget(prefix_cb); sll.addWidget(prefix_entry, 1)
        sll.addWidget(suffix_cb); sll.addWidget(suffix_entry, 1)
        self.table.setCellWidget(idx, COL_SUFFIX, sw)

        # --- 6: Output — виджеты данных (скрыты) + summary label ---
        output_entry = QLineEdit(); output_entry.setFont(BTN_FONT)
        output_entry.setToolTip("Имя выходного файла")
        rename_btn = QPushButton("✎"); rename_btn.setFont(BTN_FONT); rename_btn.setFixedWidth(24)
        rename_btn.setToolTip("Переименовать файл")
        output_summary = QLabel("", self.table)
        output_summary.setFont(BTN_FONT); output_summary.setTextFormat(Qt.RichText)
        output_summary.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(idx, COL_OUTPUT, output_summary)

        # --- 7: Title ---
        title_entry = QLineEdit(self.table); title_entry.setFont(BTN_FONT)
        title_entry.setToolTip("Название фильма")
        self.table.setCellWidget(idx, COL_TITLE, title_entry)

        # --- 8: Year ---
        year_entry = QLineEdit(self.table); year_entry.setFont(BTN_FONT); year_entry.setFixedWidth(55)
        year_entry.setToolTip("Год выпуска")
        setup_year_validation(year_entry)
        yw = QWidget(self.table); yl2 = QHBoxLayout(yw); yl2.setContentsMargins(2,1,2,1)
        yl2.addWidget(year_entry)
        self.table.setCellWidget(idx, COL_YEAR, yw)

        # --- 9: Info --- (пропускаем I/O если есть кэш)
        if cached:
            txt_files = cached.get("txt_files", [])
            txt_problem = cached.get("txt_problem", False)
        else:
            try:
                txt_files = [f for f in os.listdir(folder["path"])
                             if f.lower().endswith('.txt')]
            except OSError:
                txt_files = []
            txt_problem = False

        _tip_folder = f"Папка: {folder['name']}"
        if not txt_files:
            info_btn = QPushButton("+ Создать", self.table); info_btn.setStyleSheet("color:blue;")
            info_btn.setToolTip(f"Создать {folder['name']}.txt\n{_tip_folder}")
            if not cached: txt_problem = True
        elif len(txt_files) == 1:
            info_btn = QPushButton(txt_files[0][:15], self.table)
            info_btn.setStyleSheet("color:#006600; font-weight:bold;")
            info_btn.setToolTip(f"txt файл: {txt_files[0]}\n{_tip_folder}")
        else:
            # Несколько txt — показать меню выбора
            selected_txt = cached.get("selected_txt", "") if cached else ""
            if selected_txt and selected_txt in txt_files:
                info_btn = QPushButton(selected_txt[:15], self.table)
                info_btn.setStyleSheet("color:#006600; font-weight:bold;")
                info_btn.setToolTip(f"txt файл: {selected_txt}\n{_tip_folder}\nПравый клик — выбрать другой txt")
            else:
                info_btn = QPushButton(f"[{len(txt_files)}] ▾", self.table)
                info_btn.setStyleSheet("color:orange; font-weight:bold;")
                info_btn.setToolTip(f"{len(txt_files)} txt файлов в папке\n{_tip_folder}\nНажми чтобы выбрать")
            if not cached: txt_problem = True
        info_btn.setFont(BTN_FONT)
        self.table.setCellWidget(idx, COL_INFO, info_btn)

        # --- 10: Torrent audio — кнопка с числом + QMenu ---
        if cached:
            tor_files = cached.get("tor_files", [])
        else:
            try:
                tor_files = sorted([f for f in os.listdir(folder["path"]) if f.lower().endswith('.torrent')])
            except OSError:
                tor_files = []
        ta_btn = QPushButton(self.table); ta_btn.setFont(BTN_FONT)
        if tor_files:
            ta_btn.setText(str(len(tor_files)))
            ta_btn.setToolTip(f"Торрент-файлов: {len(tor_files)}\n" + "\n".join(f"  • {f}" for f in tor_files))
            _tor_menu = QMenu(ta_btn)
            for _tf in tor_files:
                _tor_act = _tor_menu.addAction(_tf)
                _tor_act.triggered.connect((lambda p: lambda: os.startfile(p) if os.path.isfile(p) else None)(os.path.join(folder["path"], _tf)))
            ta_btn.setMenu(_tor_menu)
        else:
            ta_btn.setText("0")
            ta_btn.setEnabled(False)
            ta_btn.setToolTip("Нет .torrent файлов аудио дорожки в папке")
        self.table.setCellWidget(idx, COL_TOR_A, ta_btn)

        # --- 11: Torrent video entry + button ---
        tw = QWidget(self.table); tvl = QHBoxLayout(tw); tvl.setContentsMargins(2,1,2,1); tvl.setSpacing(2)
        torrent_entry = QLineEdit(self.table); torrent_entry.setFont(BTN_FONT)
        torrent_entry.setToolTip("Ссылка на торрент видео")
        tor_open_btn = QPushButton("→", self.table); tor_open_btn.setFont(BTN_FONT); tor_open_btn.setFixedWidth(24)
        tor_open_btn.setToolTip("Открыть ссылку в браузере")
        tvl.addWidget(torrent_entry, 1); tvl.addWidget(tor_open_btn)
        self.table.setCellWidget(idx, COL_TOR_V, tw)

        # --- Forum russdub ---
        _rd_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "russdub_icon.png")
        fmw = QWidget(self.table); fml = QHBoxLayout(fmw); fml.setContentsMargins(2,1,2,1); fml.setSpacing(2)
        forum_entry = QLineEdit(self.table); forum_entry.setFont(BTN_FONT)
        forum_entry.setToolTip("Ссылка на тему форума russdub")
        forum_open_btn = QPushButton(self.table); forum_open_btn.setFont(BTN_FONT); forum_open_btn.setFixedWidth(28)
        # Начальное состояние: иконка russdub+лупа (поиск)
        if os.path.isfile(_rd_icon_path):
            forum_open_btn.setIcon(_make_kp_search_icon(_rd_icon_path, 48, mag_scale=0.42))
            forum_open_btn.setIconSize(QSize(20, 20))
        forum_open_btn.setToolTip("Поиск на форуме russdub по названию\nЗапрос: «название + год + завершен»")
        fml.addWidget(forum_entry, 1); fml.addWidget(forum_open_btn)
        self.table.setCellWidget(idx, COL_FORUM, fmw)
        # Обновление кнопки форума: → если есть ссылка, иконка russdub+лупа если нет
        def _update_forum_btn(text, btn=forum_open_btn, icon_path=_rd_icon_path):
            if text.strip():
                btn.setIcon(QIcon())  # Убрать иконку
                btn.setText("→"); btn.setToolTip("Открыть ссылку на форум в браузере")
            else:
                btn.setText("")
                if os.path.isfile(icon_path):
                    btn.setIcon(_make_kp_search_icon(icon_path, 48, mag_scale=0.42))
                    btn.setIconSize(QSize(20, 20))
                btn.setToolTip("Поиск на форуме russdub по названию\nЗапрос: «название + год + завершен»")
        forum_entry.textChanged.connect(_update_forum_btn)

        # --- Кинопоиск ---
        _kp_logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_logo.png")
        _kp_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_icon.png")
        kp_btn = QPushButton(self.table); kp_btn.setFont(BTN_FONT); kp_btn.setFixedWidth(28)
        kp_btn.setToolTip("Поиск на Кинопоиске по названию")
        if os.path.isfile(_kp_icon_path):
            kp_btn.setIcon(_make_kp_search_icon(_kp_icon_path, 48, mag_scale=0.42))
            kp_btn.setIconSize(QSize(20, 20))
        self.table.setCellWidget(idx, COL_KP, kp_btn)

        # --- 12: Status ---
        status_lbl = QLabel("", self.table); status_lbl.setFont(QFont("Arial", 9, QFont.Bold))
        status_lbl.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(idx, COL_STATUS, status_lbl)

        # --- 14: Date ---
        date_lbl = QLabel("", self.table); date_lbl.setFont(BTN_FONT)
        date_lbl.setAlignment(Qt.AlignCenter)
        date_lbl.setToolTip("Дата обработки")
        self.table.setCellWidget(idx, COL_DATE, date_lbl)

        # --- 15: Date Created --- (пропускаем I/O если есть кэш)
        if cached and cached.get("folder_created_cached"):
            folder_ctime = cached["folder_created_cached"]
        else:
            folder_ctime = ""
            try:
                ts = os.path.getctime(folder["path"])
                folder_ctime = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        date_created_lbl = QLabel(folder_ctime, self.table); date_created_lbl.setFont(BTN_FONT)
        date_created_lbl.setAlignment(Qt.AlignCenter)
        date_created_lbl.setToolTip("Дата создания папки аудио")
        self.table.setCellWidget(idx, COL_DATE_CREATED, date_created_lbl)

        # --- Определяем наличие архива --- (пропускаем I/O если есть кэш)
        if cached and "archive_file_cached" in cached:
            archive_file = cached["archive_file_cached"]
        else:
            archive_file = ""
            try:
                for f in os.listdir(folder["path"]):
                    fp_full = os.path.join(folder["path"], f)
                    _, ext = os.path.splitext(f)
                    if not os.path.isfile(fp_full):
                        continue
                    ext_lo = ext.lower()
                    if ext_lo in ('.rar', '.7z', '.zip') or (
                            (not ext or ' ' in ext or len(ext) > 10) and self._is_archive_by_magic(fp_full)):
                        archive_file = f
                        break
            except OSError:
                pass

        # --- COL_SUB: Абонемент ---
        sub_w = QWidget(self.table)
        sub_l = QHBoxLayout(sub_w); sub_l.setContentsMargins(2,1,2,1); sub_l.setSpacing(2)
        sub_year = NoScrollComboBox(self.table); sub_year.setFont(BTN_FONT)
        sub_year.addItem("—"); sub_year.addItems(_SUB_YEARS)
        sub_year.setToolTip("Год абонемента")
        sub_month = NoScrollComboBox(self.table); sub_month.setFont(BTN_FONT)
        sub_month.addItem("—"); sub_month.addItems(_MONTHS_RU)
        sub_month.setToolTip("Месяц абонемента")
        sub_l.addWidget(sub_year); sub_l.addWidget(sub_month)
        self.table.setCellWidget(idx, COL_SUB, sub_w)

        # --- COL_ACTIONS: Actions (как в batch_bar) ---
        aw = QWidget(self.table); al = QHBoxLayout(aw); al.setContentsMargins(0,0,0,0); al.setSpacing(0)
        btn_play = QPushButton("Обработать", aw)
        btn_play.setIcon(_make_play_icon())
        btn_play.setIconSize(QSize(16, 16))
        btn_play.setStyleSheet("QPushButton{background-color:#cce5ff;} QPushButton:hover{background-color:#99ccff;} QPushButton:disabled{background-color:#cce5ff;}")
        btn_play.setToolTip("Запустить mkvmerge для этого файла"); btn_play.setVisible(False)
        al.addWidget(btn_play)
        btn_download = QPushButton("Скачать", aw)
        btn_download.setIcon(_make_download_icon())
        btn_download.setIconSize(QSize(16, 16))
        btn_download.setStyleSheet("QPushButton{background-color:#e0f0ff;} QPushButton:hover{background-color:#99ccff;} QPushButton:disabled{background-color:#e0f0ff;}")
        btn_download.setToolTip("Скачать аудио дорожку: торрент-файл → торрент-клиент, ссылка → браузер")
        btn_download.setVisible(False)
        al.addWidget(btn_download)
        btn_unrar = QPushButton("Архив", aw)
        btn_unrar.setIcon(_make_unrar_icon())
        btn_unrar.setIconSize(QSize(32, 16))
        btn_unrar.setStyleSheet("QPushButton{background-color:#ffe4c4;} QPushButton:hover{background-color:#ffc896;} QPushButton:disabled{background-color:#ffe4c4;}")
        btn_unrar.setToolTip("Расшифровать и распаковать RAR архив используя пароль")
        btn_unrar.setVisible(False)
        al.addWidget(btn_unrar)
        btn_del_archive = QPushButton("Архив", aw)
        btn_del_archive.setIcon(_make_del_archive_icon())
        btn_del_archive.setIconSize(QSize(32, 16))
        btn_del_archive.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        btn_del_archive.setToolTip("Удалить архив (архив уже распакован)")
        btn_del_archive.setVisible(False)
        al.addWidget(btn_del_archive)
        btn_to_res = QPushButton("В Результат", aw)
        btn_to_res.setIcon(_make_to_result_icon())
        btn_to_res.setIconSize(QSize(32, 16))
        btn_to_res.setStyleSheet("QPushButton{background-color:#ccffcc;} QPushButton:hover{background-color:#99ff99;} QPushButton:disabled{background-color:#ccffcc;}")
        btn_to_res.setToolTip("Переместить тестовый файл в папку результата\nРазмер — суммарный по всем выходным файлам. Цифра (N) — количество файлов")
        btn_del_test = QPushButton("Тест", aw)
        btn_del_test.setIcon(_make_del_video_icon())
        btn_del_test.setIconSize(QSize(32, 16))
        btn_del_test.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        btn_del_test.setToolTip("Удалить тестовое видео из папки тест\nРазмер — суммарный по всем выходным файлам. Цифра (N) — количество файлов")
        btn_del_src = QPushButton("Источник", aw)
        btn_del_src.setIcon(_make_del_video_icon())
        btn_del_src.setIconSize(QSize(32, 16))
        btn_del_src.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        btn_del_src.setToolTip("Удалить видео источник из папки видео")
        btn_del_res = QPushButton("Результат", aw)
        btn_del_res.setIcon(_make_del_video_icon())
        btn_del_res.setIconSize(QSize(32, 16))
        btn_del_res.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        btn_del_res.setToolTip("Удалить видео результат из папки результата\nРазмер — суммарный по всем выходным файлам. Цифра (N) — количество файлов")
        al.addWidget(btn_to_res); al.addWidget(btn_del_test)
        al.addWidget(btn_del_src); al.addWidget(btn_del_res)
        al.addStretch()
        self.table.setCellWidget(idx, COL_ACTIONS, aw)

        # --- Row dict ---
        row = {
            "row_index": idx,
            "folder_name": folder["name"], "folder_path": folder["path"],
            "audio_files": folder["files"],
            "select_cb": select_cb, "open_btn": open_btn, "tab_btn": tab_btn,
            "folder_item": fi,
            "audio_combo": audio_combo, "starter_combo": starter_combo, "ender_combo": ender_combo,
            "audio_summary": audio_summary,
            "video_combo": video_combo, "video_btn": video_btn,
            "video_pending_btn": video_pending_btn, "video_dur_lbl": video_dur_lbl,
            "video_summary": video_summary,
            "video_pending": False,
            "delay_lbl": delay_lbl, "delay_value": _delay_value,
            "delay_confirmed": False,
            "delays": [{"value": _delay_value, "confirmed": False}],
            "prefix_cb": prefix_cb, "prefix_entry": prefix_entry,
            "suffix_cb": suffix_cb, "suffix_entry": suffix_entry,
            "output_entry": output_entry, "rename_btn": rename_btn, "output_summary": output_summary,
            "title_entry": title_entry, "year_entry": year_entry,
            "info_btn": info_btn, "txt_files": txt_files, "txt_problem": txt_problem, "selected_txt": "",
            "ta_btn": ta_btn, "tor_files": tor_files,
            "torrent_entry": torrent_entry, "tor_open_btn": tor_open_btn,
            "forum_entry": forum_entry, "forum_open_btn": forum_open_btn,
            "kp_btn": kp_btn,
            "status_lbl": status_lbl,
            "date_lbl": date_lbl, "processed_date": "",
            "date_created_lbl": date_created_lbl, "folder_created": folder_ctime,
            "password_entry": password_entry,
            "move_archive_btn": move_archive_btn,
            "sub_year": sub_year, "sub_month": sub_month,
            "btn_play": btn_play, "btn_download": btn_download,
            "btn_unrar": btn_unrar, "btn_del_archive": btn_del_archive,
            "btn_to_res": btn_to_res, "btn_del_test": btn_del_test,
            "btn_del_src": btn_del_src, "btn_del_res": btn_del_res,
            "archive_file": archive_file,
            "video_full_path": "", "video_manual": False,
            "base_color": base_color, "sort_priority": 1,
            "prev_video": "", "output_on_disk": "",
            "poster_url": "",
            "kinopoisk_url": "",
            "audio_torrent_url": "",
            "audio_tracks_cache": {},       # {audio_filename: [list_of_track_dicts]}
            "selected_audio_tracks": None,  # list[int] выбранные track id, None = не сканировали
            "extra_audio_variants": [],     # [{"starter_audio": "", "ender_audio": ""}, ...]
            "extra_videos": [],             # [{"video": "", "video_full_path": "", "video_manual": False}, ...]
            "custom_track_name_enabled": False,
            "custom_track_name": "",
            "video_fps": "авто",            # FPS видео для --default-duration
        }
        if insert_at is not None:
            self.rows.insert(insert_at, row)
        else:
            self.rows.append(row)

        # --- Сигналы ---
        # Используем ссылку на row dict (r=row) вместо захвата строки fn.
        # row — mutable dict, при перестановке данных (быстрая сортировка)
        # лямбды автоматически получают актуальное folder_name/folder_path.
        open_btn.clicked.connect(lambda _, r=row: os.startfile(r["folder_path"]) if os.path.isdir(r["folder_path"]) else None)
        tab_btn.clicked.connect(lambda _, r=row: self._open_record_tab(r["folder_name"]))
        select_cb.toggled.connect(lambda checked: self._update_batch_buttons())
        video_combo.currentTextChanged.connect(lambda text, r=row: self._on_video_selected(r["folder_name"]))
        video_btn.clicked.connect(lambda _, r=row: self._browse_video_file(r["folder_name"]))
        video_pending_btn.clicked.connect(lambda _, r=row: self._toggle_video_pending(r["folder_name"]))
        # delay_btn убран — редактирование только на вкладке фильма
        prefix_cb.toggled.connect(lambda checked, r=row: self._on_prefix_toggle(r["folder_name"]))
        suffix_cb.toggled.connect(lambda checked, r=row: self._on_suffix_toggle(r["folder_name"]))
        rename_btn.clicked.connect(lambda _, r=row: self._action_rename(r["folder_name"]))
        info_btn.clicked.connect(lambda _, r=row: self._toggle_txt_panel(r["folder_name"]))
        sub_year.currentTextChanged.connect(lambda t: self.schedule_autosave())
        sub_month.currentTextChanged.connect(lambda t: self.schedule_autosave())
        # ta_btn использует QMenu — обработчик клика не нужен
        tor_open_btn.clicked.connect(lambda _, r=row: self._open_torrent_url(r["folder_name"]))
        forum_open_btn.clicked.connect(lambda _, r=row: self._open_forum_url(r["folder_name"]))
        kp_btn.clicked.connect(lambda _, r=row: self._open_or_search_kinopoisk(r["folder_name"]))
        btn_play.clicked.connect(lambda _, r=row: self._process_single(r["folder_name"]))
        btn_unrar.clicked.connect(lambda _, r=row: self._action_unrar(r["folder_name"]))
        btn_del_archive.clicked.connect(lambda _, r=row: self._action_del_archive(r["folder_name"]))
        btn_to_res.clicked.connect(lambda _, r=row: self._action_to_result(r["folder_name"]))
        btn_del_test.clicked.connect(lambda _, r=row: self._action_del_test(r["folder_name"]))
        btn_del_src.clicked.connect(lambda _, r=row: self._action_del_source(r["folder_name"]))
        btn_del_res.clicked.connect(lambda _, r=row: self._action_del_result(r["folder_name"]))

        # Синхронизация: при смене любого аудио комбобокса — перекрёстно обновить остальные
        def _on_audio_changed_sync(idx, r=row):
            self._sync_audio_combos(r)
        audio_combo.currentIndexChanged.connect(_on_audio_changed_sync)
        starter_combo.currentIndexChanged.connect(lambda idx, r=row: (self._sync_audio_combos(r), self.schedule_autosave()))
        ender_combo.currentIndexChanged.connect(lambda idx, r=row: (self._sync_audio_combos(r), self.schedule_autosave()))

        # autosave при изменении полей
        title_entry.textChanged.connect(lambda: self.schedule_autosave())
        year_entry.textChanged.connect(lambda: self.schedule_autosave())
        forum_entry.textChanged.connect(lambda: (self.schedule_autosave(), self._update_status_filter_counts()))
        # Короткий линк для форума — при окончании редактирования
        def _shorten_forum_in_table(fe=forum_entry):
            if hasattr(self, 'short_link_default_cb') and self.short_link_default_cb.isChecked():
                txt = fe.text()
                shortened = shorten_russdub_url(txt)
                if shortened != txt:
                    fe.blockSignals(True)
                    fe.setText(shortened)
                    fe.blockSignals(False)
        forum_entry.editingFinished.connect(_shorten_forum_in_table)
        torrent_entry.textChanged.connect(lambda: self.schedule_autosave())
        prefix_entry.textChanged.connect(lambda: self.schedule_autosave())
        prefix_entry.textChanged.connect(lambda text, r=row: self._recalc_output_name(r["folder_name"]))
        suffix_entry.textChanged.connect(lambda: self.schedule_autosave())
        suffix_entry.textChanged.connect(lambda text, r=row: self._recalc_output_name(r["folder_name"]))
        password_entry.textChanged.connect(lambda: self.schedule_autosave())
        password_entry.textChanged.connect(lambda text, r=row: self._on_password_changed(r))
        move_archive_btn.clicked.connect(lambda _, r=row: self._move_archive_to_folder(r["folder_name"]))

        # Проверяем статус только если это не rebuild (нет кэша) и не начальная загрузка
        if not cached and not skip_status:
            self._check_row_status(row)

    # ──────────────────────────────────
    #  Поиск row по folder_name
    # ──────────────────────────────────
    def _find_row(self, folder_name):
        for r in self.rows:
            if r["folder_name"] == folder_name:
                return r
        return None

    def _reset_visual_order(self):
        """Сбросить визуальные перестановки verticalHeader — вернуть visual == logical.
        Также привести self.rows в физический порядок (по row_index)."""
        vh = self.table.verticalHeader()
        n = self.table.rowCount()
        vh.blockSignals(True)
        for i in range(n):
            cur = vh.visualIndex(i)
            if cur != i:
                vh.swapSections(i, cur)
        vh.blockSignals(False)
        # Привести self.rows в физический порядок
        self.rows.sort(key=lambda r: r["row_index"])

    # ──────────────────────────────────
    #  Инкрементальное добавление/удаление строк
    # ──────────────────────────────────
    def _add_single_row(self, folder_data, form_data=None):
        """Добавить одну строку в таблицу без полного перестроения.

        folder_data: dict {"name": str, "path": str, "files": list}
        form_data: dict с данными из диалога создания или None
        """
        was_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        # Сбросить визуальный порядок перед вставкой (insertRow может конфликтовать с moveSection)
        self._reset_visual_order()
        # Позиция вставки — вверх (NEW всегда первые)
        insert_idx = 0
        # _create_row сам вызывает insertRow + setRowHeight
        self._create_row(insert_idx, folder_data, insert_at=insert_idx)
        r = self.rows[insert_idx]

        # Обновить row_index у всех строк
        for i, row in enumerate(self.rows):
            row["row_index"] = i

        # Записать данные из формы если есть
        if form_data:
            if form_data.get("title"):
                r["title_entry"].setText(form_data["title"])
            if form_data.get("year"):
                r["year_entry"].setText(form_data["year"])
            if form_data.get("password"):
                r["password_entry"].setText(form_data["password"])
            if form_data.get("forum"):
                r["forum_entry"].setText(form_data["forum"])
            if form_data.get("poster_url"):
                r["poster_url"] = form_data["poster_url"]
            if form_data.get("kinopoisk_url"):
                r["kinopoisk_url"] = form_data["kinopoisk_url"]
            if form_data.get("torrent_video"):
                r["torrent_entry"].setText(form_data["torrent_video"])
            if form_data.get("torrent_audio"):
                r["audio_torrent_url"] = form_data["torrent_audio"]
            if form_data.get("sub_year") and form_data["sub_year"] != "—":
                r["sub_year"].setCurrentText(form_data["sub_year"])
            if form_data.get("sub_month") and form_data["sub_month"] != "—":
                r["sub_month"].setCurrentText(form_data["sub_month"])
            dv = form_data.get("delay", "")
            if dv and dv != "0":
                r["delays"] = [{"value": dv, "confirmed": False}]
                self._sync_delays_to_table(r)
            sel_video = form_data.get("video", "")
            if sel_video and sel_video != "— не выбирать —":
                r["video_combo"].blockSignals(True)
                idx_v = r["video_combo"].findText(sel_video)
                if idx_v >= 0:
                    r["video_combo"].setCurrentIndex(idx_v)
                r["video_combo"].blockSignals(False)
                self._on_video_selected(folder_data["name"])

        # Обновить статус и кнопки
        self._check_row_status(r)

        # Пометить NEW поверх _check_row_status
        if form_data is not None:
            r["is_new"] = True
            r["status_lbl"].setText("✦ NEW")
            r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
            self._set_row_bg(r, COLOR_NEW)
            self._update_reset_new_btn()
            self._update_tab_reset_new_btn(folder_data["name"])

        self.setUpdatesEnabled(was_enabled)
        self._update_all_video_combos()
        self._update_archive_btn_count()
        self._update_batch_buttons()
        self._update_process_button()
        self.log(f"[ADD] Строка добавлена: «{folder_data['name']}»")

    def _remove_single_row(self, folder_name):
        """Удалить одну строку из таблицы без полного перестроения."""
        r = self._find_row(folder_name)
        if not r:
            self.log(f"[REMOVE] Строка «{folder_name}» не найдена")
            return

        # Сбросить визуальный порядок и привести self.rows в физический порядок
        self._reset_visual_order()

        logical_row = r["row_index"]

        # Закрыть вкладку если открыта
        if folder_name in self._open_tabs:
            tab_idx = self._find_tab_index(folder_name)
            if tab_idx >= 0:
                self.tab_widget.removeTab(tab_idx)
            del self._open_tabs[folder_name]

        # Вернуть видео в список доступных
        cur_video = r["video_combo"].currentText()
        if cur_video and cur_video != "— снять выбор —":
            if cur_video not in self.available_videos:
                self.available_videos.append(cur_video)

        # Удалить из audio_folders
        self.audio_folders = [af for af in self.audio_folders if af["name"] != folder_name]

        # Удалить строку из таблицы (Qt уничтожит виджеты)
        self.table.removeRow(logical_row)
        self.rows.remove(r)

        # Обновить row_index: строки после удалённой сдвигаются на -1
        for row in self.rows:
            if row["row_index"] > logical_row:
                row["row_index"] -= 1

        # Обновить счётчик
        total = sum(len(f["files"]) for f in self.audio_folders)
        self.audio_count_lbl.setText(f"Папок: {len(self.audio_folders)}, аудио файлов: {total}")

        self._update_archive_btn_count()
        self._update_batch_buttons()
        self._update_process_button()
        self.log(f"[REMOVE] Строка удалена: «{folder_name}»")

    # ──────────────────────────────────
    #  Сортировка
    # ──────────────────────────────────
    SORTABLE = {COL_FOLDER: "folder", COL_VIDEO: "video", COL_DELAY: "delay", COL_SUFFIX: "suffix",
                COL_OUTPUT: "output", COL_TITLE: "title", COL_YEAR: "year",
                COL_STATUS: "status", COL_DATE: "date", COL_DATE_CREATED: "date_created",
                COL_SUB: "sub"}

    def _on_section_moved(self, logical, old_visual, new_visual):
        """Откатить перемещение заблокированных колонок (первые 3 и последняя)."""
        hdr = self.table.horizontalHeader()
        # Проверить: заблокированная колонка не должна перемещаться
        if logical in self._LOCKED_COLS:
            hdr.blockSignals(True)
            hdr.moveSection(new_visual, old_visual)
            hdr.blockSignals(False)
            return
        # Не дать перетащить на позицию заблокированных колонок
        locked_visuals = {hdr.visualIndex(c) for c in self._LOCKED_COLS}
        if new_visual in locked_visuals:
            hdr.blockSignals(True)
            hdr.moveSection(new_visual, old_visual)
            hdr.blockSignals(False)
            return
        self.schedule_autosave()

    def _toggle_column(self, col_idx, visible):
        """Переключить видимость колонки через чекбокс."""
        hidden_cols = self.config.get("hidden_columns", [])
        if visible:
            self.table.setColumnHidden(col_idx, False)
            if col_idx in hidden_cols:
                hidden_cols.remove(col_idx)
            # Отложить пересчёт — виджеты ещё не layout-нулись после показа
            QTimer.singleShot(0, lambda: self._after_column_shown(col_idx))
        else:
            self.table.setColumnHidden(col_idx, True)
            if col_idx not in hidden_cols:
                hidden_cols.append(col_idx)
            # Пересчитать ширину окна точно по видимым колонкам (без зазора справа)
            QTimer.singleShot(0, self._shrink_to_columns)
        self.config["hidden_columns"] = hidden_cols
        self.schedule_autosave()

    def _after_column_shown(self, col_idx):
        """Отложенный пересчёт после показа колонки (виджеты уже отрисованы)."""
        self._fit_single_column(col_idx)
        col_w = self.table.columnWidth(col_idx)
        new_w = self.width() + col_w
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            new_w = min(new_w, screen_w)
        except Exception:
            pass
        self.resize(new_w, self.height())

    def _fit_single_column(self, col):
        """Подогнать ширину одной колонки под максимальный контент (включая QLabel, QLineEdit, QPushButton)."""
        pad = 16
        hdr = self.table.horizontalHeader()
        max_w = max(hdr.sectionSizeHint(col), 30)
        has_custom = False
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            cw = self.table.cellWidget(row, col)
            if not cw:
                continue
            if isinstance(cw, QLineEdit):
                has_custom = True
                txt = cw.text()
                if txt:
                    tw = cw.fontMetrics().horizontalAdvance(txt) + pad
                    if tw > max_w:
                        max_w = tw
                if cw.minimumWidth() == cw.maximumWidth() and cw.minimumWidth() > 0:
                    fw = cw.minimumWidth() + 6
                    if fw > max_w:
                        max_w = fw
                continue
            if isinstance(cw, QLabel):
                has_custom = True
                if cw.textFormat() == Qt.RichText or (cw.textFormat() == Qt.AutoText and '<' in (cw.text() or '')):
                    from PySide6.QtGui import QTextDocument
                    doc = QTextDocument()
                    doc.setHtml(cw.text())
                    doc.setDefaultFont(cw.font())
                    sw = int(doc.idealWidth()) + 8
                else:
                    sw = cw.fontMetrics().horizontalAdvance(cw.text()) + pad
                if sw > max_w:
                    max_w = sw
                continue
            # Составной виджет — QLineEdit, QLabel, QPushButton внутри
            edits = cw.findChildren(QLineEdit)
            labels = cw.findChildren(QLabel)
            if edits:
                has_custom = True
                btns_w = sum(b.width() for b in cw.findChildren(QPushButton))
                margins = cw.layout().contentsMargins() if cw.layout() else None
                m_lr = (margins.left() + margins.right()) if margins else 4
                for le in edits:
                    if le.minimumWidth() == le.maximumWidth() and le.minimumWidth() > 0:
                        fw = le.minimumWidth() + btns_w + m_lr + 8
                        if fw > max_w:
                            max_w = fw
                    txt = le.text()
                    if txt:
                        tw = le.fontMetrics().horizontalAdvance(txt) + pad + btns_w + m_lr + 8
                        if tw > max_w:
                            max_w = tw
            elif labels:
                has_custom = True
                def _lbl_w(lb):
                    if lb.textFormat() == Qt.RichText or (lb.textFormat() == Qt.AutoText and '<' in (lb.text() or '')):
                        from PySide6.QtGui import QTextDocument
                        doc = QTextDocument(); doc.setHtml(lb.text()); doc.setDefaultFont(lb.font())
                        return int(doc.idealWidth()) + 8
                    return lb.fontMetrics().horizontalAdvance(lb.text()) + pad
                lbl_w = max((_lbl_w(lb) for lb in labels), default=0)
                btns_w = sum(b.sizeHint().width() for b in cw.findChildren(QPushButton))
                margins = cw.layout().contentsMargins() if cw.layout() else None
                m_lr = (margins.left() + margins.right()) if margins else 4
                spacing = cw.layout().spacing() if cw.layout() else 2
                cell_w = lbl_w + btns_w + m_lr + spacing + 4
                if cell_w > max_w:
                    max_w = cell_w
            elif isinstance(cw, QPushButton):
                has_custom = True
                txt = cw.text()
                if txt:
                    tw = cw.fontMetrics().horizontalAdvance(txt) + pad
                    if tw > max_w:
                        max_w = tw
        if has_custom:
            self.table.setColumnWidth(col, max_w)
        else:
            self.table.resizeColumnToContents(col)

    def _shrink_to_columns(self):
        """Сжать окно до суммарной ширины видимых колонок (без зазора справа)."""
        hdr = self.table.horizontalHeader()
        # Временно убрать Stretch с COL_TITLE чтобы получить естественную ширину
        title_visible = not self.table.isColumnHidden(COL_TITLE)
        if title_visible:
            hdr.setSectionResizeMode(COL_TITLE, QHeaderView.Interactive)
            self.table.resizeColumnToContents(COL_TITLE)
        total_cols = sum(self.table.columnWidth(c)
                         for c in range(self.table.columnCount())
                         if not self.table.isColumnHidden(c))
        frame_w = self.width() - self.table.viewport().width()
        needed_w = total_cols + frame_w + 4
        min_w = self._paths_group.sizeHint().width() + 40
        new_w = max(needed_w, min_w)
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            new_w = min(new_w, screen_w)
        except Exception:
            pass
        self.resize(new_w, self.height())
        # Вернуть Stretch для COL_TITLE
        if title_visible:
            hdr.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)

    def _show_column_menu(self, pos):
        """Контекстное меню для скрытия/показа колонок (правый клик на заголовке)."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for i in range(NUM_COLS):
            if i == COL_ACTIONS:
                continue  # Колонка скрыта навсегда
            name = HEADERS[i]
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(not self.table.isColumnHidden(i))
            act.setToolTip(HEADER_TOOLTIPS[i] if i < len(HEADER_TOOLTIPS) else "")
            act.setData(i)
            # Запретить скрывать только Папку
            if i == COL_FOLDER:
                act.setEnabled(False)
        chosen = menu.exec(self.table.horizontalHeader().mapToGlobal(pos))
        if chosen:
            col_idx = chosen.data()
            visible = chosen.isChecked()
            # Синхронизировать через чекбокс (он сделает всё остальное)
            if col_idx < len(self._col_checkboxes) and self._col_checkboxes[col_idx]:
                self._col_checkboxes[col_idx].setChecked(visible)

    def _apply_filter(self):
        """Скрыть строки не соответствующие критериям поиска и status filter."""
        folder = self.filter_folder.text().strip().lower()
        title = self.filter_title.text().strip().lower()
        year = self.filter_year.text().strip()
        sub_y = self.filter_sub_year.currentText()
        sub_m = self.filter_sub_month.currentText()
        # Определить активный status filter
        active_sp = None
        active_new = False
        active_custom = None
        active_key = getattr(self, '_active_preview_key', None)
        if active_key and active_key.startswith('_status_filter_'):
            suffix = active_key.replace('_status_filter_', '')
            if suffix == "new":
                active_new = True
            else:
                try: active_sp = int(suffix)
                except ValueError: pass
        elif active_key and active_key.startswith('_custom_filter_'):
            active_custom = active_key.replace('_custom_filter_', '')
        for r in self.rows:
            show = True
            if folder and folder not in r["folder_name"].lower():
                show = False
            if title and title not in r["title_entry"].text().lower():
                show = False
            if year and year != r["year_entry"].text().strip():
                show = False
            if sub_y != "—" and r["sub_year"].currentText() != sub_y:
                show = False
            if sub_m != "—" and r["sub_month"].currentText() != sub_m:
                show = False
            # Status filter
            if active_new and not r.get("is_new"):
                show = False
            elif active_sp is not None and r.get("sort_priority", 1) != active_sp:
                show = False
            elif active_custom and not self._match_custom_filter(r, active_custom):
                show = False
            self.table.setRowHidden(r["row_index"], not show)
        self._update_rows_count()

    def _reset_filter(self):
        """Сбросить все фильтры (поиск + статусы) и показать все строки."""
        self.filter_folder.clear()
        self.filter_title.clear()
        self.filter_year.clear()
        self.filter_sub_year.setCurrentIndex(0)
        self.filter_sub_month.setCurrentIndex(0)
        # Сбросить фильтры по статусам и кастомные фильтры
        self._clear_batch_preview()
        for r in self.rows:
            self.table.setRowHidden(r["row_index"], False)
        self._update_rows_count()

    def _update_rows_count(self):
        """Обновить счётчик видимых строк в таблице."""
        visible = sum(1 for r in self.rows if not self.table.isRowHidden(r["row_index"]))
        self.rows_count_lbl.setText(f"Видимых записей: <b>{visible}</b>")

    def _on_header_clicked(self, logical_index):
        # Клик по заголовку ☑ — выбрать/снять все чекбоксы
        if logical_index == COL_SELECT:
            any_checked = any(r["select_cb"].isChecked() for r in self.rows if not self.table.isRowHidden(r["row_index"]))
            self._on_select_all(not any_checked)
            return
        key = self.SORTABLE.get(logical_index)
        if not key:
            return
        if self.sort_column == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = key
            self.sort_reverse = False
        self._sort_table()
        self.schedule_autosave()

    def _sort_table(self):
        if not self.rows:
            return
        self._highlighted_row = None

        # Запомнить текущий порядок для сравнения
        old_order = [r["folder_name"] for r in self.rows]

        col = self.sort_column

        _month_idx = {m: i for i, m in enumerate(_MONTHS_RU, 1)}

        def _count_real_videos(r):
            """Подсчёт реальных видео файлов (основной + extra_videos) — как в summary."""
            n = 0
            vc = r.get("video_combo")
            if vc and vc.isEnabled():
                vn = vc.currentText()
                if vn and vn != "— снять выбор —":
                    vp = self.video_path_edit.text()
                    vfp = r.get("video_full_path") or (os.path.join(vp, vn) if vp else "")
                    if vfp and os.path.isfile(vfp):
                        n = 1
            for ev in r.get("extra_videos", []):
                if ev.get("video") or ev.get("video_full_path"):
                    n += 1
            return n

        def _count_output_files(r):
            """Подсчёт выходных файлов на диске (в тесте + в результате)."""
            op = self.output_path_edit.text()
            tp = self.test_path_edit.text()
            prefix = self._get_prefix(r)
            suffix = self._get_suffix(r)
            output_names = []
            main_out = r["output_entry"].text()
            if main_out:
                output_names.append(main_out)
            for ev in r.get("extra_videos", []):
                ev_name = ev.get("video", "")
                ev_path = ev.get("video_full_path", "")
                vn = ev_name or (os.path.basename(ev_path) if ev_path else "")
                if vn:
                    output_names.append(f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv")
            count = 0
            for name in output_names:
                if tp and os.path.isfile(os.path.join(tp, name)):
                    count += 1
                if op and os.path.isfile(os.path.join(op, name)):
                    count += 1
            return count

        def get_sort_value(r):
            if col == "folder": return r["folder_name"].lower()
            elif col == "video":
                return _count_real_videos(r)
            elif col == "delay":
                try: return int(r.get("delay_value", "0") or "0")
                except: return 0
            elif col == "suffix": return r["suffix_entry"].text().lower() if r["suffix_cb"].isChecked() else ""
            elif col == "output": return _count_output_files(r)
            elif col == "title": return r["title_entry"].text().lower()
            elif col == "year":
                try: return int(r["year_entry"].text() or "0")
                except: return 0
            elif col == "status":
                if r.get("is_new"): return 5  # Все NEW группируются вместе
                return r.get("sort_priority", 1)
            elif col == "date": return r.get("processed_date", "") or ""
            elif col == "date_created": return r.get("folder_created", "") or ""
            elif col == "sub":
                sy = r["sub_year"].currentText()
                sm = r["sub_month"].currentText()
                y = int(sy) if sy != "—" else 0
                m = _month_idx.get(sm, 0)
                return (y, m)
            return r["folder_name"].lower()

        def is_empty_for_sort(r):
            """Пустые записи ВСЕГДА внизу. Пустая = нет данных для этой колонки."""
            if not col: return False
            if col == "folder": return False
            elif col == "video":
                return _count_real_videos(r) == 0
            elif col == "delay": return False
            elif col == "suffix": return not r["suffix_entry"].text().strip()
            elif col == "output": return _count_output_files(r) == 0
            elif col == "title": return not r["title_entry"].text().strip()
            elif col == "year": return not r["year_entry"].text().strip()
            elif col == "status":
                if r.get("is_new"): return False  # NEW — никогда не пустая
                return r.get("sort_priority", 1) in (1,)
            elif col == "date": return not r.get("processed_date", "")
            elif col == "date_created": return not r.get("folder_created", "")
            elif col == "sub": return r["sub_year"].currentText() == "—" and r["sub_month"].currentText() == "—"
            return False

        if col:
            # Разделяем на непустые и пустые (пустые всегда внизу)
            empty_rows = [r for r in self.rows if is_empty_for_sort(r)]
            normal_rows = [r for r in self.rows if not is_empty_for_sort(r)]
            normal_rows.sort(key=get_sort_value, reverse=self.sort_reverse)
            self.rows = normal_rows + empty_rows
        else:
            self.rows.sort(key=lambda r: r["folder_name"].lower())

        # Заморозить ВСЁ — один repaint в конце вместо сотен промежуточных
        was_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        self.table.setUpdatesEnabled(False)

        # Перестроить таблицу только если порядок действительно изменился
        new_order = [r["folder_name"] for r in self.rows]
        if old_order != new_order:
            self._visual_sort()
        self._update_header_arrows()
        self._apply_filter()

        self.table.setUpdatesEnabled(True)
        self.setUpdatesEnabled(was_enabled)

    def _update_header_arrows(self):
        labels = []
        for i in range(NUM_COLS):
            base = HEADERS[i]
            key = self.SORTABLE.get(i)
            if key and key == self.sort_column:
                # Активная сортировка — показать направление
                labels.append(base + (" ▼" if self.sort_reverse else " ▲"))
            elif key:
                # Колонка поддерживает сортировку — показать ↕
                labels.append(base + " ↕")
            else:
                labels.append(base)
        self.table.setHorizontalHeaderLabels(labels)
        # Восстановить иконки заголовков (setHorizontalHeaderLabels пересоздаёт items)
        hitem = self.table.horizontalHeaderItem(COL_SELECT)
        if hitem:
            hitem.setIcon(self._checkbox_header_icon)
        _kp_logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_logo.png")
        if os.path.isfile(_kp_logo):
            _kp_hitem = self.table.horizontalHeaderItem(COL_KP)
            if _kp_hitem:
                _kp_hitem.setIcon(QIcon(_kp_logo))
                _kp_hitem.setText("")
        self._set_header_tooltips()

    def _set_header_tooltips(self):
        for i in range(NUM_COLS):
            item = self.table.horizontalHeaderItem(i)
            if item and i < len(HEADER_TOOLTIPS):
                item.setToolTip(HEADER_TOOLTIPS[i])
            # Центрировать заголовки колонок чекбокса и исключения
            if item and i in (COL_SELECT,):
                item.setTextAlignment(Qt.AlignCenter)

    # ──────────────────────────────────
    #  Восстановление маппингов
    # ──────────────────────────────────
    def _restore_mappings(self, skip_meta_check=False):
        mappings = self.config.get("mappings", [])
        if not mappings:
            self.log("Нет маппингов в конфиге")
            return
        self.log(f"Маппингов в конфиге: {len(mappings)}, строк в таблице: {len(self.rows)}")
        row_map = {r["folder_name"]: r for r in self.rows}
        mapping_map = {m.get("folder", ""): m for m in mappings}
        restored = 0
        for m in mappings:
            r = row_map.get(m.get("folder", ""))
            if not r:
                continue
            restored += 1
            if m.get("audio"):
                # Найти item по userData (чистое имя файла), blockSignals — чтобы не запускать _sync_audio_combos
                r["audio_combo"].blockSignals(True)
                found = False
                for i in range(r["audio_combo"].count()):
                    if r["audio_combo"].itemData(i, Qt.UserRole) == m["audio"]:
                        r["audio_combo"].setCurrentIndex(i)
                        found = True
                        break
                if not found:
                    r["audio_combo"].setCurrentText(m["audio"])  # фолбэк
                r["audio_combo"].blockSignals(False)
            # Восстановить стартовый аудио файл (blockSignals — чтобы не запускать _sync_audio_combos до полного восстановления)
            starter = m.get("starter_audio", "")
            if starter and r.get("starter_combo"):
                sc = r["starter_combo"]
                sc.blockSignals(True)
                for i in range(sc.count()):
                    if sc.itemData(i, Qt.UserRole) == starter:
                        sc.setCurrentIndex(i)
                        break
                sc.blockSignals(False)
            # Восстановить конечный аудио файл
            ender = m.get("ender_audio", "")
            if ender and r.get("ender_combo"):
                ec = r["ender_combo"]
                ec.blockSignals(True)
                for i in range(ec.count()):
                    if ec.itemData(i, Qt.UserRole) == ender:
                        ec.setCurrentIndex(i)
                        break
                ec.blockSignals(False)
            if m.get("video") and m["video"] != "— снять выбор —":
                r["video_combo"].blockSignals(True)
                r["video_combo"].clear()
                vals = ["— снять выбор —", m["video"]]
                vals.extend([v for v in self.available_videos if v and v != m["video"]])
                r["video_combo"].addItems(vals)
                r["video_combo"].setCurrentText(m["video"])
                r["video_combo"].blockSignals(False)
                r["prev_video"] = m["video"]
                if m["video"] in self.available_videos:
                    self.available_videos.remove(m["video"])
                r["video_full_path"] = m.get("video_full_path", "")
                if not r["video_full_path"]:
                    vp = self.video_path_edit.text()
                    if vp: r["video_full_path"] = os.path.join(vp, m["video"])
                # Скрыть кнопку ⏳ когда видео выбрано
                r["video_pending_btn"].setVisible(False)
            r["video_manual"] = m.get("video_manual", False)
            # Загрузить delays (новый формат) или создать из старого delay/delay_confirmed
            if m.get("delays"):
                r["delays"] = m["delays"]
            else:
                r["delays"] = [{"value": m.get("delay", "0"), "confirmed": m.get("delay_confirmed", False)}]
            self._sync_delays_to_table(r)
            # Мультивыбор: дополнительные аудио варианты и видео
            r["extra_audio_variants"] = m.get("extra_audio_variants", [])
            r["extra_videos"] = m.get("extra_videos", [])
            r["video_fps"] = m.get("video_fps", "авто")
            if m.get("output"): r["output_entry"].setText(m["output"])
            r["title_entry"].setText(m.get("title", ""))
            r["year_entry"].setText(m.get("year", ""))
            if m.get("custom_prefix_enabled"):
                r["prefix_cb"].setChecked(True); r["prefix_entry"].setEnabled(True)
            r["prefix_entry"].setText(m.get("custom_prefix", ""))
            if m.get("custom_suffix_enabled"):
                r["suffix_cb"].setChecked(True); r["suffix_entry"].setEnabled(True)
            r["suffix_entry"].setText(m.get("custom_suffix", ""))
            r["custom_track_name_enabled"] = m.get("custom_track_name_enabled", False)
            r["custom_track_name"] = m.get("custom_track_name", "")
            r["torrent_entry"].setText(m.get("torrent_url", ""))
            r["forum_entry"].setText(m.get("forum_url", ""))
            self._update_forum_open_btn(r)
            r["sort_priority"] = m.get("sort_priority", 1)
            r["processed_date"] = m.get("processed_date", "")
            if r["processed_date"]:
                r["date_lbl"].setText(r["processed_date"])
            r["video_pending"] = m.get("video_pending", False)
            r["_password_error"] = m.get("_password_error", False)
            if r["video_pending"]:
                r["video_pending_btn"].setText("⌛")
                r["video_pending_btn"].setStyleSheet("color:#8e44ad; font-weight:bold;")
            _saved_dur = m.get("video_duration", "")
            if _saved_dur:
                # Пересчитать округление минут из кэша (HH:MM:SS / N мин.)
                _dur_match = re.match(r"(\d+):(\d+):(\d+)", _saved_dur)
                if _dur_match:
                    _dur_s = int(_dur_match.group(1)) * 3600 + int(_dur_match.group(2)) * 60 + int(_dur_match.group(3))
                    _saved_dur = self._format_duration(_dur_s)
                r["video_dur_lbl"].setText(_saved_dur)
            if m.get("archive_password"):
                r["password_entry"].setText(m["archive_password"])
            r["poster_url"] = m.get("poster_url", "")
            r["kinopoisk_url"] = m.get("kinopoisk_url", "")
            self._update_kp_btn_icon(r)
            r["audio_torrent_url"] = m.get("audio_torrent_url", "")
            sel_txt = m.get("selected_txt", "")
            if sel_txt and sel_txt in r["txt_files"]:
                r["selected_txt"] = sel_txt
                r["info_btn"].setText(sel_txt[:15])
                r["info_btn"].setStyleSheet("color:#006600; font-weight:bold;")
                r["info_btn"].setToolTip(f"Выбран: {sel_txt}\nПравый клик — выбрать другой txt")
                r["txt_problem"] = False
            sy = m.get("sub_year", "")
            if sy: r["sub_year"].setCurrentText(sy)
            sm = m.get("sub_month", "")
            if sm: r["sub_month"].setCurrentText(sm)
            r["selected_audio_tracks"] = m.get("selected_audio_tracks", m.get("selected_audio_track"))
            r["right_tab_idx"] = m.get("right_tab_idx", 0)
            r["torrent_confirmed"] = m.get("torrent_confirmed", False)
            r["extra_torrent_urls"] = m.get("extra_torrent_urls", [])
            # Быстрая визуальная установка статуса из конфига (без I/O)
            self._apply_config_status(r, m)

        self._update_all_video_combos()
        # Принудительная перекрёстная синхронизация аудио комбобоксов
        for r in self.rows:
            self._sync_audio_combos(r)
        self._sort_table()
        self.log(f"Восстановлено: {restored} из {len(mappings)} сопоставлений")
        # Проверить _meta.json в папках — импорт новых и детекция расхождений
        # При восстановлении из бэкапа пропускаем: _meta.json могут содержать
        # повреждённые данные с более новым _saved_at, что перезапишет восстановленное
        if not skip_meta_check:
            self._check_meta_files(row_map, mapping_map)

    def _check_meta_files(self, row_map, mapping_map):
        """Проверить _meta.json в папках фильмов: импорт новых, детекция расхождений."""
        imported = 0
        conflicts = 0
        for fn, r in row_map.items():
            folder_path = r.get("folder_path", "")
            if not folder_path or not os.path.isdir(folder_path):
                continue
            meta = self._load_meta_from_folder(folder_path)
            if not meta:
                continue
            config_m = mapping_map.get(fn)
            if not config_m:
                # Папка есть в _meta.json, но не в films.json — импорт
                self._apply_meta_to_row(r, meta)
                imported += 1
                self.log(f"[META] Импорт из _meta.json: {fn}")
            else:
                # Оба есть — сравнить
                if not self._compare_meta(config_m, meta):
                    winner = self._resolve_meta_conflict(folder_path, config_m, meta)
                    if winner is meta:
                        # _meta.json новее — применить его данные
                        self._apply_meta_to_row(r, meta)
                        self.log(f"[META] Конфликт: {fn} — применён _meta.json (новее), старые данные → бэкап")
                    else:
                        self.log(f"[META] Конфликт: {fn} — сохранён films.json (новее), _meta.json → бэкап")
                    r["has_meta_backup"] = True
                    conflicts += 1
        if imported:
            self.log(f"[META] Импортировано из _meta.json: {imported}")
        if conflicts:
            self.log(f"[META] Расхождений обнаружено: {conflicts} (бэкапы сохранены)")

    def _apply_meta_to_row(self, r, meta):
        """Применить данные из _meta.json к строке таблицы."""
        if meta.get("title"): r["title_entry"].setText(meta["title"])
        if meta.get("year"): r["year_entry"].setText(meta["year"])
        if meta.get("delays"):
            r["delays"] = meta["delays"]
        elif meta.get("delay"):
            r["delays"] = [{"value": meta["delay"], "confirmed": meta.get("delay_confirmed", False)}]
        self._sync_delays_to_table(r)
        if meta.get("torrent_url"): r["torrent_entry"].setText(meta["torrent_url"])
        if meta.get("forum_url"): r["forum_entry"].setText(meta["forum_url"])
        self._update_forum_open_btn(r)
        if meta.get("archive_password"): r["password_entry"].setText(meta["archive_password"])
        r["poster_url"] = meta.get("poster_url", r.get("poster_url", ""))
        r["kinopoisk_url"] = meta.get("kinopoisk_url", r.get("kinopoisk_url", ""))
        self._update_kp_btn_icon(r)
        r["audio_torrent_url"] = meta.get("audio_torrent_url", r.get("audio_torrent_url", ""))
        if meta.get("sub_year"): r["sub_year"].setCurrentText(meta["sub_year"])
        if meta.get("sub_month"): r["sub_month"].setCurrentText(meta["sub_month"])
        if meta.get("custom_prefix_enabled"):
            r["prefix_cb"].setChecked(True); r["prefix_entry"].setEnabled(True)
        if meta.get("custom_prefix"): r["prefix_entry"].setText(meta["custom_prefix"])
        if meta.get("custom_suffix_enabled"):
            r["suffix_cb"].setChecked(True); r["suffix_entry"].setEnabled(True)
        if meta.get("custom_suffix"): r["suffix_entry"].setText(meta["custom_suffix"])
        if meta.get("custom_track_name_enabled"):
            r["custom_track_name_enabled"] = True
        if meta.get("custom_track_name"):
            r["custom_track_name"] = meta["custom_track_name"]
        r["sort_priority"] = meta.get("sort_priority", r.get("sort_priority", 1))
        r["processed_date"] = meta.get("processed_date", r.get("processed_date", ""))
        if r["processed_date"]:
            r["date_lbl"].setText(r["processed_date"])
        r["video_pending"] = meta.get("video_pending", r.get("video_pending", False))
        r["_password_error"] = meta.get("_password_error", r.get("_password_error", False))
        r["selected_audio_tracks"] = meta.get("selected_audio_tracks", r.get("selected_audio_tracks"))
        r["video_fps"] = meta.get("video_fps", r.get("video_fps", "авто"))

    def _get_video_usage_map(self):
        """Возвращает dict {video_name: [folder_name, ...]} — какие видео кем заняты."""
        usage = {}
        for r in self.rows:
            v = r["video_combo"].currentText()
            if v and v != "— снять выбор —":
                usage.setdefault(v, []).append(r["folder_name"])
        return usage

    def _update_all_video_combos(self):
        show_used = self.show_used_videos_cb.isChecked()
        usage_map = self._get_video_usage_map() if show_used else {}
        from PySide6.QtGui import QStandardItemModel
        for r in self.rows:
            cur = r["video_combo"].currentText()
            fn = r["folder_name"]
            r["video_combo"].blockSignals(True)
            r["video_combo"].clear()
            # Собрать занятые видео: (display_text, owner_count)
            used_items = []
            if show_used:
                for v, owners in sorted(usage_map.items()):
                    if v != cur:
                        if len(owners) >= 2:
                            _w = "КОПИИ" if len(owners) in (2, 3, 4) else "КОПИЙ"
                            # Unicode Mathematical Bold Digits для заметности
                            _bd = ''.join(chr(0x1D7CE + int(c)) if c.isdigit() else c for c in str(len(owners)))
                            label = f"{v}  ← ▶ {_bd} {_w} ◀  {', '.join(owners)}"
                        else:
                            label = f"{v}  ← {owners[0]}"
                        used_items.append((label, len(owners)))
            vals = ["— снять выбор —"]
            if cur and cur != "— снять выбор —":
                vals.append(cur)
            vals.extend([ui[0] for ui in used_items])
            used_end = len(vals)  # индекс после последнего занятого
            vals.extend([v for v in self.available_videos if v and v != cur])
            r["video_combo"].addItems(vals)
            if cur: r["video_combo"].setCurrentText(cur)
            # Подсветка занятых элементов (enabled — чтобы можно было кликнуть для назначения)
            if show_used and used_items:
                model = r["video_combo"].model()
                if isinstance(model, QStandardItemModel):
                    start_idx = 2 if (cur and cur != "— снять выбор —") else 1
                    for i, (label, owner_count) in enumerate(used_items):
                        item = model.item(start_idx + i)
                        if item:
                            if owner_count >= 2:
                                item.setBackground(QColor("#ffb0b0"))
                                _bf = item.font(); _bf.setBold(True); item.setFont(_bf)
                                item.setToolTip(f"Видео используется {owner_count} записями — кликните чтобы назначить/копировать")
                            else:
                                item.setBackground(QColor("#ffe0b0"))
                                item.setToolTip("Видео занято — кликните чтобы назначить тот же файл или копировать")
            r["video_combo"].blockSignals(False)
        # Синхронизировать открытые вкладки
        for fn_tab in list(self._open_tabs.keys()):
            self._sync_tab_video(fn_tab)

    # ──────────────────────────────────
    _STATUS_COLORS = {
        "Видео в процессе": "#8e44ad",
        "Нет аудио": "red", "Нет видео": "red",
        "Готово": "green", "В тесте": "#b37400",
        "К обработке": "blue", "TXT!": "orange",
        "✦ NEW": "#006600",
        "Ожидает видео": "#cc6600", "Ожидает аудио": "#cc6600",
        "Нет файлов": "gray", "Ожидание": "gray",
        "Чудовищная ошибка": "#cc0000",
        "Неверный пароль": "red",
    }

    @staticmethod
    def _status_text_style(text):
        """Стиль для статус-лейбла на вкладке (без background)."""
        colors = MKVMergeApp._STATUS_COLORS
        c = colors.get(text, "")
        if c:
            extra = ""
            if text == "Чудовищная ошибка":
                extra = " background-color:#ffe0e0;"
            return f"color:{c}; font-weight:bold;{extra}"
        return ""

    #  Статусы
    # ──────────────────────────────────
    def _schedule_batch_update(self):
        """Отложенное обновление батч-кнопок (debounce — объединяет множественные вызовы)."""
        if not getattr(self, '_batch_update_pending', False):
            self._batch_update_pending = True
            QTimer.singleShot(0, self._deferred_update_batch)

    def _deferred_update_batch(self):
        """Выполнить обновление батч-кнопок (вызывается из QTimer)."""
        self._batch_update_pending = False
        self._update_batch_buttons()
        self._update_status_filter_counts()

    def _update_actions_col_width(self):
        """Подстроить ширину колонки Действия строго под самую широкую строку кнопок."""
        hdr_fm = self.table.horizontalHeader().fontMetrics()
        min_w = hdr_fm.horizontalAdvance("Действия") + 24
        max_w = min_w
        for r in self.rows:
            if self.table.isRowHidden(r["row_index"]):
                continue
            aw = self.table.cellWidget(r["row_index"], COL_ACTIONS)
            if not aw:
                continue
            lay = aw.layout()
            if not lay:
                continue
            total = 0
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if w and w.isVisible():
                    # Реальная ширина если виджет уже отрисован, иначе sizeHint
                    total += max(w.width(), w.sizeHint().width())
            if total > max_w:
                max_w = total
        self.table.setColumnWidth(COL_ACTIONS, max_w + 4)

    def _ensure_columns_fit(self):
        """Убедиться что все колонки влезают в окно без горизонтальной прокрутки.
        Если суммарная ширина колонок превышает viewport — расширить окно (до размера экрана)."""
        total_cols = sum(self.table.columnWidth(c)
                         for c in range(self.table.columnCount())
                         if not self.table.isColumnHidden(c))
        viewport_w = self.table.viewport().width()
        if total_cols <= viewport_w:
            return  # Всё влезает
        diff = total_cols - viewport_w
        new_w = self.width() + diff + 2
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            new_w = min(new_w, screen_w)
        except Exception:
            pass
        self.resize(new_w, self.height())

    def _check_row_status(self, r):
        if r.get("video_pending"):
            r["status_lbl"].setText("Видео в процессе"); r["status_lbl"].setStyleSheet("color:#8e44ad;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Видео в процессе", ""))
            self._set_row_bg(r, COLOR_VIDEO_PENDING)
            r["sort_priority"] = 6
            r["is_new"] = False  # Видео в процессе — больше не NEW
            r["btn_play"].setVisible(False)
            r["btn_download"].setVisible(False)
            r["btn_to_res"].setVisible(False)
            r["btn_del_test"].setVisible(False)
            r["btn_del_src"].setVisible(False)
            r["btn_del_res"].setVisible(False)
            # Синхронизировать статус на вкладке фильма
            fn = r["folder_name"]
            if fn in self._open_tabs:
                tw = self._open_tabs[fn]["widgets"]
                slbl = tw.get("status_lbl")
                if slbl:
                    slbl.setText("Видео в процессе")
                    slbl.setStyleSheet(self._status_text_style("Видео в процессе"))
            self._update_audio_summary(r)
            self._update_video_summary(r)
            self._update_output_summary(r)
            self._schedule_batch_update()
            return

        # Неверный пароль — сбрасывается ТОЛЬКО при успешной распаковке
        if r.get("_password_error"):
            r["status_lbl"].setText("Неверный пароль")
            r["status_lbl"].setStyleSheet("color:red; font-weight:bold;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Неверный пароль", ""))
            self._set_row_bg(r, COLOR_ERROR)
            r["sort_priority"] = 5
            fn = r["folder_name"]
            if fn in self._open_tabs:
                tw = self._open_tabs[fn]["widgets"]
                slbl = tw.get("status_lbl")
                if slbl:
                    slbl.setText("Неверный пароль")
                    slbl.setStyleSheet(self._status_text_style("Неверный пароль"))
            self._update_audio_summary(r)
            self._update_video_summary(r)
            self._update_output_summary(r)
            self._schedule_batch_update()
            return

        audio_name = self._audio_filename(r)
        video_name = r["video_combo"].currentText()
        output_name = r["output_entry"].text()
        fp = r["folder_path"]
        vp = self.video_path_edit.text()
        op = self.output_path_edit.text()
        tp = self.test_path_edit.text()

        audio_ok = bool(audio_name and os.path.isfile(os.path.join(fp, audio_name)))
        video_ok = False
        if video_name and video_name != "— снять выбор —":
            vfp = r.get("video_full_path") or (os.path.join(vp, video_name) if vp else "")
            video_ok = bool(vfp and os.path.isfile(vfp))

        output_exists = bool(output_name and op and os.path.isfile(os.path.join(op, output_name)))
        in_test = bool(output_name and tp and not output_exists and os.path.isfile(os.path.join(tp, output_name)))
        # Запоминаем имя файла на диске для корректного переименования
        if output_exists or in_test:
            r["output_on_disk"] = output_name

        if audio_name and not audio_ok:
            r["status_lbl"].setText("Нет аудио"); r["status_lbl"].setStyleSheet("color:red;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Нет аудио", ""))
            self._set_row_bg(r, COLOR_ERROR); r["sort_priority"] = 3
        elif video_name and video_name != "— снять выбор —" and not video_ok:
            r["status_lbl"].setText("Нет видео"); r["status_lbl"].setStyleSheet("color:red;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Нет видео", ""))
            self._set_row_bg(r, COLOR_ERROR); r["sort_priority"] = 3
        elif output_exists:
            r["status_lbl"].setText("Готово"); r["status_lbl"].setStyleSheet("color:green;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Готово", ""))
            self._set_row_bg(r, COLOR_READY); r["sort_priority"] = 4
            r["is_new"] = False  # Готово — больше не NEW
        elif in_test:
            r["status_lbl"].setText("В тесте"); r["status_lbl"].setStyleSheet("color:#b37400;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("В тесте", ""))
            self._set_row_bg(r, COLOR_IN_TEST); r["sort_priority"] = -1
            r["is_new"] = False  # В тесте — больше не NEW
        elif audio_ok and video_ok and output_name:
            r["status_lbl"].setText("К обработке"); r["status_lbl"].setStyleSheet("color:blue;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("К обработке", ""))
            self._set_row_bg(r, COLOR_TO_PROCESS); r["sort_priority"] = 0
            r["is_new"] = False  # К обработке — больше не NEW
        elif r.get("txt_problem"):
            r["status_lbl"].setText("TXT!"); r["status_lbl"].setStyleSheet("color:orange;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("TXT!", ""))
            self._set_row_bg(r, COLOR_TXT_WARN); r["sort_priority"] = 2
        elif audio_ok and (not video_name or video_name == "— снять выбор —"):
            r["status_lbl"].setText("Ожидает видео"); r["status_lbl"].setStyleSheet("color:#cc6600;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Ожидает видео", ""))
            self._set_row_bg(r, r["base_color"]); r["sort_priority"] = 1
        elif video_ok and not audio_ok:
            r["status_lbl"].setText("Ожидает аудио"); r["status_lbl"].setStyleSheet("color:#cc6600;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Ожидает аудио", ""))
            self._set_row_bg(r, r["base_color"]); r["sort_priority"] = 1
        elif not audio_name and (not video_name or video_name == "— снять выбор —"):
            r["status_lbl"].setText("Нет файлов"); r["status_lbl"].setStyleSheet("color:gray;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Нет файлов", ""))
            self._set_row_bg(r, r["base_color"]); r["sort_priority"] = 1
        else:
            r["status_lbl"].setText("Ожидание"); r["status_lbl"].setStyleSheet("color:gray;")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Ожидание", ""))
            self._set_row_bg(r, r["base_color"]); r["sort_priority"] = 1

        # Пересканируем архив (мог быть распакован/удалён)
        archive_file = ""
        try:
            for f in os.listdir(r["folder_path"]):
                fp_full = os.path.join(r["folder_path"], f)
                _, ext = os.path.splitext(f)
                if not os.path.isfile(fp_full):
                    continue
                ext_lo = ext.lower()
                if ext_lo in ('.rar', '.7z', '.zip') or (
                        (not ext or ' ' in ext or len(ext) > 10) and self._is_archive_by_magic(fp_full)):
                    archive_file = f
                    break
        except OSError:
            pass
        r["archive_file"] = archive_file
        has_archive = bool(archive_file)
        has_audio = self._has_main_audio(r)  # >= 1 ГБ, маленькие файлы — стартовые

        # Обновить текст аудио комбобокса если нет аудио но есть архив
        if not has_audio and has_archive:
            cur_text = r["audio_combo"].currentText()
            expected = "⚠ Нет аудио, есть архив"
            if cur_text != expected:
                r["audio_combo"].blockSignals(True)
                r["audio_combo"].clear()
                r["audio_combo"].addItem(expected, "")
                r["audio_combo"].setEnabled(False)
                r["audio_combo"].setStyleSheet("color: #cc6600;")
                r["audio_combo"].setToolTip(f"В папке нет аудио файлов, но найден архив: {archive_file}\nРаспакуйте архив кнопкой «Архив»")
                r["audio_combo"].blockSignals(False)
        elif not has_audio and not has_archive:
            cur_text = r["audio_combo"].currentText()
            expected = "⚠ Нет аудио файлов"
            if cur_text != expected:
                r["audio_combo"].blockSignals(True)
                r["audio_combo"].clear()
                r["audio_combo"].addItem(expected, "")
                r["audio_combo"].setEnabled(False)
                r["audio_combo"].setStyleSheet("color: red;")
                r["audio_combo"].setToolTip("В папке нет аудио файлов — добавьте аудио дорожку")
                r["audio_combo"].blockSignals(False)

        # --- Статус "Чудовищная ошибка" — папка без каких-либо данных ---
        if not has_audio and not has_archive:
            # Проверить торрент-файлы и ссылку
            _has_tor_files = False
            try:
                _has_tor_files = any(f.lower().endswith('.torrent') for f in os.listdir(r["folder_path"]) if os.path.isfile(os.path.join(r["folder_path"], f)))
            except OSError:
                pass
            _has_tor_url = bool(r.get("audio_torrent_url", ""))
            if not _has_tor_files and not _has_tor_url:
                r["status_lbl"].setText("Чудовищная ошибка"); r["status_lbl"].setStyleSheet("color:#cc0000; font-weight:bold; background-color:#ffe0e0;")
                r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("Чудовищная ошибка", ""))
                self._set_row_bg(r, "#ffe0e0"); r["sort_priority"] = 1

        # Кнопки действий — скрывать если нечего делать, показывать размер файла
        _pending = self._count_pending_outputs(r)
        # Считаем общее кол-во видео-источников (основной + extra)
        _vn = r["video_combo"].currentText()
        _extra_with_src = sum(
            1 for ev in r.get("extra_videos", []) if ev.get("video") or ev.get("video_full_path"))
        _total_src = (1 if _vn and _vn != "— снять выбор —" else 0) + _extra_with_src
        _sp = r.get("sort_priority")
        _can_process = _sp == 0 or _pending > 0
        # Запасная проверка: основной обработан (в тесте/результате), есть доп. видео с источником,
        # и хотя бы один доп. выходной файл ещё НЕ в тесте/результате
        if not _can_process and _sp in (-1, 4) and _extra_with_src > 0:
            _fb_prefix = self._get_prefix(r)
            _fb_suffix = self._get_suffix(r)
            _fb_tp = self.test_path_edit.text()
            _fb_op = self.output_path_edit.text()
            _fb_pending = 0
            for _fb_ev in r.get("extra_videos", []):
                _fb_v = _fb_ev.get("video", "")
                _fb_vfp = _fb_ev.get("video_full_path", "")
                _fb_vn = _fb_v or (os.path.basename(_fb_vfp) if _fb_vfp else "")
                if _fb_vn:
                    _fb_out = f"{_fb_prefix}{os.path.splitext(_fb_vn)[0]}{_fb_suffix}.mkv"
                    if not (_fb_op and os.path.isfile(os.path.join(_fb_op, _fb_out))) and \
                       not (_fb_tp and os.path.isfile(os.path.join(_fb_tp, _fb_out))):
                        _fb_pending += 1
            if _fb_pending > 0:
                _can_process = True
                _pending = _fb_pending
        # При 2+ источниках — всегда показывать кнопку с счётчиком, disabled если pending=0
        if _total_src >= 2:
            r["btn_play"].setVisible(True)
            r["btn_play"].setEnabled(_can_process)
            r["btn_play"].setText(f"Обработать ({_pending})")
            r["btn_play"].setToolTip(
                f"Запустить mkvmerge: {_pending} из {_total_src} файлов к обработке\n"
                f"Файлы уже в тесте/результате пропускаются")
        elif _can_process:
            r["btn_play"].setVisible(True)
            r["btn_play"].setEnabled(True)
            r["btn_play"].setText("Обработать")
            r["btn_play"].setToolTip("Запустить mkvmerge для этой записи")
        else:
            r["btn_play"].setVisible(False)
        # btn_download — видна когда нет аудио, нет архива, но есть торрент-файлы или ссылка
        # _has_tor_files и _has_tor_url вычисляются в секции "Чудовищная ошибка" выше
        if not has_audio and not has_archive and (_has_tor_files or _has_tor_url):
            r["btn_download"].setVisible(True)
            _dl_parts = []
            if _has_tor_files:
                _dl_parts.append("торрент-файл")
            if _has_tor_url:
                _dl_parts.append("ссылка")
            r["btn_download"].setToolTip(f"Скачать аудио дорожку\nДоступно: {', '.join(_dl_parts)}")
        else:
            r["btn_download"].setVisible(False)
        r["btn_unrar"].setVisible(has_archive)
        r["btn_del_archive"].setVisible(has_archive)
        if has_archive:
            _sz = _format_file_size_gb(os.path.join(fp, archive_file) if not os.path.isabs(archive_file) else archive_file)
            r["btn_unrar"].setText(f"Архив {_sz}" if _sz else "Архив")
            r["btn_del_archive"].setText(f"Архив {_sz}" if _sz else "Архив")
        r["btn_to_res"].setVisible(in_test)
        r["btn_del_test"].setVisible(in_test)
        if in_test:
            _sz, _cnt = self._output_size_label(r, tp)
            r["btn_to_res"].setText(f"В Результат {_sz}{_cnt}" if _sz else "В Результат")
            r["btn_del_test"].setText(f"Тест {_sz}{_cnt}" if _sz else "Тест")
        r["btn_del_src"].setVisible(video_ok)
        if video_ok:
            _vfp = r.get("video_full_path") or (os.path.join(vp, video_name) if vp else "")
            _sz = _format_file_size_gb(_vfp)
            r["btn_del_src"].setText(f"Источник {_sz}" if _sz else "Источник")
        r["btn_del_res"].setVisible(output_exists)
        if output_exists:
            _sz, _cnt = self._output_size_label(r, op)
            r["btn_del_res"].setText(f"Результат {_sz}{_cnt}" if _sz else "Результат")
        # Обновить батч-панель если текущая вкладка — этот фильм
        fn = r["folder_name"]
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() > 0:
            if self.tab_widget.tabText(self.tab_widget.currentIndex()) == fn:
                self._update_batch_buttons()
        if fn in self._open_tabs:
            tw = self._open_tabs[fn]["widgets"]
            # Обновить статус
            slbl = tw.get("status_lbl")
            if slbl:
                st = r["status_lbl"].text()
                slbl.setText(st)
                slbl.setStyleSheet(self._status_text_style(st))
            # Обновить кнопки открытия папок
            _ovd = tw.get("open_video_dir")
            if _ovd:
                vfp = r.get("video_full_path", "")
                has_vdir = bool(vfp and os.path.isfile(vfp)) or bool(self.video_path_edit.text() and os.path.isdir(self.video_path_edit.text()))
                _ovd.setEnabled(has_vdir)
            _ood = tw.get("open_output_dir")
            if _ood:
                out_name = r["output_entry"].text()
                op = self.output_path_edit.text()
                tp = self.test_path_edit.text()
                has_out = bool(out_name and ((op and os.path.isfile(os.path.join(op, out_name))) or (tp and os.path.isfile(os.path.join(tp, out_name)))))
                _ood.setEnabled(has_out)
            # Обновить выходные файлы + кнопки "ВСЕ"
            _upd_eo = tw.get("update_extra_output_names")
            if _upd_eo: _upd_eo()
        # Индикатор мультивыбора в tooltip аудио
        _n_av = len(r.get("extra_audio_variants", []))
        _n_ev = len(r.get("extra_videos", []))
        if _n_av > 0 or _n_ev > 0:
            _multi_tip = f"\n── Мультивыбор ──\nАудио вариантов: {_n_av + 1} | Видео: {_n_ev + 1}"
            _base_tip = r["audio_combo"].toolTip().split("\n── Мультивыбор")[0]
            r["audio_combo"].setToolTip(_base_tip + _multi_tip)
        # Обновить summary labels в таблице
        self._update_audio_summary(r)
        self._update_video_summary(r)
        self._update_output_summary(r)
        # Восстановить подсветку если строка выделена
        if self._highlighted_row is r:
            self._set_row_bg(r, COLOR_HIGHLIGHT, _is_highlight=True)
        self._schedule_batch_update()
        # Обновить счётчики на кнопках фильтрации по статусу
        self._update_status_filter_counts()

    def _fit_columns_to_content(self):
        """Подогнать ширину колонок под контент, включая текст внутри QLineEdit.
        Учитывает только видимые (не скрытые фильтром) строки.
        Также уменьшает ширину окна под суммарную ширину колонок."""
        hdr = self.table.horizontalHeader()
        # Снять Stretch с COL_TITLE чтобы setColumnWidth работал
        hdr.setSectionResizeMode(COL_TITLE, QHeaderView.Interactive)
        for col in range(self.table.columnCount()):
            if self.table.isColumnHidden(col):
                continue
            self._fit_single_column(col)
        # НЕ возвращаем Stretch — колонки остаются по ширине контента
        # Подогнать ширину окна: колонки + рамки таблицы, не меньше шапки
        total_cols = sum(self.table.columnWidth(c) for c in range(self.table.columnCount()) if not self.table.isColumnHidden(c))
        # Разница между шириной окна и viewport таблицы = рамки, скроллбар, отступы
        frame_w = self.width() - self.table.viewport().width()
        needed_w = total_cols + frame_w + 4
        min_w = self._paths_group.sizeHint().width() + 40
        new_w = max(needed_w, min_w)
        try:
            screen_w = QApplication.primaryScreen().availableGeometry().width()
            new_w = min(new_w, screen_w)
        except Exception:
            pass
        self.resize(new_w, self.height())

    def _set_row_bg(self, r, color, _is_highlight=False):
        if not _is_highlight:
            # Пропустить если цвет не изменился (экономим ~28 setStyleSheet вызовов)
            if r.get("_status_bg") == color:
                return
            r["_status_bg"] = color
        idx = r.get("row_index", -1)
        if idx < 0: return
        _bg = QColor(color)
        for col in range(NUM_COLS):
            item = self.table.item(idx, col)
            if item:
                item.setBackground(_bg)
            w = self.table.cellWidget(idx, col)
            if w:
                # Сбросить stylesheet контейнера чтобы QPalette работал
                if w.styleSheet():
                    w.setStyleSheet("")
                # QPalette для фона (Window = контейнер, Base = QLineEdit/QComboBox, Button = кнопки)
                w.setAutoFillBackground(True)
                pal = w.palette()
                pal.setColor(QPalette.Window, _bg)
                pal.setColor(QPalette.Base, _bg)
                pal.setColor(QPalette.Button, _bg)
                w.setPalette(pal)
                # autoFillBackground для дочерних виджетов (один раз)
                if not w.property("_bg_init"):
                    w.setProperty("_bg_init", True)
                    for child in w.findChildren(QWidget):
                        child.setAutoFillBackground(True)
        # Восстановить стиль status_lbl (текст + фон)
        st = r["status_lbl"]
        st_color = ""
        txt = st.text()
        if txt == "Нет аудио" or txt == "Нет видео": st_color = "red"
        elif txt == "Готово": st_color = "green"
        elif txt == "В тесте": st_color = "#b37400"
        elif txt == "К обработке": st_color = "blue"
        elif txt == "TXT!": st_color = "orange"
        elif txt == "Видео в процессе": st_color = "#8e44ad"
        elif txt == "✦ NEW": st_color = "#006600"
        elif txt in ("Неверный пароль", "Ошибка распаковки"): st_color = "red"
        if st_color:
            st.setStyleSheet(f"color:{st_color}; background-color:{color};")
        # Восстановить фон summary labels
        for _sk in ("audio_summary", "video_summary", "output_summary"):
            _sw = r.get(_sk)
            if _sw:
                _sw.setStyleSheet(f"background:{color};")
        # Восстановить цвета кнопок действий поверх фона
        r["ta_btn"].setStyleSheet(f"background:{color};")
        r["btn_play"].setStyleSheet(f"QPushButton{{background-color:#cce5ff;}} QPushButton:hover{{background-color:#99ccff;}} QPushButton:disabled{{background-color:#cce5ff;}}")
        r["btn_to_res"].setStyleSheet(f"QPushButton{{background-color:#ccffcc;}} QPushButton:hover{{background-color:#99ff99;}} QPushButton:disabled{{background-color:#ccffcc;}}")
        r["btn_del_test"].setStyleSheet(f"QPushButton{{background-color:#ffcccc;}} QPushButton:hover{{background-color:#ff9999;}} QPushButton:disabled{{background-color:#ffcccc;}}")
        r["btn_del_src"].setStyleSheet(f"QPushButton{{background-color:#ffcccc;}} QPushButton:hover{{background-color:#ff9999;}} QPushButton:disabled{{background-color:#ffcccc;}}")
        r["btn_del_res"].setStyleSheet(f"QPushButton{{background-color:#ffcccc;}} QPushButton:hover{{background-color:#ff9999;}} QPushButton:disabled{{background-color:#ffcccc;}}")
        r["btn_unrar"].setStyleSheet(f"QPushButton{{background-color:#ffe4c4;}} QPushButton:hover{{background-color:#ffc896;}} QPushButton:disabled{{background-color:#ffe4c4;}}")
        r["btn_del_archive"].setStyleSheet(f"QPushButton{{background-color:#ffcccc;}} QPushButton:hover{{background-color:#ff9999;}} QPushButton:disabled{{background-color:#ffcccc;}}")
        # Восстановить стиль info_btn (текст + фон)
        ib = r.get("info_btn")
        if ib:
            ib_txt = ib.text()
            if ib_txt.startswith("+ "):
                ib.setStyleSheet(f"color:blue;background:{color};")
            elif ib_txt.startswith("["):
                ib.setStyleSheet(f"color:orange;font-weight:bold;background:{color};")
            else:
                ib.setStyleSheet(f"color:#006600;font-weight:bold;background:{color};")
            # Восстановить рамку если это активная TXT кнопка
            if self._active_txt_fn == r.get("folder_name") and ib is self._active_txt_btn:
                ib.setStyleSheet(ib.styleSheet() + " border: 2px solid #0078d4;")
        # Восстановить фон delay_lbl (цвет значка через rich text)
        dl = r.get("delay_lbl")
        if dl:
            dl.setStyleSheet(f"background:{color};")

    _SP_VISUAL = {
        6:  ("Видео в процессе", "#8e44ad", COLOR_VIDEO_PENDING),
        5:  ("Неверный пароль",  "red",     COLOR_ERROR),
        -1: ("В тесте",          "#b37400", COLOR_IN_TEST),
        0:  ("К обработке",      "blue",    COLOR_TO_PROCESS),
        4:  ("Готово",           "green",   COLOR_READY),
        2:  ("TXT!",             "orange",  COLOR_TXT_WARN),
        3:  (None,               "red",     COLOR_ERROR),     # text from saved
        1:  ("",                 "",        None),             # no status
    }

    _STATUS_TOOLTIPS = {
        "Видео в процессе": "Ставится вручную кнопкой ⏳ в колонке «Видео файл».\nОзначает что видео ещё скачивается или обрабатывается.\nСбрасывается автоматически при выборе видео файла\nили вручную повторным нажатием ⏳.",
        "В тесте":          "Файл с заданным выходным именем (с суффиксом)\nнайден в тестовой папке.",
        "К обработке":      "Есть аудио файл, видео файл и имя выходного файла —\nвсё готово для запуска mkvmerge.",
        "Готово":           "Файл с заданным выходным именем (с суффиксом)\nнайден в папке результата.",
        "TXT!":             "Проблема с текстовым файлом:\nфайл .txt не найден в папке или он пустой.",
        "Нет аудио":        "Аудио файл указан в селекте, но не найден на диске\nпо пути в папке аудио.",
        "Нет видео":        "Видео файл указан в селекте, но не найден на диске\nпо пути в папке видео.",
        "✦ NEW":            "Запись ожидает обработки.\nСбрасывается автоматически после обработки\nили вручную кнопкой «Сбросить NEW».\nNEW-записи всегда отображаются вверху таблицы.",
        "Ожидает видео":    "Аудио файл найден, но видео источник не выбран.\nВыберите видео файл в колонке «Видео файл (источник)».",
        "Ожидает аудио":    "Видео файл найден, но аудио дорожка не выбрана.\nРаспакуйте архив или добавьте аудио файл в папку.",
        "Нет файлов":       "Аудио и видео файлы не выбраны.\nДобавьте файлы в папку.",
        "Ожидание":         "Группа статусов: не хватает данных для обработки.\nВключает: «Ожидает видео», «Ожидает аудио», «Нет файлов».\nСбрасывается автоматически при добавлении недостающих файлов.",
        "Чудовищная ошибка":    "Нет аудио, нет архива, нет торрент-файлов, нет ссылок на торрент.\nЗачем была создана папка если нет никаких данных?\nДобавьте торрент-файл, ссылку или аудио дорожку.",
        "Неверный пароль":  "Попытка распаковки архива не удалась — указан неверный пароль.\nСбрасывается ТОЛЬКО при успешной распаковке архива.\nВведите правильный пароль и нажмите кнопку «Архив» для повторной попытки.",
        "Ошибка":
            "Группа статусов: файл ВЫБРАН в селекте, но НЕ НАЙДЕН на диске.\n\n"
            "Включает:\n"
            "• «Нет аудио» — аудио файл выбран в комбобоксе,\n"
            "   но не найден в папке аудио дорожек.\n\n"
            "• «Нет видео» — видео файл выбран в комбобоксе,\n"
            "   но не найден в основной папке видео.\n\n"
            "Важно: если файл НЕ выбран (комбобокс пустой) —\n"
            "это НЕ ошибка, а статус «Ожидание».\n"
            "Ошибка = файл был, но пропал.",
    }

    def _apply_saved_status(self, r, saved):
        """Быстрое восстановление статуса из сохранённых данных (без I/O)."""
        sp = saved["sort_priority"]
        text, color, bg = self._SP_VISUAL.get(sp, ("", "", None))
        if text is None:
            text = saved.get("_status_text", "")
        r["status_lbl"].setText(text)
        r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get(text, ""))
        if color:
            r["status_lbl"].setStyleSheet(f"color:{color};")
        else:
            r["status_lbl"].setStyleSheet("")
        self._set_row_bg(r, bg or r["base_color"])
        r["btn_play"].setVisible(saved.get("_btn_play_vis", False))
        r["btn_download"].setVisible(saved.get("_btn_download_vis", False))
        r["btn_unrar"].setVisible(saved.get("_btn_unrar_vis", False))
        r["btn_del_archive"].setVisible(saved.get("_btn_del_archive_vis", False))
        r["btn_to_res"].setVisible(saved.get("_btn_to_res_vis", False))
        r["btn_del_test"].setVisible(saved.get("_btn_del_test_vis", False))
        r["btn_del_src"].setVisible(saved.get("_btn_del_src_vis", False))
        r["btn_del_res"].setVisible(saved.get("_btn_del_res_vis", False))
        # Восстановить видимость кнопки ⏳
        r["video_pending_btn"].setVisible(saved.get("_video_pending_btn_vis", False))

    def _apply_config_status(self, r, m):
        """Быстрая визуальная установка статуса из конфига (без I/O).
        Используется при начальной загрузке вместо _check_row_status."""
        sp = m.get("sort_priority", 1)
        r["sort_priority"] = sp
        is_new = m.get("is_new", False)
        r["is_new"] = is_new

        if is_new:
            r["status_lbl"].setText("✦ NEW")
            r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
            self._set_row_bg(r, COLOR_NEW)
        else:
            text, color, bg = self._SP_VISUAL.get(sp, ("", "", None))
            if text is None:
                text = "Ошибка"
            r["status_lbl"].setText(text)
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get(text, ""))
            if color:
                r["status_lbl"].setStyleSheet(f"color:{color};")
            else:
                r["status_lbl"].setStyleSheet("")
            self._set_row_bg(r, bg or r["base_color"])

        # Примерная видимость кнопок из sort_priority (уточнится при deferred проверке)
        r["btn_play"].setVisible(sp == 0 and not is_new)
        r["btn_to_res"].setVisible(sp == -1)
        r["btn_del_test"].setVisible(sp == -1)
        r["btn_del_res"].setVisible(sp == 4)
        # btn_download, btn_unrar, btn_del_archive, btn_del_src — будут уточнены при deferred проверке
        r["btn_download"].setVisible(False)
        r["btn_unrar"].setVisible(False)
        r["btn_del_archive"].setVisible(False)
        r["btn_del_src"].setVisible(False)

    def _visual_sort(self):
        """Мгновенная сортировка — визуальная перестановка строк через verticalHeader.
        Использует swapSections (O(1) за операцию) вместо moveSection (O(n) за операцию).
        Максимум n свопов вместо n² сдвигов."""
        n = len(self.rows)
        if n == 0:
            return
        vh = self.table.verticalHeader()
        was_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        vh.blockSignals(True)
        for i in range(n):
            desired_logical = self.rows[i]["row_index"]
            cur_visual = vh.visualIndex(desired_logical)
            if cur_visual != i:
                vh.swapSections(i, cur_visual)
        vh.blockSignals(False)
        self.setUpdatesEnabled(was_enabled)

    def _rescan_single_folder(self, fn):
        """Пересканировать файлы в папке одного фильма и обновить строку."""
        r = self._find_row(fn)
        if not r:
            self.log(f"[RESCAN] Строка «{fn}» не найдена")
            return
        fp = r["folder_path"]
        if not os.path.isdir(fp):
            self.log(f"[RESCAN] Папка не существует: {fp}")
            return

        # Пересканировать аудио файлы
        try:
            all_files = os.listdir(fp)
        except OSError as e:
            self.log(f"[RESCAN] Ошибка чтения: {e}")
            return

        new_audio = [f for f in all_files
                     if os.path.isfile(os.path.join(fp, f)) and self._is_audio(f)]
        old_audio_sel = self._audio_filename(r)
        r["audio_files"] = new_audio

        # Обновить audio_combo
        r["audio_combo"].blockSignals(True)
        if new_audio:
            self._populate_audio_combo(r["audio_combo"], new_audio, fp)
            if old_audio_sel and old_audio_sel in new_audio:
                for i in range(r["audio_combo"].count()):
                    if r["audio_combo"].itemData(i, Qt.UserRole) == old_audio_sel:
                        r["audio_combo"].setCurrentIndex(i)
                        break
            r["audio_combo"].setEnabled(True)
            r["audio_combo"].setStyleSheet("")
            r["audio_combo"].setToolTip("Основной аудио файл — будет вставлен в видео при обработке\nРазмер файла показан в скобках")
        else:
            r["audio_combo"].clear()
            r["audio_combo"].addItem("⚠ Нет аудио файлов", "")
            r["audio_combo"].setEnabled(False)
            r["audio_combo"].setStyleSheet("color: red;")
            r["audio_combo"].setToolTip("В папке нет аудио файлов — добавьте аудио дорожку")
        r["audio_combo"].blockSignals(False)

        # Обновить starter_combo и ender_combo
        main_file = self._audio_filename(r)
        for combo_key, fname_fn in (("starter_combo", self._starter_filename), ("ender_combo", self._ender_filename)):
            sc = r.get(combo_key)
            if sc:
                old_val = fname_fn(r)
                sc.blockSignals(True)
                self._populate_starter_combo(sc, new_audio, fp, exclude_file=main_file)
                if old_val and old_val in new_audio and old_val != main_file:
                    for i in range(sc.count()):
                        if sc.itemData(i, Qt.UserRole) == old_val:
                            sc.setCurrentIndex(i)
                            break
                sc.setEnabled(len(new_audio) > 1)
                sc.blockSignals(False)

        # Обновить audio_folders тоже
        for af in self.audio_folders:
            if af["name"] == fn:
                af["files"] = new_audio
                break

        # Пересканировать txt файлы
        txt_files = sorted([f for f in all_files if f.lower().endswith('.txt')
                            and os.path.isfile(os.path.join(fp, f))])
        r["txt_files"] = txt_files
        r["txt_problem"] = len(txt_files) > 1
        if not r.get("selected_txt") or r["selected_txt"] not in txt_files:
            if len(txt_files) == 1:
                r["selected_txt"] = txt_files[0]
                r["info_btn"].setText(txt_files[0][:15])
                r["info_btn"].setStyleSheet("color:#006600; font-weight:bold;")
                r["info_btn"].setToolTip(f"Выбран: {txt_files[0]}\nПравый клик — выбрать другой txt")

        # Пересканировать torrent файлы
        tor_files = sorted([f for f in all_files if f.lower().endswith('.torrent')
                            and os.path.isfile(os.path.join(fp, f))])
        r["tor_files"] = tor_files
        self._update_torrent_btn(r)

        # Сохранить is_new до _check_row_status
        was_new = r.get("is_new", False)

        # Обновить статус и кнопки
        self._check_row_status(r)

        # Восстановить NEW если был
        if was_new:
            r["is_new"] = True
            r["status_lbl"].setText("✦ NEW")
            r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
            r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
            self._set_row_bg(r, COLOR_NEW)

        # Обновить аудио комбобокс на вкладке если открыта
        if fn in self._open_tabs:
            tw = self._open_tabs[fn].get("widgets", {})
            tab_audio = tw.get("audio_combo")
            if tab_audio:
                tab_audio.blockSignals(True)
                old_tab_sel = tab_audio.currentData(Qt.UserRole) or ""
                tab_audio.clear()
                if new_audio:
                    _thr = self._AUDIO_MAIN_THRESHOLD
                    for f in new_audio:
                        try:
                            _fsz = os.path.getsize(os.path.join(fp, f))
                        except OSError:
                            _fsz = 0
                        if _fsz >= _thr:
                            tab_audio.addItem(self._format_audio_size(fp, f), f)
                    target = old_tab_sel if old_tab_sel in new_audio else (old_audio_sel if old_audio_sel in new_audio else "")
                    if target:
                        for i in range(tab_audio.count()):
                            if tab_audio.itemData(i, Qt.UserRole) == target:
                                tab_audio.setCurrentIndex(i)
                                break
                    tab_audio.setEnabled(tab_audio.count() > 0)
                else:
                    tab_audio.addItem("⚠ Нет аудио файлов", "")
                    tab_audio.setEnabled(False)
                tab_audio.blockSignals(False)
            # Обновить кнопку "Сканировать дорожки" на вкладке
            _scan_btn = tw.get("scan_tracks_btn")
            if _scan_btn and tab_audio:
                _cur_a = tab_audio.currentData(Qt.UserRole) or ""
                _a_ok = bool(_cur_a and not _cur_a.startswith("\u26A0") and
                             os.path.isfile(os.path.join(fp, _cur_a)))
                _scan_btn.setEnabled(_a_ok)
            # Обновить starter_combo и ender_combo на вкладке
            main_file = self._audio_filename(r)
            for tab_key in ("starter_combo", "ender_combo"):
                tab_combo = tw.get(tab_key)
                if tab_combo:
                    tab_combo.blockSignals(True)
                    old_tab_val = tab_combo.currentData(Qt.UserRole) or ""
                    self._populate_starter_combo(tab_combo, new_audio, fp, exclude_file=main_file)
                    if old_tab_val and old_tab_val in new_audio and old_tab_val != main_file:
                        for i in range(tab_combo.count()):
                            if tab_combo.itemData(i, Qt.UserRole) == old_tab_val:
                                tab_combo.setCurrentIndex(i)
                                break
                    tab_combo.setEnabled(tab_combo.count() > 1)
                    tab_combo.blockSignals(False)

            # Обновить отображение архива на вкладке
            archive_name = r.get("archive_file", "")
            arc_lbl = tw.get("archive_label")
            if arc_lbl:
                if archive_name:
                    arc_lbl.setText(archive_name)
                    arc_lbl.setStyleSheet("font-family: Consolas, monospace; color:#8B4513; font-weight:bold;")
                    arc_lbl.setToolTip(f"Файл архива:\n{os.path.join(fp, archive_name)}")
                else:
                    arc_lbl.setText("нет")
                    arc_lbl.setStyleSheet("color:#aaa;")
                    arc_lbl.setToolTip("Архив звуковой дорожки не найден в папке")
            arc_btn = tw.get("archive_btn")
            if arc_btn:
                arc_btn.setVisible(not bool(archive_name))
            # Обновить кнопку торрент файла на вкладке
            tor_btn = tw.get("tor_open_btn")
            if tor_btn:
                # Удалить старое меню
                _old_m = tor_btn.menu()
                if _old_m:
                    tor_btn.setMenu(None)
                    _old_m.deleteLater()
                try: tor_btn.clicked.disconnect()
                except RuntimeError: pass
                if tor_files:
                    tor_btn.setText(f"Торрент ({len(tor_files)})")
                    tor_btn.setStyleSheet("color:green;")
                    tor_btn.setEnabled(True)
                    tor_btn.setToolTip(f"Торрент-файлов: {len(tor_files)}\n" + "\n".join(f"  • {f}" for f in tor_files))
                    _tmenu = QMenu(tor_btn)
                    for _tf in tor_files:
                        _tp3 = os.path.join(fp, _tf)
                        _tact = _tmenu.addAction(_tf)
                        _tact.triggered.connect((lambda p: lambda: os.startfile(p) if os.path.isfile(p) else None)(_tp3))
                    tor_btn.setMenu(_tmenu)
                else:
                    tor_btn.setText("Выбрать торрент файл")
                    tor_btn.setStyleSheet("")
                    tor_btn.setEnabled(True)
                    tor_btn.setToolTip("Выбрать .torrent файл аудио дорожки — он будет ПЕРЕМЕЩЁН в папку фильма")
                    tor_btn.clicked.connect(lambda _, f=fn: self._move_torrent_to_folder(f))
                tor_btn.adjustSize()

        # Обновить счётчик аудио
        total = sum(len(f["files"]) for f in self.audio_folders)
        self.audio_count_lbl.setText(f"Папок: {len(self.audio_folders)}, аудио файлов: {total}")

        self._update_archive_btn_count()
        self._update_batch_buttons()
        self.schedule_autosave()
        self.log(f"[RESCAN] Папка «{fn}» пересканирована: аудио={len(new_audio)}, "
                 f"txt={len(txt_files)}, torrent={len(tor_files)}, архив={r.get('archive_file', '')}")

    def _show_backup_settings(self):
        """Диалог настроек резервного копирования."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройки бэкапов")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        header = QLabel("Параметры резервного копирования")
        header.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(header)

        # Текущие значения из конфига
        bk = self.config.get("backup_settings", {})

        # --- Дневные бэкапы films.json.daily_ ---
        g1 = QGroupBox("Дневные бэкапы (films.json.daily_*)")
        g1.setToolTip("Датированные копии основного конфига films.json.\n"
                       "Создаются автоматически, не затираются быстрой ротацией .bak1-.bak5.")
        g1l = QGridLayout(g1)

        g1l.addWidget(QLabel("Интервал между бэкапами (часы):"), 0, 0)
        spin_interval = QSpinBox()
        spin_interval.setRange(1, 168)
        spin_interval.setValue(bk.get("daily_interval_hours", 12))
        spin_interval.setToolTip("Минимальный интервал между дневными бэкапами.\n"
                                  "По умолчанию: 12 часов (2 бэкапа в день).")
        g1l.addWidget(spin_interval, 0, 1)

        g1l.addWidget(QLabel("Хранить копий (максимум):"), 1, 0)
        spin_daily_keep = QSpinBox()
        spin_daily_keep.setRange(2, 100)
        spin_daily_keep.setValue(bk.get("daily_keep", 10))
        spin_daily_keep.setToolTip("Сколько самых свежих дневных бэкапов хранить.\n"
                                    "Старые удаляются автоматически.\n"
                                    "По умолчанию: 10 (≈5 дней при интервале 12 ч).")
        g1l.addWidget(spin_daily_keep, 1, 1)
        layout.addWidget(g1)

        # --- Аварийные бэкапы films.json.safe_ ---
        g2 = QGroupBox("Аварийные бэкапы (films.json.safe_*)")
        g2.setToolTip("Создаются когда обнаружена массовая потеря данных.\n"
                       "Хранят копию хорошего файла перед перезаписью.")
        g2l = QGridLayout(g2)

        g2l.addWidget(QLabel("Хранить копий (максимум):"), 0, 0)
        spin_safe_keep = QSpinBox()
        spin_safe_keep.setRange(1, 50)
        spin_safe_keep.setValue(bk.get("safe_keep", 5))
        spin_safe_keep.setToolTip("Сколько аварийных бэкапов хранить.\n"
                                   "По умолчанию: 5.")
        g2l.addWidget(spin_safe_keep, 0, 1)

        g2l.addWidget(QLabel("Порог потери данных (%):"), 1, 0)
        spin_threshold = QSpinBox()
        spin_threshold.setRange(5, 80)
        spin_threshold.setValue(bk.get("safe_threshold_pct", 20))
        spin_threshold.setToolTip("Если потеряно больше этого процента записей с данными —\n"
                                   "создать аварийный бэкап перед сохранением.\n"
                                   "По умолчанию: 20%.")
        g2l.addWidget(spin_threshold, 1, 1)
        layout.addWidget(g2)

        # --- _meta.json.safe в папках фильмов ---
        g3 = QGroupBox("Бэкапы в папках фильмов (_meta.json.safe)")
        g3.setToolTip("При сохранении _meta.json: если новые данные пустые,\n"
                       "а на диске заполненные — создаётся копия _meta.json.safe.\n"
                       "Хранится в той же папке что и аудио дорожка фильма.")
        g3l = QGridLayout(g3)

        g3l.addWidget(QLabel("Хранить копий в каждой папке:"), 0, 0)
        spin_meta_keep = QSpinBox()
        spin_meta_keep.setRange(1, 20)
        spin_meta_keep.setValue(bk.get("meta_safe_keep", 3))
        spin_meta_keep.setToolTip("Сколько бэкапов _meta.json.safe хранить в каждой папке фильма.\n"
                                   "Файлы: _meta.json.safe_1, _meta.json.safe_2 и т.д.\n"
                                   "По умолчанию: 3.")
        g3l.addWidget(spin_meta_keep, 0, 1)
        layout.addWidget(g3)

        # --- Быстрая ротация .bak ---
        g4 = QGroupBox("Быстрая ротация (.bak1 — .bak5)")
        g4.setToolTip("Копии файла при каждом сохранении.\n"
                       "Защита от единичных сбоев записи.")
        g4l = QGridLayout(g4)

        g4l.addWidget(QLabel("Количество .bak копий:"), 0, 0)
        spin_bak = QSpinBox()
        spin_bak.setRange(1, 20)
        spin_bak.setValue(bk.get("bak_count", 5))
        spin_bak.setToolTip("Сколько файлов .bak1-.bakN хранить.\nПо умолчанию: 5.")
        g4l.addWidget(spin_bak, 0, 1)
        layout.addWidget(g4)

        # --- Восстановление из бэкапа ---
        g_restore = QGroupBox("Восстановление из бэкапа")
        g_restore.setToolTip("Выбрать бэкап из списка и восстановить films.json.\n"
                              "Текущий файл будет сохранён как films.json.before_restore.")
        g_restore_l = QVBoxLayout(g_restore)

        # Типы бэкапов: название, цвет, описание
        _BAK_TYPES = {
            "bak":     ("Ротация",    "#333333",
                        "Циклический бэкап (#1 = самый свежий, #5 = самый старый).\n"
                        "Создаётся автоматически перед каждым сохранением."),
            "daily":   ("Ежедневный", "#0066aa",
                        "Создаётся один раз в сутки при первом сохранении за день."),
            "safe":    ("Аварийный",  "#cc0000",
                        "Создаётся автоматически при обнаружении потери данных\n"
                        "(если новые данные значительно хуже старых)."),
            "restore": ("Авто-снимок","#886600",
                        "Автоматическая копия films.json, сделанная ПЕРЕД\n"
                        "последним восстановлением из бэкапа (страховка)."),
        }
        def _bak_type_key(fn):
            if fn.endswith(".before_restore"): return "restore"
            if ".daily_" in fn: return "daily"
            if ".safe_" in fn: return "safe"
            for i in range(1, 10):
                if fn.endswith(f".bak{i}"): return "bak"
            return "bak"
        def _bak_type_label(fn):
            key = _bak_type_key(fn)
            label = _BAK_TYPES[key][0]
            for i in range(1, 10):
                if fn.endswith(f".bak{i}"): return f"{label} #{i}"
            return label

        # QListWidget с бэкапами
        _bak_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_films")
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        _bak_list = QListWidget()
        _bak_list.setFont(QFont("Consolas", 9))
        _bak_list.setAlternatingRowColors(True)
        _bak_list.setStyleSheet("QListWidget{border:1px solid #ccc;} "
                                 "QListWidget::item{padding:3px 4px;} "
                                 "QListWidget::item:selected{background:#cde4f7;}")
        _bak_list.setToolTip("Выберите бэкап и нажмите «Восстановить» или двойной клик.\n\n"
                              "Колонки:\n"
                              "  video — фильмов с назначенным видеофайлом\n"
                              "  title — фильмов с заполненным названием\n"
                              "  sub — фильмов с указанным годом абонемента\n\n"
                              "Типы бэкапов:\n"
                              "  Ротация #1-5 — циклические, перед каждым сохранением (#1 = свежий)\n"
                              "  Ежедневный — один раз в сутки при первом сохранении за день\n"
                              "  Аварийный — при обнаружении потери данных (защита от коррупции)\n"
                              "  Авто-снимок — копия перед последним восстановлением (страховка)")
        _bak_files = {}  # display text → full path
        try:
            import datetime
            _entries = []
            for fn in os.listdir(_bak_dir):
                if fn.startswith("films.json.") and not fn.endswith(".corrupted_20260207"):
                    fp = os.path.join(_bak_dir, fn)
                    sz = os.path.getsize(fp)
                    mt = datetime.datetime.fromtimestamp(os.path.getmtime(fp))
                    _type_key = _bak_type_key(fn)
                    _type_label = _bak_type_label(fn)
                    try:
                        with open(fp, "r", encoding="utf-8") as _f:
                            _d = json.load(_f)
                        _m = _d.get("mappings", [])
                        _nv = sum(1 for i in _m if i.get("video"))
                        _nt = sum(1 for i in _m if i.get("title"))
                        _ns = sum(1 for i in _m if i.get("sub_year", "—") not in ("—", ""))
                        _stats = f"video={_nv}  title={_nt}  sub={_ns}"
                    except:
                        _stats = "[ошибка чтения]"
                    _entries.append((mt, fn, fp, sz, _type_key, _type_label, _stats))
            # Сортировка: новые сверху
            _entries.sort(key=lambda x: x[0], reverse=True)
            for mt, fn, fp, sz, _type_key, _type_label, _stats in _entries:
                _text = f"[{_type_label:20s}]  {mt:%Y-%m-%d %H:%M}  [{sz/1024:.0f} КБ]  {_stats}    {fn}"
                _bt = _BAK_TYPES[_type_key]
                item = QListWidgetItem(_text)
                item.setForeground(QColor(_bt[1]))
                item.setToolTip(f"Файл: {fn}\nРазмер: {sz/1024:.0f} КБ\n"
                                f"Дата: {mt:%Y-%m-%d %H:%M:%S}\n\n"
                                f"Тип: {_type_label}\n{_bt[2]}\n\n"
                                f"Содержимое:\n"
                                f"  video — фильмов с видеофайлом: {_stats.split('video=')[1].split()[0] if 'video=' in _stats else '?'}\n"
                                f"  title — фильмов с названием: {_stats.split('title=')[1].split()[0] if 'title=' in _stats else '?'}\n"
                                f"  sub — фильмов с абонементом: {_stats.split('sub=')[1].split()[0] if 'sub=' in _stats else '?'}")
                item.setData(Qt.UserRole, fp)
                _bak_list.addItem(item)
        except:
            _bak_list.addItem("Ошибка сканирования папки бэкапов")
        _bak_list.setMinimumHeight(150)
        g_restore_l.addWidget(_bak_list)

        _restore_btns = QHBoxLayout()
        restore_btn = QPushButton("⬆ Восстановить выбранный")
        restore_btn.setStyleSheet("QPushButton{background-color:#ffe4c4; font-weight:bold; padding:5px 12px;} "
                                   "QPushButton:hover{background-color:#ffc896;}")
        restore_btn.setToolTip("Восстановить films.json из выбранного бэкапа.\n"
                                "Текущий файл сохранится как films.json.before_restore")
        def _do_restore(chosen_path=None):
            if not chosen_path:
                sel = _bak_list.currentItem()
                if not sel or not sel.data(Qt.UserRole):
                    QMessageBox.warning(dlg, "Внимание", "Выберите бэкап из списка")
                    return
                chosen_path = sel.data(Qt.UserRole)
            try:
                with open(chosen_path, "r", encoding="utf-8") as _f:
                    _test = json.load(_f)
                _tm = _test.get("mappings", [])
                if not _tm:
                    QMessageBox.warning(dlg, "Ошибка", "Файл не содержит mappings")
                    return
                _nv = sum(1 for i in _tm if i.get("video"))
                _nt = sum(1 for i in _tm if i.get("title"))
                _ns = sum(1 for i in _tm if i.get("sub_year", "—") not in ("—", ""))
                _bn = os.path.basename(chosen_path)
                reply = QMessageBox.question(
                    dlg, "Подтверждение",
                    f"Восстановить из:\n{_bn}\n\n"
                    f"Записей: {len(_tm)}, с видео: {_nv}, title: {_nt}, sub_year: {_ns}\n\n"
                    f"Текущий films.json будет сохранён как films.json.before_restore\n"
                    f"Таблица и все вкладки обновятся сразу.",
                    QMessageBox.Yes | QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return
                # Сохраняем текущий файл
                _curr_path = os.path.join(_bak_dir, "films.json")
                _save_path = _curr_path + ".before_restore"
                import shutil
                if os.path.isfile(_curr_path):
                    shutil.copy2(_curr_path, _save_path)
                # Записываем бэкап на диск
                shutil.copy2(chosen_path, _curr_path)
                # Применяем в память: обновляем config и UI
                self.config["mappings"] = _tm
                # Сбросить available_videos — при повторном вызове они уже исчерпаны
                self.available_videos = self.video_files.copy()
                self.setUpdatesEnabled(False)
                self._restore_mappings(skip_meta_check=True)
                self.setUpdatesEnabled(True)
                # Удалить _meta_backup.json во всех папках — конфликтов после
                # восстановления нет, иначе вкладки покажут ложное предупреждение
                _cleaned = 0
                for _r in self.rows:
                    _fp = _r.get("folder_path", "")
                    _mbp = os.path.join(_fp, "_meta_backup.json") if _fp else ""
                    if _mbp and os.path.isfile(_mbp):
                        try:
                            os.remove(_mbp)
                            _cleaned += 1
                        except Exception:
                            pass
                    _r["has_meta_backup"] = False
                if _cleaned:
                    self.log(f"Удалено {_cleaned} устаревших _meta_backup.json после восстановления")
                # Обновить все открытые вкладки — закрыть и переоткрыть
                open_tabs = list(self._open_tabs.keys())
                for fn in open_tabs:
                    idx = self._find_tab_index(fn)
                    if idx >= 0:
                        self.tab_widget.removeTab(idx)
                    if fn in self._open_tabs:
                        del self._open_tabs[fn]
                for fn in open_tabs:
                    if self._find_row(fn):
                        self._open_record_tab(fn)
                self.tab_widget.setCurrentIndex(0)
                # Сохранить восстановленное состояние
                if not self._readonly:
                    self._save_films()
                    self._save_settings()
                dlg.accept()
                QMessageBox.information(self, "Готово",
                    f"Восстановлено из {_bn}.\n"
                    f"Таблица и {len(open_tabs)} вкладок обновлены.")
            except Exception as ex:
                import traceback
                self.log(f"Ошибка восстановления: {traceback.format_exc()}")
                QMessageBox.critical(dlg, "Ошибка", f"Не удалось восстановить:\n{ex}")
        restore_btn.clicked.connect(lambda: _do_restore())
        _bak_list.itemDoubleClicked.connect(lambda item: _do_restore(item.data(Qt.UserRole)))
        _restore_btns.addWidget(restore_btn)

        open_folder_btn = QPushButton("📁 Открыть папку бэкапов")
        open_folder_btn.setToolTip("Открыть config_films/ в проводнике")
        open_folder_btn.clicked.connect(lambda: os.startfile(_bak_dir) if hasattr(os, 'startfile') else None)
        _restore_btns.addWidget(open_folder_btn)
        _restore_btns.addStretch()
        g_restore_l.addLayout(_restore_btns)
        layout.addWidget(g_restore)

        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Сохранить")
        save_btn.setToolTip("Сохранить настройки бэкапов")
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setToolTip("Закрыть без сохранения")
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        cancel_btn.clicked.connect(dlg.reject)

        def _on_save():
            self.config["backup_settings"] = {
                "daily_interval_hours": spin_interval.value(),
                "daily_keep": spin_daily_keep.value(),
                "safe_keep": spin_safe_keep.value(),
                "safe_threshold_pct": spin_threshold.value(),
                "meta_safe_keep": spin_meta_keep.value(),
                "bak_count": spin_bak.value(),
            }
            self.schedule_autosave()
            dlg.accept()

        save_btn.clicked.connect(_on_save)
        dlg.exec()

    def _get_backup_setting(self, key, default):
        """Получить настройку бэкапов из конфига."""
        return self.config.get("backup_settings", {}).get(key, default)

    def _show_status_legend(self):
        """Показать модальное окно справки с вкладками."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Справка")
        dlg.setMinimumWidth(800)
        dlg.setMinimumHeight(450)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        # Создаём вкладки
        tabs = QTabWidget(dlg)

        # === ВКЛАДКА 1: СТАТУСЫ ===
        tab_statuses = QWidget()
        tab_statuses_layout = QVBoxLayout(tab_statuses)
        tab_statuses_layout.setSpacing(6)

        header = QLabel("Как определяется статус каждой строки:")
        header.setFont(QFont("Arial", 11, QFont.Bold))
        tab_statuses_layout.addWidget(header)

        statuses = [
            ("✦ NEW", "#006600", COLOR_NEW,
             "Запись ожидает обработки. Ставится автоматически при создании записи "
             "через диалог «Создать папку». "
             "Сбрасывается автоматически после обработки "
             "или вручную кнопкой «Сбросить NEW» в панели кнопок / на вкладке фильма. "
             "NEW-записи всегда отображаются вверху таблицы."),
            ("К обработке", "blue", COLOR_TO_PROCESS,
             "Аудио файл существует на диске, видео файл существует на диске, "
             "имя выходного файла задано — всё готово для запуска mkvmerge."),
            ("Готово", "green", COLOR_READY,
             "Файл с заданным выходным именем (включая суффикс) "
             "найден в папке результата."),
            ("В тесте", "#b37400", COLOR_IN_TEST,
             "Файл с заданным выходным именем (включая суффикс) "
             "найден в тестовой папке, но НЕ в папке результата."),
            ("Нет аудио", "red", COLOR_ERROR,
             "В «Аудио файл (источник)» выбран файл, но он не найден на диске "
             "в папке аудио. Причина: архив не распакован, файл удалён или переименован."),
            ("Нет видео", "red", COLOR_ERROR,
             "В «Видео файл (источник)» выбран файл, но он не найден на диске "
             "в папке видео. Причина: файл удалён, перемещён или ещё не скачан."),
            ("TXT!", "orange", COLOR_TXT_WARN,
             "В папке аудио дорожки не найден файл .txt или он пустой."),
            ("Видео в процессе", "#8e44ad", COLOR_VIDEO_PENDING,
             "Ставится вручную кнопкой ⏳ в колонке «Видео файл». "
             "Означает что видео ещё скачивается или обрабатывается. "
             "Сбрасывается автоматически при выборе видео файла "
             "или вручную повторным нажатием ⏳."),
            ("Неверный пароль", "red", COLOR_ERROR,
             "Попытка распаковки архива не удалась — указан неверный пароль. "
             "Сбрасывается ТОЛЬКО при успешной распаковке архива. "
             "Введите правильный пароль и нажмите кнопку «Архив» для повторной попытки."),
            ("Ожидает видео", "#cc6600", "#f0f0f0",
             "Аудио файл найден, но видео источник не выбран. "
             "Выберите видео файл в колонке «Видео файл (источник)»."),
            ("Ожидает аудио", "#cc6600", "#f0f0f0",
             "Видео файл найден, но аудио дорожка не выбрана. "
             "Распакуйте архив или добавьте аудио файл в папку."),
            ("Нет файлов", "gray", "#f0f0f0",
             "Аудио и видео файлы не выбраны. Добавьте файлы в папку."),
            ("Чудовищная ошибка", "#cc0000", "#ffe0e0",
             "Папка создана, но в ней нет НИЧЕГО: "
             "нет аудио файлов, нет архива, нет торрент-файлов (.torrent), "
             "нет ссылки на торрент аудио. "
             "Зачем была создана папка если нет никаких данных? "
             "Добавьте торрент-файл, ссылку на торрент или аудио дорожку."),
        ]
        for name, color, bg_color, desc in statuses:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(8)
            lbl_name = QLabel(f"<b>{name}</b>")
            lbl_name.setStyleSheet(f"color:{color}; min-width:140px;")
            lbl_name.setFixedWidth(150)
            row_l.addWidget(lbl_name)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            row_l.addWidget(lbl_desc, 1)
            if bg_color:
                row_w.setStyleSheet(f"background:{bg_color}; border-radius:3px; padding:2px;")
            tab_statuses_layout.addWidget(row_w)

        tab_statuses_layout.addStretch()
        tabs.addTab(tab_statuses, "Статусы")

        # === ВКЛАДКА 2: КНОПКИ ДЕЙСТВИЯ ===
        tab_actions = QWidget()
        tab_actions_layout = QVBoxLayout(tab_actions)
        tab_actions_layout.setSpacing(6)

        header2 = QLabel("Кнопки действий на вкладке фильма:")
        header2.setFont(QFont("Arial", 11, QFont.Bold))
        tab_actions_layout.addWidget(header2)

        # Список кнопок с иконками (icon_func, label, bg_color, border_color, desc)
        # Цвета как в реальном интерфейсе (активные кнопки)
        actions = [
            (_make_play_icon, "Обработать", "#e6f0ff", "#99b3cc",
             "Запустить mkvmerge: вставить выбранную аудио дорожку в видео файл "
             "и сохранить результат с заданным именем.\n"
             "Доступна если есть хотя бы один необработанный видео-источник.\n"
             "Цифра в скобках (N) — количество файлов к обработке.\n"
             "Файлы уже в тесте/результате пропускаются автоматически."),
            (_make_unrar_icon, "Архив", "#fff0e0", "#ccb499",
             "Расшифровать RAR архив с аудио дорожкой используя указанный пароль. "
             "Архив определяется автоматически: файл с расширением .rar/.7z/.zip, "
             "либо файл без расширения с сигнатурой архива (RAR, 7z, ZIP). "
             "После распаковки аудио файл появится в папке."),
            (_make_del_archive_icon, "Архив", "#ffe8e8", "#cc9999",
             "Удалить расшифрованный архив из папки аудио. "
             "Кнопка появляется только если в папке одновременно есть и архив, и аудио файл "
             "(то есть архив уже распакован и больше не нужен)."),
            (_make_to_result_icon, "В Результат", "#e8ffe8", "#99cc99",
             "Переместить файл из тестовой папки в папку результата. "
             "Доступна только при статусе «В тесте». "
             "На кнопке отображается суммарный размер всех выходных файлов. "
             "Цифра в скобках (2) — количество файлов, если их больше одного."),
            (_make_del_video_icon, "Тест", "#ffe8e8", "#cc9999",
             "Удалить тестовый видео файл из папки тест. Доступна только при статусе «В тесте». "
             "Суммарный размер и количество файлов (N) отображаются на кнопке."),
            (_make_del_video_icon, "Источник", "#ffe8e8", "#cc9999",
             "Удалить исходное видео из папки видео. "
             "Используйте после того как видео больше не нужно."),
            (_make_del_video_icon, "Результат", "#ffe8e8", "#cc9999",
             "Удалить готовый видео файл из папки результата. "
             "Суммарный размер и количество файлов (N) отображаются на кнопке."),
            (_make_del_archive_icon, "Неподтвержденные настройки", "#ffcccc", "#cc9999",
             "Сбросить все неподтверждённые настройки записи.\n"
             "Сюда входят: задержки без галочки подтверждения, "
             "дополнительные аудио варианты (start/end) без подтверждения.\n"
             "Цифра в скобках — количество неподтверждённых настроек.\n"
             "Перед сбросом показывает диалог со списком удаляемых настроек.\n"
             "Кнопка активна только если есть что сбрасывать."),
        ]
        for icon_func, label, bg_color, border_color, desc in actions:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.setSpacing(8)
            # Создаём кнопку-превью (активная, но без обработчика клика)
            btn_preview = QPushButton(label)
            btn_preview.setIcon(icon_func())
            btn_preview.setIconSize(QSize(32, 16))
            btn_preview.setFixedWidth(230)
            btn_preview.setStyleSheet(f"QPushButton{{color:black; background-color:{bg_color}; border:1px solid {border_color}; padding:2px 6px;}}")
            btn_preview.setFocusPolicy(Qt.NoFocus)  # Не получает фокус
            row_l.addWidget(btn_preview)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            row_l.addWidget(lbl_desc, 1)
            tab_actions_layout.addWidget(row_w)

        tab_actions_layout.addStretch()
        tabs.addTab(tab_actions, "Кнопки действия")

        # === ВКЛАДКА 3: РАСШИРЕНИЯ ФАЙЛОВ ===
        tab_extensions = QWidget()
        tab_ext_layout = QVBoxLayout(tab_extensions)
        tab_ext_layout.setSpacing(10)

        header3 = QLabel("Распознаваемые расширения файлов:")
        header3.setFont(QFont("Arial", 11, QFont.Bold))
        tab_ext_layout.addWidget(header3)

        exts_audio = ", ".join(AUDIO_EXTS)
        exts_video = ", ".join(VIDEO_EXTS)

        # Аудио расширения
        audio_group = QWidget()
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        audio_header = QLabel("<b>🎵 Аудио файлы:</b>")
        audio_header.setStyleSheet("font-size:12pt;")
        audio_layout.addWidget(audio_header)
        audio_list = QLabel(exts_audio)
        audio_list.setWordWrap(True)
        audio_list.setStyleSheet("padding-left:10px; color:#333;")
        audio_layout.addWidget(audio_list)
        audio_group.setStyleSheet("background:#f0f8ff; border-radius:4px;")
        tab_ext_layout.addWidget(audio_group)

        # Видео расширения
        video_group = QWidget()
        video_layout = QVBoxLayout(video_group)
        video_layout.setContentsMargins(8, 8, 8, 8)
        video_header = QLabel("<b>📽️ Видео файлы:</b>")
        video_header.setStyleSheet("font-size:12pt;")
        video_layout.addWidget(video_header)
        video_list = QLabel(exts_video)
        video_list.setWordWrap(True)
        video_list.setStyleSheet("padding-left:10px; color:#333;")
        video_layout.addWidget(video_list)
        video_group.setStyleSheet("background:#fff8f0; border-radius:4px;")
        tab_ext_layout.addWidget(video_group)

        # Архивы
        archive_group = QWidget()
        archive_layout = QVBoxLayout(archive_group)
        archive_layout.setContentsMargins(8, 8, 8, 8)
        archive_header = QLabel("<b>📦 Архивы:</b>")
        archive_header.setStyleSheet("font-size:12pt;")
        archive_layout.addWidget(archive_header)
        archive_list = QLabel(".rar, .7z, .zip или файл без расширения с сигнатурой архива (magic bytes)")
        archive_list.setWordWrap(True)
        archive_list.setStyleSheet("padding-left:10px; color:#333;")
        archive_layout.addWidget(archive_list)
        archive_group.setStyleSheet("background:#fff0f8; border-radius:4px;")
        tab_ext_layout.addWidget(archive_group)

        # Примечание
        note = QLabel("<i>Для добавления нового расширения необходимо изменить константы "
                     "AUDIO_EXTS / VIDEO_EXTS в исходном коде программы.</i>")
        note.setWordWrap(True)
        note.setStyleSheet("color:#666; padding:8px;")
        tab_ext_layout.addWidget(note)

        tab_ext_layout.addStretch()
        tabs.addTab(tab_extensions, "Расширения файлов")

        # === ВКЛАДКА 4: БЭКАПЫ ===
        tab_backup = QWidget()
        tab_bak_layout = QVBoxLayout(tab_backup)
        tab_bak_layout.setSpacing(10)

        bak_header = QLabel("Система резервного копирования:")
        bak_header.setFont(QFont("Arial", 11, QFont.Bold))
        tab_bak_layout.addWidget(bak_header)

        # --- _meta.json ---
        meta_group = QWidget()
        meta_layout = QVBoxLayout(meta_group)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.addWidget(QLabel("<b>_meta.json в папке каждого фильма</b>"))
        meta_desc = QLabel(
            "При каждом автосохранении в папку аудио дорожки каждого фильма "
            "записывается файл <b>_meta.json</b> — полная копия настроек этого фильма "
            "(название, год, ссылки, пароль архива, задержка, приоритет и т.д.).\n\n"
            "Это независимый бэкап: даже если основной конфиг повреждён, "
            "данные можно восстановить из _meta.json в папках фильмов.\n\n"
            "Если новые данные пустые, а на диске уже есть заполненный _meta.json — "
            "перед перезаписью создаётся ротация бэкапов <b>_meta.json.safe_1</b>, "
            "<b>_meta.json.safe_2</b> и т.д. в той же папке.\n"
            "Количество настраивается в «Настройки бэкапов»."
        )
        meta_desc.setWordWrap(True)
        meta_layout.addWidget(meta_desc)
        meta_group.setStyleSheet("background:#f0fff0; border-radius:4px;")
        tab_bak_layout.addWidget(meta_group)

        # --- Быстрая ротация .bak ---
        bak_group = QWidget()
        bak_layout = QVBoxLayout(bak_group)
        bak_layout.setContentsMargins(8, 8, 8, 8)
        bak_layout.addWidget(QLabel("<b>Быстрая ротация .bak1 — .bak5</b>"))
        bak_desc = QLabel(
            "При каждом сохранении файл films.json копируется в .bak1, "
            "предыдущий .bak1 сдвигается в .bak2 и так далее до .bak5.\n\n"
            "Это защита от единичных сбоев записи. "
            "При многократных ошибочных сохранениях все 5 копий могут быть перезаписаны."
        )
        bak_desc.setWordWrap(True)
        bak_layout.addWidget(bak_desc)
        bak_group.setStyleSheet("background:#f0f8ff; border-radius:4px;")
        tab_bak_layout.addWidget(bak_group)

        # --- Бэкап по дням .daily_ ---
        daily_group = QWidget()
        daily_layout = QVBoxLayout(daily_group)
        daily_layout.setContentsMargins(8, 8, 8, 8)
        daily_layout.addWidget(QLabel("<b>Бэкап по дням .daily_</b>"))
        daily_desc = QLabel(
            "Не чаще чем раз в 12 часов создаётся датированная копия:\n"
            "<b>films.json.daily_20260206_143000</b>\n\n"
            "Эти файлы НЕ затираются быстрой ротацией .bak1-.bak5.\n"
            "Хранятся 10 самых свежих копий (примерно 5 дней при постоянной работе).\n"
            "Промежуток между бэкапами может быть любым — "
            "если программа не запускалась месяц, предыдущий бэкап сохраняется."
        )
        daily_desc.setWordWrap(True)
        daily_layout.addWidget(daily_desc)
        daily_group.setStyleSheet("background:#fff8f0; border-radius:4px;")
        tab_bak_layout.addWidget(daily_group)

        # --- Аварийный бэкап .safe_ ---
        safe_group = QWidget()
        safe_layout = QVBoxLayout(safe_group)
        safe_layout.setContentsMargins(8, 8, 8, 8)
        safe_layout.addWidget(QLabel("<b>Аварийный бэкап .safe_</b>"))
        safe_desc = QLabel(
            "Если при сохранении обнаружена массовая потеря данных "
            "(больше 3 записей и больше 20% полей стали пустыми), "
            "программа автоматически сохраняет копию текущего хорошего файла:\n"
            "<b>films.json.safe_20260206_225700</b>\n\n"
            "Сохранение при этом продолжается, но копия хороших данных "
            "остаётся нетронутой для восстановления."
        )
        safe_desc.setWordWrap(True)
        safe_layout.addWidget(safe_desc)
        safe_group.setStyleSheet("background:#fff0f0; border-radius:4px;")
        tab_bak_layout.addWidget(safe_group)

        # --- Где хранятся ---
        path_group = QWidget()
        path_layout = QVBoxLayout(path_group)
        path_layout.setContentsMargins(8, 8, 8, 8)
        path_layout.addWidget(QLabel("<b>Расположение файлов</b>"))
        path_desc = QLabel(
            f"Основной конфиг: <b>config_films/films.json</b>\n"
            f"Бэкапы .bak/.daily_/.safe_: <b>config_films/</b>\n"
            f"_meta.json: в папке аудио дорожки каждого фильма\n"
            f"Настройки: <b>config_settings/settings.json</b>"
        )
        path_desc.setWordWrap(True)
        path_layout.addWidget(path_desc)
        path_group.setStyleSheet("background:#f8f8f8; border-radius:4px;")
        tab_bak_layout.addWidget(path_group)

        tab_bak_layout.addStretch()
        tabs.addTab(tab_backup, "Бэкапы")

        # === ВКЛАДКА 5: КАК ПОЛЬЗОВАТЬСЯ ===
        tab_howto = QWidget()
        tab_howto_scroll = QScrollArea()
        tab_howto_scroll.setWidgetResizable(True)
        tab_howto_scroll.setWidget(tab_howto)
        howto_layout = QVBoxLayout(tab_howto)
        howto_layout.setSpacing(8)
        howto_layout.setContentsMargins(12, 12, 12, 12)

        def _howto_section(title, text, bg="#f8f8ff"):
            grp = QWidget()
            gl = QVBoxLayout(grp)
            gl.setContentsMargins(10, 8, 10, 8)
            hdr = QLabel(f"<b>{title}</b>")
            hdr.setStyleSheet("font-size:11pt;")
            gl.addWidget(hdr)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setStyleSheet("padding-left:6px;")
            gl.addWidget(body)
            grp.setStyleSheet(f"background:{bg}; border-radius:4px;")
            return grp

        howto_header = QLabel("Как получить фильм с новой аудио дорожкой")
        howto_header.setFont(QFont("Arial", 12, QFont.Bold))
        howto_layout.addWidget(howto_header)

        howto_layout.addWidget(_howto_section(
            "1. Настроить пути",
            "Вверху окна в блоке «Пути» указать 6 путей:\n"
            "- 🎵 Папка аудио (источник) — корневая папка, внутри которой будут подпапки "
            "для каждого фильма (каждая подпапка = одна аудио дорожка)\n"
            "- 🎵 Папка куда скачиваются аудио дорожки — папка куда торрент-клиент "
            "скачивает архивы с аудио. Нужна только если НЕ используется qBittorrent API. "
            "Если API включён — торренты скачиваются прямо в папку фильма, и эта папка не используется\n"
            "- 📽️ Папка видео (источник) — папка с исходными видео файлами (MKV)\n"
            "- 📽️ Папка результата — куда перемещать готовые файлы после проверки\n"
            "- 📽️ Папка тест — куда сохраняются файлы после обработки для проверки\n"
            "- mkvmerge.exe — путь к mkvmerge.exe (скачать MKVToolNix с mkvtoolnix.download)\n\n"
            "Кнопка «...» рядом с каждым полем открывает выбор папки/файла.",
            "#f0f8ff"))

        howto_layout.addWidget(_howto_section(
            "2. Настройки по умолчанию",
            "В блоке «Настройки по умолчанию» задать:\n"
            "- Имя новой дорожки в файле — название аудио дорожки в MKV "
            "(например: ATMOS, AC3, DTS)\n"
            "- Аффикс выходного файла — текст, который добавится к имени готового файла: "
            "префикс и суффикс\n"
            "  Пример: суффикс «_ATMOS» → Фильм_ATMOS.mkv",
            "#f8f0ff"))

        howto_layout.addWidget(_howto_section(
            "3. Создать папку для аудио дорожки",
            "Нажать зелёную кнопку «Создать папку для аудио дорожки».\n"
            "Откроется форма, в которой можно заполнить:\n\n"
            "Обязательно:\n"
            "- Название папки — имя подпапки (обычно «Название фильма Год»)\n\n"
            "Необязательно (можно заполнить позже в таблице):\n"
            "- Заметки — текст для .txt файла (варианты задержек, источник и т.д.)\n"
            "- Пароль — пароль от зашифрованного архива с аудио\n"
            "- Выбрать архив — файл .rar/.7z будет ПЕРЕМЕЩЁН в созданную папку\n"
            "- Задержка (мс) — начальная задержка аудио относительно видео\n"
            "- Выбрать торрент файл — .torrent будет перемещён в папку\n"
            "- Ссылки: торрент аудио, форум Russdub\n"
            "- Данные о фильме: название, год, постер, кинопоиск, торрент видео, видео файл\n\n"
            "После нажатия «Создать» — папка появится в 🎵 Папка аудио (источник), "
            "и в таблице добавится новая строка с данными из формы.",
            "#e8f8e8"))

        howto_layout.addWidget(_howto_section(
            "4. Распаковать архив с аудио",
            "Если аудио пришло как зашифрованный архив (RAR/7z):\n\n"
            "- Кликните на строку фильма — откроется вкладка с деталями\n"
            "- Введите пароль архива в поле «Пароль» (если не ввели при создании)\n"
            "- Нажмите кнопку распаковки архива на вкладке\n"
            "- После распаковки аудио файл появится в папке — программа его подхватит\n"
            "- Кнопкой «Удалить архив» можно убрать архив, чтобы не занимал место\n\n"
            "Если аудио уже распаковано — этот шаг не нужен.",
            "#fff8f0"))

        howto_layout.addWidget(_howto_section(
            "5. Выбрать видео файл",
            "В колонке «Видео файл (источник)» выбрать из выпадающего списка "
            "нужный видео файл из 📽️ Папка видео (источник).\n\n"
            "Список содержит все видео файлы из этой папки. "
            "Если нужного файла нет — убедитесь что он лежит в папке "
            "📽️ Папка видео (источник) и нажмите «👀 Сканировать все папки».",
            "#f0fff0"))

        howto_layout.addWidget(_howto_section(
            "6. Указать задержку аудио",
            "Задержка (в миллисекундах) — сдвиг аудио относительно видео.\n\n"
            "- Положительное значение: аудио сдвигается вперёд\n"
            "- Отрицательное значение: аудио сдвигается назад\n"
            "- Нажмите галочку (✓) рядом с задержкой, чтобы пометить "
            "правильную задержку для выбранного видео файла источника\n\n"
            "Несколько вариантов задержки:\n"
            "Нажмите «+» рядом с полем задержки — появятся дополнительные поля. "
            "Каждая задержка станет отдельной аудио дорожкой в готовом MKV.\n"
            "Дорожки будут названы по шаблону: задержка_имя, например:\n"
            "  0_ATMOS,  100_ATMOS,  -50_ATMOS\n"
            "(где ATMOS — значение поля «Имя новой дорожки в файле»)",
            "#fff0f8"))

        howto_layout.addWidget(_howto_section(
            "7. Заполнить TXT заметки",
            "В каждой папке аудио дорожки есть .txt файл — "
            "его содержимое видно в текстовом редакторе внизу вкладки фильма.\n\n"
            "Рекомендуется записывать:\n"
            "- Все испробованные варианты задержек и результаты\n"
            "- Источник аудио (откуда скачана дорожка)\n"
            "- Формат и качество (Atmos, TrueHD, AC3 и т.д.)\n"
            "- Заметки: проблемы со звуком, рассинхрон на конкретных сценах\n\n"
            "TXT сохраняется автоматически при редактировании.",
            "#fffff0"))

        howto_layout.addWidget(_howto_section(
            "8. Обработать (mkvmerge)",
            "Когда аудио, видео и задержка заданы — строка получит статус "
            "«К обработке» (синий фон).\n\n"
            "- Нажмите кнопку «Обработать» в строке фильма\n"
            "- Программа вызовет mkvmerge: вставит аудио дорожку в видео "
            "с указанной задержкой\n"
            "- Результат сохраняется в 📽️ Папка тест\n"
            "- Имя файла: {префикс}{имя видео}{суффикс}.mkv\n"
            "  Пример: Фильм_ATMOS.mkv",
            "#f0fff8"))

        howto_layout.addWidget(_howto_section(
            "9. Проверить и переместить в результат",
            "Готовый файл попадает в 📽️ Папка тест (статус «В тесте»).\n\n"
            "- Откройте файл в видеоплеере, проверьте синхронизацию звука\n"
            "- Если несколько дорожек — переключайте их, найдите лучшую задержку\n"
            "- Если всё ОК — нажмите «В Результат» (файл переместится в "
            "📽️ Папка результата)\n"
            "- Если не ОК — удалите тестовый файл, измените задержку, "
            "обработайте заново",
            "#f8fff0"))

        howto_layout.addStretch()

        # === ВКЛАДКА: qBittorrent API ===
        tab_qbt = QWidget()
        tab_qbt_scroll = QScrollArea()
        tab_qbt_scroll.setWidgetResizable(True)
        tab_qbt_scroll.setWidget(tab_qbt)
        qbt_layout = QVBoxLayout(tab_qbt)
        qbt_layout.setSpacing(8)
        qbt_layout.setContentsMargins(12, 12, 12, 12)

        _qbt_ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "qbittorrent_icon.png")
        _qbt_ico = f'<img src="{_qbt_ico_path}" width="20" height="20">' if os.path.isfile(_qbt_ico_path) else ""
        qbt_header = QLabel(f'Скачивание аудио дорожек через {_qbt_ico} qBittorrent')
        qbt_header.setTextFormat(Qt.RichText)
        qbt_header.setFont(QFont("Arial", 12, QFont.Bold))
        qbt_layout.addWidget(qbt_header)

        def _qbt_section(title, text, bg="#f0f8ff"):
            grp = QWidget()
            gl = QVBoxLayout(grp)
            gl.setContentsMargins(10, 8, 10, 8)
            hdr = QLabel(f"<b>{title}</b>")
            hdr.setStyleSheet("font-size:11pt;")
            gl.addWidget(hdr)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setStyleSheet("padding-left:6px;")
            gl.addWidget(body)
            grp.setStyleSheet(f"background:{bg}; border-radius:4px;")
            return grp

        qbt_layout.addWidget(_qbt_section(
            "Что это?",
            "Кнопка «Скачать» в панели действий позволяет массово добавлять торренты "
            "в qBittorrent для скачивания аудио дорожек.\n\n"
            "Два источника данных:\n"
            "• Торрент-файл (.torrent) — файл в папке фильма\n"
            "• Ссылка на торрент — поле «Торрент аудио» в данных фильма\n\n"
            "Кнопка доступна для записей без аудио и без архива, "
            "у которых есть хотя бы один из источников."))

        qbt_layout.addWidget(_qbt_section(
            "Зачем нужен API?",
            "Без API: торрент открывается через os.startfile() → qBittorrent показывает диалог "
            "с папкой по умолчанию. Нужно ВРУЧНУЮ менять папку для каждого торрента.\n\n"
            "С API: торрент добавляется СРАЗУ в нужную папку (папка фильма), "
            "без диалогов и ручного выбора. Скачивание начинается мгновенно.",
            bg="#e8ffe8"))

        qbt_layout.addWidget(_qbt_section(
            "Как включить API",
            "1. Откройте qBittorrent\n"
            "2. Меню: Инструменты → Настройки → Веб-интерфейс\n"
            "3. Поставьте галку «Веб-интерфейс (удалённое управление)»\n"
            "4. Порт: 8080 (по умолчанию)\n"
            "5. Поставьте галку «Пропускать аутентификацию клиентов с localhost»\n"
            "6. Задайте любой пароль (минимум 6 символов) — он нужен только для сохранения настроек\n"
            "7. Нажмите «Применить» → «OK»",
            bg="#fffff0"))

        qbt_layout.addWidget(_qbt_section(
            "Как работает скачивание",
            "Если есть .torrent файл:\n"
            "   Сразу добавляется в клиент, скачивание начнётся автоматически.\n\n"
            "Если есть только ссылка:\n"
            "   Скачиваем .torrent по ссылке → сохраняем в папку фильма →\n"
            "   добавляем в клиент → скачивание начнётся автоматически.\n\n"
            "Если установлен qBittorrent + включён веб-интерфейс:\n"
            "   Скачивание в папку фильма.\n\n"
            "Если другой клиент или веб-интерфейс не включён:\n"
            "   Скачивание в общую папку торрент-клиента."))

        qbt_layout.addWidget(_qbt_section(
            "Настройки подключения",
            "По умолчанию используется http://localhost:8080.\n"
            "Для изменения добавьте в config_settings/settings.json:\n\n"
            "  \"qbt_url\": \"http://localhost:8080\"\n"
            "  \"qbt_user\": \"\"         (пустой если localhost без авторизации)\n"
            "  \"qbt_password\": \"\"  (пустой если localhost без авторизации)",
            bg="#f8f0ff"))

        qbt_layout.addStretch()
        _qbt_tab_idx = tabs.addTab(tab_qbt_scroll, "qBittorrent")
        if os.path.isfile(_qbt_ico_path):
            tabs.setTabIcon(_qbt_tab_idx, QIcon(_qbt_ico_path))

        tabs.insertTab(0, tab_howto_scroll, "Как пользоваться")
        tabs.setCurrentIndex(0)

        layout.addWidget(tabs, 1)

        # Кнопка закрыть
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setToolTip("Закрыть окно справки")
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _check_all_statuses(self):
        old_count = len(self.rows)
        old_names = {r["folder_name"] for r in self.rows}

        # Пересканировать папки (только данные, БЕЗ перестроения таблицы)
        self._scan_audio_silent()
        self.setUpdatesEnabled(False)
        new_names = {af["name"] for af in self.audio_folders}

        # Удалить исчезнувшие строки
        removed = old_names - new_names
        for fn in removed:
            self._remove_single_row(fn)
            self.log(f"[SCAN] Строка удалена: {fn}")

        # Принудительно закрыть вкладки для папок которых нет в таблице
        row_names = {r["folder_name"] for r in self.rows}
        for fn in list(self._open_tabs.keys()):
            if fn not in row_names:
                tab_idx = self._find_tab_index(fn)
                if tab_idx >= 0:
                    self.tab_widget.removeTab(tab_idx)
                del self._open_tabs[fn]
                self.log(f"[SCAN] Вкладка закрыта: {fn}")

        # Добавить новые строки (без form_data — это не из модалки)
        added = new_names - old_names
        existing_names = {r["folder_name"] for r in self.rows}
        for af in self.audio_folders:
            if af["name"] in added and af["name"] not in existing_names:
                self._add_single_row(af)

        # Обновить аудио файлы и комбобоксы для существующих строк (могли измениться)
        af_map = {af["name"]: af for af in self.audio_folders}
        for r in self.rows:
            af = af_map.get(r["folder_name"])
            if af:
                r["audio_files"] = af["files"]
                r["folder_path"] = af["path"]
                # Обновить audio_combo (удалённые/новые файлы)
                old_audio_sel = self._audio_filename(r)
                r["audio_combo"].blockSignals(True)
                if af["files"]:
                    self._populate_audio_combo(r["audio_combo"], af["files"], af["path"])
                    if old_audio_sel and old_audio_sel in af["files"]:
                        for i in range(r["audio_combo"].count()):
                            if r["audio_combo"].itemData(i, Qt.UserRole) == old_audio_sel:
                                r["audio_combo"].setCurrentIndex(i)
                                break
                    r["audio_combo"].setEnabled(True)
                    r["audio_combo"].setStyleSheet("")
                    r["audio_combo"].setToolTip("Основной аудио файл — будет вставлен в видео при обработке\nРазмер файла показан в скобках")
                else:
                    r["audio_combo"].clear()
                    r["audio_combo"].addItem("⚠ Нет аудио файлов", "")
                    r["audio_combo"].setEnabled(False)
                    r["audio_combo"].setStyleSheet("color: red;")
                    r["audio_combo"].setToolTip("В папке нет аудио файлов — добавьте аудио дорожку")
                r["audio_combo"].blockSignals(False)
                # Обновить starter_combo и ender_combo
                main_file = self._audio_filename(r)
                for combo_key, fname_fn in (("starter_combo", self._starter_filename), ("ender_combo", self._ender_filename)):
                    sc = r.get(combo_key)
                    if sc:
                        old_val = fname_fn(r)
                        sc.blockSignals(True)
                        self._populate_starter_combo(sc, af["files"], af["path"], exclude_file=main_file)
                        if old_val and old_val in af["files"] and old_val != main_file:
                            for i in range(sc.count()):
                                if sc.itemData(i, Qt.UserRole) == old_val:
                                    sc.setCurrentIndex(i)
                                    break
                        sc.setEnabled(len(af["files"]) > 1)
                        sc.blockSignals(False)
                # Обновить аудио комбобокс на вкладке если открыта
                fn = r["folder_name"]
                if fn in self._open_tabs:
                    tw = self._open_tabs[fn].get("widgets", {})
                    tab_audio = tw.get("audio_combo")
                    if tab_audio:
                        tab_audio.blockSignals(True)
                        old_tab_sel = tab_audio.currentData(Qt.UserRole) or ""
                        tab_audio.clear()
                        if af["files"]:
                            _thr = self._AUDIO_MAIN_THRESHOLD
                            for f in af["files"]:
                                try:
                                    _fsz = os.path.getsize(os.path.join(af["path"], f))
                                except OSError:
                                    _fsz = 0
                                if _fsz >= _thr:
                                    tab_audio.addItem(self._format_audio_size(af["path"], f), f)
                            target = old_tab_sel if old_tab_sel in af["files"] else (old_audio_sel if old_audio_sel in af["files"] else "")
                            if target:
                                for i in range(tab_audio.count()):
                                    if tab_audio.itemData(i, Qt.UserRole) == target:
                                        tab_audio.setCurrentIndex(i)
                                        break
                            tab_audio.setEnabled(tab_audio.count() > 0)
                        else:
                            tab_audio.addItem("⚠ Нет аудио файлов", "")
                            tab_audio.setEnabled(False)
                        tab_audio.blockSignals(False)
                    # Обновить кнопку "Сканировать дорожки" на вкладке
                    _scan_btn = tw.get("scan_tracks_btn")
                    if _scan_btn:
                        _cur_a = tab_audio.currentData(Qt.UserRole) if tab_audio else ""
                        _a_ok = bool(_cur_a and not _cur_a.startswith("\u26A0") and
                                     os.path.isfile(os.path.join(r.get("folder_path", ""), _cur_a)))
                        _scan_btn.setEnabled(_a_ok)
                    # Обновить starter_combo и ender_combo на вкладке
                    main_file = self._audio_filename(r)
                    for tab_key in ("starter_combo", "ender_combo"):
                        tab_combo = tw.get(tab_key)
                        if tab_combo:
                            tab_combo.blockSignals(True)
                            old_tab_val = tab_combo.currentData(Qt.UserRole) or ""
                            self._populate_starter_combo(tab_combo, af["files"], af["path"], exclude_file=main_file)
                            if old_tab_val and old_tab_val in af["files"] and old_tab_val != main_file:
                                for i in range(tab_combo.count()):
                                    if tab_combo.itemData(i, Qt.UserRole) == old_tab_val:
                                        tab_combo.setCurrentIndex(i)
                                        break
                            tab_combo.setEnabled(len(af["files"]) > 1)
                            tab_combo.blockSignals(False)

        # Пересканировать видео
        vp = self.video_path_edit.text()
        if vp and os.path.isdir(vp):
            self.video_files = [f for f in os.listdir(vp) if f.lower().endswith(VIDEO_EXTS)]
            used = {r["video_combo"].currentText() for r in self.rows if r["video_combo"].currentText() and r["video_combo"].currentText() != "— снять выбор —"}
            self.available_videos = [f for f in self.video_files if f not in used]
            self._update_all_video_combos()
            self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")
            # Обновить video_full_path для всех назначенных файлов (кроме ручных)
            for r in self.rows:
                if r.get("video_manual"):
                    continue  # Ручные пути не трогаем
                vn = r["video_combo"].currentText()
                if vn and vn != "— снять выбор —":
                    new_path = os.path.join(vp, vn)
                    if os.path.exists(new_path):
                        r["video_full_path"] = new_path

        # Обновить статусы ВСЕХ строк in-place (без перестроения)
        for r in self.rows:
            self._check_row_status(r)
            # Восстановить NEW подсветку поверх стандартного статуса
            if r.get("is_new"):
                r["status_lbl"].setText("✦ NEW")
                r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
                r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
                self._set_row_bg(r, COLOR_NEW)

        # Пересортировать если были изменения (с защитой от лишнего rebuild)
        if added or removed:
            self._sort_table()

        self.setUpdatesEnabled(True)
        self._update_counts()
        self._update_process_button()
        self._update_archive_btn_count()
        self._update_batch_buttons()
        self.schedule_autosave()
        new_count = len(self.rows)
        diff = new_count - old_count
        if diff != 0:
            self.log(f"Сканирование: было {old_count}, стало {new_count} (добавлено: {len(added)}, удалено: {len(removed)})")
        else:
            self.log("Статусы обновлены")

    def _update_counts(self):
        tp = self.test_path_edit.text()
        if tp and os.path.isdir(tp):
            self.test_count_lbl.setText(f"Тест файлов: {len([f for f in os.listdir(tp) if f.lower().endswith('.mkv')])}")
        op = self.output_path_edit.text()
        if op and os.path.isdir(op):
            self.output_count_lbl.setText(f"Готовых файлов: {len([f for f in os.listdir(op) if f.lower().endswith('.mkv')])}")
        self._update_paths_summary()

    def _update_process_button(self):
        """Обновить кнопку обработки (заглушка, кнопка удалена)."""
        pass

    # ──────────────────────────────────
    #  Батч-панель: выбор и массовые действия
    # ──────────────────────────────────
    def _update_reset_new_btn(self, _=None):
        """Обновить кнопку 'Сбросить NEW' — активна ТОЛЬКО если выделены чекбоксом записи со статусом NEW."""
        # Считаем выбранные чекбоксом NEW записи
        selected_new = sum(1 for r in self.rows if r["select_cb"].isChecked() and r.get("is_new") and not self.table.isRowHidden(r["row_index"]))
        total_new = sum(1 for r in self.rows if r.get("is_new"))
        enabled = selected_new > 0
        self.reset_new_btn.setEnabled(enabled)
        # Обновить текст — на неактивной кнопке только название, без цифр
        if selected_new > 0:
            self.reset_new_btn.setText(f"📌 Сбросить NEW ({selected_new})")
        else:
            self.reset_new_btn.setText("📌 Сбросить NEW")
        if enabled:
            self.reset_new_btn.setStyleSheet(
                "QPushButton{background-color:#ffd699;} "
                "QPushButton:hover{background-color:#f0be60;}")
            self.reset_new_preview_btn.show()
            self.reset_new_preview_btn.setStyleSheet(
                "QPushButton{background-color:#ffd699; border-left:1px solid #888;} "
                "QPushButton:hover{background-color:#f0be60;} "
                "QPushButton:checked{background-color:#ff8c00; border:3px solid #cc3300; border-radius:2px;}")
        else:
            self.reset_new_btn.setStyleSheet("")
            self.reset_new_preview_btn.hide()

    def _on_select_all(self, checked):
        for r in self.rows:
            if self.table.isRowHidden(r["row_index"]):
                continue
            r["select_cb"].blockSignals(True)
            r["select_cb"].setChecked(checked)
            r["select_cb"].blockSignals(False)
        self._update_batch_buttons()

    def _calc_row_size(self, r, bk, vp, op, tp):
        """Вычислить размер файла (в байтах) для кнопки bk и строки r."""
        try:
            if bk == "btn_del_archive" or bk == "btn_unrar":
                path = r.get("archive_file", "")
                if path and not os.path.isabs(path):
                    path = os.path.join(r["folder_path"], path)
                if path and os.path.isfile(path):
                    return os.path.getsize(path)
            elif bk == "btn_del_test" or bk == "btn_to_res":
                out_name = r["output_entry"].text()
                if tp and out_name:
                    path = os.path.join(tp, out_name)
                    if os.path.isfile(path):
                        return os.path.getsize(path)
            elif bk == "btn_del_src":
                path = r.get("video_full_path") or ""
                if not path:
                    vname = r["video_combo"].currentText()
                    if vp and vname and vname != "— снять выбор —":
                        path = os.path.join(vp, vname)
                if path and os.path.isfile(path):
                    return os.path.getsize(path)
            elif bk == "btn_del_res":
                out_name = r["output_entry"].text()
                if op and out_name:
                    path = os.path.join(op, out_name)
                    if os.path.isfile(path):
                        return os.path.getsize(path)
        except:
            pass
        return 0

    def _update_batch_buttons(self):
        if not hasattr(self, 'batch_btns'):
            return
        counts = {k: 0 for k in self.batch_btns}
        sizes = {k: 0 for k in self.batch_btns}
        vp = self.video_path_edit.text()
        op = self.output_path_edit.text()
        tp = self.test_path_edit.text()

        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        film_mode = current_tab > 0

        if film_mode:
            # === РЕЖИМ ФИЛЬМА: данные только о текущем фильме ===
            fn = self.tab_widget.tabText(current_tab)
            r = self._find_row(fn)
            self.batch_bar_widget.setTitle(f"Действия для фильма: {fn}")
            self.batch_bar_widget.setToolTip(f"Действия для фильма «{fn}»")

            if r:
                for bk in counts:
                    if not r[bk].isHidden():
                        if bk == "btn_play":
                            # Количество видео-вариантов (основной + extra_videos)
                            extra = r.get("extra_videos", [])
                            counts[bk] = 1 + len([ev for ev in extra if ev.get("video") or ev.get("video_full_path")])
                        else:
                            counts[bk] = 1
                        sizes[bk] = self._calc_row_size(r, bk, vp, op, tp)

            # Скрыть ВСЕ кнопки-глаз (preview) в режиме фильма
            for pb in self.batch_preview_btns.values():
                pb.hide()
            # Показать кнопки "Старые бекапы", "Переименовать" и "Удалить папку" для текущего фильма
            if hasattr(self, 'tab_old_backups_btn'):
                _fp = r["folder_path"] if r else ""
                _old_bk = self._list_old_backups(_fp) if _fp else []
                _ob_cnt = len(_old_bk)
                self.tab_old_backups_btn.setText(f"Старые бекапы ({_ob_cnt})" if _ob_cnt else "Старые бекапы")
                self.tab_old_backups_btn.setEnabled(_ob_cnt > 0)
                self.tab_old_backups_btn.setVisible(True)
            if hasattr(self, 'tab_copy_btn'):
                self.tab_copy_btn.setToolTip(f"Копировать папку «{fn}»\nСоздать новую папку с теми же настройками")
                self.tab_copy_btn.setVisible(True)
            if hasattr(self, 'tab_rename_btn'):
                self.tab_rename_btn.setToolTip(f"Переименовать папку «{fn}»\nОткроет диалог для ввода нового имени")
                self.tab_rename_btn.setVisible(True)
            if hasattr(self, 'tab_delfolder_btn'):
                # Пересчитать размер папки
                _fp = r["folder_path"] if r else ""
                _fb = 0
                if _fp:
                    try:
                        for _root, _dirs, _files in os.walk(_fp):
                            for _f in _files:
                                try: _fb += os.path.getsize(os.path.join(_root, _f))
                                except OSError: pass
                    except OSError: pass
                if _fb >= 1024 ** 3: _fsz = f"{_fb / (1024 ** 3):.2f} ГБ"
                elif _fb >= 1024 ** 2: _fsz = f"{_fb / (1024 ** 2):.0f} МБ"
                elif _fb > 0: _fsz = f"{_fb / 1024:.0f} КБ"
                else: _fsz = ""
                self.tab_delfolder_btn.setText(_fsz if _fsz else "")
                self.tab_delfolder_btn.setToolTip(f"Безвозвратно удалить папку «{fn}» и все файлы в ней\n"
                                                  f"(аудио, архивы, txt, _meta.json и т.д.)\nПуть: {_fp}\n"
                                                  "Запись также будет удалена из таблицы.")
                self.tab_delfolder_btn.setVisible(True)
        else:
            # === РЕЖИМ ТАБЛИЦЫ: существующая логика ===
            self.batch_bar_widget.setTitle("Действия для выбранных:")
            self.batch_bar_widget.setToolTip("Действия для строк, выбранных чекбоксами ☑ в первой колонке.\n"
                                      "Клик по заголовку ☑ — выбрать/снять все.")
            # Скрыть кнопки "Старые бекапы", "Копировать", "Переименовать" и "Удалить папку" (видны только в режиме фильма)
            if hasattr(self, 'tab_old_backups_btn'):
                self.tab_old_backups_btn.setVisible(False)
            if hasattr(self, 'tab_copy_btn'):
                self.tab_copy_btn.setVisible(False)
            if hasattr(self, 'tab_rename_btn'):
                self.tab_rename_btn.setVisible(False)
            if hasattr(self, 'tab_delfolder_btn'):
                self.tab_delfolder_btn.setVisible(False)

            for r in self.rows:
                if self.table.isRowHidden(r["row_index"]):
                    continue
                if not r["select_cb"].isChecked():
                    continue
                for bk in counts:
                    if not r[bk].isHidden():
                        counts[bk] += 1
                        sizes[bk] += self._calc_row_size(r, bk, vp, op, tp)

        # === Обновление текста и стилей кнопок (общее для обоих режимов) ===
        for bk, btn in self.batch_btns.items():
            c = counts[bk]
            lbl = self._batch_labels[bk]
            bg_color = self._batch_colors.get(bk, "#cce5ff")
            size_str = ""
            if bk in ["btn_del_archive", "btn_del_test", "btn_del_src", "btn_del_res", "btn_to_res", "btn_unrar"] and sizes[bk] > 0:
                size_gb = sizes[bk] / (1024 ** 3)
                if size_gb >= 0.01:
                    size_str = f" {size_gb:.2f} ГБ"
                else:
                    size_mb = sizes[bk] / (1024 ** 2)
                    size_str = f" {size_mb:.0f} МБ"
            btn.setText(f"{lbl} ({c}){size_str}" if c else lbl)
            btn.setEnabled(c > 0)
            if bg_color == "#ffcccc":
                hover_bg = "#ff9999"
            elif bg_color == "#ccffcc":
                hover_bg = "#99ff99"
            elif bg_color == "#ffe4c4":
                hover_bg = "#ffc896"
            else:
                hover_bg = "#99ccff"
            btn.setStyleSheet(f"QPushButton{{background-color:{bg_color};}} QPushButton:hover{{background-color:{hover_bg};}} QPushButton:disabled{{background-color:{bg_color};}}")
            # Показать/скрыть preview — только в режиме таблицы
            if not film_mode:
                preview_btn = self.batch_preview_btns.get(bk)
                if preview_btn:
                    if c > 0:
                        preview_btn.show()
                        preview_btn.setStyleSheet(f"QPushButton{{background-color:{bg_color}; border-left:1px solid #888;}} QPushButton:hover{{background-color:{hover_bg};}} QPushButton:checked{{background-color:#ff8c00; border:3px solid #cc3300; border-radius:2px;}}")
                    else:
                        preview_btn.hide()

        # Обновить кнопку "Сбросить NEW"
        if film_mode:
            fn = self.tab_widget.tabText(current_tab)
            r = self._find_row(fn)
            is_new = bool(r.get("is_new")) if r else False
            self.reset_new_btn.setEnabled(is_new)
            self.reset_new_btn.setText(f"📌 Сбросить NEW" if is_new else "📌 Сбросить NEW")
            self.reset_new_preview_btn.hide()
        else:
            self._update_reset_new_btn()
        # Колонка Действия скрыта — пересчёт ширины не нужен

    def _count_video_audio_tracks(self, filepath):
        """Подсчитать аудио дорожки в видео файле через pymediainfo."""
        _init_mediainfo()
        if not HAS_MEDIAINFO or not MediaInfo:
            return 0
        try:
            mi = MediaInfo.parse(filepath)
            return sum(1 for t in mi.tracks if t.track_type == "Audio")
        except Exception:
            return 0

    def _scan_audio_tracks(self, filepath):
        """Получить список аудио дорожек через mkvmerge -J (точно совпадает с ID треков при обработке).

        Возвращает list of dict:
        [{"id": 0, "codec": "TrueHD", "channels": 8, "frequency": 48000,
          "label": "Track 0: TrueHD 7.1ch 48000Hz"}, ...]
        """
        mkvmerge = self.mkvmerge_path_edit.text()
        if not mkvmerge or not os.path.exists(mkvmerge):
            return self._scan_audio_tracks_mediainfo(filepath)
        try:
            result = subprocess.run(
                [mkvmerge, "-J", filepath],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode not in (0, 1):
                return self._scan_audio_tracks_mediainfo(filepath)
            info = json.loads(result.stdout)
            tracks = []
            for trk in info.get("tracks", []):
                if trk.get("type") != "audio":
                    continue
                tid = trk.get("id", 0)
                props = trk.get("properties", {})
                codec = trk.get("codec", "?")
                channels = props.get("audio_channels", 0)
                freq = props.get("audio_sampling_frequency", 0)
                # Человекочитаемый label
                if channels > 2:
                    ch_label = f"{channels - 1}.1" if channels in (6, 8) else f"{channels}ch"
                elif channels == 2:
                    ch_label = "Stereo"
                elif channels == 1:
                    ch_label = "Mono"
                else:
                    ch_label = ""
                freq_label = f"{freq}Hz" if freq else ""
                label = f"Track {tid}: {codec} {ch_label} {freq_label}".strip()
                tracks.append({
                    "id": tid, "codec": codec, "channels": channels,
                    "frequency": freq, "label": label,
                })
            return tracks
        except Exception as e:
            self.log(f"[TRACKS] Ошибка mkvmerge -J {os.path.basename(filepath)}: {e}")
            return self._scan_audio_tracks_mediainfo(filepath)

    def _scan_audio_tracks_mediainfo(self, filepath):
        """Fallback: сканирование через pymediainfo (может не разделять TrueHD+AC3)."""
        _init_mediainfo()
        if not HAS_MEDIAINFO or not MediaInfo:
            return []
        try:
            mi = MediaInfo.parse(filepath)
            tracks = []
            idx = 0
            for t in mi.tracks:
                if t.track_type != "Audio":
                    continue
                fmt = getattr(t, 'format', '?') or '?'
                channels = int(getattr(t, 'channel_s', 0) or 0)
                if channels > 2:
                    ch_label = f"{channels - 1}.1" if channels in (6, 8) else f"{channels}ch"
                elif channels == 2:
                    ch_label = "Stereo"
                elif channels == 1:
                    ch_label = "Mono"
                else:
                    ch_label = ""
                bitrate = int(getattr(t, 'bit_rate', 0) or 0)
                br_label = f"~{bitrate // 1000} kbps" if bitrate else ""
                label = f"Track {idx}: {fmt} {ch_label} {br_label}".strip()
                tracks.append({"id": idx, "codec": fmt, "channels": channels,
                               "frequency": 0, "label": label})
                idx += 1
            return tracks
        except Exception:
            return []

    @staticmethod
    def _auto_select_best_track(tracks):
        """Автовыбор: трек с наибольшим количеством каналов (= самый крупный)."""
        if not tracks:
            return 0
        if len(tracks) == 1:
            return tracks[0]["id"]
        best = max(tracks, key=lambda t: (t.get("channels", 0), t.get("frequency", 0)))
        return best["id"]

    def _populate_audio_tracks(self, fn):
        """Сканировать аудио файл и показать дорожки с чекбоксами на вкладке."""
        r = self._find_row(fn)
        if not r or fn not in self._open_tabs:
            return
        tw = self._open_tabs[fn]["widgets"]
        tracks_container = tw.get("tracks_container")
        tracks_layout = tw.get("tracks_layout")
        status_lbl = tw.get("tracks_status")
        if not tracks_container or not tracks_layout:
            return

        # Очистить старые виджеты
        for cb_w in tw.get("track_checkboxes", []):
            cb_w.setParent(None); cb_w.deleteLater()
        tw["track_checkboxes"] = []

        audio_name = self._audio_filename(r)
        if not audio_name or audio_name.startswith("⚠"):
            tracks_container.setVisible(False)
            if status_lbl:
                status_lbl.setText("")
            return

        # Проверить кэш
        cache = r.get("audio_tracks_cache", {})
        if audio_name in cache:
            tracks = cache[audio_name]
        else:
            audio_path = os.path.join(r["folder_path"], audio_name)
            if not os.path.exists(audio_path):
                tracks_container.setVisible(False)
                if status_lbl:
                    status_lbl.setText("Файл не найден")
                return
            if status_lbl:
                status_lbl.setText("Сканирование...")
            QApplication.processEvents()
            tracks = self._scan_audio_tracks(audio_path)
            if "audio_tracks_cache" not in r:
                r["audio_tracks_cache"] = {}
            r["audio_tracks_cache"][audio_name] = tracks

        if not tracks:
            tracks_container.setVisible(False)
            if status_lbl:
                status_lbl.setText("Не удалось определить дорожки")
            return

        # Восстановить сохранённые выбранные треки или автовыбор
        saved_sel = r.get("selected_audio_tracks")
        if saved_sel is None:
            # Автовыбор — только самая крупная
            best_tid = self._auto_select_best_track(tracks)
            saved_sel = [best_tid]
            r["selected_audio_tracks"] = saved_sel

        for t in tracks:
            cb = QCheckBox(t["label"])
            cb.setToolTip(f"Включить дорожку {t['id']} ({t.get('codec','?')}) в результат")
            cb.setChecked(t["id"] in saved_sel)
            cb.toggled.connect(lambda checked, tid=t["id"], f=fn: self._on_track_cb_toggled(f, tid, checked))
            tracks_layout.addWidget(cb)
            tw["track_checkboxes"].append(cb)

        tracks_container.setVisible(True)
        if status_lbl:
            checked_n = sum(1 for t in tracks if t["id"] in saved_sel)
            status_lbl.setText(f"Дорожек: {len(tracks)}, выбрано: {checked_n}  •  Выбранные дорожки имеют приоритет")
        # Обновить краткую сводку в строке кнопки сканирования
        summary_fn = tw.get("update_tracks_summary")
        if summary_fn:
            summary_fn()

    def _on_track_cb_toggled(self, fn, tid, checked):
        """Обработка переключения чекбокса дорожки."""
        r = self._find_row(fn)
        if not r:
            return
        sel = r.get("selected_audio_tracks") or []
        if checked and tid not in sel:
            sel.append(tid)
        elif not checked and tid in sel:
            sel.remove(tid)
        r["selected_audio_tracks"] = sel
        # Обновить статус
        if fn in self._open_tabs:
            tw = self._open_tabs[fn]["widgets"]
            status_lbl = tw.get("tracks_status")
            if status_lbl:
                cache = r.get("audio_tracks_cache", {})
                audio_name = self._audio_filename(r)
                total = len(cache.get(audio_name, []))
                status_lbl.setText(f"Дорожек: {total}, выбрано: {len(sel)}  •  Выбранные дорожки имеют приоритет")
            update_fn = tw.get("update_audio_status")
            if update_fn:
                update_fn()
            summary_fn = tw.get("update_tracks_summary")
            if summary_fn:
                summary_fn()
        self.schedule_autosave()

    def _force_rescan_tracks(self, fn):
        """Принудительно пересканировать треки (сбросить кэш)."""
        r = self._find_row(fn)
        if not r:
            return
        audio_name = self._audio_filename(r)
        cache = r.get("audio_tracks_cache", {})
        if audio_name in cache:
            del cache[audio_name]
        r["selected_audio_tracks"] = None  # Сбросить выбор → автовыбор
        self._populate_audio_tracks(fn)

    def _show_batch_preview(self, btn_key):
        """Отфильтровать таблицу — показать только записи которые будут обработаны. Повторный клик — сброс."""
        self.log(f"[PREVIEW] Клик на {btn_key}")
        # Если уже показан этот preview — сбросить
        if getattr(self, '_active_preview_key', None) == btn_key:
            self._clear_batch_preview()
            return
        # Сбросить предыдущий preview если был
        self._clear_batch_preview()

        checked = [r for r in self.rows if r["select_cb"].isChecked() and not self.table.isRowHidden(r["row_index"])]
        self.log(f"[PREVIEW] Выбрано чекбоксами: {len(checked)}")
        if not checked:
            self.log("[PREVIEW] Нет выбранных записей — выбери строки чекбоксами ☑")
            return
        targets = [r for r in checked if not r[btn_key].isHidden()]
        self.log(f"[PREVIEW] Подходит для действия: {len(targets)}")
        if not targets:
            self.log("[PREVIEW] Нет записей для этого действия")
            return

        # Запомнить активный preview
        self._active_preview_key = btn_key
        self._preview_rows = targets
        target_set = set(id(r) for r in targets)

        # Скрыть все строки кроме targets
        for r in self.rows:
            if id(r) in target_set:
                self.table.setRowHidden(r["row_index"], False)
                r["_preview_active"] = True
            else:
                self.table.setRowHidden(r["row_index"], True)

        # Установить состояние checked для кнопки глаз
        if btn_key in self.batch_preview_btns:
            self.batch_preview_btns[btn_key].setChecked(True)

        lbl = self._batch_labels.get(btn_key, "действие")
        self._update_rows_count()
        self.log(f"[PREVIEW] «{lbl}»: показано {len(targets)} записей. Повторный клик 👁 — сброс.")

    def _clear_batch_preview(self):
        """Сбросить фильтр предпросмотра — показать все строки."""
        if not getattr(self, '_active_preview_key', None):
            return
        # Показать все строки
        for r in self.rows:
            r.pop("_preview_active", None)
            self.table.setRowHidden(r["row_index"], False)
        # Сбросить checked состояние всех кнопок глаз
        for btn in self.batch_preview_btns.values():
            btn.setChecked(False)
        self.reset_new_preview_btn.setChecked(False)
        # Сбросить кнопки фильтрации по статусу
        for btn in self._status_filter_btns.values():
            btn.setChecked(False)
        self._active_preview_key = None
        self._preview_rows = []
        # Применить текущий фильтр поиска если есть
        self._apply_filter()
        self._update_status_filter_counts()
        self.log("[PREVIEW] Фильтр сброшен — показаны все записи")

    def _show_status_filter_settings(self):
        """Показать меню с чекбоксами для настройки видимости кнопок фильтрации."""
        menu = QMenu(self)
        for key, btn in self._status_filter_btns.items():
            label = btn.text().split(" (")[0]
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(btn.isVisible())
            action.toggled.connect(lambda vis, b=btn: self._toggle_filter_btn_vis(b, vis))
        menu.exec(self._status_settings_btn.mapToGlobal(
            QPoint(0, self._status_settings_btn.height())))

    def _toggle_filter_btn_vis(self, btn, visible):
        """Переключить видимость кнопки фильтрации и сохранить настройку."""
        btn.setVisible(visible)
        hidden = [k for k, b in self._status_filter_btns.items() if not b.isVisible()]
        self.config["hidden_status_buttons"] = hidden
        self.schedule_autosave()

    def _match_custom_filter(self, r, fkey):
        """Проверить запись на соответствие произвольному фильтру."""
        if fkey == "no_audio_no_archive":
            has_audio = self._has_main_audio(r)  # >= 1 ГБ
            has_archive = bool(r.get("archive_file"))
            return not has_audio and not has_archive
        elif fkey == "no_forum_url":
            fe = r.get("forum_entry")
            return not fe or not fe.text().strip()
        return False

    def _filter_matches(self, r, key):
        """Проверить соответствие записи фильтру по ключу."""
        if key == "new":
            return bool(r.get("is_new"))
        elif key.startswith("text:"):
            return r["status_lbl"].text() == key[5:]
        elif key.startswith("sp:"):
            return r.get("sort_priority", 1) == int(key[3:])
        elif key.startswith("custom:"):
            return self._match_custom_filter(r, key[7:])
        return False

    def _on_status_filter(self, filter_key):
        """Единая фильтрация по статусу/группе/произвольному условию."""
        self._update_status_filter_counts()
        preview_key = f'_filter_{filter_key}'
        if getattr(self, '_active_preview_key', None) == preview_key:
            self._clear_batch_preview()
            return
        self._clear_batch_preview()
        targets = [r for r in self.rows if self._filter_matches(r, filter_key)]
        if not targets:
            label = self._status_filter_btns[filter_key].text().split(" (")[0]
            self.log(f"[ФИЛЬТР] Нет записей для «{label}»")
            return
        self._active_preview_key = preview_key
        self._preview_rows = targets
        target_set = set(id(r) for r in targets)
        for r in self.rows:
            if id(r) in target_set:
                self.table.setRowHidden(r["row_index"], False)
                r["_preview_active"] = True
            else:
                self.table.setRowHidden(r["row_index"], True)
        btn = self._status_filter_btns.get(filter_key)
        if btn:
            btn.setChecked(True)
        label = btn.text().split(" (")[0] if btn else filter_key
        self._update_rows_count()
        self.log(f"[ФИЛЬТР] «{label}»: показано {len(targets)} записей. Повторный клик — сброс.")

    def _update_status_filter_counts(self):
        """Обновить счётчики на кнопках фильтрации."""
        # Подсчитать всё за один проход
        text_counts = {}
        sp_counts = {}
        new_count = 0
        custom_counts = {"no_audio_no_archive": 0, "no_forum_url": 0}
        for r in self.rows:
            sp = r.get("sort_priority", 1)
            sp_counts[sp] = sp_counts.get(sp, 0) + 1
            text = r["status_lbl"].text()
            text_counts[text] = text_counts.get(text, 0) + 1
            if r.get("is_new"):
                new_count += 1
            if self._match_custom_filter(r, "no_audio_no_archive"):
                custom_counts["no_audio_no_archive"] += 1
            if self._match_custom_filter(r, "no_forum_url"):
                custom_counts["no_forum_url"] += 1
        for key, btn in self._status_filter_btns.items():
            label = btn.text().split(" (")[0]
            if key == "new":
                c = new_count
            elif key.startswith("text:"):
                c = text_counts.get(key[5:], 0)
            elif key.startswith("sp:"):
                c = sp_counts.get(int(key[3:]), 0)
            elif key.startswith("custom:"):
                c = custom_counts.get(key[7:], 0)
            else:
                c = 0
            btn.setText(f"{label} ({c})")
            btn.setEnabled(c > 0)

    def _show_new_preview(self):
        """Показать только NEW записи. Повторный клик — сброс."""
        # Если уже показан preview NEW — сбросить
        if getattr(self, '_active_preview_key', None) == '_new_preview':
            self._clear_batch_preview()
            return
        # Сбросить предыдущий preview если был
        self._clear_batch_preview()

        targets = [r for r in self.rows if r.get("is_new")]
        if not targets:
            self.log("[PREVIEW] Нет NEW записей")
            return

        # Запомнить активный preview
        self._active_preview_key = '_new_preview'
        self._preview_rows = targets
        target_set = set(id(r) for r in targets)

        # Скрыть все строки кроме targets
        for r in self.rows:
            if id(r) in target_set:
                self.table.setRowHidden(r["row_index"], False)
                r["_preview_active"] = True
            else:
                self.table.setRowHidden(r["row_index"], True)

        # Установить состояние checked для кнопки глаз NEW
        self.reset_new_preview_btn.setChecked(True)

        self.log(f"[PREVIEW] NEW записи: показано {len(targets)}. Повторный клик 👁 — сброс.")

    def _batch_action(self, btn_key, action_fn):
        # Режим фильма — действие для одного фильма
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        if current_tab > 0:
            fn = self.tab_widget.tabText(current_tab)
            r = self._find_row(fn)
            if not r or r[btn_key].isHidden():
                self.log(f"[BATCH FILM] Действие {btn_key} недоступно для «{fn}»")
                return
            checked = [r]
            targets = [r]
        else:
            checked = [r for r in self.rows if r["select_cb"].isChecked() and not self.table.isRowHidden(r["row_index"])]
            if not checked:
                self.log(f"[BATCH] Нет строк с включённым чекбоксом")
                return
            targets = [r for r in checked if not r[btn_key].isHidden()]
        if not targets:
            for r in checked:
                fn = r["folder_name"]
                hidden = r[btn_key].isHidden()
                archive = r.get("archive_file", "")
                pw = r["password_entry"].text().strip()
                audio = r.get("audio_files", [])
                self.log(f"[BATCH] Пропуск «{fn}»: кнопка {btn_key} скрыта={hidden}, "
                         f"archive_file=«{archive}», пароль={'да' if pw else 'нет'}, "
                         f"аудио файлов={len(audio)}")
            return
        lbl = self._batch_labels.get(btn_key, "действие")
        n = len(targets)
        # Для кнопки Обработать — подробный диалог
        if btn_key == "btn_play":
            names = [r["folder_name"] for r in targets[:10]]
            names_text = "\n".join(f"  - {name}" for name in names)
            if n > 10:
                names_text += f"\n  ... и ещё {n - 10}"
            msg = f"Обработать {n} файлов через mkvmerge?\n\n{names_text}"
            # Информация об удалении аудио дорожек
            del_audio_count = n if self.batch_del_audio_cb.isChecked() else 0
            if del_audio_count > 0:
                msg += f"\n\nУдаление оригинальных аудио дорожек: {del_audio_count} из {n} файлов"
            ans = QMessageBox.question(self, "Обработка файлов", msg)
        else:
            # Для остальных действий — простой диалог
            ans = QMessageBox.question(self, lbl,
                f"{lbl} — выполнить для {n} файлов?")
        if btn_key == "btn_download":
            # Для скачивания — собственный диалог вместо стандартного подтверждения
            self._batch_download_dialog(targets)
            self._update_batch_buttons()
            return
        if ans != QMessageBox.Yes:
            return
        # Обработка: используем специализированные батч-методы
        if btn_key == "btn_play":
            self._batch_process(targets)
        elif btn_key == "btn_to_res":
            self._batch_to_result(targets)
        elif btn_key == "btn_del_test":
            self._batch_del_files(targets, "test")
        elif btn_key == "btn_del_src":
            self._batch_del_files(targets, "source")
        elif btn_key == "btn_del_res":
            self._batch_del_files(targets, "result")
        elif btn_key == "btn_unrar":
            self._batch_unrar(targets)
        elif btn_key == "btn_del_archive":
            self._batch_del_archive(targets)
        self._update_batch_buttons()

    def _batch_process(self, targets):
        """Батч-обработка mkvmerge для выбранных строк."""
        mkvmerge = self.mkvmerge_path_edit.text()
        if not mkvmerge or not os.path.exists(mkvmerge):
            QMessageBox.critical(self, "Ошибка", "Укажите mkvmerge.exe"); return
        tp = self.test_path_edit.text()
        if not tp or not os.path.isdir(tp):
            QMessageBox.critical(self, "Ошибка", "Укажите папку тест"); return
        op = self.output_path_edit.text()
        task_refs = []
        for r in targets:
            an = self._audio_filename(r); vn = r["video_combo"].currentText()
            on = r["output_entry"].text()
            if not an or not vn or vn == "— снять выбор —" or not on: continue
            # Флаги всегда из единой батч-панели
            del_audio = self.batch_del_audio_cb.isChecked()
            best_track = self.batch_best_track_cb.isChecked()
            refs = self._build_task_refs(r, tp, op, del_audio, best_track)
            task_refs.extend(refs)
        if not task_refs:
            QMessageBox.information(self, "Инфо", "Нет заданий"); return
        self.log(f"=== БАТЧ ОБРАБОТКА: {len(task_refs)} файлов ===")
        self._save_config()
        threading.Thread(target=self._process_tasks, args=(task_refs, mkvmerge), daemon=True).start()

    def _batch_to_result(self, targets):
        """Батч: переместить тестовые файлы в результат."""
        tp, op = self.test_path_edit.text(), self.output_path_edit.text()
        if not tp or not op: return
        moved = 0
        for r in targets:
            name = r["output_entry"].text()
            if not name: continue
            src = os.path.join(tp, name); dst = os.path.join(op, name)
            if not os.path.exists(src): continue
            try:
                if os.path.exists(dst): os.remove(dst)
                shutil.move(src, dst); moved += 1
                self.log(f"[OK] В результат: {name}")
            except Exception as e:
                self.log(f"[ERR] {name}: {e}")
        self.log(f"[BATCH] В результат: {moved}/{len(targets)}")
        self._check_all_statuses()

    def _batch_del_files(self, targets, kind):
        """Батч: удалить файлы (test/source/result)."""
        deleted = 0
        for r in targets:
            if kind == "test":
                tp = self.test_path_edit.text(); name = r["output_entry"].text()
                if not tp or not name: continue
                path = os.path.join(tp, name)
            elif kind == "source":
                path = r.get("video_full_path", "")
            elif kind == "result":
                op = self.output_path_edit.text(); name = r["output_entry"].text()
                if not op or not name: continue
                path = os.path.join(op, name)
            else:
                continue
            if not path or not os.path.exists(path): continue
            try:
                os.remove(path); deleted += 1
                self.log(f"[DEL] {kind}: {os.path.basename(path)}")
                if kind == "source":
                    vn = r["video_combo"].currentText()
                    if vn in self.available_videos: self.available_videos.remove(vn)
                    if vn in self.video_files: self.video_files.remove(vn)
                    r["video_combo"].blockSignals(True); r["video_combo"].setCurrentText(""); r["video_combo"].blockSignals(False)
                    r["output_entry"].setText(""); r["video_full_path"] = ""; r["prev_video"] = ""
            except Exception as e:
                self.log(f"[ERR] {os.path.basename(path)}: {e}")
        self.log(f"[BATCH] Удалено ({kind}): {deleted}/{len(targets)}")
        self._check_all_statuses()
        if kind == "source":
            self._update_all_video_combos()
            self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")

    def _batch_unrar(self, targets):
        """Батч: распаковать архивы для выбранных строк."""
        queue = []
        for r in targets:
            fn = r["folder_name"]
            archive = r.get("archive_file", "")
            pw = r["password_entry"].text().strip()
            if not archive:
                self.log(f"[BATCH UNRAR] Пропуск «{fn}»: archive_file пуст")
                continue
            archive_path = os.path.join(r["folder_path"], archive)
            if not os.path.isfile(archive_path):
                self.log(f"[BATCH UNRAR] Пропуск «{fn}»: файл не существует — {archive_path}")
                continue
            r["status_lbl"].setText("В очереди...")
            r["status_lbl"].setStyleSheet("color:#8B4513; font-weight:bold;")
            r["btn_unrar"].setEnabled(False)
            queue.append((fn, archive_path, pw, r["folder_path"]))
        if not queue:
            self.log(f"[BATCH UNRAR] Очередь пуста — ни один файл не прошёл проверку")
            return
        self.log(f"[BATCH UNRAR] Очередь: {len(queue)} архив(ов)")
        threading.Thread(target=self._unrar_all_worker, args=(queue,), daemon=True).start()

    def _batch_del_archive(self, targets):
        """Батч: удалить архивы для выбранных строк."""
        deleted = 0
        for r in targets:
            archive = r.get("archive_file", "")
            if not archive: continue
            path = os.path.join(r["folder_path"], archive)
            try:
                if os.path.isfile(path):
                    os.remove(path); r["archive_file"] = ""; deleted += 1
                    self.log(f"[DEL] Архив: {archive}")
            except Exception as e:
                self.log(f"[ERR] {archive}: {e}")
        self.log(f"[BATCH] Удалено архивов: {deleted}/{len(targets)}")
        self._check_all_statuses()
        self._update_archive_btn_count()

    def _action_download(self, fn):
        """Скачать аудио дорожку для одного фильма."""
        r = self._find_row(fn) if isinstance(fn, str) else fn
        if not r:
            return
        self._batch_download_dialog([r])

    def _batch_download_dialog(self, targets):
        """Модальное окно для скачивания аудио дорожек."""
        # Подсчёт данных
        # Собираем данные для КАЖДОЙ записи: и торрент-файлы, и URL
        _dl_data = []  # [(r, tor_files_list, url_str), ...]
        _cnt_tor = 0
        _cnt_url = 0
        _cnt_none = 0
        for r in targets:
            fp = r["folder_path"]
            _tor_files = []
            try:
                _tor_files = [f for f in os.listdir(fp) if f.lower().endswith('.torrent') and os.path.isfile(os.path.join(fp, f))]
            except OSError:
                pass
            _url = r.get("audio_torrent_url", "").strip()
            _dl_data.append((r, _tor_files, _url))
            if _tor_files:
                _cnt_tor += 1
            if _url:
                _cnt_url += 1
            if not _tor_files and not _url:
                _cnt_none += 1

        # Считаем только по ссылке (без файла)
        _cnt_url_only = sum(1 for _, tf, u in _dl_data if not tf and u)

        if _cnt_tor == 0 and _cnt_url == 0:
            QMessageBox.information(self, "Скачать", "Нет данных для скачивания.\nНет торрент-файлов и нет ссылок на торрент.")
            return

        # Проверить доступность qBittorrent API
        _qbt_available = self._qbt_check_available()

        dlg = QDialog(self)
        dlg.setWindowTitle("Скачать аудио дорожки")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)

        # Статистика
        _info_lines = [f"Выбрано записей: {len(targets)}"]
        if _cnt_tor:
            _info_lines.append(f"С торрент-файлами: {_cnt_tor}")
        if _cnt_url_only:
            _info_lines.append(f"Только ссылки (нет файла): {_cnt_url_only} (скачается .torrent → API)")
        if _cnt_none:
            _info_lines.append(f"Без данных: {_cnt_none} (пропускаются)")
        info = QLabel("\n".join(_info_lines))
        info.setStyleSheet("padding: 8px;")
        lay.addWidget(info)

        # Описание логики (HTML для вставки иконки qBittorrent)
        _qbt_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "qbittorrent_icon.png")
        _qbt_img = f'<img src="{_qbt_icon}" width="16" height="16">' if os.path.isfile(_qbt_icon) else ""
        logic_lbl = QLabel(
            "Если есть .torrent файл:<br>"
            "&nbsp;&nbsp;&nbsp;Сразу добавляется в клиент, скачивание начнётся автоматически.<br><br>"
            "Если есть только ссылка:<br>"
            "&nbsp;&nbsp;&nbsp;Скачиваем .torrent по ссылке → сохраняем в папку фильма →<br>"
            "&nbsp;&nbsp;&nbsp;добавляем в клиент → скачивание начнётся автоматически.<br><br>"
            f"Если установлен {_qbt_img} qBittorrent + включён веб-интерфейс:<br>"
            "&nbsp;&nbsp;&nbsp;Скачивание в папку фильма.<br><br>"
            "Если другой клиент или веб-интерфейс не включён:<br>"
            "&nbsp;&nbsp;&nbsp;Скачивание в общую папку торрент-клиента.")
        logic_lbl.setTextFormat(Qt.RichText)
        logic_lbl.setWordWrap(True)
        logic_lbl.setStyleSheet("color: #555; padding: 4px 8px;")
        lay.addWidget(logic_lbl)

        # qBittorrent API статус
        if _qbt_available:
            qbt_lbl = QLabel("✅ qBittorrent API доступен — торренты скачаются в папку фильма")
            qbt_lbl.setStyleSheet("color: green; padding: 4px 8px; font-weight: bold;")
            qbt_lbl.setToolTip("qBittorrent WebUI включён, порт 8080.\n"
                               "Торренты будут добавлены через API с savepath = папка фильма.")
        else:
            qbt_lbl = QLabel("❌ qBittorrent API не доступен — торренты скачаются в папку по умолчанию торрент-клиента")
            qbt_lbl.setStyleSheet("color: red; padding: 4px 8px; font-weight: bold;")
            qbt_lbl.setWordWrap(True)
            qbt_lbl.setToolTip("Чтобы включить qBittorrent API:\n"
                               "1. Откройте qBittorrent → Инструменты → Настройки → Веб-интерфейс\n"
                               "2. ☑ «Веб-интерфейс (удалённое управление)», порт 8080\n"
                               "3. ☑ «Пропускать аутентификацию клиентов с localhost»\n"
                               "4. Задайте пароль (мин. 6 символов) → Применить")
        lay.addWidget(qbt_lbl)

        # Галка "Перезаписать существующие"
        overwrite_cb = QCheckBox("Перезаписать существующие (удалить старый торрент + файлы и добавить заново)")
        overwrite_cb.setToolTip(
            "Если торрент уже добавлен в qBittorrent — удалить его\n"
            "вместе со скачанными файлами и добавить заново\n"
            "с правильной папкой сохранения.\n\n"
            "Полезно если торрент был скачан ранее в другую папку.")
        overwrite_cb.setEnabled(_qbt_available)
        if not _qbt_available:
            overwrite_cb.setToolTip("Требуется qBittorrent API для перезаписи")
        lay.addWidget(overwrite_cb)

        # Кнопки
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        dl_btn = QPushButton("Скачать")
        dl_btn.setStyleSheet("QPushButton{background-color:#cce5ff; padding: 6px 20px;} QPushButton:hover{background-color:#99ccff;}")
        dl_btn.setToolTip("Начать скачивание аудио дорожек")
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setToolTip("Отмена скачивания")
        btn_lay.addWidget(dl_btn)
        btn_lay.addWidget(cancel_btn)
        lay.addLayout(btn_lay)

        cancel_btn.clicked.connect(dlg.reject)

        def _do_download():
            dlg.accept()
            self._execute_download(_dl_data, _qbt_available, overwrite_cb.isChecked())

        dl_btn.clicked.connect(_do_download)
        dlg.exec()

    def _execute_download(self, dl_data, use_qbt, overwrite=False):
        """Выполнить скачивание торрент-файлов и/или ссылок.
        dl_data: [(r, tor_files_list, url_str), ...]
        Приоритет: торрент-файл → ссылка (если файла нет).
        overwrite: при ошибке "Fails." удалить старый торрент + файлы и добавить заново.
        """
        downloaded = 0
        url_added = 0
        skipped = 0
        overwritten = 0
        errors = []

        for r, tor_files, url in dl_data:
            fn = r["folder_name"]
            fp = r["folder_path"]
            done = False

            # Торрент-файл (приоритет)
            if tor_files:
                tor_path = os.path.join(fp, tor_files[0])
                if use_qbt:
                    ok, err = self._qbt_add_torrent(tor_path, fp)
                    if ok:
                        self.log(f"[DOWNLOAD] qBittorrent API: файл «{tor_files[0]}» → «{fp}»")
                        downloaded += 1; done = True
                    elif overwrite and "fails" in err.lower():
                        # Торрент уже существует — удаляем и добавляем заново
                        _hash = self._torrent_info_hash(tor_path)
                        if _hash:
                            del_ok, del_err = self._qbt_delete_torrent(_hash, delete_files=True)
                            if del_ok:
                                self.log(f"[OVERWRITE] Удалён старый торрент {_hash[:8]}… для «{fn}»")
                                import time as _time; _time.sleep(1)  # подождать удаления
                                ok2, err2 = self._qbt_add_torrent(tor_path, fp)
                                if ok2:
                                    self.log(f"[DOWNLOAD] qBittorrent API (перезапись): «{tor_files[0]}» → «{fp}»")
                                    downloaded += 1; overwritten += 1; done = True
                                else:
                                    errors.append(f"{fn}: перезапись не удалась — {err2}")
                                    self.log(f"[ERR] «{fn}»: повторное добавление — {err2}")
                            else:
                                errors.append(f"{fn}: не удалось удалить старый — {del_err}")
                                self.log(f"[ERR] «{fn}»: удаление торрента — {del_err}")
                        else:
                            errors.append(f"{fn}: не удалось прочитать info_hash из .torrent")
                            self.log(f"[ERR] «{fn}»: info_hash не вычислен")
                    else:
                        errors.append(f"{fn}: API ошибка — {err}")
                        self.log(f"[ERR] «{fn}»: qBittorrent API — {err}")
                else:
                    try:
                        os.startfile(tor_path)
                        downloaded += 1; done = True
                        self.log(f"[DOWNLOAD] os.startfile: «{tor_files[0]}» (⚠ папка по умолчанию)")
                    except Exception as e:
                        errors.append(f"{fn}: {e}")
                        self.log(f"[ERR] «{fn}»: os.startfile — {e}")

            # Ссылка — если торрент-файл не обработан
            if not done and url:
                if url.startswith('magnet:') and use_qbt:
                    # Magnet-ссылки — напрямую через API
                    ok, err = self._qbt_add_torrent_url(url, fp)
                    if ok:
                        self.log(f"[DOWNLOAD] qBittorrent API: magnet → «{fp}»")
                        url_added += 1; done = True
                    else:
                        errors.append(f"{fn}: API magnet — {err}")
                        self.log(f"[ERR] «{fn}»: magnet — {err}")
                if not done:
                    # Скачать .torrent файл через Python в папку фильма, потом добавить через API
                    _dl_ok, _dl_path, _dl_err = self._download_torrent_file(url, fp)
                    if _dl_ok and _dl_path:
                        self.log(f"[DOWNLOAD] Скачан .torrent: «{os.path.basename(_dl_path)}» → «{fp}»")
                        if use_qbt:
                            ok, err = self._qbt_add_torrent(_dl_path, fp)
                            if ok:
                                self.log(f"[DOWNLOAD] qBittorrent API: файл «{os.path.basename(_dl_path)}» → «{fp}»")
                                url_added += 1; done = True
                            else:
                                # .torrent скачан но API не добавил — открываем через os.startfile
                                try:
                                    os.startfile(_dl_path)
                                    url_added += 1; done = True
                                    self.log(f"[DOWNLOAD] os.startfile: «{os.path.basename(_dl_path)}»")
                                except Exception as e2:
                                    errors.append(f"{fn}: API — {err}, startfile — {e2}")
                        else:
                            try:
                                os.startfile(_dl_path)
                                url_added += 1; done = True
                                self.log(f"[DOWNLOAD] os.startfile: «{os.path.basename(_dl_path)}»")
                            except Exception as e:
                                errors.append(f"{fn}: {e}")
                    else:
                        # Не удалось через Python (авторизация) — браузер + мониторинг загрузок
                        self.log(f"[WARN] «{fn}»: Python не смог — {_dl_err}, пробуем браузер")
                        _br_ok, _br_path = self._download_via_browser_and_wait(url, fp, fn)
                        if _br_ok and _br_path:
                            if use_qbt:
                                ok2, err2 = self._qbt_add_torrent(_br_path, fp)
                                if ok2:
                                    self.log(f"[DOWNLOAD] qBittorrent API: «{os.path.basename(_br_path)}» → «{fp}»")
                                    url_added += 1; done = True
                                else:
                                    try:
                                        os.startfile(_br_path)
                                        url_added += 1; done = True
                                        self.log(f"[DOWNLOAD] os.startfile: «{os.path.basename(_br_path)}»")
                                    except Exception as e2:
                                        errors.append(f"{fn}: API — {err2}")
                            else:
                                try:
                                    os.startfile(_br_path)
                                    url_added += 1; done = True
                                except Exception as e:
                                    errors.append(f"{fn}: {e}")
                        elif _br_ok is None:
                            # Пользователь отменил ожидание
                            self.log(f"[SKIP] «{fn}»: ожидание отменено")
                            skipped += 1
                        else:
                            errors.append(f"{fn}: .torrent не появился в папке загрузок")
                            self.log(f"[ERR] «{fn}»: .torrent не найден после скачивания браузером")

            if not done:
                if not tor_files and not url:
                    self.log(f"[SKIP] «{fn}»: нет ни торрент-файлов ни ссылок")
                skipped += 1

        # Итого
        parts = []
        if downloaded:
            parts.append(f"торрентов: {downloaded}")
        if overwritten:
            parts.append(f"перезаписано: {overwritten}")
        if url_added:
            parts.append(f"ссылок: {url_added}")
        if skipped:
            parts.append(f"пропущено: {skipped}")
        if errors:
            parts.append(f"ошибок: {len(errors)}")
        summary = ", ".join(parts) if parts else "ничего не обработано"
        self.log(f"[BATCH DOWNLOAD] Итого: {summary}")
        if errors:
            self.log(f"[BATCH DOWNLOAD] Ошибки:\n" + "\n".join(errors[:10]))
        self.statusBar().showMessage(f"Скачивание: {summary}", 8000)

    def _qbt_check_available(self):
        """Проверить доступность qBittorrent WebUI."""
        try:
            import urllib.request
            _settings = {}
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_settings", "settings.json")
                if os.path.isfile(_sp):
                    with open(_sp, "r", encoding="utf-8") as f:
                        _settings = __import__("json").load(f)
            except Exception:
                pass
            _url = _settings.get("qbt_url", "http://localhost:8080")
            req = urllib.request.Request(f"{_url}/api/v2/app/version", method="GET")
            resp = urllib.request.urlopen(req, timeout=2)
            return resp.status == 200
        except Exception:
            return False

    def _qbt_add_torrent(self, torrent_path, save_path):
        """Добавить торрент через qBittorrent WebUI API. Возвращает (ok, error_msg)."""
        try:
            import urllib.request
            import json as _json
            _settings = {}
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_settings", "settings.json")
                if os.path.isfile(_sp):
                    with open(_sp, "r", encoding="utf-8") as f:
                        _settings = _json.load(f)
            except Exception:
                pass
            _url = _settings.get("qbt_url", "http://localhost:8080")
            _user = _settings.get("qbt_user", "")
            _pwd = _settings.get("qbt_password", "")

            # Авторизация (если нужна)
            _cookie = ""
            if _user:
                _auth_data = f"username={_user}&password={_pwd}".encode()
                _auth_req = urllib.request.Request(f"{_url}/api/v2/auth/login", data=_auth_data, method="POST")
                _auth_resp = urllib.request.urlopen(_auth_req, timeout=5)
                _cookie = _auth_resp.getheader("Set-Cookie", "")

            # Отправка торрент-файла (multipart/form-data)
            boundary = "----PythonBoundary" + str(int(__import__("time").time() * 1000))
            body = b""
            # Файл торрента
            with open(torrent_path, "rb") as f:
                _tor_data = f.read()
            body += f"--{boundary}\r\n".encode()
            body += f"Content-Disposition: form-data; name=\"torrents\"; filename=\"{os.path.basename(torrent_path)}\"\r\n".encode()
            body += b"Content-Type: application/x-bittorrent\r\n\r\n"
            body += _tor_data
            body += b"\r\n"
            # Папка сохранения
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"savepath\"\r\n\r\n"
            body += save_path.encode("utf-8")
            body += b"\r\n"
            body += f"--{boundary}--\r\n".encode()

            req = urllib.request.Request(f"{_url}/api/v2/torrents/add", data=body, method="POST")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            if _cookie:
                req.add_header("Cookie", _cookie)
            resp = urllib.request.urlopen(req, timeout=10)
            _body = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status == 200 and _body.lower().startswith("ok"):
                return (True, "")
            return (False, f"Ответ API: {_body} (HTTP {resp.status})")
        except Exception as e:
            return (False, str(e))

    def _download_via_browser_and_wait(self, url, film_folder, film_name):
        """Открыть ссылку в браузере, подождать скачивания .torrent, переместить в папку фильма.
        Возвращает (ok, path) — ok=True+path, ok=False (не нашли), ok=None (отмена).
        """
        import webbrowser
        import time as _time
        import shutil

        # Определяем папку загрузок
        _dl_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(_dl_dir):
            _dl_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
        if not os.path.isdir(_dl_dir):
            self.log(f"[ERR] Папка загрузок не найдена: {_dl_dir}")
            return (False, "")

        # Запоминаем существующие .torrent файлы
        _before = set()
        try:
            _before = {f for f in os.listdir(_dl_dir) if f.lower().endswith('.torrent')}
        except OSError:
            pass

        # Открываем в браузере
        try:
            webbrowser.open(url)
        except Exception as e:
            self.log(f"[ERR] webbrowser.open: {e}")
            return (False, "")

        # Показываем прогресс-диалог и ждём появления нового .torrent файла
        progress = QProgressDialog(
            f"Ожидание скачивания .torrent для «{film_name}»...\n"
            f"Браузер открыл ссылку, ждём файл в {_dl_dir}",
            "Отмена", 0, 30, self)
        progress.setWindowTitle("Скачивание .torrent")
        progress.setMinimumWidth(450)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        _new_file = ""
        for i in range(30):  # 30 секунд максимум
            QApplication.processEvents()
            if progress.wasCanceled():
                return (None, "")
            _time.sleep(1)
            progress.setValue(i + 1)
            QApplication.processEvents()
            # Проверяем новые .torrent файлы
            try:
                _after = {f for f in os.listdir(_dl_dir) if f.lower().endswith('.torrent')}
            except OSError:
                continue
            _new = _after - _before
            if _new:
                # Берём самый свежий
                _new_file = max(_new, key=lambda f: os.path.getmtime(os.path.join(_dl_dir, f)))
                break

        progress.close()

        if not _new_file:
            return (False, "")

        # Перемещаем в папку фильма
        _src = os.path.join(_dl_dir, _new_file)
        _dst = os.path.join(film_folder, _new_file)
        try:
            shutil.move(_src, _dst)
            self.log(f"[DOWNLOAD] .torrent перемещён: {_dl_dir} → {film_folder}")
            return (True, _dst)
        except Exception as e:
            self.log(f"[ERR] Не удалось переместить .torrent: {e}")
            # Если не удалось переместить — используем файл где он есть
            return (True, _src)

    def _download_torrent_file(self, url, save_dir):
        """Скачать .torrent файл по URL в папку save_dir. Возвращает (ok, path, error)."""
        try:
            import urllib.request
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            if len(data) < 50:
                return (False, "", f"Слишком маленький ответ ({len(data)} байт), возможно ошибка авторизации")
            # Проверяем что это bencode (торрент-файл начинается с 'd')
            if not data[:1] == b'd':
                # Может быть HTML (страница авторизации)
                _snippet = data[:200].decode("utf-8", errors="replace")
                if "<html" in _snippet.lower() or "<head" in _snippet.lower():
                    return (False, "", f"Сервер вернул HTML вместо .torrent (нужна авторизация?)")
                # Может быть другой формат — всё равно сохраняем
            # Имя файла из Content-Disposition или из URL
            _cd = resp.getheader("Content-Disposition", "")
            _fname = ""
            if "filename=" in _cd:
                _fname = _cd.split("filename=")[-1].strip().strip('"').strip("'")
            if not _fname:
                _fname = os.path.basename(url.split("?")[0])
            if not _fname or not _fname.lower().endswith('.torrent'):
                _fname = f"audio_{int(__import__('time').time())}.torrent"
            # Убираем запрещённые символы
            for c in r'\/:*?"<>|':
                _fname = _fname.replace(c, "_")
            _save_path = os.path.join(save_dir, _fname)
            with open(_save_path, "wb") as f:
                f.write(data)
            return (True, _save_path, "")
        except Exception as e:
            return (False, "", str(e))

    def _qbt_add_torrent_url(self, torrent_url, save_path):
        """Добавить торрент по URL/magnet через qBittorrent WebUI API. Возвращает (ok, error_msg)."""
        try:
            import urllib.request
            import json as _json
            _settings = {}
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_settings", "settings.json")
                if os.path.isfile(_sp):
                    with open(_sp, "r", encoding="utf-8") as f:
                        _settings = _json.load(f)
            except Exception:
                pass
            _url = _settings.get("qbt_url", "http://localhost:8080")

            # multipart/form-data с urls и savepath
            boundary = "----PythonBoundary" + str(int(__import__("time").time() * 1000))
            body = b""
            # URL торрента
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"urls\"\r\n\r\n"
            body += torrent_url.encode("utf-8")
            body += b"\r\n"
            # Папка сохранения
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"savepath\"\r\n\r\n"
            body += save_path.encode("utf-8")
            body += b"\r\n"
            body += f"--{boundary}--\r\n".encode()

            req = urllib.request.Request(f"{_url}/api/v2/torrents/add", data=body, method="POST")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            resp = urllib.request.urlopen(req, timeout=10)
            _body = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status == 200 and _body.lower().startswith("ok"):
                return (True, "")
            return (False, f"Ответ API: {_body} (HTTP {resp.status})")
        except Exception as e:
            return (False, str(e))

    @staticmethod
    def _torrent_info_hash(torrent_path):
        """Вычислить info_hash из .torrent файла (SHA1 от bencode info dict)."""
        import hashlib
        try:
            with open(torrent_path, 'rb') as f:
                data = f.read()
        except OSError:
            return None
        if not data or data[0:1] != b'd':
            return None

        def _skip(d, i):
            """Пропустить одно bencode-значение, вернуть индекс после него."""
            ch = d[i:i + 1]
            if ch == b'd':
                i += 1
                while d[i:i + 1] != b'e':
                    i = _skip(d, i)  # key
                    i = _skip(d, i)  # value
                return i + 1
            elif ch == b'l':
                i += 1
                while d[i:i + 1] != b'e':
                    i = _skip(d, i)
                return i + 1
            elif ch == b'i':
                return d.index(b'e', i) + 1
            else:
                colon = d.index(b':', i)
                length = int(d[i:colon])
                return colon + 1 + length

        # Парсим top-level dict, ищем ключ b'info'
        i = 1  # после 'd'
        try:
            while data[i:i + 1] != b'e':
                # Читаем ключ (строка)
                colon = data.index(b':', i)
                klen = int(data[i:colon])
                key = data[colon + 1:colon + 1 + klen]
                i = colon + 1 + klen
                # Позиция значения
                val_start = i
                i = _skip(data, i)
                if key == b'info':
                    return hashlib.sha1(data[val_start:i]).hexdigest()
        except (ValueError, IndexError):
            pass
        return None

    def _qbt_delete_torrent(self, info_hash, delete_files=True):
        """Удалить торрент из qBittorrent через API. Возвращает (ok, error_msg)."""
        try:
            import urllib.request
            import json as _json
            _settings = {}
            try:
                _sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_settings", "settings.json")
                if os.path.isfile(_sp):
                    with open(_sp, "r", encoding="utf-8") as f:
                        _settings = _json.load(f)
            except Exception:
                pass
            _url = _settings.get("qbt_url", "http://localhost:8080")
            _user = _settings.get("qbt_user", "")
            _pwd = _settings.get("qbt_password", "")
            _cookie = ""
            if _user:
                _auth_data = f"username={_user}&password={_pwd}".encode()
                _auth_req = urllib.request.Request(f"{_url}/api/v2/auth/login", data=_auth_data, method="POST")
                _auth_resp = urllib.request.urlopen(_auth_req, timeout=5)
                _cookie = _auth_resp.getheader("Set-Cookie", "")
            _del_files = "true" if delete_files else "false"
            _data = f"hashes={info_hash}&deleteFiles={_del_files}".encode()
            req = urllib.request.Request(f"{_url}/api/v2/torrents/delete", data=_data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            if _cookie:
                req.add_header("Cookie", _cookie)
            resp = urllib.request.urlopen(req, timeout=10)
            if resp.status == 200:
                return (True, "")
            return (False, f"HTTP {resp.status}")
        except Exception as e:
            return (False, str(e))

    # ──────────────────────────────────
    #  Обработчики
    # ──────────────────────────────────

    def _on_video_selected(self, fn):
        r = self._find_row(fn)
        if not r: return
        sel = r["video_combo"].currentText()
        old = r.get("prev_video", "")

        # Занятые видео (с пометкой ← folder) — диалог назначения/копирования
        if "  ← " in sel:
            video_name = sel.split("  ← ")[0]
            # Откатить комбо на время диалога
            r["video_combo"].blockSignals(True)
            if old:
                r["video_combo"].setCurrentText(old)
            else:
                r["video_combo"].setCurrentIndex(0)
            r["video_combo"].blockSignals(False)
            self._sync_tab_video(fn)
            # Защита от повторного вызова (стрелки клавиатуры)
            if getattr(self, '_occupied_dlg_open', False):
                return
            self._occupied_dlg_open = True
            try:
                self._show_occupied_video_dialog(r, fn, video_name)
            finally:
                self._occupied_dlg_open = False
            return

        if old and old != sel and old not in self.available_videos and old in self.video_files:
            # Не возвращать в available если другая запись всё ещё использует это видео
            _still_used = any(rr["video_combo"].currentText() == old for rr in self.rows if rr is not r)
            if not _still_used:
                self.available_videos.append(old); self.available_videos.sort()

        if sel == "— снять выбор —" or not sel:
            r["video_combo"].blockSignals(True)
            r["video_combo"].setCurrentIndex(0)
            r["video_combo"].blockSignals(False)
            r["output_entry"].setText(""); r["video_full_path"] = ""; r["prev_video"] = ""
            r["video_manual"] = False
            r["video_dur_lbl"].setText("")
            # Показать кнопку ⏳ когда видео не выбрано
            r["video_pending_btn"].setVisible(True)
        else:
            if sel in self.available_videos: self.available_videos.remove(sel)
            r["prev_video"] = sel
            vp = self.video_path_edit.text()
            r["video_full_path"] = os.path.join(vp, sel) if vp else sel
            r["video_manual"] = False
            prefix = self._get_prefix(r)
            suffix = self._get_suffix(r)
            r["output_entry"].setText(f"{prefix}{os.path.splitext(sel)[0]}{suffix}.mkv")
            # Обновить длительность
            r["video_dur_lbl"].setText(self._get_video_duration(r["video_full_path"]))
            # Скрыть кнопку ⏳ когда видео выбрано
            r["video_pending_btn"].setVisible(False)
            # Сбросить video_pending если было установлено
            if r.get("video_pending"):
                r["video_pending"] = False
                r["video_pending_btn"].setText("⏳")
                r["video_pending_btn"].setStyleSheet("")

        self._sync_tab_video(fn)
        self._check_row_status(r)
        self._update_all_video_combos()
        self.schedule_autosave()

    def _show_occupied_video_dialog(self, r, fn, video_name):
        """Показать диалог для занятого видео: назначить тот же файл или копировать."""
        # Найти владельцев и путь к файлу
        owners = []
        owner_path = ""
        for rr in self.rows:
            if rr["video_combo"].currentText() == video_name:
                owners.append(rr["folder_name"])
                if not owner_path:
                    owner_path = rr.get("video_full_path", "")
        if not owner_path:
            # Попробовать найти по имени в папке видео
            vp = self.video_path_edit.text()
            if vp:
                _try = os.path.join(vp, video_name)
                if os.path.isfile(_try):
                    owner_path = _try
        if not owner_path or not os.path.isfile(owner_path):
            QMessageBox.warning(self, "Ошибка", f"Файл не найден на диске:\n{video_name}")
            return
        _sz = os.path.getsize(owner_path)
        _sz_str = f"{_sz / (1024**3):.2f} ГБ" if _sz >= 1024**3 else f"{_sz / (1024**2):.0f} МБ"
        msg = QMessageBox(self)
        msg.setWindowTitle("Занятое видео")
        msg.setText(f"Видео файл:\n{video_name} ({_sz_str})")
        msg.setInformativeText(f"Используется: {', '.join(owners)}\n\nЧто сделать?")
        btn_share = msg.addButton("Назначить тот же файл", QMessageBox.ActionRole)
        btn_copy = msg.addButton("Копировать файл", QMessageBox.ActionRole)
        msg.addButton("Отмена", QMessageBox.RejectRole)
        btn_share.setToolTip("Оба записи будут использовать один физический файл.\nКаждая обработает его со своей аудио дорожкой.")
        btn_copy.setToolTip("Создать физическую копию видео файла на диске\nи назначить копию этой записи.")
        msg.exec()
        if msg.clickedButton() == btn_share:
            self._assign_shared_video(r, fn, video_name, owner_path)
        elif msg.clickedButton() == btn_copy:
            self._copy_video_file(r, fn, video_name, owner_path)

    def _assign_shared_video(self, r, fn, video_name, video_path):
        """Назначить тот же видео файл (разделяемое использование)."""
        old = r.get("prev_video", "")
        # Вернуть старое видео в available_videos если никто больше не использует
        if old and old != video_name and old not in self.available_videos and old in self.video_files:
            _still_used = any(rr["video_combo"].currentText() == old for rr in self.rows if rr is not r)
            if not _still_used:
                self.available_videos.append(old)
                self.available_videos.sort()
        # Назначить видео
        r["prev_video"] = video_name
        r["video_full_path"] = video_path
        r["video_manual"] = False
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        r["output_entry"].setText(f"{prefix}{os.path.splitext(video_name)[0]}{suffix}.mkv")
        r["video_dur_lbl"].setText(self._get_video_duration(video_path))
        r["video_pending_btn"].setVisible(False)
        if r.get("video_pending"):
            r["video_pending"] = False
            r["video_pending_btn"].setText("⏳")
            r["video_pending_btn"].setStyleSheet("")
        # Установить текст в комбо (временно добавить элемент для setCurrentText)
        r["video_combo"].blockSignals(True)
        if r["video_combo"].findText(video_name) < 0:
            r["video_combo"].addItem(video_name)
        r["video_combo"].setCurrentText(video_name)
        r["video_combo"].blockSignals(False)
        self._sync_tab_video(fn)
        self._check_row_status(r)
        self._update_all_video_combos()
        self.schedule_autosave()
        self.log(f"[SHARE] {video_name} → {fn}")

    def _copy_video_file(self, r, fn, video_name, video_path):
        """Скопировать видео файл на диске и назначить копию этой записи."""
        vp = self.video_path_edit.text()
        if not vp:
            QMessageBox.warning(self, "Ошибка", "Не указан путь к папке видео")
            return
        base, ext = os.path.splitext(video_name)
        copy_name = f"{base} Copy{ext}"
        copy_path = os.path.join(vp, copy_name)
        counter = 2
        while os.path.exists(copy_path):
            copy_name = f"{base} Copy {counter}{ext}"
            copy_path = os.path.join(vp, copy_name)
            counter += 1
        _sz = os.path.getsize(video_path)
        _sz_str = f"{_sz / (1024**3):.2f} ГБ" if _sz >= 1024**3 else f"{_sz / (1024**2):.0f} МБ"
        if QMessageBox.question(self, "Копировать видео",
                f"Копировать файл ({_sz_str})?\n\n{video_name}\n→ {copy_name}") != QMessageBox.Yes:
            return
        # Копирование с прогрессом
        progress = QProgressDialog(f"Копирование {copy_name}...", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        buf_size = 16 * 1024 * 1024  # 16 МБ
        copied = 0
        ok = True
        try:
            with open(video_path, 'rb') as src_f, open(copy_path, 'wb') as dst_f:
                while True:
                    if progress.wasCanceled():
                        ok = False
                        break
                    buf = src_f.read(buf_size)
                    if not buf:
                        break
                    dst_f.write(buf)
                    copied += len(buf)
                    progress.setValue(int(copied * 100 / _sz) if _sz else 100)
                    QApplication.processEvents()
        except Exception as e:
            progress.close()
            if os.path.exists(copy_path):
                try: os.remove(copy_path)
                except OSError: pass
            QMessageBox.critical(self, "Ошибка копирования", str(e))
            return
        progress.close()
        if not ok:
            if os.path.exists(copy_path):
                try: os.remove(copy_path)
                except OSError: pass
            return
        # Добавить копию в списки
        self.video_files.append(copy_name)
        self.video_files.sort()
        # Не добавлять в available_videos — видео сразу назначается
        # Назначить копию
        old = r.get("prev_video", "")
        if old and old != copy_name and old not in self.available_videos and old in self.video_files:
            _still_used = any(rr["video_combo"].currentText() == old for rr in self.rows if rr is not r)
            if not _still_used:
                self.available_videos.append(old)
                self.available_videos.sort()
        r["prev_video"] = copy_name
        r["video_full_path"] = copy_path
        r["video_manual"] = False
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        r["output_entry"].setText(f"{prefix}{os.path.splitext(copy_name)[0]}{suffix}.mkv")
        r["video_dur_lbl"].setText(self._get_video_duration(copy_path))
        r["video_pending_btn"].setVisible(False)
        if r.get("video_pending"):
            r["video_pending"] = False
            r["video_pending_btn"].setText("⏳")
            r["video_pending_btn"].setStyleSheet("")
        r["video_combo"].blockSignals(True)
        if r["video_combo"].findText(copy_name) < 0:
            r["video_combo"].addItem(copy_name)
        r["video_combo"].setCurrentText(copy_name)
        r["video_combo"].blockSignals(False)
        self._sync_tab_video(fn)
        self._check_row_status(r)
        self._update_all_video_combos()
        self.schedule_autosave()
        self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")
        self.log(f"[COPY] {video_name} → {copy_name}")

    def _browse_video_file(self, fn):
        r = self._find_row(fn)
        if not r: return
        fp, _ = QFileDialog.getOpenFileName(self, "Выбрать видео", self.video_path_edit.text() or "",
            "Видео (*.mkv *.mp4 *.avi *.m2ts);;Все (*.*)")
        if not fp: return
        old = r.get("prev_video", "")
        if old and old not in self.available_videos and old in self.video_files:
            _still_used = any(rr["video_combo"].currentText() == old for rr in self.rows if rr is not r)
            if not _still_used:
                self.available_videos.append(old); self.available_videos.sort()
        name = os.path.basename(fp)
        r["video_combo"].blockSignals(True)
        r["video_combo"].clear(); r["video_combo"].addItems(["— снять выбор —", name])
        r["video_combo"].setCurrentText(name)
        r["video_combo"].blockSignals(False)
        r["video_full_path"] = fp; r["video_manual"] = True; r["prev_video"] = name
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        r["output_entry"].setText(f"{prefix}{os.path.splitext(name)[0]}{suffix}.mkv")
        r["video_dur_lbl"].setText(self._get_video_duration(fp))
        # Скрыть кнопку ⏳ когда видео выбрано
        r["video_pending_btn"].setVisible(False)
        if r.get("video_pending"):
            r["video_pending"] = False
            r["video_pending_btn"].setText("⏳")
            r["video_pending_btn"].setStyleSheet("")
        # Синхронизировать видео комбо и путь на вкладке
        self._sync_tab_video(fn)
        self._check_row_status(r); self._update_all_video_combos(); self.schedule_autosave()

    def _toggle_video_pending(self, fn):
        r = self._find_row(fn)
        if not r: return
        r["video_pending"] = not r["video_pending"]
        if r["video_pending"]:
            r["video_pending_btn"].setText("⌛")
            r["video_pending_btn"].setStyleSheet("color:#8e44ad; font-weight:bold;")
        else:
            r["video_pending_btn"].setText("⏳")
            r["video_pending_btn"].setStyleSheet("")
        # Синхронизировать кнопку на вкладке фильма
        if fn in self._open_tabs:
            tw = self._open_tabs[fn]["widgets"]
            tab_pending = tw.get("video_pending_btn")
            if tab_pending:
                if r["video_pending"]:
                    tab_pending.setText("⌛")
                    tab_pending.setStyleSheet("color:#8e44ad; font-weight:bold;")
                else:
                    tab_pending.setText("⏳")
                    tab_pending.setStyleSheet("")
        self._check_row_status(r)
        self._update_process_button()
        self.schedule_autosave()

    def _sync_delays_to_table(self, r):
        """Синхронизировать delays список с label задержки в таблице."""
        delays = r.get("delays", [{"value": "0", "confirmed": False}])
        confirmed_delay = next((d for d in delays if d.get("confirmed")), None)
        value = confirmed_delay["value"] if confirmed_delay else delays[0]["value"]
        r["delay_value"] = value
        r["delay_confirmed"] = bool(confirmed_delay)
        count = len(delays)
        clr = "green" if r["delay_confirmed"] else "red"
        mark = "✓" if r["delay_confirmed"] else "✗"
        r["delay_lbl"].setText(f'{count} <span style="color:{clr}">{mark}</span>')
        r["delay_lbl"].setTextFormat(Qt.RichText)
        bg = r.get("_status_bg", "")
        bg_part = f"background:{bg};" if bg else ""
        r["delay_lbl"].setStyleSheet(bg_part if bg_part else "")
        r["delay_lbl"].setToolTip(
            f"Задержек: {count}, подтверждено: {'да' if r['delay_confirmed'] else 'нет'}"
            + "\nРедактирование на вкладке фильма")

    def _update_audio_summary(self, r):
        """Обновить summary label аудио в таблице: количество вариантов + статус подтверждения."""
        lbl = r.get("audio_summary")
        if not lbl:
            return
        ac = r["audio_combo"]
        has_audio = ac.isEnabled() and ac.count() > 0 and not ac.itemText(0).startswith("⚠")
        if not has_audio:
            cur = ac.currentText()
            if "архив" in cur.lower():
                lbl.setText('<span style="color:#cc6600">Не распакован</span>')
                lbl.setToolTip("Аудио: нет файлов, найден архив\nРаспакуйте архив кнопкой «Архив»")
            else:
                lbl.setText('<span style="color:red">Нет аудио</span>')
                lbl.setToolTip("Аудио: нет файлов в папке")
            return
        extras = r.get("extra_audio_variants", [])
        n_variants = 1 + len(extras)
        # Если только основной вариант без extra — синий кружок (подтверждение не требуется)
        if not extras:
            main_file = ac.currentData(Qt.UserRole) or ac.currentText()
            lbl.setText('<span style="color:#2196F3">●</span>')
            lines = []
            lines.append("Основной аудио файл (единственный)")
            lines.append(f"Файл: {main_file}")
            sc = r["starter_combo"]
            if sc.isEnabled() and sc.currentData(Qt.UserRole):
                lines.append(f"Стартовый: {sc.currentData(Qt.UserRole)}")
            ec = r["ender_combo"]
            if ec.isEnabled() and ec.currentData(Qt.UserRole):
                lines.append(f"Конечный: {ec.currentData(Qt.UserRole)}")
            lines.append("")
            lines.append("● = один основной вариант, подтверждение не требуется")
            lbl.setToolTip("\n".join(lines))
            bg = r.get("_status_bg", "")
            if bg:
                lbl.setStyleSheet(f"background:{bg};")
            return
        has_confirmed = r.get("audio_variant_1_confirmed", False)
        if not has_confirmed:
            for v in extras:
                if v.get("confirmed", False):
                    has_confirmed = True
                    break
        clr = "green" if has_confirmed else "red"
        mark = "✓" if has_confirmed else "✗"
        lbl.setText(f'{n_variants} <span style="color:{clr}">{mark}</span>')
        # Динамический tooltip — легенда
        lines = []
        lines.append(f"Аудио вариантов: {n_variants}")
        lines.append(f"Подтверждено: {'да' if has_confirmed else 'нет'}")
        main_file = ac.currentData(Qt.UserRole) or ac.currentText()
        lines.append(f"Основной файл: {main_file}")
        sc = r["starter_combo"]
        if sc.isEnabled() and sc.currentData(Qt.UserRole):
            lines.append(f"Стартовый: {sc.currentData(Qt.UserRole)}")
        ec = r["ender_combo"]
        if ec.isEnabled() and ec.currentData(Qt.UserRole):
            lines.append(f"Конечный: {ec.currentData(Qt.UserRole)}")
        for i, v in enumerate(extras, 2):
            _st = v.get("starter_audio", "")
            _en = v.get("ender_audio", "")
            _conf = "✓" if v.get("confirmed") else "✗"
            lines.append(f"Вариант {i}: starter={_st or '—'}, ender={_en or '—'} {_conf}")
        lines.append("")
        lines.append(f"Цифра = количество вариантов")
        lines.append(f"✓ = есть подтверждённый вариант")
        lines.append(f"✗ = нет подтверждённых вариантов")
        lines.append("Редактирование на вкладке фильма")
        lbl.setToolTip("\n".join(lines))
        bg = r.get("_status_bg", "")
        if bg:
            lbl.setStyleSheet(f"background:{bg};")

    def _update_video_summary(self, r):
        """Обновить summary label видео в таблице: количество источников."""
        lbl = r.get("video_summary")
        if not lbl:
            return
        video_name = r["video_combo"].currentText()
        video_ok = False
        vp = self.video_path_edit.text()
        if video_name and video_name != "— снять выбор —":
            vfp = r.get("video_full_path") or (os.path.join(vp, video_name) if vp else "")
            video_ok = bool(vfp and os.path.isfile(vfp))
        if not video_ok and not r.get("video_pending"):
            lbl.setText('<span style="color:red">Нет видео</span>')
            lbl.setToolTip("Видео: источник не выбран\nВыберите видео на вкладке фильма")
            return
        # Считаем количество видео с файлами
        n_videos = 1 if video_ok else 0
        lines = []
        if video_ok:
            lines.append(f"1. {video_name}")
        for i, ev in enumerate(r.get("extra_videos", []), 2):
            ev_name = ev.get("video", "")
            ev_path = ev.get("video_full_path", "")
            if ev_name or ev_path:
                n_videos += 1
                lines.append(f"{i}. {ev_name or os.path.basename(ev_path)}")
        if n_videos > 0:
            lbl.setText(str(n_videos))
        else:
            lbl.setText('<span style="color:red">Нет видео</span>')
        # Tooltip
        tip = [f"Видео источников: {n_videos}"]
        tip.extend(lines)
        tip.append("")
        tip.append("Цифра = количество видео файлов-источников")
        tip.append("Редактирование на вкладке фильма")
        lbl.setToolTip("\n".join(tip))
        bg = r.get("_status_bg", "")
        if bg:
            lbl.setStyleSheet(f"background:{bg};")

    def _update_output_summary(self, r):
        """Обновить summary label выходных файлов: количество в тесте и результате."""
        lbl = r.get("output_summary")
        if not lbl:
            return
        op = self.output_path_edit.text()
        tp = self.test_path_edit.text()
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        # Собираем все имена выходных файлов (основной + extra)
        output_names = []
        main_out = r["output_entry"].text()
        if main_out:
            output_names.append(main_out)
        for ev in r.get("extra_videos", []):
            ev_name = ev.get("video", "")
            ev_path = ev.get("video_full_path", "")
            vn = ev_name or (os.path.basename(ev_path) if ev_path else "")
            if vn:
                output_names.append(f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv")
        in_test = 0
        in_result = 0
        tip_test = []
        tip_result = []
        for name in output_names:
            if tp and os.path.isfile(os.path.join(tp, name)):
                in_test += 1
                tip_test.append(f"  • {name}")
            if op and os.path.isfile(os.path.join(op, name)):
                in_result += 1
                tip_result.append(f"  • {name}")
        if in_test == 0 and in_result == 0:
            lbl.setText("—")
            lbl.setToolTip("Выходные файлы: нет\nОбработка ещё не запускалась")
        else:
            parts = []
            if in_test > 0:
                parts.append(f'В тесте: <b>{in_test}</b>')
            if in_result > 0:
                parts.append(f'В результате: <b>{in_result}</b>')
            lbl.setText("  ".join(parts))
            # Tooltip
            tip = [f"Выходных файлов ожидается: {len(output_names)}"]
            if in_test:
                tip.append(f"В тесте: {in_test}")
                tip.extend(tip_test)
            if in_result:
                tip.append(f"В результате: {in_result}")
                tip.extend(tip_result)
            tip.append("")
            tip.append("Редактирование на вкладке фильма")
            lbl.setToolTip("\n".join(tip))
        bg = r.get("_status_bg", "")
        if bg:
            lbl.setStyleSheet(f"background:{bg};")

    def _update_torrent_btn(self, r):
        """Обновить кнопку торрентов в таблице после пересканирования."""
        ta_btn = r.get("ta_btn")
        if not ta_btn:
            return
        tor_files = r.get("tor_files", [])
        # Удалить старое меню
        old_menu = ta_btn.menu()
        if old_menu:
            ta_btn.setMenu(None)
            old_menu.deleteLater()
        if tor_files:
            ta_btn.setText(str(len(tor_files)))
            ta_btn.setEnabled(True)
            ta_btn.setToolTip(f"Торрент-файлов: {len(tor_files)}\n" + "\n".join(f"  • {f}" for f in tor_files))
            _menu = QMenu(ta_btn)
            for _tf in tor_files:
                _path = os.path.join(r["folder_path"], _tf)
                _act = _menu.addAction(_tf)
                _act.triggered.connect((lambda p: lambda: os.startfile(p) if os.path.isfile(p) else None)(_path))
            ta_btn.setMenu(_menu)
        else:
            ta_btn.setText("0")
            ta_btn.setEnabled(False)
            ta_btn.setToolTip("Нет .torrent файлов аудио дорожки в папке")

    def _toggle_delay(self, fn):
        """Переключить подтверждение задержки в таблице (radio: подтвердить/снять)."""
        r = self._find_row(fn)
        if not r: return
        delays = r.get("delays", [{"value": "0", "confirmed": False}])
        has_confirmed = any(d.get("confirmed") for d in delays)
        if has_confirmed:
            # Снять подтверждение
            for d in delays:
                d["confirmed"] = False
        else:
            # Подтвердить задержку, совпадающую с текущим значением (или первую)
            val = r.get("delay_value", "0")
            found = False
            for d in delays:
                if d["value"] == val:
                    d["confirmed"] = True
                    found = True
                    break
            if not found and delays:
                delays[0]["confirmed"] = True
        self._sync_delays_to_table(r)
        # Обновить вкладку если открыта
        if r["folder_name"] in self._open_tabs:
            tw = self._open_tabs[r["folder_name"]]["widgets"]
            rebuild = tw.get("rebuild_delay_rows")
            if rebuild:
                rebuild()
            update_status = tw.get("update_delay_status")
            if update_status:
                update_status()
        self.schedule_autosave()

    def _on_table_delay_changed(self, fn):
        """Устаревшая — delay_entry убран из таблицы, редактирование только на вкладке."""
        pass

    def _warn_orphan_output(self, old_name, new_name=None):
        """Предупредить об осиротевших выходных файлах при смене имени.
        Если файл с old_name есть в тесте/результате — спросить удалить ли."""
        tp = self.test_path_edit.text()
        op = self.output_path_edit.text()
        orphans = []
        if tp and os.path.isfile(os.path.join(tp, old_name)):
            orphans.append(("тест", os.path.join(tp, old_name)))
        if op and os.path.isfile(os.path.join(op, old_name)):
            orphans.append(("результат", os.path.join(op, old_name)))
        if not orphans:
            return
        locs = ", ".join(loc for loc, _ in orphans)
        msg = f"Файл «{old_name}» уже есть в папке {locs}."
        if new_name:
            msg += f"\nНовое имя: «{new_name}»."
        msg += ("\n\nУдалить старый файл?\n"
                "Если не удалить — файл останется на диске без связи с системой.")
        ans = QMessageBox.question(self, "Смена имени выходного файла",
                                   msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            for loc, path in orphans:
                try:
                    os.remove(path)
                    self.log(f"[DEL] Осиротевший файл ({loc}): {os.path.basename(path)}")
                except Exception as e:
                    self.log(f"[ERR] Не удалось удалить: {path} — {e}")

    def _recalc_output_name(self, fn):
        """Пересчитать имя выходного файла на основе текущего видео, префикса и суффикса."""
        r = self._find_row(fn)
        if not r: return
        vn = r["video_combo"].currentText()
        if vn and vn != "— снять выбор —":
            prefix = self._get_prefix(r)
            suffix = self._get_suffix(r)
            new_name = f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv"
            old_name = r["output_entry"].text()
            if old_name and old_name != new_name:
                self._warn_orphan_output(old_name, new_name)
            r["output_entry"].setText(new_name)
            # Синхронизировать вкладку
            if fn in self._open_tabs:
                tab_out = self._open_tabs[fn]["widgets"].get("output_entry")
                if tab_out:
                    tab_out.setText(new_name)
                    tab_out.setCursorPosition(0)

    def _on_global_affix_changed(self):
        """Пересчитать выходные имена и статусы всех строк при изменении глобального аффикса."""
        tp = self.test_path_edit.text()
        op = self.output_path_edit.text()
        orphan_files = []  # [(old_name, path, loc), ...]
        for r in self.rows:
            # Пересчитать имя только для строк без кастомного аффикса
            vn = r["video_combo"].currentText()
            if vn and vn != "— снять выбор —":
                prefix = self._get_prefix(r)
                suffix = self._get_suffix(r)
                new_name = f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv"
                old_name = r["output_entry"].text()
                if old_name and old_name != new_name:
                    # Проверить осиротевшие файлы ДО смены имени
                    if tp and os.path.isfile(os.path.join(tp, old_name)):
                        orphan_files.append((old_name, os.path.join(tp, old_name), "тест"))
                    if op and os.path.isfile(os.path.join(op, old_name)):
                        orphan_files.append((old_name, os.path.join(op, old_name), "результат"))
                    r["output_entry"].setText(new_name)
            self._check_row_status(r)
            # Восстановить NEW подсветку поверх стандартного статуса
            if r.get("is_new"):
                r["status_lbl"].setText("✦ NEW")
                r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
                r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
                self._set_row_bg(r, COLOR_NEW)
        # Показать ОДИН диалог для всех осиротевших файлов
        if orphan_files:
            names_list = "\n".join(f"  • {name} ({loc})" for name, _, loc in orphan_files)
            msg = (f"При смене аффикса {len(orphan_files)} файлов останутся без связи:\n\n"
                   f"{names_list}\n\n"
                   f"Удалить эти файлы?\n"
                   f"Если не удалить — файлы останутся на диске без связи с системой.")
            ans = QMessageBox.question(self, "Смена глобального аффикса",
                                       msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans == QMessageBox.Yes:
                for name, path, loc in orphan_files:
                    try:
                        os.remove(path)
                        self.log(f"[DEL] Осиротевший файл ({loc}): {name}")
                    except Exception as e:
                        self.log(f"[ERR] Не удалось удалить: {path} — {e}")
                # Обновить статусы после удаления
                for r in self.rows:
                    self._check_row_status(r)
        self._update_batch_buttons()
        self.schedule_autosave()

    def _on_prefix_toggle(self, fn):
        r = self._find_row(fn)
        if not r: return
        enabled = r["prefix_cb"].isChecked()
        r["prefix_entry"].setEnabled(enabled)
        if enabled and not r["prefix_entry"].text():
            r["prefix_entry"].setText(self.file_prefix_edit.text())
        # Обновить выходной файл
        vn = r["video_combo"].currentText()
        if vn and vn != "— снять выбор —":
            prefix = self._get_prefix(r)
            suffix = self._get_suffix(r)
            new_name = f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv"
            old_name = r["output_entry"].text()
            if old_name and old_name != new_name:
                self._warn_orphan_output(old_name, new_name)
            r["output_entry"].setText(new_name)
        self.schedule_autosave()

    def _on_suffix_toggle(self, fn):
        r = self._find_row(fn)
        if not r: return
        enabled = r["suffix_cb"].isChecked()
        r["suffix_entry"].setEnabled(enabled)
        if enabled and not r["suffix_entry"].text():
            r["suffix_entry"].setText(self.file_suffix_edit.text())
        # Обновить выходной файл
        vn = r["video_combo"].currentText()
        if vn and vn != "— снять выбор —":
            prefix = self._get_prefix(r)
            suffix = self._get_suffix(r)
            new_name = f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv"
            old_name = r["output_entry"].text()
            if old_name and old_name != new_name:
                self._warn_orphan_output(old_name, new_name)
            r["output_entry"].setText(new_name)
        self.schedule_autosave()

    def _get_prefix(self, r):
        """Получить префикс для имени выходного файла (в начале)."""
        if r["prefix_cb"].isChecked() and r["prefix_entry"].text():
            return r["prefix_entry"].text()
        return self.file_prefix_edit.text()

    def _get_suffix(self, r):
        """Получить суффикс для имени выходного файла (в конце)."""
        if r["suffix_cb"].isChecked() and r["suffix_entry"].text():
            return r["suffix_entry"].text()
        return self.file_suffix_edit.text()

    def _get_all_output_names(self, r):
        """Собрать все имена выходных файлов: основной + extra_videos."""
        names = []
        main = r["output_entry"].text()
        if main:
            names.append(main)
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        for ev in r.get("extra_videos", []):
            vn = ev.get("video", "") or (os.path.basename(ev.get("video_full_path", "")) if ev.get("video_full_path") else "")
            if vn:
                names.append(f"{prefix}{os.path.splitext(vn)[0]}{suffix}.mkv")
        return names

    def _output_size_label(self, r, dir_path):
        """Суммарный размер и количество выходных файлов в папке.
        Возвращает (size_str, count_suffix). count_suffix = ' (N)' если N>=2, иначе ''."""
        names = self._get_all_output_names(r)
        total, count = 0, 0
        for name in names:
            p = os.path.join(dir_path, name)
            if os.path.isfile(p):
                try:
                    total += os.path.getsize(p)
                except Exception:
                    pass
                count += 1
        sz = _format_bytes_size(total)
        cnt = f" ({count})" if count >= 2 else ""
        return sz, cnt

    def _count_pending_outputs(self, r):
        """Сколько выходных файлов готовы к обработке (видео-источник есть, выход ещё не создан).
        Зеркалирует логику _build_task_refs: пропускает файлы уже в тесте или результате."""
        tp = self.test_path_edit.text()
        op = self.output_path_edit.text()
        vp = self.video_path_edit.text()
        prefix = self._get_prefix(r)
        suffix = self._get_suffix(r)
        an = self._audio_filename(r)
        fp = r["folder_path"]
        audio_ok = bool(an and os.path.isfile(os.path.join(fp, an)))
        _has_extra = any(ev.get("video") or ev.get("video_full_path") for ev in r.get("extra_videos", []))
        if not audio_ok:
            if _has_extra:
                self.log(f"[DIAG] _count_pending: audio_ok=False, an='{an}', fp='{fp}', "
                         f"path='{os.path.join(fp, an) if an else '?'}'")
            return 0
        pending = 0
        # Основное видео
        vn = r["video_combo"].currentText()
        vfp = r.get("video_full_path") or (os.path.join(vp, vn) if vp and vn and vn != "— снять выбор —" else "")
        on = r["output_entry"].text()
        if vn and vn != "— снять выбор —" and vfp and os.path.isfile(vfp) and on:
            if not (op and os.path.isfile(os.path.join(op, on))) and not (tp and os.path.isfile(os.path.join(tp, on))):
                pending += 1
        # Дополнительные видео
        for ev in r.get("extra_videos", []):
            ev_v = ev.get("video", "")
            ev_vfp = ev.get("video_full_path", "")
            if not ev_vfp:
                ev_vfp = os.path.join(vp, ev_v) if vp and ev_v else ""
            ev_vn = ev_v or (os.path.basename(ev_vfp) if ev_vfp else "")
            if ev_vfp and os.path.isfile(ev_vfp) and ev_vn:
                ev_out = f"{prefix}{os.path.splitext(ev_vn)[0]}{suffix}.mkv"
                if not (op and os.path.isfile(os.path.join(op, ev_out))) and not (tp and os.path.isfile(os.path.join(tp, ev_out))):
                    pending += 1
            elif (ev_v or ev_vfp) and _has_extra:
                self.log(f"[DIAG] extra pending skip: v='{ev_v}', vfp='{ev_vfp}', "
                         f"exists={os.path.isfile(ev_vfp) if ev_vfp else '?'}, vn='{ev_vn}'")
        return pending

    @staticmethod
    def _format_duration(dur_sec):
        """Форматирование секунд в '01:47:09 / 107 мин.'"""
        dur_sec = int(dur_sec)
        if dur_sec <= 0:
            return ""
        h, rem = divmod(dur_sec, 3600)
        m, s = divmod(rem, 60)
        total_min = (dur_sec + 30) // 60  # округление по правилам (>=30 сек → вверх)
        return f"{h:02d}:{m:02d}:{s:02d} / {total_min} мин."

    def _get_video_duration(self, filepath):
        """Получить длительность видео через pymediainfo или mkvmerge."""
        if not filepath or not os.path.exists(filepath):
            self.log(f"[DUR] Файл не найден: {filepath}")
            return ""

        self.log(f"[DUR] Проверяю: {os.path.basename(filepath)}")

        # 1) pymediainfo
        _init_mediainfo()
        self.log(f"[DUR] pymediainfo: {'OK' if HAS_MEDIAINFO else 'НЕТ'}")
        if HAS_MEDIAINFO:
            try:
                mi = MediaInfo.parse(filepath)
                self.log(f"[DUR] треков: {len(mi.tracks)}")
                for track in mi.tracks:
                    dur = getattr(track, 'duration', None)
                    self.log(f"[DUR] {track.track_type}: duration={dur}")
                    if track.track_type == "General" and dur and float(dur) > 0:
                        res = self._format_duration(float(dur) / 1000)
                        self.log(f"[DUR] Результат: {res}")
                        return res
                for track in mi.tracks:
                    dur = getattr(track, 'duration', None)
                    if track.track_type == "Video" and dur and float(dur) > 0:
                        res = self._format_duration(float(dur) / 1000)
                        self.log(f"[DUR] Результат: {res}")
                        return res
            except Exception as e:
                self.log(f"[DUR] pymediainfo ошибка: {e}")

        # 2) mkvmerge -J (fallback)
        mkvmerge = self.mkvmerge_path_edit.text()
        self.log(f"[DUR] mkvmerge: {mkvmerge}")
        if mkvmerge and os.path.exists(mkvmerge):
            try:
                result = subprocess.run(
                    [mkvmerge, "-J", filepath],
                    capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.log(f"[DUR] mkvmerge код: {result.returncode}")
                if result.returncode in (0, 1):
                    info = json.loads(result.stdout)
                    dur_ns = info.get("container", {}).get("properties", {}).get("duration")
                    self.log(f"[DUR] container duration: {dur_ns}")
                    if dur_ns and int(dur_ns) > 0:
                        res = self._format_duration(int(dur_ns) / 1_000_000_000)
                        self.log(f"[DUR] Результат: {res}")
                        return res
                    for trk in info.get("tracks", []):
                        td = trk.get("properties", {}).get("duration")
                        if td and int(td) > 0:
                            res = self._format_duration(int(td) / 1_000_000_000)
                            self.log(f"[DUR] Результат (track): {res}")
                            return res
            except Exception as e:
                self.log(f"[DUR] Ошибка mkvmerge: {e}")

        self.log("[DUR] Не удалось определить")
        return ""

    def _get_track_name(self, r):
        """Имя аудио дорожки в MKV файле. Per-film override приоритетнее настроек по умолчанию."""
        if r.get("custom_track_name_enabled") and r.get("custom_track_name"):
            return r["custom_track_name"]
        return self.track_name_edit.text()

    def _open_torrent_url(self, fn):
        r = self._find_row(fn)
        if not r: return
        url = r["torrent_entry"].text().strip()
        if not url: return
        if not url.startswith("http"): url = "https://" + url
        webbrowser.open(url)

    def _open_forum_url(self, fn):
        """Открыть ссылку на форум. Если ссылки нет — поиск по названию (как _search_russdub)."""
        r = self._find_row(fn)
        if not r: return
        url = r["forum_entry"].text().strip()
        if url:
            if not url.startswith("http"): url = "https://" + url
            webbrowser.open(url)
        else:
            self._search_russdub(fn)

    def _open_or_search_kinopoisk(self, fn):
        """Открыть ссылку на Кинопоиск. Если ссылки нет — поиск по названию и году."""
        r = self._find_row(fn)
        if not r: return
        url = r.get("kinopoisk_url", "").strip()
        if url:
            if not url.startswith("http"): url = "https://" + url
            webbrowser.open(url)
        else:
            self._search_kinopoisk(fn)

    def _update_forum_open_btn(self, r):
        """Обновить кнопку форума в таблице: → (есть URL) ↔ иконка russdub+лупа (нет URL)."""
        btn = r.get("forum_open_btn")
        if not btn: return
        url = r.get("forum_entry")
        has_url = bool(url and url.text().strip())
        if has_url:
            btn.setIcon(QIcon())
            btn.setText("→")
            btn.setToolTip("Открыть ссылку на форум в браузере")
        else:
            btn.setText("")
            _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "russdub_icon.png")
            if os.path.isfile(_icon):
                btn.setIcon(_make_kp_search_icon(_icon, 48, mag_scale=0.42))
                btn.setIconSize(QSize(20, 20))
            btn.setToolTip("Поиск на форуме russdub по названию\nЗапрос: «название + год + завершен»")

    def _update_kp_btn_icon(self, r):
        """Обновить кнопку КП в таблице: → (есть URL) ↔ иконка+лупа (нет URL)."""
        btn = r.get("kp_btn")
        if not btn: return
        url = r.get("kinopoisk_url", "").strip()
        if url:
            # Есть ссылка — стрелка (как в форуме)
            btn.setIcon(QIcon())
            btn.setText("→")
            btn.setToolTip("Открыть страницу на Кинопоиске")
        else:
            # Нет ссылки — иконка КП с лупой (поиск)
            btn.setText("")
            _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_icon.png")
            if os.path.isfile(_icon):
                btn.setIcon(_make_kp_search_icon(_icon, 48, mag_scale=0.42))
                btn.setIconSize(QSize(20, 20))
            btn.setToolTip("Поиск на Кинопоиске по названию")

    def _open_kinopoisk_url(self, fn):
        r = self._find_row(fn)
        if not r: return
        url = r.get("kinopoisk_url", "").strip()
        if not url: return
        if not url.startswith("http"): url = "https://" + url
        webbrowser.open(url)

    def _show_film_search_error(self, fn, msg):
        """Показать ошибку в блоке 'Данные о фильме' и скрыть через 15 сек."""
        if fn not in self._open_tabs:
            return
        tw = self._open_tabs[fn].get("widgets", {})
        err_label = tw.get("film_error_label")
        if err_label:
            err_label.setText(msg)
            err_label.setVisible(True)
            QTimer.singleShot(15000, lambda: err_label.setVisible(False) if err_label else None)

    def _search_kinopoisk(self, fn):
        """Поиск фильма на Кинопоиске по названию и году. Если название пустое — по имени папки."""
        r = self._find_row(fn)
        if not r: return
        title = r["title_entry"].text().strip()
        year = r["year_entry"].text().strip()
        if not title:
            title = r.get("folder_name", "")
        if not title:
            QMessageBox.warning(self, "Поиск на Кинопоиске",
                                f"Не удалось выполнить поиск.\n\n"
                                f"Поле «Название» пустое на вкладке «{fn}»\n"
                                f"в блоке «Данные о фильме».\n\n"
                                f"Заполните название и нажмите поиск ещё раз.")
            return
        query = f"{title} ({year})" if year else title
        url = f"https://www.kinopoisk.ru/index.php?kp_query={urllib.parse.quote(query)}"
        webbrowser.open(url)

    def _search_rutracker(self, fn):
        """Поиск фильма на RuTracker по названию и году."""
        r = self._find_row(fn)
        if not r: return
        title = r["title_entry"].text().strip()
        year = r["year_entry"].text().strip()
        if not title:
            QMessageBox.warning(self, "Поиск на RuTracker",
                                f"Не удалось выполнить поиск.\n\n"
                                f"Поле «Название» пустое на вкладке «{fn}»\n"
                                f"в блоке «Данные о фильме».\n\n"
                                f"Заполните название и нажмите поиск ещё раз.")
            return
        query = f"{title} ({year})" if year else title
        url = f"https://rutracker.org/forum/tracker.php?nm={urllib.parse.quote(query)}&o=7&s=2"
        webbrowser.open(url)

    def _search_russdub(self, fn):
        """Поиск фильма на форуме RussDub по названию."""
        r = self._find_row(fn)
        if not r: return
        title = r["title_entry"].text().strip()
        if not title:
            QMessageBox.warning(self, "Поиск на RussDub",
                                f"Не удалось выполнить поиск.\n\n"
                                f"Поле «Название» пустое на вкладке «{fn}»\n"
                                f"в блоке «Данные о фильме».\n\n"
                                f"Заполните название и нажмите поиск ещё раз.")
            return
        year = r["year_entry"].text().strip()
        q = f"{title} {year} завершен" if year else f"{title} завершен"
        url = f"https://russdub.ru:22223/search.php?keywords={urllib.parse.quote(q)}"
        webbrowser.open(url)

    # ──────────────────────────────────
    #  Бэкапы _meta_backup.json
    # ──────────────────────────────────
    def _restore_backup(self, fn):
        """Восстановить бэкап: текущие данные → backup/, бэкап → основные."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        backup_path = os.path.join(fp, "_meta_backup.json")
        if not os.path.isfile(backup_path):
            self.log(f"[BACKUP] Нет бэкапа для «{fn}»")
            return
        # Подтверждение
        ans = QMessageBox.question(self, "Восстановить бэкап",
            f"Восстановить данные из бэкапа для «{fn}»?\n\n"
            "Текущие данные будут перемещены в архив бэкапов,\n"
            "а данные из бэкапа станут основными.")
        if ans != QMessageBox.Yes:
            return
        # Загрузить бэкап
        backup_data = self._load_meta_backup_from_folder(fp)
        if not backup_data:
            return
        # Сохранить текущие данные как архивный бэкап (перезаписать _meta_backup.json текущими данными и переместить в backup/)
        current_meta = self._load_meta_from_folder(fp)
        if current_meta:
            current_meta["_backup_reason"] = "заменён восстановлением из бэкапа"
            current_meta["_backup_created"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(current_meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        # Переместить _meta_backup.json (с текущими данными) в архив backup/
        self._move_backup_to_archive(fp)
        # Применить бэкап
        self._apply_meta_to_row(r, backup_data)
        r["has_meta_backup"] = False
        self.schedule_autosave()
        self.log(f"[BACKUP] Восстановлен бэкап для «{fn}» — текущие данные → архив, бэкап → основные")
        # Переоткрыть вкладку для обновления UI
        self._reopen_record_tab(fn)

    def _delete_backup(self, fn):
        """Переместить _meta_backup.json в папку backup/ (архив старых бэкапов)."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        backup_path = os.path.join(fp, "_meta_backup.json")
        if not os.path.isfile(backup_path):
            return
        ans = QMessageBox.question(self, "Удалить бэкап",
            f"Удалить активный бэкап для «{fn}»?\n\n"
            "Файл будет перемещён в архив старых бэкапов (backup/).")
        if ans != QMessageBox.Yes:
            return
        self._move_backup_to_archive(fp)
        r["has_meta_backup"] = False
        self.log(f"[BACKUP] Бэкап для «{fn}» перемещён в архив")
        # Переоткрыть вкладку для обновления UI
        self._reopen_record_tab(fn)

    def _show_old_backups(self, fn):
        """Показать старые бэкапы во вкладке правой панели (right_tabs)."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        old_backups = self._list_old_backups(fp)
        if not old_backups:
            QMessageBox.information(self, "Старые бекапы", f"Нет архивных бэкапов для «{fn}».")
            return

        # Получить right_tabs из открытой вкладки
        tab_data = self._open_tabs.get(fn)
        if not tab_data:
            return
        right_tabs = tab_data["widgets"].get("right_tabs")
        if not right_tabs:
            return

        # Удалить существующую вкладку "Старые бекапы" если есть
        for i in range(right_tabs.count()):
            if right_tabs.tabText(i).startswith("📂"):
                right_tabs.removeTab(i)
                break

        # Создать виджет вкладки
        old_bk_widget = QWidget()
        old_bk_layout = QVBoxLayout(old_bk_widget)
        old_bk_layout.setContentsMargins(4, 4, 4, 4)
        old_bk_layout.setSpacing(4)

        # Пояснительная строка
        info_lbl = QLabel(
            f"Архив старых бэкапов настроек из папки <b>backup/</b> ({len(old_backups)} из макс. 5). "
            "Хранятся автоматически — при появлении 6-го самый старый удаляется.")
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color:#555; font-size:9pt; padding:2px 4px; background:#f8f8f0; border:1px solid #ddd; border-radius:3px;")
        info_lbl.setToolTip("Бэкапы создаются автоматически при разрешении конфликтов или восстановлении данных.\n"
            "Максимум хранится 5 архивных бэкапов. При превышении лимита самый старый удаляется.\n"
            "Ручное удаление отдельных бэкапов не предусмотрено — ротация полностью автоматическая.")
        old_bk_layout.addWidget(info_lbl)

        # Горизонтальные вкладки: каждый бэкап = вкладка с датой
        sub_tabs = QTabWidget(old_bk_widget)
        sub_tabs.setToolTip("Каждая вкладка — один старый бэкап с датой создания")
        old_bk_layout.addWidget(sub_tabs)

        fields_display = [
            ("Название", "title"), ("Год", "year"),
            ("Задержка", "delay"), ("Пароль архива", "archive_password"),
            ("Форум russdub", "forum_url"), ("Торрент видео", "torrent_url"),
            ("Торрент аудио", "audio_torrent_url"), ("Постер", "poster_url"),
            ("Кинопоиск", "kinopoisk_url"), ("Абонемент год", "sub_year"),
            ("Абонемент месяц", "sub_month"), ("Приоритет", "sort_priority"),
            ("Дата обработки", "processed_date"),
            ("Видео ожидается", "video_pending"), ("NEW", "is_new"),
            ("Префикс", "custom_prefix"), ("Суффикс", "custom_suffix"),
        ]

        for fname_bk, date_str_ru, bk_data in old_backups:
            tab = QWidget()
            tab_lay = QVBoxLayout(tab)
            tab_lay.setContentsMargins(4, 4, 4, 4)
            tab_lay.setSpacing(2)

            reason = bk_data.get("_backup_reason", "")
            if reason:
                reason_lbl = QLabel(f"Причина создания бэкапа: {reason}")
                reason_lbl.setStyleSheet("color:#8B4513; font-size:9pt;")
                reason_lbl.setToolTip("Причина записывается автоматически в момент создания бэкапа:\n"
                    "— при обнаружении расхождения данных между базой и файлом в папке фильма\n"
                    "— при восстановлении из другого бэкапа (текущие данные сохраняются как бэкап)")
                tab_lay.addWidget(reason_lbl)

            # Заголовки
            hdr = QHBoxLayout()
            hdr.setSpacing(4)
            h1 = QLabel("<b>Поле</b>"); h1.setFixedWidth(110); hdr.addWidget(h1)
            h2 = QLabel("<b>Бэкап</b>"); h2.setStyleSheet("color:#cc0000;"); hdr.addWidget(h2)
            h3 = QLabel("<b>Текущее</b>"); h3.setStyleSheet("color:#006600;"); hdr.addWidget(h3)
            tab_lay.addLayout(hdr)

            # Сетка значений
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, (label, key) in enumerate(fields_display):
                lbl = QLabel(f"<b>{label}:</b>")
                lbl.setTextFormat(Qt.RichText)
                lbl.setFixedWidth(110)
                grid.addWidget(lbl, i, 0)
                bk_val = str(bk_data.get(key, ""))
                cur_val = self._get_current_field_value(r, key)
                bk_val_n = self._normalize_meta_val(bk_val)
                cur_val_n = self._normalize_meta_val(cur_val)
                bk_le = QLineEdit(bk_val); bk_le.setReadOnly(True)
                bk_le.setToolTip(f"Значение из бэкапа: {label}")
                if bk_val_n != cur_val_n:
                    bk_le.setStyleSheet("background-color:#fff0f0; border:1px solid #ff8888;")
                else:
                    bk_le.setStyleSheet("background-color:#f0fff0; border:1px solid #88cc88;")
                grid.addWidget(bk_le, i, 1)
                cur_le = QLineEdit(cur_val); cur_le.setReadOnly(True)
                cur_le.setToolTip(f"Текущее значение: {label}")
                cur_le.setStyleSheet("background-color:#f8f8f8;")
                grid.addWidget(cur_le, i, 2)
            tab_lay.addLayout(grid)
            tab_lay.addStretch()
            sub_tabs.addTab(tab, date_str_ru)

        # Кнопки внизу
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        restore_btn = QPushButton("Восстановить выбранный бэкап")
        restore_btn.setStyleSheet("QPushButton{background-color:#c8f0c8; font-weight:bold; padding:6px 12px;} QPushButton:hover{background-color:#99ff99;}")
        restore_btn.setToolTip("Текущие данные → архив бэкапов, выбранный старый бэкап → основные данные")

        def _do_restore_old():
            idx = sub_tabs.currentIndex()
            if idx < 0 or idx >= len(old_backups):
                return
            fname_sel, date_sel, bk_data_sel = old_backups[idx]
            ans = QMessageBox.question(self, "Восстановить старый бэкап",
                f"Восстановить данные из бэкапа от {date_sel}?\n\n"
                "Текущие данные будут перемещены в архив бэкапов.")
            if ans != QMessageBox.Yes:
                return
            rr = self._find_row(fn)
            if not rr:
                return
            ffp = rr.get("folder_path", "")
            # Сохранить текущие данные как бэкап
            current_meta = self._load_meta_from_folder(ffp)
            if current_meta:
                current_meta["_backup_reason"] = "заменён восстановлением из старого бэкапа"
                current_meta["_backup_created"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                bk_tmp_path = os.path.join(ffp, "_meta_backup.json")
                try:
                    with open(bk_tmp_path, "w", encoding="utf-8") as f:
                        json.dump(current_meta, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                self._move_backup_to_archive(ffp)
            # Применить старый бэкап
            self._apply_meta_to_row(rr, bk_data_sel)
            self.schedule_autosave()
            self.log(f"[BACKUP] Восстановлен старый бэкап от {date_sel} для «{fn}»")
            self._reopen_record_tab(fn)

        restore_btn.clicked.connect(_do_restore_old)
        btn_row.addWidget(restore_btn)

        close_old_btn = QPushButton("Закрыть вкладку")
        close_old_btn.setStyleSheet("QPushButton{padding:6px 12px;}")
        close_old_btn.setToolTip("Закрыть вкладку старых бэкапов и вернуться к txt")

        def _close_old_backups_tab():
            for i in range(right_tabs.count()):
                if right_tabs.tabText(i).startswith("📂"):
                    right_tabs.removeTab(i)
                    right_tabs.setCurrentIndex(0)
                    break
        close_old_btn.clicked.connect(_close_old_backups_tab)
        btn_row.addWidget(close_old_btn)
        btn_row.addStretch()
        old_bk_layout.addLayout(btn_row)

        # Добавить вкладку в right_tabs
        tab_idx = right_tabs.addTab(old_bk_widget, f"📂 Старые бекапы ({len(old_backups)})")
        right_tabs.tabBar().setTabTextColor(tab_idx, QColor("#6a0dad"))
        right_tabs.setCurrentIndex(tab_idx)

    def _open_audio_torrent_url(self, fn):
        r = self._find_row(fn)
        if not r: return
        url = r.get("audio_torrent_url", "").strip()
        if not url: return
        if not url.startswith("http"): url = "https://" + url
        webbrowser.open(url)

    def _open_video_dir_from_tab(self, fn):
        """Открыть папку видео источника из вкладки."""
        r = self._find_row(fn)
        if not r: return
        vfp = r.get("video_full_path", "")
        if vfp and os.path.isfile(vfp):
            os.startfile(os.path.dirname(vfp))
        elif self.video_path_edit.text() and os.path.isdir(self.video_path_edit.text()):
            os.startfile(self.video_path_edit.text())

    def _open_output_dir_from_tab(self, fn):
        """Открыть папку с результатом (тест или выходная).
        Приоритет: результат (если файл там) → тест (если файл там) → тест (папка) → результат (папка)."""
        r = self._find_row(fn)
        if not r: return
        name = r["output_entry"].text()
        op = self.output_path_edit.text()
        tp = self.test_path_edit.text()
        # Если файл найден — открыть ту папку где он лежит
        if name:
            if op and os.path.isfile(os.path.join(op, name)):
                os.startfile(op); return
            if tp and os.path.isfile(os.path.join(tp, name)):
                os.startfile(tp); return
        # Файл не найден — открыть папку тест или результат
        if tp and os.path.isdir(tp):
            os.startfile(tp)
        elif op and os.path.isdir(op):
            os.startfile(op)

    def _open_output_dir_for_file(self, file_name, output_path, test_path):
        """Открыть папку содержащую конкретный выходной файл (для extra videos).
        Приоритет: результат → тест → тест (папка) → результат (папка)."""
        if file_name:
            if output_path and os.path.isfile(os.path.join(output_path, file_name)):
                os.startfile(output_path); return
            if test_path and os.path.isfile(os.path.join(test_path, file_name)):
                os.startfile(test_path); return
        if test_path and os.path.isdir(test_path):
            os.startfile(test_path)
        elif output_path and os.path.isdir(output_path):
            os.startfile(output_path)

    # ──────────────────────────────────
    #  Переключение вкладок / клик по строке
    # ──────────────────────────────────
    def _on_extra_video_fps_changed(self, fn, idx, val):
        """Изменение FPS для доп. видео."""
        r = self._find_row(fn)
        if not r: return
        evs = r.get("extra_videos", [])
        if idx < len(evs):
            evs[idx]["fps"] = val
            self.schedule_autosave()

    def _on_extra_video_affix_changed(self, fn, idx, field, val):
        """Изменение prefix/suffix для доп. видео.
        НЕ вызывает _update_extra_output_names — это пересоздаст виджеты
        и убьёт поле ввода. Имя пересчитается при следующем rebuild."""
        r = self._find_row(fn)
        if not r: return
        evs = r.get("extra_videos", [])
        if idx < len(evs):
            evs[idx][field] = val
            self.schedule_autosave()

    def _on_tab_splitter_moved(self, pos, idx):
        """При изменении ширины txt-панели — применить ко ВСЕМ открытым вкладкам."""
        sender = self.sender()
        if not isinstance(sender, QSplitter):
            return
        new_sizes = sender.sizes()
        self._tab_splitter_sizes = new_sizes
        for fn, tab_data in self._open_tabs.items():
            w = tab_data.get("widget")
            if w and isinstance(w, QSplitter) and w is not sender:
                w.setSizes(new_sizes)
        self.schedule_autosave()

    def _sync_all_tabs_to_table(self):
        """Синхронизировать данные из открытых вкладок фильмов в таблицу."""
        for fn, tab_info in self._open_tabs.items():
            r = self._find_row(fn)
            if not r:
                continue
            tw = tab_info["widgets"]
            # Название
            te = tw.get("title_entry")
            if te:
                r["title_entry"].blockSignals(True)
                r["title_entry"].setText(te.text())
                r["title_entry"].blockSignals(False)
            # Год
            ye = tw.get("year_entry")
            if ye:
                r["year_entry"].blockSignals(True)
                r["year_entry"].setText(ye.text())
                r["year_entry"].blockSignals(False)
            # Форум russdub
            fe = tw.get("forum_entry")
            if fe:
                r["forum_entry"].blockSignals(True)
                r["forum_entry"].setText(fe.text())
                r["forum_entry"].blockSignals(False)
                self._update_forum_open_btn(r)
            # Пароль
            pe = tw.get("password_entry")
            if pe:
                r["password_entry"].blockSignals(True)
                r["password_entry"].setText(pe.text())
                r["password_entry"].blockSignals(False)
            # Торрент видео
            tv = tw.get("torrent_entry")
            if tv:
                r["torrent_entry"].blockSignals(True)
                r["torrent_entry"].setText(tv.text())
                r["torrent_entry"].blockSignals(False)
            # Постер URL
            pu = tw.get("poster_url_entry")
            if pu:
                r["poster_url"] = pu.text().strip()
            # Кинопоиск URL
            kp = tw.get("kinopoisk_entry")
            if kp:
                r["kinopoisk_url"] = kp.text().strip()
                self._update_kp_btn_icon(r)
            # Абонемент
            sy = tw.get("sub_year")
            if sy:
                r["sub_year"].blockSignals(True)
                r["sub_year"].setCurrentText(sy.currentText())
                r["sub_year"].blockSignals(False)
            sm = tw.get("sub_month")
            if sm:
                r["sub_month"].blockSignals(True)
                r["sub_month"].setCurrentText(sm.currentText())
                r["sub_month"].blockSignals(False)
        self._update_status_filter_counts()

    def _on_tab_changed(self, index):
        """При переключении вкладок — обновить батч-панель, скрыть/показать фильтры."""
        if index == 0:
            # Переключились на таблицу — синхронизировать данные из вкладок фильмов
            self._sync_all_tabs_to_table()
        self._update_txt_panel_visibility()
        self._update_scan_button_for_tab()
        self._update_select_open_btn()
        self._update_batch_buttons()

    def _update_txt_panel_visibility(self):
        """Скрыть блок фильтрации если открыта вкладка записи, показать если таблица."""
        on_table = self.tab_widget.currentIndex() == 0
        if hasattr(self, 'filter_group'):
            self.filter_group.setVisible(on_table)
        if hasattr(self, 'status_bar_widget'):
            self.status_bar_widget.setVisible(on_table)

    def _update_scan_button_for_tab(self):
        """Переключить видимость кнопок при смене вкладок."""
        if not hasattr(self, 'scan_all_btn'):
            return
        on_table = self.tab_widget.currentIndex() == 0
        # "Выровнять колонки" — только на таблице
        self.fit_cols_btn.setVisible(on_table)

    def _on_cell_clicked(self, row, col):
        """Клик по ячейке таблицы — подсветить строку, закрыть TXT если другая строка."""
        for r in self.rows:
            if r["row_index"] == row:
                self._highlight_row(r)
                # Закрыть TXT панель при выборе ДРУГОЙ строки
                if self._active_txt_fn and self._active_txt_fn != r["folder_name"]:
                    self._close_txt_panel()
                return

    def _highlight_row(self, r):
        """Подсветить выбранную строку, снять подсветку с предыдущей."""
        prev = self._highlighted_row
        if prev is not None and prev is not r and prev in self.rows:
            restore_color = prev.get("_status_bg", prev["base_color"])
            prev["_status_bg"] = None  # Сбросить кэш чтобы _set_row_bg не пропустил обновление
            self._set_row_bg(prev, restore_color)
        self._highlighted_row = r
        self._set_row_bg(r, COLOR_HIGHLIGHT, _is_highlight=True)

    # ──────────────────────────────────
    #  Вкладки записей
    # ──────────────────────────────────
    def _find_tab_index(self, fn):
        """Найти индекс вкладки по folder_name (через tabText)."""
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == fn:
                return i
        return -1

    def _install_anti_flash_hook(self):
        """Установить Windows CBT-хук: убрать WS_VISIBLE у top-level окон при создании.
        Возвращает функцию unhook() для снятия хука."""
        if sys.platform != "win32":
            return lambda: None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class CREATESTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("lpCreateParams", ctypes.c_void_p),
                    ("hInstance", wintypes.HANDLE),
                    ("hMenu", wintypes.HMENU),
                    ("hwndParent", wintypes.HWND),
                    ("cy", ctypes.c_int), ("cx", ctypes.c_int),
                    ("y", ctypes.c_int), ("x", ctypes.c_int),
                    ("style", wintypes.DWORD),
                    ("lpszName", ctypes.c_wchar_p),
                    ("lpszClass", ctypes.c_wchar_p),
                    ("dwExStyle", wintypes.DWORD),
                ]

            class CBT_CREATEWNDW(ctypes.Structure):
                _fields_ = [
                    ("lpcs", ctypes.POINTER(CREATESTRUCTW)),
                    ("hwndInsertAfter", wintypes.HWND),
                ]

            WH_CBT = 5
            HCBT_CREATEWND = 3
            WS_VISIBLE = 0x10000000
            WS_CHILD = 0x40000000
            HOOKPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            _main_hwnd = int(self.winId())

            @HOOKPROC
            def _cbt_proc(nCode, wParam, lParam):
                if nCode == HCBT_CREATEWND:
                    try:
                        cbt = ctypes.cast(lParam, ctypes.POINTER(CBT_CREATEWNDW)).contents
                        cs = cbt.lpcs.contents
                        # Top-level окно (без parent, не child) с WS_VISIBLE — убрать видимость
                        if not cs.hwndParent and (cs.style & WS_VISIBLE) and not (cs.style & WS_CHILD):
                            cs.style &= ~WS_VISIBLE
                    except Exception:
                        pass
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            # Сохранить ссылку на callback чтобы GC не удалил
            self._anti_flash_proc = _cbt_proc
            tid = kernel32.GetCurrentThreadId()
            hook = user32.SetWindowsHookExW(WH_CBT, _cbt_proc, None, tid)
            if not hook:
                return lambda: None

            def _unhook():
                try:
                    user32.UnhookWindowsHookEx(hook)
                except Exception:
                    pass
                self._anti_flash_proc = None
            return _unhook
        except Exception:
            return lambda: None

    def _open_record_tab(self, fn):
        """Открыть вкладку редактирования записи. Если уже открыта — переключиться."""
        if fn in self._open_tabs:
            idx = self._find_tab_index(fn)
            if idx >= 0:
                self.tab_widget.setCurrentIndex(idx)
            else:
                # Вкладка потерялась — удалить запись и пересоздать
                del self._open_tabs[fn]
                self._open_record_tab(fn)
            return
        r = self._find_row(fn)
        if not r:
            self.log(f"[TAB] Запись не найдена: {fn}")
            return
        try:
            self.setUpdatesEnabled(False)
            _unhook = self._install_anti_flash_hook()
            self._create_record_tab(fn, r)
        except Exception as e:
            self.log(f"[TAB] Ошибка открытия вкладки «{fn}»: {e}")
            import traceback; self.log(traceback.format_exc())
        finally:
            _unhook()
            self.setUpdatesEnabled(True)

    def _create_record_tab(self, fn, r):
        """Создать содержимое вкладки записи."""
        # === Главный виджет вкладки: форма слева, txt справа ===
        tab_root = QSplitter(Qt.Horizontal)
        tab_root.setProperty("folder_name", fn)
        # Сразу добавить в tab_widget — tab_root перестаёт быть top-level окном,
        # все дочерние виджеты будут внутри иерархии tab_widget (анти-мигание).
        # setCurrentIndex вызывается в конце метода — пока вкладка невидима.
        _tab_idx = self.tab_widget.addTab(tab_root, fn)

        # --- ЛЕВАЯ ЧАСТЬ: контейнер с кнопками сверху и scroll снизу ---
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.setSpacing(2)

        # --- Вычисление условий для кнопок (как в _update_row_status) ---
        fp = r["folder_path"]
        vp = self.video_path_edit.text()
        op = self.output_path_edit.text()
        tp = self.test_path_edit.text()
        audio_name = self._audio_filename(r)
        video_name = r["video_combo"].currentText()
        output_name = r["output_entry"].text()
        audio_ok = bool(audio_name and os.path.isfile(os.path.join(fp, audio_name)))
        video_ok = False
        if video_name and video_name != "— снять выбор —":
            vfp = r.get("video_full_path") or (os.path.join(vp, video_name) if vp else "")
            video_ok = bool(vfp and os.path.isfile(vfp))
        output_exists = bool(output_name and op and os.path.isfile(os.path.join(op, output_name)))
        in_test = bool(output_name and tp and not output_exists and os.path.isfile(os.path.join(tp, output_name)))
        has_archive = bool(r.get("archive_file"))
        _tab_pending = self._count_pending_outputs(r)
        _tab_extra_src = sum(1 for ev in r.get("extra_videos", []) if ev.get("video") or ev.get("video_full_path"))
        _tab_sp = r.get("sort_priority")
        can_process = _tab_sp == 0 or _tab_pending > 0
        # Запасная проверка: основной обработан, есть доп. видео с источником,
        # и хотя бы один доп. выходной файл ещё НЕ в тесте/результате
        if not can_process and _tab_sp in (-1, 4) and _tab_extra_src > 0:
            _fb_prefix = self._get_prefix(r)
            _fb_suffix = self._get_suffix(r)
            _fb_pending = 0
            for _fb_ev in r.get("extra_videos", []):
                _fb_v = _fb_ev.get("video", "")
                _fb_vfp = _fb_ev.get("video_full_path", "")
                _fb_vn = _fb_v or (os.path.basename(_fb_vfp) if _fb_vfp else "")
                if _fb_vn:
                    _fb_out = f"{_fb_prefix}{os.path.splitext(_fb_vn)[0]}{_fb_suffix}.mkv"
                    if not (op and os.path.isfile(os.path.join(op, _fb_out))) and \
                       not (tp and os.path.isfile(os.path.join(tp, _fb_out))):
                        _fb_pending += 1
            if _fb_pending > 0:
                can_process = True
                _tab_pending = _fb_pending

        tab_widgets = {}
        connections = []
        _btn_h = self._btn_h

        # --- Раннее определение наличия бэкапа (для кнопки вверху) ---
        _early_backup_exists = os.path.isfile(os.path.join(fp, "_meta_backup.json"))

        # --- Кнопка "⚠ Бэкап" вверху при конфликте ---
        backup_top_btn = None
        if _early_backup_exists:
            backup_top_btn = QPushButton("⚠ Бэкап — требуется решение")
            backup_top_btn.setStyleSheet(
                "QPushButton{background-color:#ffcccc; color:#cc0000; font-weight:bold; "
                "padding:6px 12px; border:2px solid #cc0000; border-radius:4px;} "
                "QPushButton:hover{background-color:#ff9999;}")
            backup_top_btn.setToolTip("Обнаружено расхождение данных. Нажмите чтобы перейти к бэкапу и принять решение.")
            left_layout.addWidget(backup_top_btn)

        # --- Хелперы для кнопок "Старые бекапы" и "Удалить папку" (используются в row1/row2/scroll) ---
        _old_backups = self._list_old_backups(fp)
        _old_backups_count = len(_old_backups)
        _ob_text = f"Старые бекапы ({_old_backups_count})" if _old_backups_count else "Старые бекапы"
        _ob_style = ("QPushButton{background-color:#e8e0f0; padding:4px 8px;} "
                     "QPushButton:hover{background-color:#d0c0e8;} "
                     "QPushButton:disabled{background-color:#f0f0f0; color:#999;}")
        _ob_tip = "Просмотр архива старых бэкапов настроек из папки backup/ в каталоге фильма"
        def _make_ob():
            b = QPushButton(_ob_text); b.setEnabled(_old_backups_count > 0)
            b.setStyleSheet(_ob_style); b.setToolTip(_ob_tip)
            b.clicked.connect(lambda _, f=fn: self._show_old_backups(f)); return b

        # (row1/row2 удалены — кнопки вынесены в верхнюю панель и на батч-панель)

        # --- Scroll area ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setSpacing(2)
        main_layout.setContentsMargins(4, 0, 4, 4)
        # --- Приоритет настроек ---
        # (priority_lbl удалён — настройки теперь на единой батч-панели)

        # === Блок russdub ===
        russdub_group = QGroupBox("russdub")
        russdub_group.setStyleSheet("QGroupBox { background-color: #e8f0fe; border: 1px solid #b0c4de; border-radius: 4px; margin-top: 10px; padding-top: 0px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        russdub_outer = QHBoxLayout(russdub_group)
        russdub_outer.setContentsMargins(0, 0, 0, 0)
        russdub_outer.setSpacing(0)
        russdub_left = QWidget()
        russdub_layout = QVBoxLayout(russdub_left)
        russdub_layout.setSpacing(2)
        russdub_layout.setContentsMargins(6, 22, 6, 4)
        russdub_left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        _lp = QLabel("Папка:")
        _lp.setToolTip("Имя папки аудио дорожки")
        row1.addWidget(_lp)
        folder_lbl = QLabel(fn)
        folder_lbl.setStyleSheet("font-weight:bold;")
        folder_lbl.setToolTip(f"Путь к папке аудио дорожки:\n{r.get('folder_path', '')}")
        row1.addWidget(folder_lbl)
        fp = r.get("folder_path", "")
        open_folder_btn = QPushButton("📁")
        open_folder_btn.setFont(BTN_FONT)
        open_folder_btn.setFixedWidth(28)
        open_folder_btn.setToolTip(f"Открыть папку аудио источника:\n{fp}")
        open_folder_btn.clicked.connect(lambda _, p=fp: os.startfile(p) if os.path.isdir(p) else None)
        row1.addWidget(open_folder_btn)
        row1.addSpacing(8)
        row1.addWidget(QLabel("Статус:"))
        _st_text = r["status_lbl"].text() if r.get("status_lbl") else ""
        tab_status_lbl = QLabel(_st_text)
        tab_status_lbl.setStyleSheet(self._status_text_style(_st_text))
        tab_widgets["status_lbl"] = tab_status_lbl
        row1.addWidget(tab_status_lbl)
        row1.addSpacing(8)
        row1.addWidget(QLabel("Создано:"))
        row1.addWidget(QLabel(r["date_created_lbl"].text() if r.get("date_created_lbl") else "—"))
        row1.addSpacing(8)
        row1.addWidget(QLabel("Дата обработки:"))
        _date_proc = r["date_lbl"].text() if r.get("date_lbl") else ""
        row1.addWidget(QLabel(_date_proc if _date_proc and _date_proc != "—" else "Нет"))
        row1.addSpacing(8)
        row1.addStretch()
        russdub_layout.addLayout(row1)

        # --- Ссылки + Абонемент ---
        row_links = QHBoxLayout()
        row_links.setSpacing(4)
        _lat = QLabel("Торрент аудио:")
        _lat.setToolTip("Ссылка на торрент с аудио дорожкой для скачивания")
        row_links.addWidget(_lat)
        tab_audio_torrent = QLineEdit(r.get("audio_torrent_url", ""))
        self._setup_auto_width(tab_audio_torrent, 200)
        tab_audio_torrent.setPlaceholderText("https://...")
        tab_audio_torrent.setToolTip("URL торрента с аудио дорожкой — нажмите → чтобы открыть в браузере")
        setup_url_validation(tab_audio_torrent)
        tab_widgets["audio_torrent_entry"] = tab_audio_torrent
        row_links.addWidget(tab_audio_torrent)
        atb = QPushButton("→"); atb.setFont(BTN_FONT); atb.setFixedSize(_btn_h, _btn_h)
        atb.setToolTip("Открыть ссылку на торрент аудио дорожки в браузере")
        atb.clicked.connect(lambda _, f=fn: self._open_audio_torrent_url(f))
        row_links.addWidget(atb)
        row_links.addSpacing(8)
        # Кнопка торрент файл аудио дорожки (перенесена из row_files)
        tor_files = r.get("tor_files", [])
        _has_tor = bool(tor_files)
        tor_open_btn = QPushButton(f"Торрент ({len(tor_files)})" if _has_tor else "Выбрать торрент файл")
        tor_open_btn.setFont(BTN_FONT)
        _qbt_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "qbittorrent_icon.png")
        if os.path.isfile(_qbt_icon_path):
            tor_open_btn.setIcon(QIcon(_qbt_icon_path))
        if _has_tor:
            tor_open_btn.setStyleSheet("color:green;")
            tor_open_btn.setToolTip(f"Торрент-файлов: {len(tor_files)}\n" + "\n".join(f"  • {f}" for f in tor_files))
            _tab_tor_menu = QMenu(tor_open_btn)
            for _tf in tor_files:
                _tp2 = os.path.join(r.get("folder_path", ""), _tf)
                _act = _tab_tor_menu.addAction(_tf)
                _act.triggered.connect((lambda p: lambda: os.startfile(p) if os.path.isfile(p) else None)(_tp2))
            tor_open_btn.setMenu(_tab_tor_menu)
        else:
            tor_open_btn.setToolTip("Выбрать .torrent файл аудио дорожки — он будет ПЕРЕМЕЩЁН в папку фильма")
            tor_open_btn.clicked.connect(lambda _, f=fn: self._move_torrent_to_folder(f))
        tab_widgets["tor_open_btn"] = tor_open_btn
        row_links.addWidget(tor_open_btn)
        row_links.addStretch()
        russdub_layout.addLayout(row_links)

        # --- Строка 2: Russdub + Абонемент ---
        row_links2 = QHBoxLayout()
        row_links2.setSpacing(4)
        _lf = QLabel("Форум russdub:")
        _lf.setToolTip("Ссылка на тему на форуме russdub.ru с описанием фильма")
        row_links2.addWidget(_lf)
        tab_forum = QLineEdit(r["forum_entry"].text() if r.get("forum_entry") else "")
        self._setup_auto_width(tab_forum, 200)
        tab_forum.setToolTip("URL темы на форуме russdub.ru — нажмите → чтобы открыть в браузере")
        setup_url_validation(tab_forum)
        tab_widgets["forum_entry"] = tab_forum
        row_links2.addWidget(tab_forum)
        # Чекбокс "короткий линк"
        tab_short_link_cb = QCheckBox("Кор.")
        tab_short_link_cb.setChecked(True)
        tab_short_link_cb.setToolTip("Автоматически сокращать ссылку russdub (убирать &p=...&hilit=...#p...)")
        row_links2.addWidget(tab_short_link_cb)
        def _on_tab_forum_changed(forum_entry=tab_forum, cb=tab_short_link_cb):
            if cb.isChecked():
                txt = forum_entry.text()
                shortened = shorten_russdub_url(txt)
                if shortened != txt:
                    forum_entry.blockSignals(True)
                    forum_entry.setText(shortened)
                    forum_entry.blockSignals(False)
                    forum_entry.textChanged.emit(shortened)
        tab_forum.editingFinished.connect(_on_tab_forum_changed)
        fb = QPushButton("→"); fb.setFont(BTN_FONT); fb.setFixedSize(_btn_h, _btn_h)
        fb.setToolTip("Открыть ссылку на форум russdub в браузере")
        fb.clicked.connect(lambda _, f=fn: self._open_forum_url(f))
        row_links2.addWidget(fb)
        # Кнопка поиска на RussDub
        rd_search = QPushButton(); rd_search.setFixedSize(_btn_h, _btn_h)
        _rd_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "russdub_icon.png")
        if os.path.isfile(_rd_icon_path):
            rd_search.setIcon(_make_kp_search_icon(_rd_icon_path, 48, mag_scale=0.42))
            rd_search.setIconSize(QSize(20, 20))
        rd_search.setToolTip("Поиск фильма на форуме RussDub\nЗапрос: «название + год + завершен» → russdub.ru/search.php")
        rd_search.clicked.connect(lambda _, f=fn: self._search_russdub(f))
        row_links2.addWidget(rd_search)
        row_links2.addSpacing(8)
        _lsub = QLabel("Абонемент:")
        _lsub.setToolTip("Год и месяц абонемента для этого фильма")
        row_links2.addWidget(_lsub)
        tab_sub_year = QComboBox(); tab_sub_year.setMaximumWidth(80)
        tab_sub_year.addItem("—"); tab_sub_year.addItems(_SUB_YEARS)
        tab_sub_year.setCurrentText(r["sub_year"].currentText())
        tab_sub_year.setToolTip("Год абонемента")
        tab_widgets["sub_year"] = tab_sub_year
        row_links2.addWidget(tab_sub_year)
        tab_sub_month = QComboBox(); tab_sub_month.setMaximumWidth(120)
        tab_sub_month.addItem("—"); tab_sub_month.addItems(_MONTHS_RU)
        tab_sub_month.setCurrentText(r["sub_month"].currentText())
        tab_sub_month.setToolTip("Месяц абонемента")
        tab_widgets["sub_month"] = tab_sub_month
        row_links2.addWidget(tab_sub_month)
        row_links2.addStretch()
        russdub_layout.addLayout(row_links2)

        # --- Файлы в папке фильма ---
        files_group = QGroupBox("Файлы в папке фильма")
        files_group.setToolTip("Файлы в папке аудио дорожки: архив, аудио, задержки")
        files_layout = QVBoxLayout(files_group)
        files_layout.setSpacing(2)
        files_layout.setContentsMargins(6, 14, 6, 4)
        row_files = QHBoxLayout()
        row_files.setSpacing(4)
        # Чекбокс + инпут для per-film track name (приоритетнее настроек по умолчанию)
        _tn_cb = QCheckBox("Имя дорожки:")
        _tn_cb.setToolTip("Задать имя аудио дорожки для этого фильма\nПриоритетнее глобальной настройки «Имя новой дорожки»")
        _tn_cb.setChecked(r.get("custom_track_name_enabled", False))
        _tn_edit = QLineEdit(r.get("custom_track_name", ""))
        _tn_edit.setMaximumWidth(120)
        _tn_edit.setPlaceholderText(self.track_name_edit.text())
        _tn_edit.setEnabled(_tn_cb.isChecked())
        _tn_edit.setToolTip("Имя аудио дорожки в MKV файле для этого фильма\nПриоритетнее глобальной настройки")
        tab_widgets["track_name_cb"] = _tn_cb
        tab_widgets["track_name_edit"] = _tn_edit
        def _on_track_name_cb(checked):
            _tn_edit.setEnabled(checked)
            rr = self._find_row(fn)
            if rr:
                rr["custom_track_name_enabled"] = checked
                _update_track_preview()
                self.schedule_autosave()
        def _on_track_name_edit(text):
            rr = self._find_row(fn)
            if rr:
                rr["custom_track_name"] = text
                _update_track_preview()
                self.schedule_autosave()
        _tn_cb.toggled.connect(_on_track_name_cb)
        _tn_edit.textChanged.connect(_on_track_name_edit)
        row_files.addWidget(_tn_cb)
        row_files.addWidget(_tn_edit)
        row_files.addSpacing(8)

        archive_name = r.get("archive_file", "")
        _arc_lbl = QLabel("Архив:")
        _arc_lbl.setToolTip("Архив или файл без расширения с аудио дорожкой для фильма\nПоддерживаются: .rar, .7z, .zip и файлы без расширения")
        row_files.addWidget(_arc_lbl)
        _arc_file_lbl = QLabel(archive_name if archive_name else "нет")
        if archive_name:
            _arc_file_lbl.setStyleSheet("font-family: Consolas, monospace; color:#8B4513; font-weight:bold;")
            _arc_file_lbl.setToolTip(f"Файл архива:\n{os.path.join(r.get('folder_path', ''), archive_name)}")
        else:
            _arc_file_lbl.setStyleSheet("color:#aaa;")
            _arc_file_lbl.setToolTip("Архив звуковой дорожки не найден в папке")
        row_files.addWidget(_arc_file_lbl)
        tab_widgets["archive_label"] = _arc_file_lbl
        # Кнопка "Переместить архив" — показывается только если архива нет
        archive_btn = QPushButton()
        archive_btn.setIcon(_make_two_notes_icon())
        tab_widgets["archive_btn"] = archive_btn
        if not archive_name:
            archive_btn.setText("Переместить архив с аудио дорожкой")
            archive_btn.setToolTip("Выбрать архив с аудио дорожкой и переместить в папку этого фильма\nПоддерживаются: .rar, .7z, .zip и файлы без расширения")
            archive_btn.clicked.connect(lambda _, f=fn: self._move_archive_to_folder(f))
            row_files.addWidget(archive_btn)
        row_files.addSpacing(8)
        _lpw = QLabel("Пароль:")
        _lpw.setToolTip("Пароль для расшифровки RAR архива с аудио дорожкой")
        row_files.addWidget(_lpw)
        tab_password = QLineEdit(r["password_entry"].text() if r.get("password_entry") else "")
        tab_password.setMaximumWidth(100)
        tab_password.setToolTip("Пароль от архива с аудио дорожкой — используется при распаковке RAR архива")
        tab_widgets["password_entry"] = tab_password
        row_files.addWidget(tab_password)
        row_files.addStretch()
        files_layout.addLayout(row_files)

        # --- Вариант 1: ТОЛЬКО стартовый + конечный (как и все остальные варианты) ---
        row_audio = QHBoxLayout()
        _la = QLabel("1:")
        _la.setStyleSheet("font-weight:bold;")
        _la.setToolTip("Вариант 1 — стартовый + конечный файл\n"
                       "Основная аудио дорожка — общая, выбирается выше")
        row_audio.addWidget(_la)
        # Стартовый аудио файл (intro)
        _ls = QLabel("Start:")
        _ls.setToolTip("Стартовый файл воспроизводится ДО основного аудио\nmkvmerge append: starter + main")
        row_audio.addWidget(_ls)
        tab_starter = QComboBox()
        tab_starter.setToolTip("Стартовый аудио файл (< 1 ГБ) — воспроизводится первым (intro/заставка)")
        self._setup_auto_width(tab_starter, 200)
        src_starter = r.get("starter_combo")
        if src_starter:
            for i in range(src_starter.count()):
                tab_starter.addItem(src_starter.itemText(i), src_starter.itemData(i, Qt.UserRole))
            tab_starter.setCurrentIndex(src_starter.currentIndex())
            tab_starter.setEnabled(src_starter.isEnabled())
        tab_widgets["starter_combo"] = tab_starter
        row_audio.addWidget(tab_starter)
        # Конечный аудио файл (outro)
        _le = QLabel("End:")
        _le.setToolTip("Конечный файл воспроизводится ПОСЛЕ основного аудио\nmkvmerge append: main + ender")
        row_audio.addWidget(_le)
        tab_ender = QComboBox()
        tab_ender.setToolTip("Конечный аудио файл (< 1 ГБ) — воспроизводится последним (outro/титры)")
        self._setup_auto_width(tab_ender, 200)
        src_ender = r.get("ender_combo")
        if src_ender:
            for i in range(src_ender.count()):
                tab_ender.addItem(src_ender.itemText(i), src_ender.itemData(i, Qt.UserRole))
            tab_ender.setCurrentIndex(src_ender.currentIndex())
            tab_ender.setEnabled(src_ender.isEnabled())
        tab_widgets["ender_combo"] = tab_ender
        row_audio.addWidget(tab_ender)
        # Кнопка подтверждения варианта 1
        _v1_confirmed = r.get("audio_variant_1_confirmed", False)
        _v1_confirm_btn = QPushButton("✓" if _v1_confirmed else "○")
        _v1_confirm_btn.setFixedSize(_btn_h, _btn_h)
        _v1_confirm_btn.setStyleSheet("color:green;" if _v1_confirmed else "color:gray;")
        _v1_confirm_btn.setToolTip("Подтвердить вариант 1 — подтверждённые варианты будут включены в обработку")
        tab_widgets["variant_1_confirm_btn"] = _v1_confirm_btn
        row_audio.addWidget(_v1_confirm_btn)
        # Кнопка "−" — удалить вариант 1 (промоутить следующий), видна при 2+ вариантах
        _v1_del_btn = QPushButton("−")
        _v1_del_btn.setFixedSize(_btn_h, _btn_h)
        _v1_del_btn.setStyleSheet("QPushButton{color:black; background-color:#ffe8e8; border:1px solid #cc9999;} QPushButton:hover{background-color:#ffcccc;}")
        _v1_del_btn.setToolTip("Удалить вариант 1 — следующий вариант станет первым")
        _v1_del_btn.setVisible(len(r.get("extra_audio_variants", [])) > 0)
        tab_widgets["variant_1_del_btn"] = _v1_del_btn
        row_audio.addWidget(_v1_del_btn)
        # Кнопка "+" — добавить аудио вариант
        _add_av_btn = QPushButton("+")
        _add_av_btn.setFont(BTN_FONT)
        _add_av_btn.setFixedSize(_btn_h, _btn_h)
        _add_av_btn.setToolTip("Добавить вариант стартовый/конечный (макс 5)\n"
                               "Основная аудио дорожка — общая для всех вариантов.\n"
                               "Варианты отличаются только стартовыми и конечными файлами.")
        row_audio.addWidget(_add_av_btn)
        _av_count_lbl = QLabel(f"[{1 + len(r.get('extra_audio_variants', []))}/5]")
        _av_count_lbl.setStyleSheet("color:#666; font-size:10px;")
        _av_count_lbl.setToolTip("Текущее / макс. кол-во аудио вариантов\nМакс. 5: 1 основной + 4 дополнительных")
        tab_widgets["audio_var_count_lbl"] = _av_count_lbl
        row_audio.addWidget(_av_count_lbl)
        row_audio.addStretch()
        # _del_unconfirmed_btn создаётся ниже и добавляется в row_main_audio
        # row_main_audio и row_audio добавляются в files_layout ниже

        # --- Основная дорожка + сканирование (один блок с рамкой) ---
        # Генерируем изображение галочки (один раз) для кастомного чекбокса
        _check_img = os.path.join(os.environ.get("TEMP", "."), "_russdub_check.png")
        if not os.path.exists(_check_img):
            from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
            _pm = QPixmap(14, 14)
            _pm.fill(Qt.white)
            _qp = QPainter(_pm)
            _qp.setRenderHint(QPainter.Antialiasing)
            _qp.setPen(QPen(QColor("#006600"), 2.5))
            _qp.drawLine(3, 7, 6, 11)
            _qp.drawLine(6, 11, 12, 3)
            _qp.end()
            _pm.save(_check_img)
        _check_css = _check_img.replace("\\", "/")
        _tracks_frame = QFrame()
        _tracks_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Plain)
        _tracks_frame.setStyleSheet(
            "QFrame#tracks_frame { border: 1px solid #b0c4de; border-radius: 4px; background: #f4f8ff; }"
            " QCheckBox::indicator { width: 14px; height: 14px; border: 2px solid #666; background: white; }"
            f" QCheckBox::indicator:checked {{ border-color: #006600; image: url({_check_css}); }}"
        )
        _tracks_frame.setObjectName("tracks_frame")
        _tracks_frame_layout = QVBoxLayout(_tracks_frame)
        _tracks_frame_layout.setContentsMargins(6, 6, 6, 6)
        _tracks_frame_layout.setSpacing(4)
        # Строка: Основная дорожка + комбо + подсказка
        row_main_audio = QHBoxLayout()
        _lma = QLabel("Основная дорожка:")
        _lma.setStyleSheet("font-weight:bold; border:none; background:transparent;")
        _lma.setToolTip("Основной аудио файл — один для ВСЕХ вариантов.\n"
                        "В селект попадают ТОЛЬКО файлы >= 1 ГБ.")
        row_main_audio.addWidget(_lma)
        tab_audio = QComboBox()
        tab_audio.setToolTip("Основной аудио файл (>= 1 ГБ) — будет использован как замена звука в видео")
        self._setup_auto_width(tab_audio, 250)
        src_audio = r.get("audio_combo")
        if src_audio:
            for i in range(src_audio.count()):
                tab_audio.addItem(src_audio.itemText(i), src_audio.itemData(i, Qt.UserRole))
            tab_audio.setCurrentIndex(src_audio.currentIndex())
            tab_audio.setEnabled(src_audio.isEnabled())
        tab_widgets["audio_combo"] = tab_audio
        row_main_audio.addWidget(tab_audio)
        _audio_hint = QLabel("(только > 1 ГБ)")
        _audio_hint.setStyleSheet("color:#888; font-size:10px; border:none; background:transparent;")
        _audio_hint.setToolTip("В селект основной дорожки попадают ТОЛЬКО файлы размером > 1 ГБ.\n"
                               "Файлы < 1 ГБ доступны как стартовые/конечные в вариантах ниже.")
        row_main_audio.addWidget(_audio_hint)
        # Кнопка сканирования — в той же строке
        tab_scan_tracks_btn = QPushButton("Сканировать дорожки")
        tab_scan_tracks_btn.setFont(BTN_FONT)
        tab_scan_tracks_btn.setToolTip("Сканирует дорожки внутри основного аудио файла (mkvmerge -J).\n"
                                       "Выбранные дорожки применяются ко ВСЕМ аудио вариантам.\n"
                                       "По умолчанию выбирается самая большая дорожка.\n"
                                       "─────────────────────────────\n"
                                       "Логика определения файлов:\n"
                                       "  • Файлы > 1 ГБ → основная аудио дорожка\n"
                                       "  • Файлы < 1 ГБ → стартовые/конечные")
        tab_scan_tracks_btn.clicked.connect(lambda _, f=fn: self._force_rescan_tracks(f))
        _cur_audio = tab_audio.currentData(Qt.UserRole) or ""
        _audio_exists = bool(_cur_audio and not _cur_audio.startswith("⚠") and
                             os.path.isfile(os.path.join(r.get("folder_path", ""), _cur_audio)))
        tab_scan_tracks_btn.setEnabled(_audio_exists)
        tab_widgets["scan_tracks_btn"] = tab_scan_tracks_btn
        row_main_audio.addWidget(tab_scan_tracks_btn)
        # Кнопка скрыть/показать дорожки
        _tracks_toggle_btn = QPushButton("▼")
        _tracks_toggle_btn.setFixedSize(_btn_h, _btn_h)
        _tracks_toggle_btn.setToolTip("Скрыть/показать детали дорожек")
        _tracks_toggle_btn.setVisible(False)
        tab_widgets["tracks_toggle_btn"] = _tracks_toggle_btn
        row_main_audio.addWidget(_tracks_toggle_btn)
        # Краткая информация о выбранных дорожках
        _tracks_summary = QLabel("")
        _tracks_summary.setStyleSheet("color:#006600; font-weight:bold; border:none; background:transparent;")
        _tracks_summary.setToolTip("Количество выбранных дорожек из общего числа")
        tab_widgets["tracks_summary"] = _tracks_summary
        row_main_audio.addWidget(_tracks_summary)
        # Кнопка "удалить неподтверждённые настройки" — после сканирования
        _del_unconfirmed_btn = QPushButton("Неподтвержденные настройки (0)")
        _del_unconfirmed_btn.setIcon(_make_del_archive_icon())
        _del_unconfirmed_btn.setIconSize(QSize(32, 16))
        _del_unconfirmed_btn.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc; color:#999;}")
        _del_unconfirmed_btn.setToolTip("Нет неподтверждённых настроек для сброса")
        _del_unconfirmed_btn.setEnabled(False)
        tab_widgets["del_unconfirmed_btn"] = _del_unconfirmed_btn
        row_main_audio.addWidget(_del_unconfirmed_btn)
        row_main_audio.addStretch()
        _tracks_frame_layout.addLayout(row_main_audio)
        # Контейнер чекбоксов дорожек
        tracks_container = QWidget()
        tracks_container.setStyleSheet("background:transparent;")
        tracks_main = QVBoxLayout(tracks_container)
        tracks_main.setContentsMargins(10, 0, 0, 0)
        tracks_main.setSpacing(2)
        tracks_hint = QLabel("Только дорожки с галочками будут добавлены в результат:")
        tracks_hint.setStyleSheet("color:#555; font-style:italic; border:none; background:transparent;")
        tracks_hint.setToolTip("Отметьте чекбоксами нужные аудио дорожки.\n"
                               "Выбор дорожек применяется ко ВСЕМ аудио вариантам.\n"
                               "По умолчанию выбрана самая крупная дорожка.")
        tracks_main.addWidget(tracks_hint)
        tracks_layout = QVBoxLayout()
        tracks_layout.setSpacing(2)
        tracks_main.addLayout(tracks_layout)
        tab_tracks_status = QLabel("")
        tab_tracks_status.setStyleSheet("color:#666; border:none; background:transparent;")
        tab_tracks_status.setToolTip("Количество аудио дорожек в файле и сколько выбрано")
        tracks_main.addWidget(tab_tracks_status)
        tracks_container.setVisible(False)
        tab_widgets["tracks_container"] = tracks_container
        tab_widgets["tracks_layout"] = tracks_layout
        tab_widgets["tracks_status"] = tab_tracks_status
        tab_widgets["track_checkboxes"] = []
        def _toggle_tracks_visibility():
            vis = tracks_container.isVisible()
            tracks_container.setVisible(not vis)
            _tracks_toggle_btn.setText("▶" if vis else "▼")
            _tracks_toggle_btn.setToolTip("Показать детали дорожек" if vis else "Скрыть детали дорожек")
        _tracks_toggle_btn.clicked.connect(_toggle_tracks_visibility)
        def _update_tracks_summary():
            """Обновить краткую информацию о дорожках в строке кнопки сканирования."""
            cbs = tab_widgets.get("track_checkboxes", [])
            if not cbs:
                _tracks_summary.setText("")
                _tracks_toggle_btn.setVisible(False)
                return
            total = len(cbs)
            sel = sum(1 for cb in cbs if cb.isChecked())
            _tracks_summary.setText(f"выбрано {sel} из {total}")
            _tracks_toggle_btn.setVisible(True)
        tab_widgets["update_tracks_summary"] = _update_tracks_summary
        _tracks_frame_layout.addWidget(tracks_container)
        files_layout.addWidget(_tracks_frame)    # Один блок: основная дорожка + сканирование
        files_layout.addLayout(row_audio)        # Вариант 1: стартовый + конечный

        # --- Дополнительные аудио варианты (контейнер, без отступа) ---
        _ea_status = QLabel("")
        _ea_status.setStyleSheet("color:#666;")
        _ea_status.setToolTip("Итого аудио дорожек = варианты × задержки\nПрименяется к каждому видео")
        tab_widgets["extra_audio_status"] = _ea_status

        _ea_container = QWidget()
        _ea_container_layout = QVBoxLayout(_ea_container)
        _ea_container_layout.setContentsMargins(0, 0, 0, 0)
        _ea_container_layout.setSpacing(2)
        tab_widgets["extra_audio_widgets"] = []
        tab_widgets["_extra_audio_containers"] = []

        def _update_audio_status():
            """Обновить счётчик дорожек и проверить дубликаты."""
            rr = self._find_row(fn)
            if not rr: return
            n_variants = 1 + len(rr.get("extra_audio_variants", []))
            n_delays = len(rr.get("delays", [{"value": "0", "confirmed": False}]))
            # Основное видео всегда 1, доп. только с выбранным файлом
            n_videos = 1
            for ev in rr.get("extra_videos", []):
                if ev.get("video") or ev.get("video_full_path"):
                    n_videos += 1
            # Считаем выбранные дорожки
            n_sel_tracks = max(1, sum(1 for cb in tab_widgets.get("track_checkboxes", []) if cb.isChecked()))
            total_tracks = n_variants * n_delays * n_sel_tracks
            # Проверка дубликатов (сравниваем стартовый+конечный, аудио общий)
            main_s = self._starter_filename(rr)
            main_e = self._ender_filename(rr)
            combos = [(main_s, main_e)]
            dup = False
            _ea_widgets = tab_widgets.get("extra_audio_widgets", [])
            for ei, ev in enumerate(rr.get("extra_audio_variants", [])):
                c = (ev.get("starter_audio", ""), ev.get("ender_audio", ""))
                _is_dup = c in combos
                if _is_dup:
                    dup = True
                # Обновить лейбл дубликата в строке варианта
                if ei < len(_ea_widgets):
                    _dl = _ea_widgets[ei].get("dup_lbl")
                    if _dl:
                        _dl.setText("⚠ дубликат" if _is_dup else "")
                combos.append(c)
            # Формируем текст
            parts = []
            if n_variants > 1:
                parts.append(f"{n_variants} вар")
            parts.append(f"{n_delays} зад")
            if n_sel_tracks > 1:
                parts.append(f"{n_sel_tracks} дор")
            tracks_str = (" × ".join(parts) + f" = {total_tracks} дорожек") if len(parts) > 1 else f"{total_tracks} дорожек"
            if n_videos > 1:
                tracks_str += f" × {n_videos} видео = {n_videos} файлов"
            if dup:
                _ea_status.setText(f"⚠ Дубликат! {tracks_str}")
                _ea_status.setStyleSheet("color:red; font-weight:bold;")
            elif n_variants > 1 or n_delays > 1 or n_sel_tracks > 1 or n_videos > 1:
                _ea_status.setText(tracks_str)
                _ea_status.setStyleSheet("color:#006600; font-weight:bold;")
            else:
                _ea_status.setText("")
                _ea_status.setStyleSheet("color:#666;")
            _update_track_preview()
        tab_widgets["update_audio_status"] = _update_audio_status

        # --- Как будут выглядеть дорожки в итоговом файле (спойлер) ---
        _preview_btn = QPushButton("▶ Как будут выглядеть дорожки в итоговом файле")
        _preview_btn.setFlat(True)
        _preview_btn.setCursor(Qt.PointingHandCursor)
        _preview_btn.setStyleSheet("text-align:left; color:#0066cc; font-weight:bold; padding:2px;")
        _preview_btn.setToolTip("Показать/скрыть список имён дорожек в выходном файле\n"
                                "Формат: v{вариант}_{задержка}_{кодек}[_{номер}]")
        _preview_text = QLabel("")
        _preview_text.setWordWrap(True)
        _preview_text.setTextFormat(Qt.RichText)
        _preview_text.setStyleSheet("color:#333; font-family:Consolas,monospace; font-size:11px; "
                                    "padding:4px; background:#f8f8f8; border:1px solid #ddd; border-radius:3px;")
        _preview_text.setVisible(False)
        _preview_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tab_widgets["track_preview_btn"] = _preview_btn
        tab_widgets["track_preview_text"] = _preview_text

        def _toggle_preview():
            vis = not _preview_text.isVisible()
            _preview_text.setVisible(vis)
            n = _preview_text.text().count("<br>") if _preview_text.text() else 0
            _preview_btn.setText(f"{'▼' if vis else '▶'} Как будут выглядеть дорожки в итоговом файле ({n})" if n else
                                 f"{'▼' if vis else '▶'} Как будут выглядеть дорожки в итоговом файле")
        _preview_btn.clicked.connect(_toggle_preview)

        def _update_track_preview():
            """Обновить предпросмотр имён дорожек в выходном файле.
            Логика нумерации и пропуска дубликатов — как в _build_task_refs/_process_tasks."""
            rr = self._find_row(fn)
            if not rr:
                _preview_text.setText("")
                return
            delays = rr.get("delays", [{"value": "0", "confirmed": False}])
            # Выбранные дорожки из сканирования
            cache = rr.get("audio_tracks_cache", {})
            audio_name = self._audio_filename(rr)
            all_tracks = cache.get(audio_name, [])
            sel_ids = rr.get("selected_audio_tracks", [])
            sel_tracks = [t for t in all_tracks if t["id"] in sel_ids]
            if not sel_tracks:
                sel_tracks = [{"id": 0, "codec": "audio", "label": "основная"}]
            n_sel = len(sel_tracks)
            track_name = self._get_track_name(rr)
            # Собрать варианты аудио — как _build_task_refs (с пропуском дубликатов)
            fp = rr.get("folder_path", "")
            av_list = []  # [(variant_idx, starter_name, ender_name), ...]
            s0 = self._starter_filename(rr) or ""
            e0 = self._ender_filename(rr) or ""
            av_list.append((1, s0, e0))
            seen_combos = {(s0, e0)}
            for ev_idx, ev in enumerate(rr.get("extra_audio_variants", [])):
                _s = ev.get("starter_audio", "") or ""
                _e = ev.get("ender_audio", "") or ""
                _combo = (_s, _e)
                if _combo in seen_combos:
                    continue  # дубликат — пропускаем (как в _build_task_refs)
                seen_combos.add(_combo)
                av_list.append((ev_idx + 2, _s, _e))
            is_multi_variant = len(av_list) > 1
            is_multi_delay = len(delays) > 1
            lines = []
            track_num = 0
            for v_idx, s_name, e_name in av_list:
                parts_desc = []
                if s_name:
                    parts_desc.append(f"старт: {os.path.splitext(s_name)[0][:25]}")
                if e_name:
                    parts_desc.append(f"конец: {os.path.splitext(e_name)[0][:25]}")
                v_info = f" ({', '.join(parts_desc)})" if parts_desc else ""
                for idx_d, d in enumerate(delays):
                    d_val = d.get("value", "0")
                    for ti, t in enumerate(sel_tracks):
                        track_num += 1
                        # Имя дорожки: v{N}_{delay}_{track_name}[_{seq}] — как в _process_tasks
                        name_parts = []
                        if is_multi_variant:
                            name_parts.append(f"v{v_idx}")
                        if is_multi_delay or is_multi_variant:
                            name_parts.append(str(d_val))
                        name_parts.append(track_name)
                        t_suffix = f"_{ti + 1}" if n_sel > 1 else ""
                        name = "_".join(name_parts) + t_suffix
                        codec_info = t.get("codec", "audio")
                        desc = f"Вариант {v_idx}{v_info}, задержка {d_val}мс, {codec_info}"
                        if n_sel > 1:
                            desc += f" #{ti + 1}"
                        lines.append(f"&nbsp;&nbsp;{track_num}. <b>{name}</b> — {desc}")
            if lines:
                legend = "<span style='color:#888; font-size:10px;'><b>Жирным</b> — имя дорожки в MKV файле (без знака или + = позже, − = раньше)</span><br>"
                _preview_text.setText(legend + "<br>".join(lines))
                vis = _preview_text.isVisible()
                _preview_btn.setText(f"{'▼' if vis else '▶'} Как будут выглядеть дорожки в итоговом файле ({track_num})")
            else:
                _preview_text.setText("")
                _preview_btn.setText("▶ Как будут выглядеть дорожки в итоговом файле")
        tab_widgets["update_track_preview"] = _update_track_preview

        def _rebuild_extra_audio():
            """Перестроить UI дополнительных аудио вариантов (только стартовый/конечный)."""
            rr = self._find_row(fn)
            if not rr: return
            for c in tab_widgets.get("_extra_audio_containers", []):
                c.setParent(None); c.deleteLater()
            tab_widgets["_extra_audio_containers"] = []
            tab_widgets["extra_audio_widgets"] = []
            variants = rr.get("extra_audio_variants", [])
            for i, var in enumerate(variants):
                row_w = QWidget()
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(0, 0, 0, 0)
                row_h.setSpacing(4)
                _v_lbl = QLabel(f"{i + 2}:")
                _v_lbl.setToolTip(f"Вариант стартовый/конечный #{i + 2}\n"
                                  "Основная аудио дорожка — общая для всех вариантов (выше)")
                _v_lbl.setStyleSheet("font-weight:bold;")
                row_h.addWidget(_v_lbl)
                # Стартовый
                _sl = QLabel("Start:")
                _sl.setToolTip("Стартовый аудио — воспроизводится перед основным")
                row_h.addWidget(_sl)
                sc = QComboBox()
                self._setup_auto_width(sc, 180)
                sc.setToolTip("Стартовый аудио файл (< 1 ГБ) — воспроизводится перед основной дорожкой")
                self._populate_starter_combo(sc, rr["audio_files"], rr["folder_path"], exclude_file="")
                saved_s = var.get("starter_audio", "")
                if saved_s:
                    for j in range(sc.count()):
                        if sc.itemData(j, Qt.UserRole) == saved_s:
                            sc.setCurrentIndex(j); break
                row_h.addWidget(sc)
                # Конечный
                _el = QLabel("End:")
                _el.setToolTip("Конечный аудио — воспроизводится после основного")
                row_h.addWidget(_el)
                ec = QComboBox()
                self._setup_auto_width(ec, 180)
                ec.setToolTip("Конечный аудио файл (< 1 ГБ) — воспроизводится после основной дорожки")
                self._populate_starter_combo(ec, rr["audio_files"], rr["folder_path"], exclude_file="")
                saved_e = var.get("ender_audio", "")
                if saved_e:
                    for j in range(ec.count()):
                        if ec.itemData(j, Qt.UserRole) == saved_e:
                            ec.setCurrentIndex(j); break
                row_h.addWidget(ec)
                # Кнопка подтверждения варианта
                _var_confirmed = var.get("confirmed", False)
                confirm_b = QPushButton("✓" if _var_confirmed else "○")
                confirm_b.setFixedSize(_btn_h, _btn_h)
                confirm_b.setStyleSheet("color:green;" if _var_confirmed else "color:gray;")
                confirm_b.setToolTip("Подтвердить вариант — подтверждённые варианты будут включены в обработку")
                confirm_b.clicked.connect(lambda _, idx=i: _on_confirm_audio_var(idx))
                row_h.addWidget(confirm_b)
                # Кнопка удаления
                del_b = QPushButton("−")
                del_b.setFixedSize(_btn_h, _btn_h)
                del_b.setStyleSheet("QPushButton{color:black; background-color:#ffe8e8; border:1px solid #cc9999;} QPushButton:hover{background-color:#ffcccc;}")
                del_b.setToolTip("Удалить этот вариант стартовый/конечный")
                del_b.clicked.connect(lambda _, idx=i: _on_del_audio_var(idx))
                row_h.addWidget(del_b)
                # Лейбл дубликата (заполняется в _update_audio_status)
                _dup_lbl = QLabel("")
                _dup_lbl.setStyleSheet("color:red; font-weight:bold;")
                row_h.addWidget(_dup_lbl)
                row_h.addStretch()
                _ea_container_layout.addWidget(row_w)
                tab_widgets["_extra_audio_containers"].append(row_w)
                dw = {"starter_combo": sc, "ender_combo": ec, "confirm_btn": confirm_b, "dup_lbl": _dup_lbl}
                tab_widgets["extra_audio_widgets"].append(dw)
                sc.currentIndexChanged.connect(lambda _, idx=i: _on_extra_audio_changed(idx))
                ec.currentIndexChanged.connect(lambda _, idx=i: _on_extra_audio_changed(idx))
            _update_audio_status()
            _update_del_unconfirmed_visibility()
            # Обновить счётчик аудио вариантов
            _avcl = tab_widgets.get("audio_var_count_lbl")
            if _avcl:
                _avcl.setText(f"[{1 + len(variants)}/5]")
            # Обновить видимость кнопки "−" варианта 1
            _v1db = tab_widgets.get("variant_1_del_btn")
            if _v1db:
                _v1db.setVisible(len(variants) > 0)

        def _on_confirm_variant_1():
            """Toggle подтверждения варианта 1."""
            rr = self._find_row(fn)
            if not rr: return
            was = rr.get("audio_variant_1_confirmed", False)
            rr["audio_variant_1_confirmed"] = not was
            _v1_confirm_btn.setText("✓" if not was else "○")
            _v1_confirm_btn.setStyleSheet("color:green;" if not was else "color:gray;")
            _update_del_unconfirmed_visibility()
            self._update_audio_summary(rr)
            self.schedule_autosave()
        _v1_confirm_btn.clicked.connect(_on_confirm_variant_1)

        def _on_del_variant_1():
            """Удалить вариант 1: промоутить первый extra → вариант 1, сдвинуть остальные."""
            rr = self._find_row(fn)
            if not rr: return
            extras = rr.get("extra_audio_variants", [])
            if not extras: return  # Нечего промоутить
            promoted = extras.pop(0)
            # Установить start/end варианта 1 из промоутнутого
            s_combo = rr.get("starter_combo")
            e_combo = rr.get("ender_combo")
            if s_combo:
                s_combo.blockSignals(True)
                target_s = promoted.get("starter_audio", "")
                matched = False
                for i in range(s_combo.count()):
                    if s_combo.itemData(i, Qt.UserRole) == target_s:
                        s_combo.setCurrentIndex(i); matched = True; break
                if not matched:
                    s_combo.setCurrentIndex(0)
                s_combo.blockSignals(False)
            if e_combo:
                e_combo.blockSignals(True)
                target_e = promoted.get("ender_audio", "")
                matched = False
                for i in range(e_combo.count()):
                    if e_combo.itemData(i, Qt.UserRole) == target_e:
                        e_combo.setCurrentIndex(i); matched = True; break
                if not matched:
                    e_combo.setCurrentIndex(0)
                e_combo.blockSignals(False)
            rr["audio_variant_1_confirmed"] = promoted.get("confirmed", False)
            _v1_confirm_btn.setText("✓" if rr["audio_variant_1_confirmed"] else "○")
            _v1_confirm_btn.setStyleSheet("color:green;" if rr["audio_variant_1_confirmed"] else "color:gray;")
            self._sync_audio_combos(rr)
            _rebuild_extra_audio()
            _update_audio_status()
            self._update_audio_summary(rr)
            # Обновить видимость кнопки "−" варианта 1
            _v1_del_btn.setVisible(len(rr.get("extra_audio_variants", [])) > 0)
            self.schedule_autosave()
        _v1_del_btn.clicked.connect(_on_del_variant_1)

        def _on_confirm_audio_var(idx):
            """Toggle подтверждения доп. варианта."""
            rr = self._find_row(fn)
            if not rr: return
            variants = rr.get("extra_audio_variants", [])
            if idx >= len(variants): return
            was = variants[idx].get("confirmed", False)
            variants[idx]["confirmed"] = not was
            _rebuild_extra_audio()
            _update_del_unconfirmed_visibility()
            self._update_audio_summary(rr)
            self.schedule_autosave()

        def _count_unconfirmed_details(rr):
            """Подсчитать неподтверждённые настройки и описания для кнопки/диалога."""
            count = 0
            details = []
            variants = rr.get("extra_audio_variants", [])
            # Вариант 1 — неподтверждён: считаем если есть start/end ИЛИ есть extra варианты
            if not rr.get("audio_variant_1_confirmed", False):
                v1_s = self._starter_filename(rr)
                v1_e = self._ender_filename(rr)
                if v1_s or v1_e or variants:
                    count += 1
                    parts = []
                    if v1_s: parts.append(f"start: {v1_s}")
                    if v1_e: parts.append(f"end: {v1_e}")
                    details.append(f"Вариант 1 ({', '.join(parts) if parts else 'пустой'})")
            # Неподтверждённые доп. варианты start/end — будут удалены
            unconf_variants = [v for v in variants if not v.get("confirmed", False)]
            for uv in unconf_variants:
                count += 1
                parts = []
                if uv.get("starter_audio"): parts.append(f"start: {uv['starter_audio']}")
                if uv.get("ender_audio"): parts.append(f"end: {uv['ender_audio']}")
                details.append(f"Доп. вариант ({', '.join(parts) if parts else 'пустой'})")
            # Задержки — считаем сколько реально будет сброшено
            delays = rr.get("delays", [])
            confirmed_delays = [d for d in delays if d.get("confirmed", False)]
            unconf_delays = [d for d in delays if not d.get("confirmed", False)]
            if confirmed_delays:
                for ud in unconf_delays:
                    count += 1
                    details.append(f"Задержка: {ud.get('value', '0')}мс")
            else:
                is_default = len(delays) == 1 and delays[0].get("value", "0") == "0"
                if not is_default:
                    for d in delays:
                        count += 1
                        details.append(f"Задержка: {d.get('value', '0')}мс")
            return count, details

        def _update_del_unconfirmed_visibility():
            """Активировать кнопку 'удалить неподтверждённые' только если есть что реально удалять."""
            rr = self._find_row(fn)
            if not rr:
                _del_unconfirmed_btn.setEnabled(False)
                _del_unconfirmed_btn.setText("Неподтвержденные настройки (0)")
                _del_unconfirmed_btn.setToolTip("Нет неподтверждённых настроек для сброса")
                return
            count, details = _count_unconfirmed_details(rr)
            _del_unconfirmed_btn.setText(f"Неподтвержденные настройки ({count})")
            _del_unconfirmed_btn.setEnabled(count > 0)
            if count > 0:
                tip = f"Сбросить {count} неподтверждённых настроек:\n" + "\n".join(f"• {d}" for d in details)
            else:
                tip = "Нет неподтверждённых настроек для сброса"
            _del_unconfirmed_btn.setToolTip(tip)
        tab_widgets["update_del_unconfirmed_visibility"] = _update_del_unconfirmed_visibility

        def _on_del_unconfirmed():
            """Удалить все неподтверждённые варианты start/end и задержки (с подтверждением)."""
            rr = self._find_row(fn)
            if not rr: return
            count, details = _count_unconfirmed_details(rr)
            if count == 0: return
            # Модальное окно подтверждения
            msg = QMessageBox(self)
            msg.setWindowTitle("Сброс неподтверждённых настроек")
            msg.setIcon(QMessageBox.Warning)
            msg.setText(f"Будут удалены {count} неподтверждённых настроек:")
            msg.setInformativeText("\n".join(f"  {i+1}. {d}" for i, d in enumerate(details))
                                   + "\n\nЗадержки будут сброшены на дефолт (0мс).\nПродолжить?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            if msg.exec() != QMessageBox.Yes:
                return
            # 1. Вариант 1: если неподтверждён — удалить (промоутить подтверждённый extra или очистить)
            if not rr.get("audio_variant_1_confirmed", False):
                extras = rr.get("extra_audio_variants", [])
                confirmed_extras = [v for v in extras if v.get("confirmed", False)]
                if confirmed_extras:
                    # Промоутить первый подтверждённый extra → вариант 1
                    promoted = confirmed_extras[0]
                    s_combo = rr.get("starter_combo")
                    e_combo = rr.get("ender_combo")
                    if s_combo:
                        s_combo.blockSignals(True)
                        target_s = promoted.get("starter_audio", "")
                        matched = False
                        for i in range(s_combo.count()):
                            if s_combo.itemData(i, Qt.UserRole) == target_s:
                                s_combo.setCurrentIndex(i); matched = True; break
                        if not matched:
                            s_combo.setCurrentIndex(0)
                        s_combo.blockSignals(False)
                    if e_combo:
                        e_combo.blockSignals(True)
                        target_e = promoted.get("ender_audio", "")
                        matched = False
                        for i in range(e_combo.count()):
                            if e_combo.itemData(i, Qt.UserRole) == target_e:
                                e_combo.setCurrentIndex(i); matched = True; break
                        if not matched:
                            e_combo.setCurrentIndex(0)
                        e_combo.blockSignals(False)
                    rr["audio_variant_1_confirmed"] = True
                    extras.remove(promoted)
                else:
                    # Нет подтверждённых extra — очистить вариант 1
                    s_combo = rr.get("starter_combo")
                    e_combo = rr.get("ender_combo")
                    if s_combo:
                        s_combo.blockSignals(True)
                        s_combo.setCurrentIndex(0)
                        s_combo.blockSignals(False)
                    if e_combo:
                        e_combo.blockSignals(True)
                        e_combo.setCurrentIndex(0)
                        e_combo.blockSignals(False)
                self._sync_audio_combos(rr)
                _v1_confirm_btn.setText("✓" if rr.get("audio_variant_1_confirmed") else "○")
                _v1_confirm_btn.setStyleSheet("color:green;" if rr.get("audio_variant_1_confirmed") else "color:gray;")
            # 2. Удалить неподтверждённые доп. варианты
            rr["extra_audio_variants"] = [v for v in rr.get("extra_audio_variants", []) if v.get("confirmed", False)]
            _rebuild_extra_audio()
            # 3. Задержки: убрать неподтверждённые, сброс на дефолт если нет подтверждённых
            delays = rr.get("delays", [])
            confirmed_delays = [d for d in delays if d.get("confirmed", False)]
            if confirmed_delays:
                rr["delays"] = confirmed_delays
            else:
                rr["delays"] = [{"value": "0", "confirmed": False}]
            self._sync_delays_to_table(rr)
            _rebuild_tab_delays()
            _update_delay_status()
            _update_del_unconfirmed_visibility()
            _update_audio_status()
            self._update_audio_summary(rr)
            self.schedule_autosave()
        _del_unconfirmed_btn.clicked.connect(_on_del_unconfirmed)
        _update_del_unconfirmed_visibility()

        def _on_add_audio_var():
            rr = self._find_row(fn)
            if not rr: return
            variants = rr.get("extra_audio_variants", [])
            if len(variants) >= 4:
                QMessageBox.warning(self, "Ограничение",
                                    "Максимум 5 аудио вариантов\n(1 основной + 4 дополнительных)")
                return
            variants.append({"starter_audio": "", "ender_audio": ""})
            rr["extra_audio_variants"] = variants
            _rebuild_extra_audio()
            self._update_audio_summary(rr)
            _update_track_preview()
            self.schedule_autosave()

        def _on_del_audio_var(idx):
            rr = self._find_row(fn)
            if not rr: return
            variants = rr.get("extra_audio_variants", [])
            if idx < len(variants):
                variants.pop(idx)
                _rebuild_extra_audio()
                self._update_audio_summary(rr)
                _update_track_preview()
                self.schedule_autosave()

        def _on_extra_audio_changed(idx):
            rr = self._find_row(fn)
            if not rr: return
            variants = rr.get("extra_audio_variants", [])
            widgets = tab_widgets.get("extra_audio_widgets", [])
            if idx < len(variants) and idx < len(widgets):
                w = widgets[idx]
                variants[idx]["starter_audio"] = w["starter_combo"].currentData(Qt.UserRole) or ""
                variants[idx]["ender_audio"] = w["ender_combo"].currentData(Qt.UserRole) or ""
            _update_audio_status()
            self._update_audio_summary(rr)
            _update_track_preview()
            self.schedule_autosave()

        _add_av_btn.clicked.connect(_on_add_audio_var)
        tab_widgets["rebuild_extra_audio"] = _rebuild_extra_audio
        files_layout.addWidget(_ea_container)
        _rebuild_extra_audio()

        row2b = QHBoxLayout()
        _v1_lbl = QLabel("1:")
        _v1_lbl.setStyleSheet("font-weight:bold;")
        _v1_lbl.setFixedWidth(18)
        _v1_lbl.setToolTip("Видео файл 1 (основной) — синхронизирован с таблицей")
        row2b.addWidget(_v1_lbl)
        tab_video = QComboBox()
        tab_video.setItemDelegate(_BoldPartDelegate(tab_video))
        tab_video.setToolTip("Видео файл (исходник) — в него будет вставлена аудио дорожка при обработке mkvmerge")
        self._setup_auto_width(tab_video, 250)
        src_video = r.get("video_combo")
        if src_video:
            for i in range(src_video.count()):
                tab_video.addItem(src_video.itemText(i))
            tab_video.setCurrentText(src_video.currentText())
        tab_widgets["video_combo"] = tab_video
        row2b.addWidget(tab_video)
        _combo_h = tab_video.sizeHint().height()
        tab_video_browse = QPushButton("...")
        tab_video_browse.setFont(BTN_FONT); tab_video_browse.setFixedSize(28, _combo_h)
        tab_video_browse.setToolTip("Выбрать видео файл из другой папки (ручной выбор)")
        tab_video_browse.clicked.connect(lambda _, f=fn: self._browse_video_file(f))
        row2b.addWidget(tab_video_browse)
        _video_dir = ""
        _vfp = r.get("video_full_path", "")
        if _vfp and os.path.isfile(_vfp):
            _video_dir = os.path.dirname(_vfp)
        elif self.video_path_edit.text() and os.path.isdir(self.video_path_edit.text()):
            _video_dir = self.video_path_edit.text()
        tab_open_video_dir = QPushButton("📁")
        tab_open_video_dir.setFont(BTN_FONT); tab_open_video_dir.setFixedSize(28, _combo_h)
        tab_open_video_dir.setToolTip(f"Открыть папку видео источника:\n{_video_dir}" if _video_dir else "Папка видео не найдена")
        tab_open_video_dir.setEnabled(bool(_video_dir and os.path.isdir(_video_dir)))
        tab_open_video_dir.clicked.connect(lambda _, f=fn: self._open_video_dir_from_tab(f))
        tab_widgets["open_video_dir"] = tab_open_video_dir
        row2b.addWidget(tab_open_video_dir)
        # Кнопка "+" — добавить доп. видео (на одной строке с основным видео)
        _add_ev_btn = QPushButton("+")
        _add_ev_btn.setFont(BTN_FONT)
        _add_ev_btn.setFixedSize(24, _combo_h)
        _add_ev_btn.setToolTip("Добавить дополнительный видео файл\n(макс 4 доп + 1 основной = 5)\nВсе аудио варианты × все видео = итого файлов")
        row2b.addWidget(_add_ev_btn)
        # Кнопка "видео в процессе" ⏳ — как в таблице
        tab_video_pending = QPushButton("⏳")
        tab_video_pending.setFont(BTN_FONT); tab_video_pending.setFixedSize(28, _combo_h)
        tab_video_pending.setToolTip("Пометить: видео ещё скачивается")
        _is_pending = r.get("video_pending", False)
        if _is_pending:
            tab_video_pending.setText("⌛")
            tab_video_pending.setStyleSheet("color:#8e44ad; font-weight:bold;")
        _has_video = bool(r.get("video_full_path"))
        tab_video_pending.setVisible(not _has_video)
        tab_video_pending.clicked.connect(lambda _, f=fn: self._toggle_video_pending(f))
        tab_widgets["video_pending_btn"] = tab_video_pending
        row2b.addWidget(tab_video_pending)
        # Label продолжительности видео — как в таблице
        tab_video_dur = QLabel("")
        tab_video_dur.setFont(QFont("Arial", 8, QFont.Bold))
        tab_video_dur.setStyleSheet("color:#333;")
        tab_video_dur.setToolTip("Длительность видео")
        _dur_lbl = r.get("video_dur_lbl")
        if _dur_lbl and hasattr(_dur_lbl, "text"):
            tab_video_dur.setText(_dur_lbl.text())
        tab_widgets["video_dur_lbl"] = tab_video_dur
        row2b.addWidget(tab_video_dur)
        # Кнопка "Удалить источник" для основного видео
        _del_src_1 = QPushButton("Источник")
        _del_src_1.setIcon(_make_del_video_icon())
        _del_src_1.setIconSize(QSize(32, 16))
        _del_src_1.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
        _vfp_main = r.get("video_full_path", "")
        _src_sz = _format_file_size_gb(_vfp_main) if _vfp_main and os.path.isfile(_vfp_main) else ""
        if _src_sz:
            _del_src_1.setText(f"Источник {_src_sz}")
        _del_src_1.setToolTip("Удалить видео-источник 1 (основной)")
        _del_src_1.setEnabled(bool(_vfp_main and os.path.isfile(_vfp_main)))
        _del_src_1.clicked.connect(lambda _, f=fn: self._action_del_source_single(f,
                                   self._find_row(f).get("video_full_path", "") if self._find_row(f) else ""))
        tab_widgets["del_src_1"] = _del_src_1
        row2b.addWidget(_del_src_1)
        row2b.addStretch()
        # Полный путь к видео (если выбран вручную из другой папки)
        row2b2_widget = QWidget()
        row2b2 = QHBoxLayout(row2b2_widget)
        row2b2.setContentsMargins(0, 0, 0, 0)
        tab_video_path_lbl = QLabel("")
        tab_video_path_lbl.setStyleSheet("color:#666; font-size:10px;")
        tab_video_path_lbl.setToolTip("Полный путь к видео файлу (показывается если файл выбран из нестандартной папки)")
        tab_widgets["video_path_lbl"] = tab_video_path_lbl
        tab_widgets["video_path_widget"] = row2b2_widget
        vfp = r.get("video_full_path", "")
        if vfp and r.get("video_manual"):
            tab_video_path_lbl.setText(vfp)
            row2b2_widget.setVisible(True)
        else:
            row2b2_widget.setVisible(False)
        row2b2.addWidget(tab_video_path_lbl)
        row2b2.addStretch()

        # --- Контейнер для доп. видео (кнопка "+" в строке видео выше) ---
        _ev_container = QWidget()
        _ev_container_layout = QVBoxLayout(_ev_container)
        _ev_container_layout.setContentsMargins(0, 0, 0, 0)
        _ev_container_layout.setSpacing(2)
        tab_widgets["extra_video_widgets"] = []
        tab_widgets["_extra_video_containers"] = []

        def _rebuild_extra_videos():
            """Перестроить UI дополнительных видео."""
            rr = self._find_row(fn)
            if not rr: return
            for c in tab_widgets.get("_extra_video_containers", []):
                c.setParent(None); c.deleteLater()
            tab_widgets["_extra_video_containers"] = []
            tab_widgets["extra_video_widgets"] = []
            evs = rr.get("extra_videos", [])
            vp = self.video_path_edit.text()
            # Собрать уже выбранные видео для исключения из селектов
            _main_vname = os.path.basename(rr.get("video_full_path", "")) if rr.get("video_full_path") else ""
            _all_selected = set()
            if _main_vname:
                _all_selected.add(_main_vname)
            for _ev in evs:
                if _ev.get("video"):
                    _all_selected.add(_ev["video"])
            for i, ev in enumerate(evs):
                row_w = QWidget()
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(0, 0, 0, 0)
                row_h.setSpacing(4)
                _vn_lbl = QLabel(f"{i + 2}:")
                _vn_lbl.setToolTip(f"Дополнительное видео #{i + 2}")
                _vn_lbl.setStyleSheet("font-weight:bold;")
                _vn_lbl.setFixedWidth(18)
                row_h.addWidget(_vn_lbl)
                # Видео комбо
                vc = QComboBox()
                self._setup_auto_width(vc, 250)
                vc.setToolTip("Видео файл для этого варианта")
                vc.addItem("— выбрать —", "")
                _exclude_this = _all_selected - ({ev.get("video")} if ev.get("video") else set())
                if vp and os.path.isdir(vp):
                    try:
                        for vf in sorted(os.listdir(vp)):
                            if vf in _exclude_this:
                                continue
                            if os.path.isfile(os.path.join(vp, vf)):
                                _ext = os.path.splitext(vf)[1].lower()
                                if _ext in ('.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.wmv', '.mov'):
                                    _sz = _format_file_size_gb(os.path.join(vp, vf))
                                    vc.addItem(f"{vf} ({_sz})" if _sz else vf, vf)
                    except OSError:
                        pass
                # Ручной путь (если video_manual)
                saved_v = ev.get("video", "")
                saved_vfp = ev.get("video_full_path", "")
                if ev.get("video_manual") and saved_vfp:
                    _found = False
                    for j in range(vc.count()):
                        if vc.itemData(j, Qt.UserRole) == saved_v:
                            vc.setCurrentIndex(j); _found = True; break
                    if not _found:
                        _sz = _format_file_size_gb(saved_vfp)
                        vc.addItem(f"[Ручной] {os.path.basename(saved_vfp)} ({_sz})" if _sz else f"[Ручной] {os.path.basename(saved_vfp)}", saved_v)
                        vc.setCurrentIndex(vc.count() - 1)
                elif saved_v:
                    for j in range(vc.count()):
                        if vc.itemData(j, Qt.UserRole) == saved_v:
                            vc.setCurrentIndex(j); break
                row_h.addWidget(vc)
                # Кнопка "..." для ручного выбора
                br_btn = QPushButton("...")
                br_btn.setFixedSize(28, 24)
                br_btn.setToolTip("Выбрать видео файл вручную")
                br_btn.clicked.connect(lambda _, idx=i: _on_browse_extra_video(idx))
                row_h.addWidget(br_btn)
                # Вычислить путь к видео файлу
                _ev_path = ev.get("video_full_path", "")
                if not _ev_path and saved_v and vp:
                    _ev_path = os.path.join(vp, saved_v)
                # Кнопка 📁 — открыть папку видео источника
                _ev_video_dir = ""
                if _ev_path and os.path.isfile(_ev_path):
                    _ev_video_dir = os.path.dirname(_ev_path)
                elif vp and os.path.isdir(vp):
                    _ev_video_dir = vp
                _ev_open_dir = QPushButton("📁")
                _ev_open_dir.setFont(BTN_FONT); _ev_open_dir.setFixedSize(28, 24)
                _ev_open_dir.setToolTip(f"Открыть папку видео источника:\n{_ev_video_dir}" if _ev_video_dir else "Папка видео не найдена")
                _ev_open_dir.setEnabled(bool(_ev_video_dir and os.path.isdir(_ev_video_dir)))
                _ev_open_dir.clicked.connect(lambda _, d=_ev_video_dir: os.startfile(d) if d and os.path.isdir(d) else None)
                row_h.addWidget(_ev_open_dir)
                # Кнопка удаления
                del_b = QPushButton("−")
                del_b.setFixedSize(_btn_h, _btn_h)
                del_b.setStyleSheet("QPushButton{color:black; background-color:#ffe8e8; border:1px solid #cc9999;} QPushButton:hover{background-color:#ffcccc;}")
                del_b.setToolTip("Удалить это дополнительное видео")
                del_b.clicked.connect(lambda _, idx=i: _on_del_extra_video(idx))
                row_h.addWidget(del_b)
                # Длительность видео
                _ev_dur = QLabel("")
                _ev_dur.setFont(QFont("Arial", 8, QFont.Bold))
                _ev_dur.setStyleSheet("color:#333;")
                _ev_dur.setToolTip("Длительность видео")
                if _ev_path and os.path.isfile(_ev_path):
                    _ev_cached = ev.get("_cached_duration", "")
                    _ev_cached_path = ev.get("_cached_dur_path", "")
                    if not _ev_cached or _ev_cached_path != _ev_path:
                        try:
                            _ev_cached = self._get_video_duration(_ev_path)
                        except Exception:
                            _ev_cached = ""
                        ev["_cached_duration"] = _ev_cached
                        ev["_cached_dur_path"] = _ev_path
                    _ev_dur.setText(_ev_cached)
                row_h.addWidget(_ev_dur)
                # Кнопка "Удалить источник" для доп. видео
                _ev_del_src = QPushButton("Источник")
                _ev_del_src.setIcon(_make_del_video_icon())
                _ev_del_src.setIconSize(QSize(32, 16))
                _ev_del_src.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;} QPushButton:disabled{background-color:#ffcccc;}")
                _ev_src_path = _ev_path
                _ev_src_sz = _format_file_size_gb(_ev_src_path) if _ev_src_path and os.path.isfile(_ev_src_path) else ""
                if _ev_src_sz:
                    _ev_del_src.setText(f"Источник {_ev_src_sz}")
                _ev_del_src.setToolTip(f"Удалить видео-источник #{i + 2}")
                _ev_del_src.setEnabled(bool(_ev_src_path and os.path.isfile(_ev_src_path)))
                _ev_del_src.clicked.connect(lambda _, f=fn, idx=i, p=_ev_src_path: self._action_del_source_single(f, p, ev_idx=idx))
                row_h.addWidget(_ev_del_src)
                row_h.addStretch()
                _ev_container_layout.addWidget(row_w)
                tab_widgets["_extra_video_containers"].append(row_w)
                dw = {"video_combo": vc, "browse_btn": br_btn}
                tab_widgets["extra_video_widgets"].append(dw)
                vc.currentIndexChanged.connect(lambda _, idx=i: _on_extra_video_changed(idx))
            # Обновить заголовок блока видео с текущим количеством
            sel_count = sum(1 for e in evs if e.get("video") or e.get("video_full_path"))
            total = 1 + sel_count
            _vsg = tab_widgets.get("video_src_group")
            if _vsg:
                _vsg.setTitle(f"Видео файл (источник) [{total}/5]")

        def _on_add_extra_video():
            rr = self._find_row(fn)
            if not rr: return
            evs = rr.get("extra_videos", [])
            if len(evs) >= 4:
                QMessageBox.warning(self, "Ограничение",
                                    "Максимум 5 видео файлов\n(1 основной + 4 дополнительных)")
                return
            evs.append({"video": "", "video_full_path": "", "video_manual": False,
                        "fps": "", "prefix": "", "suffix": "",
                        "prefix_cb": False, "suffix_cb": False})
            rr["extra_videos"] = evs
            _rebuild_extra_videos()
            _update_audio_status()
            _update_extra_output_names()
            self._check_row_status(rr)
            self.schedule_autosave()

        def _on_del_extra_video(idx):
            rr = self._find_row(fn)
            if not rr: return
            evs = rr.get("extra_videos", [])
            if idx < len(evs):
                ev = evs[idx]
                ev_v = ev.get("video", "")
                ev_vfp = ev.get("video_full_path", "")
                ev_vn = ev_v or (os.path.basename(ev_vfp) if ev_vfp else "")
                # Проверить есть ли выходные файлы этого видео в тесте/результате
                if ev_vn:
                    _prefix = self._get_prefix(rr)
                    _suffix = self._get_suffix(rr)
                    _ev_out = f"{_prefix}{os.path.splitext(ev_vn)[0]}{_suffix}.mkv"
                    _tp2 = self.test_path_edit.text()
                    _op2 = self.output_path_edit.text()
                    _orphans = []
                    if _tp2 and os.path.isfile(os.path.join(_tp2, _ev_out)):
                        _orphans.append(("тест", os.path.join(_tp2, _ev_out)))
                    if _op2 and os.path.isfile(os.path.join(_op2, _ev_out)):
                        _orphans.append(("результат", os.path.join(_op2, _ev_out)))
                    if _orphans:
                        _locs = ", ".join(loc for loc, _ in _orphans)
                        ans = QMessageBox.question(self, "Удаление доп. видео",
                            f"Файл «{_ev_out}» уже есть в папке {_locs}.\n\n"
                            f"Удалить этот файл вместе с видео-источником?\n"
                            f"Если не удалить — файл останется на диске без связи с системой.",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                        if ans == QMessageBox.Yes:
                            for loc, path in _orphans:
                                try:
                                    os.remove(path)
                                    self.log(f"[DEL] Файл доп. видео ({loc}): {os.path.basename(path)}")
                                except Exception as e:
                                    self.log(f"[ERR] Не удалось удалить: {path} — {e}")
                evs.pop(idx)
                _rebuild_extra_videos()
                _update_audio_status()
                _update_extra_output_names()
                self._check_row_status(rr)
                self.schedule_autosave()

        def _on_extra_video_changed(idx):
            rr = self._find_row(fn)
            if not rr: return
            evs = rr.get("extra_videos", [])
            widgets = tab_widgets.get("extra_video_widgets", [])
            if idx < len(evs) and idx < len(widgets):
                w = widgets[idx]
                v_name = w["video_combo"].currentData(Qt.UserRole) or ""
                # Проверка дублей имён
                if v_name:
                    main_vn = rr["video_combo"].currentText()
                    existing = [main_vn] if main_vn and main_vn != "— снять выбор —" else []
                    for j, e in enumerate(evs):
                        if j != idx and e.get("video"):
                            existing.append(e["video"])
                    if v_name in existing:
                        QMessageBox.warning(self, "Ошибка",
                            f"Файл «{v_name}» уже выбран.\n"
                            "Нельзя использовать видео с одинаковым именем —\n"
                            "выходные файлы будут иметь одинаковые имена.")
                        w["video_combo"].blockSignals(True)
                        w["video_combo"].setCurrentIndex(0)
                        w["video_combo"].blockSignals(False)
                        evs[idx]["video"] = ""
                        evs[idx]["video_full_path"] = ""
                        evs[idx].pop("_cached_duration", None)
                        _rebuild_extra_videos()
                        return
                evs[idx]["video"] = v_name
                vp = self.video_path_edit.text()
                if v_name and vp:
                    evs[idx]["video_full_path"] = os.path.join(vp, v_name)
                    evs[idx]["video_manual"] = False
                    evs[idx].pop("_cached_duration", None)
                elif not v_name:
                    evs[idx]["video_full_path"] = ""
                    evs[idx].pop("_cached_duration", None)
            _rebuild_extra_videos()
            _update_audio_status()
            _update_extra_output_names()
            self._check_row_status(rr)
            self.schedule_autosave()

        def _on_browse_extra_video(idx):
            rr = self._find_row(fn)
            if not rr: return
            evs = rr.get("extra_videos", [])
            if idx >= len(evs): return
            vp = self.video_path_edit.text() or ""
            path, _ = QFileDialog.getOpenFileName(self, "Выбрать видео файл", vp,
                                                  "Видео (*.mkv *.mp4 *.avi *.ts *.m2ts *.wmv *.mov);;Все (*)")
            if path:
                bname = os.path.basename(path)
                # Проверка дублей
                main_vn = rr["video_combo"].currentText()
                existing = [main_vn] if main_vn and main_vn != "— снять выбор —" else []
                for j, e in enumerate(evs):
                    if j != idx and e.get("video"):
                        existing.append(e["video"])
                if bname in existing:
                    QMessageBox.warning(self, "Ошибка",
                        f"Файл «{bname}» уже выбран.\n"
                        "Нельзя использовать видео с одинаковым именем.")
                    return
                evs[idx]["video"] = bname
                evs[idx]["video_full_path"] = path
                evs[idx]["video_manual"] = True
                evs[idx].pop("_cached_duration", None)
                _rebuild_extra_videos()
                _update_audio_status()
                _update_extra_output_names()
                self._check_row_status(rr)
                self.schedule_autosave()

        _add_ev_btn.clicked.connect(_on_add_extra_video)
        tab_widgets["rebuild_extra_videos"] = _rebuild_extra_videos
        # _ev_container будет добавлен в video_src_layout ниже
        _rebuild_extra_videos()

        # --- Задержки аудио (5 в ряд) ---
        delays_header = QHBoxLayout()
        delays_header.setSpacing(4)
        _init_delay_count = len(r.get("delays", [{"value": "0", "confirmed": False}]))
        _dl = QLabel(f"Задержки аудио (мс) [{_init_delay_count}/10]:")
        _dl.setStyleSheet("font-weight:bold;")
        tab_widgets["delays_header_lbl"] = _dl
        _dl.setToolTip("Задержки аудио дорожки в миллисекундах.\n"
                        "Каждая задержка создаёт отдельную аудио дорожку в MKV.\n"
                        "Значение задержки добавляется в начало имени аудио дорожки.\n"
                        "Если задержек несколько — дорожки располагаются в том порядке,\n"
                        "в котором они заданы здесь.\n"
                        "Подтверждённая задержка (✓) отображается в таблице.")
        delays_header.addWidget(_dl)
        _delay_fmt = QLabel("без знака или + → аудио позже,  со знаком − → аудио раньше")
        _delay_fmt.setStyleSheet("color:#888; font-size:10px;")
        _delay_fmt.setToolTip("Примеры задержек:\n"
                              "  500  → аудио позже на 500мс (= +500)\n"
                              "  −500 → аудио раньше на 500мс\n"
                              "  0    → без задержки")
        delays_header.addWidget(_delay_fmt)
        add_delay_btn = QPushButton("+")
        add_delay_btn.setFont(BTN_FONT)
        add_delay_btn.setFixedWidth(24)
        add_delay_btn.setToolTip("Добавить ещё одну задержку (макс 10) — создаст дополнительную аудио дорожку при обработке")
        delays_header.addWidget(add_delay_btn)
        delay_status_lbl = QLabel("")
        delay_status_lbl.setStyleSheet("color:green; font-weight:bold;")
        delay_status_lbl.setToolTip("Информация о подтверждённой задержке, отображаемой в таблице")
        tab_widgets["delay_status_lbl"] = delay_status_lbl
        delays_header.addWidget(delay_status_lbl)
        delay_dup_lbl = QLabel("")
        delay_dup_lbl.setStyleSheet("color:red; font-weight:bold;")
        delay_dup_lbl.setToolTip("Количество задержек с одинаковыми значениями — дубли создадут одинаковые дорожки")
        tab_widgets["delay_dup_lbl"] = delay_dup_lbl
        delays_header.addWidget(delay_dup_lbl)
        delays_header.addStretch()
        files_layout.addLayout(delays_header)

        delays_container = QWidget()
        delays_container_layout = QVBoxLayout(delays_container)
        delays_container_layout.setContentsMargins(0, 0, 0, 0)
        delays_container_layout.setSpacing(2)
        tab_widgets["delay_widgets"] = []
        tab_widgets["_delay_row_containers"] = []

        def _rebuild_tab_delays():
            """Перестроить UI задержек из r['delays'] — по 5 в ряд."""
            rr = self._find_row(fn)
            if not rr: return
            for rc in tab_widgets.get("_delay_row_containers", []):
                rc.setParent(None)
                rc.deleteLater()
            tab_widgets["_delay_row_containers"] = []
            tab_widgets["delay_widgets"] = []
            delays = rr.get("delays", [{"value": "0", "confirmed": False}])
            can_del = len(delays) > 1
            current_container = None
            current_hbox = None
            for i, d in enumerate(delays):
                if i % 5 == 0:
                    current_container = QWidget()
                    current_hbox = QHBoxLayout(current_container)
                    current_hbox.setContentsMargins(0, 0, 0, 0)
                    current_hbox.setSpacing(2)
                    delays_container_layout.addWidget(current_container)
                    tab_widgets["_delay_row_containers"].append(current_container)
                input_w = QLineEdit(d.get("value", "0"))
                input_w.setMaximumWidth(70)
                input_w.setToolTip("Задержка аудио дорожки в миллисекундах (положительное = аудио позже)")
                current_hbox.addWidget(input_w)
                confirmed = d.get("confirmed", False)
                confirm_btn = QPushButton("✓" if confirmed else "○")
                confirm_btn.setFixedSize(_btn_h, _btn_h)
                confirm_btn.setStyleSheet("color:green;" if confirmed else "color:gray;")
                confirm_btn.setToolTip("Подтвердить задержку — подтверждённая отображается в таблице")
                current_hbox.addWidget(confirm_btn)
                del_btn = QPushButton("−")
                del_btn.setFixedSize(_btn_h, _btn_h)
                del_btn.setToolTip("Удалить эту задержку")
                del_btn.setStyleSheet("QPushButton{color:black; background-color:#ffe8e8; border:1px solid #cc9999;} QPushButton:hover{background-color:#ffcccc;}")
                del_btn.setEnabled(can_del)
                current_hbox.addWidget(del_btn)
                if (i + 1) % 5 != 0 and i < len(delays) - 1:
                    current_hbox.addSpacing(8)
                dw = {"input": input_w, "confirm_btn": confirm_btn, "delete_btn": del_btn}
                tab_widgets["delay_widgets"].append(dw)
                confirm_btn.clicked.connect(lambda _, idx=i: _on_tab_confirm_delay(idx))
                del_btn.clicked.connect(lambda _, idx=i: _on_tab_delete_delay(idx))
                input_w.textChanged.connect(lambda text, idx=i: _on_tab_delay_value_changed(idx, text))
            if current_hbox:
                current_hbox.addStretch()
            # Добавить stretch ко всем предыдущим строкам (чтобы элементы были прижаты влево)
            for rc in tab_widgets["_delay_row_containers"][:-1] if len(tab_widgets["_delay_row_containers"]) > 1 else []:
                rc.layout().addStretch()
            # Обновить заголовок с количеством задержек
            _dhl = tab_widgets.get("delays_header_lbl")
            if _dhl:
                _dhl.setText(f"Задержки аудио (мс) [{len(delays)}/10]:")
            _update_delay_duplicates()

        def _update_delay_duplicates():
            """Подсветить дубли задержек красным и показать количество."""
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            values = [d.get("value", "0") for d in delays]
            from collections import Counter
            counts = Counter(values)
            dup_values = {v for v, c in counts.items() if c > 1}
            total_dups = sum(c - 1 for c in counts.values() if c > 1)
            dws = tab_widgets.get("delay_widgets", [])
            for i, dw in enumerate(dws):
                inp = dw.get("input")
                if inp and i < len(values):
                    if values[i] in dup_values:
                        inp.setStyleSheet("border: 2px solid red;")
                        inp.setToolTip(f"Дубль! Значение «{values[i]}» повторяется {counts[values[i]]} раз")
                    else:
                        inp.setStyleSheet("")
                        inp.setToolTip("Задержка аудио дорожки в миллисекундах (положительное = аудио позже)")
            _dup_lbl = tab_widgets.get("delay_dup_lbl")
            if _dup_lbl:
                if total_dups:
                    _dup_lbl.setText(f"⚠ дублей: {total_dups}")
                else:
                    _dup_lbl.setText("")
        tab_widgets["update_delay_duplicates"] = _update_delay_duplicates

        def _on_tab_confirm_delay(idx):
            """Radio-подтверждение задержки на вкладке."""
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            if idx >= len(delays): return
            was_confirmed = delays[idx].get("confirmed", False)
            for d in delays:
                d["confirmed"] = False
            if not was_confirmed:
                delays[idx]["confirmed"] = True
            self._sync_delays_to_table(rr)
            _rebuild_tab_delays()
            _update_delay_status()
            _update_audio_status()
            _update_del_unconfirmed_visibility()
            _update_track_preview()
            self.schedule_autosave()

        def _on_tab_delete_delay(idx):
            """Удалить задержку на вкладке."""
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            if len(delays) <= 1 or idx >= len(delays): return
            was_confirmed = delays[idx].get("confirmed", False)
            delays.pop(idx)
            if was_confirmed and delays:
                delays[0]["confirmed"] = True
            self._sync_delays_to_table(rr)
            _rebuild_tab_delays()
            _update_delay_status()
            _update_audio_status()
            _update_del_unconfirmed_visibility()
            _update_track_preview()
            self.schedule_autosave()

        def _on_tab_delay_value_changed(idx, text):
            """Значение задержки на вкладке изменилось."""
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            if idx >= len(delays): return
            delays[idx]["value"] = text
            self._sync_delays_to_table(rr)
            _update_delay_duplicates()
            _update_track_preview()
            self.schedule_autosave()

        def _on_add_tab_delay():
            """Добавить новую задержку."""
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            if len(delays) >= 10:
                QMessageBox.warning(self, "Ограничение",
                                    "Максимум 10 задержек")
                return
            delays.append({"value": "0", "confirmed": False})
            self._sync_delays_to_table(rr)
            _rebuild_tab_delays()
            _update_delay_status()
            _update_audio_status()
            _update_del_unconfirmed_visibility()
            _update_track_preview()
            self.schedule_autosave()

        def _update_delay_status():
            rr = self._find_row(fn)
            if not rr: return
            delays = rr.get("delays", [])
            confirmed = [d for d in delays if d.get("confirmed")]
            if confirmed:
                val = confirmed[0]["value"]
                total = len(delays)
                if total > 1:
                    delay_status_lbl.setText(f"Задержка подтверждена: {val}мс (всего дорожек: {total})")
                else:
                    delay_status_lbl.setText(f"Задержка подтверждена: {val}мс")
                delay_status_lbl.setStyleSheet("color:green; font-weight:bold;")
            else:
                delay_status_lbl.setText("Задержка не подтверждена")
                delay_status_lbl.setStyleSheet("color:gray;")
        tab_widgets["update_delay_status"] = _update_delay_status

        add_delay_btn.clicked.connect(_on_add_tab_delay)
        tab_widgets["rebuild_delay_rows"] = _rebuild_tab_delays
        _rebuild_tab_delays()
        _update_delay_status()
        files_layout.addWidget(delays_container)
        files_layout.addWidget(_preview_btn)
        files_layout.addWidget(_preview_text)
        russdub_layout.addWidget(files_group)

        # --- Выходной файл (QGroupBox) ---
        output_group = QGroupBox()
        output_group.setTitle("Выходной файл")
        output_group.setStyleSheet("QGroupBox { background-color: #e8f0fe; border: 1px solid #b0c4de; border-radius: 4px; margin-top: 6px; padding-top: 12px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        output_group.setToolTip("Выходные файлы и кастомный префикс/суффикс.\nФормат: {префикс}{имя_видео}{суффикс}.mkv")
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(2)
        output_layout.setContentsMargins(6, 14, 6, 4)
        # Кнопка 📁 — будет добавлена в строку аффиксов ниже
        _out_dir = ""
        _out_text = r["output_entry"].text() if r.get("output_entry") else ""
        _op = self.output_path_edit.text()
        _tp = self.test_path_edit.text()
        if _out_text and _op and os.path.isfile(os.path.join(_op, _out_text)):
            _out_dir = _op
        elif _out_text and _tp and os.path.isfile(os.path.join(_tp, _out_text)):
            _out_dir = _tp
        tab_open_output_dir = QPushButton("📁")
        tab_open_output_dir.setFont(BTN_FONT); tab_open_output_dir.setFixedWidth(28)
        tab_open_output_dir.setToolTip(f"Открыть папку с результатом:\n{_out_dir}" if _out_dir else "Открыть папку тест/результат")
        tab_open_output_dir.clicked.connect(lambda _, f=fn: self._open_output_dir_from_tab(f))
        tab_widgets["open_output_dir"] = tab_open_output_dir

        # Основной выходной файл — вариант 1
        _out_v1_frame = QWidget()
        _out_v1_lay = QVBoxLayout(_out_v1_frame)
        _out_v1_lay.setContentsMargins(0, 0, 0, 0)
        _out_v1_lay.setSpacing(2)
        # Строка имени файла
        row2c_name = QHBoxLayout()
        _out_num = QLabel("1:")
        _out_num.setStyleSheet("font-weight:bold;")
        _out_num.setToolTip("Выходной файл 1 (основной видео)")
        row2c_name.addWidget(_out_num)
        tab_output = QLineEdit(_out_text)
        tab_output.setReadOnly(True)
        tab_output.setStyleSheet("border:none; background:transparent; color:#333;")
        tab_output.setToolTip("Имя выходного файла — результат объединения аудио и видео через mkvmerge")
        tab_output.setMinimumWidth(300)
        tab_output.setCursorPosition(0)
        tab_widgets["output_entry"] = tab_output
        if not _out_text:
            tab_output.setPlaceholderText("файл не найден")
        row2c_name.addWidget(tab_output)
        row2c_name.addStretch()
        _out_v1_lay.addLayout(row2c_name)
        # Строка FPS + аффикс + 📁 (внутри фрейма 1)
        _v1_affix = QHBoxLayout()
        _v1_affix.setSpacing(4)
        _fps_lbl1 = QLabel("FPS:")
        _fps_lbl1.setStyleSheet("font-weight:bold;")
        _fps_lbl1.setToolTip("Частота кадров видео (--default-duration).\n"
                             "«авто» — mkvmerge оставит оригинальную частоту.\n"
                             "Изменение FPS замедляет/ускоряет воспроизведение.\n"
                             "23.976 — стандарт для фильмов (NTSC film).")
        _v1_affix.addWidget(_fps_lbl1)
        _fps_combo = QComboBox()
        _fps_combo.setEditable(True)
        _fps_combo.addItems(["авто", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60"])
        _fps_combo.setFixedWidth(80)
        _fps_combo.setToolTip("Частота кадров для видео дорожки.\n"
                              "«авто» — оставить оригинальную.\n"
                              "Можно ввести произвольное значение.\n"
                              "Добавляет --default-duration 0:XXfps в mkvmerge.")
        _fps_combo.setCurrentText(r.get("video_fps", "авто"))
        def _on_fps_changed(val, _fn=fn):
            rr = self._find_row(_fn)
            if rr:
                rr["video_fps"] = val
                self.schedule_autosave()
        _fps_combo.currentTextChanged.connect(_on_fps_changed)
        tab_widgets["fps_combo"] = _fps_combo
        _v1_affix.addWidget(_fps_combo)
        _v1_affix.addSpacing(8)
        _v1_affix_lbl = QLabel("Аффикс:")
        _v1_affix_lbl.setStyleSheet("font-weight:bold;")
        _v1_affix_lbl.setToolTip("Кастомный префикс и суффикс для имени выходного файла.\nФормат: {префикс}{имя_видео}{суффикс}.mkv")
        _v1_affix.addWidget(_v1_affix_lbl)
        _v1_affix.addWidget(QLabel("в начале:"))
        tab_prefix_cb = QCheckBox()
        tab_prefix_cb.setChecked(r["prefix_cb"].isChecked() if r.get("prefix_cb") else False)
        tab_prefix_cb.setToolTip("Включить кастомный префикс (в начале имени файла)")
        tab_widgets["prefix_cb"] = tab_prefix_cb
        _v1_affix.addWidget(tab_prefix_cb)
        tab_prefix = QLineEdit(r["prefix_entry"].text() if r.get("prefix_entry") else "")
        tab_prefix.setToolTip("Кастомный префикс — добавляется В НАЧАЛО имени выходного файла")
        tab_prefix.setEnabled(tab_prefix_cb.isChecked())
        tab_prefix.setMaximumWidth(100)
        tab_widgets["prefix_entry"] = tab_prefix
        _v1_affix.addWidget(tab_prefix)
        _v1_affix.addSpacing(8)
        _v1_affix.addWidget(QLabel("в конце:"))
        tab_suffix_cb = QCheckBox()
        tab_suffix_cb.setChecked(r["suffix_cb"].isChecked() if r.get("suffix_cb") else False)
        tab_suffix_cb.setToolTip("Включить кастомный суффикс (в конце имени файла)")
        tab_widgets["suffix_cb"] = tab_suffix_cb
        _v1_affix.addWidget(tab_suffix_cb)
        tab_suffix = QLineEdit(r["suffix_entry"].text() if r.get("suffix_entry") else "")
        tab_suffix.setToolTip("Кастомный суффикс — добавляется В КОНЕЦ имени выходного файла (например: _ATMOS)")
        tab_suffix.setEnabled(tab_suffix_cb.isChecked())
        tab_suffix.setMaximumWidth(100)
        tab_widgets["suffix_entry"] = tab_suffix
        _v1_affix.addWidget(tab_suffix)
        _v1_affix.addSpacing(4)
        _v1_affix.addWidget(tab_open_output_dir)
        _v1_affix.addStretch()
        _out_v1_lay.addLayout(_v1_affix)
        # Строка кнопок (под аффиксом)
        row2c_btns = QHBoxLayout()
        _btn_to_res_1 = QPushButton("1 В Результат")
        _btn_to_res_1.setIcon(_make_to_result_icon())
        _btn_to_res_1.setIconSize(QSize(32, 16))
        _btn_to_res_1.setStyleSheet("QPushButton{background-color:#ccffcc;} QPushButton:hover{background-color:#99ff99;}")
        _btn_to_res_1.setToolTip("Переместить выходной файл 1 из папки тест в папку результат")
        _btn_to_res_1.clicked.connect(lambda _, f=fn: self._action_to_result(f))
        _btn_to_res_1.setEnabled(False)
        tab_widgets["out_btn_to_res_1"] = _btn_to_res_1
        row2c_btns.addWidget(_btn_to_res_1)
        _btn_del_test_1 = QPushButton("1 Тест")
        _btn_del_test_1.setIcon(_make_del_video_icon())
        _btn_del_test_1.setIconSize(QSize(32, 16))
        _btn_del_test_1.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;}")
        _btn_del_test_1.setToolTip("Удалить тестовый файл 1 из папки тест")
        _btn_del_test_1.clicked.connect(lambda _, f=fn: self._action_del_test(f))
        _btn_del_test_1.setEnabled(False)
        tab_widgets["out_btn_del_test_1"] = _btn_del_test_1
        row2c_btns.addWidget(_btn_del_test_1)
        _btn_del_res_1 = QPushButton("1 Результат")
        _btn_del_res_1.setIcon(_make_del_video_icon())
        _btn_del_res_1.setIconSize(QSize(32, 16))
        _btn_del_res_1.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;}")
        _btn_del_res_1.setToolTip("Удалить выходной файл 1 из результата")
        _btn_del_res_1.clicked.connect(lambda _, f=fn: self._action_del_result(f))
        _btn_del_res_1.setEnabled(False)
        tab_widgets["out_btn_del_res_1"] = _btn_del_res_1
        row2c_btns.addWidget(_btn_del_res_1)
        row2c_btns.addStretch()
        _out_v1_lay.addLayout(row2c_btns)
        output_layout.addWidget(_out_v1_frame)

        # --- Контейнер доп. выходных файлов ---
        _extra_out_container = QWidget()
        _extra_out_layout = QVBoxLayout(_extra_out_container)
        _extra_out_layout.setContentsMargins(0, 0, 0, 0)
        _extra_out_layout.setSpacing(1)
        tab_widgets["_extra_out_container"] = _extra_out_container
        tab_widgets["_extra_out_labels"] = []
        _extra_out_container.setVisible(False)

        def _update_extra_output_names():
            """Обновить имена доп. выходных файлов при >1 видео."""
            rr = self._find_row(fn)
            if not rr: return
            # Удалить старые виджеты
            for w in tab_widgets.get("_extra_out_labels", []):
                w.setParent(None); w.deleteLater()
            tab_widgets["_extra_out_labels"] = []
            evs = rr.get("extra_videos", [])
            prefix = self._get_prefix(rr)
            suffix = self._get_suffix(rr)
            _op2 = self.output_path_edit.text()
            _tp2 = self.test_path_edit.text()
            has_any = False
            for i, ev in enumerate(evs):
                v_name = ev.get("video", "")
                v_path = ev.get("video_full_path", "")
                if not v_name and v_path:
                    v_name = os.path.basename(v_path)
                if not v_name:
                    continue
                has_any = True
                # Per-video prefix/suffix: если чекбокс включён — использовать своё, иначе наследовать
                _ev_prefix = ev.get("prefix", "") if ev.get("prefix_cb") else prefix
                _ev_suffix = ev.get("suffix", "") if ev.get("suffix_cb") else suffix
                out_name = f"{_ev_prefix}{os.path.splitext(v_name)[0]}{_ev_suffix}.mkv"
                num = i + 2
                # Разделитель между вариантами
                _sep = QFrame()
                _sep.setFrameShape(QFrame.HLine)
                _sep.setFrameShadow(QFrame.Sunken)
                _sep.setStyleSheet("color: #bbb;")
                _extra_out_layout.addWidget(_sep)
                tab_widgets["_extra_out_labels"].append(_sep)
                # Контейнер варианта
                _v_frame = QWidget()
                _v_lay = QVBoxLayout(_v_frame)
                _v_lay.setContentsMargins(0, 0, 0, 0)
                _v_lay.setSpacing(2)
                # Строка имени файла
                _name_row = QHBoxLayout()
                _n_lbl = QLabel(f"{num}:")
                _n_lbl.setStyleSheet("font-weight:bold;")
                _n_lbl.setToolTip(f"Выходной файл {num} (видео #{num})")
                _name_row.addWidget(_n_lbl)
                _name_lbl = QLabel(out_name)
                _name_lbl.setStyleSheet("color:#333;")
                _name_lbl.setToolTip(f"Выходной файл для видео: {v_name}")
                _name_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                _name_row.addWidget(_name_lbl)
                _name_row.addStretch()
                _v_lay.addLayout(_name_row)
                # Строка FPS + аффикс (как в frame 1)
                _ev_idx = i  # захватить индекс
                _affix_row = QHBoxLayout()
                _affix_row.setSpacing(4)
                _ev_fps_lbl = QLabel("FPS:")
                _ev_fps_lbl.setStyleSheet("font-weight:bold;")
                _ev_fps_lbl.setToolTip(f"FPS для видео #{num}.\nПусто = наследовать от основного ({rr.get('video_fps', 'авто')}).")
                _affix_row.addWidget(_ev_fps_lbl)
                _ev_fps = QComboBox()
                _ev_fps.setEditable(True)
                _ev_fps.addItems(["", "авто", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60"])
                _ev_fps.setFixedWidth(80)
                _ev_fps.setCurrentText(ev.get("fps", ""))
                _ev_fps.setToolTip(f"FPS для видео #{num}.\nПусто = наследовать от основного.\nМожно ввести произвольное значение.")
                _ev_fps.lineEdit().setPlaceholderText(rr.get("video_fps", "авто"))
                _ev_fps.currentTextChanged.connect(
                    lambda val, _idx=_ev_idx, _fn=fn: self._on_extra_video_fps_changed(_fn, _idx, val))
                _affix_row.addWidget(_ev_fps)
                _affix_row.addSpacing(8)
                _ev_affix_lbl = QLabel("Аффикс:")
                _ev_affix_lbl.setStyleSheet("font-weight:bold;")
                _ev_affix_lbl.setToolTip(f"Кастомный префикс и суффикс для выходного файла #{num}.\nПусто = наследовать от основного.")
                _affix_row.addWidget(_ev_affix_lbl)
                _pre_lbl = QLabel("в начале:")
                _pre_lbl.setToolTip(f"Префикс для видео #{num}.\nВключите чекбокс и введите значение.\nОтключен = наследовать от основного.")
                _affix_row.addWidget(_pre_lbl)
                _ev_pre_cb = QCheckBox()
                _ev_pre_cb.setChecked(ev.get("prefix_cb", False))
                _ev_pre_cb.setToolTip(f"Включить кастомный префикс для видео #{num}")
                _ev_pre_cb.stateChanged.connect(
                    lambda st, _idx=_ev_idx, _fn=fn: self._on_extra_video_affix_changed(_fn, _idx, "prefix_cb", bool(st)))
                _affix_row.addWidget(_ev_pre_cb)
                _ev_pre = QLineEdit(ev.get("prefix", ""))
                _ev_pre.setMaximumWidth(100)
                _ev_pre.setPlaceholderText(prefix)
                _ev_pre.setEnabled(_ev_pre_cb.isChecked())
                _ev_pre.setToolTip(f"Префикс имени выходного файла #{num}.\nОтключен = наследовать от основного ({prefix}).")
                _ev_pre.textChanged.connect(
                    lambda val, _idx=_ev_idx, _fn=fn: self._on_extra_video_affix_changed(_fn, _idx, "prefix", val))
                _ev_pre_cb.toggled.connect(_ev_pre.setEnabled)
                _affix_row.addWidget(_ev_pre)
                _affix_row.addSpacing(8)
                _suf_lbl = QLabel("в конце:")
                _suf_lbl.setToolTip(f"Суффикс для видео #{num}.\nВключите чекбокс и введите значение.\nОтключен = наследовать от основного.")
                _affix_row.addWidget(_suf_lbl)
                _ev_suf_cb = QCheckBox()
                _ev_suf_cb.setChecked(ev.get("suffix_cb", False))
                _ev_suf_cb.setToolTip(f"Включить кастомный суффикс для видео #{num}")
                _ev_suf_cb.stateChanged.connect(
                    lambda st, _idx=_ev_idx, _fn=fn: self._on_extra_video_affix_changed(_fn, _idx, "suffix_cb", bool(st)))
                _affix_row.addWidget(_ev_suf_cb)
                _ev_suf = QLineEdit(ev.get("suffix", ""))
                _ev_suf.setMaximumWidth(100)
                _ev_suf.setPlaceholderText(suffix)
                _ev_suf.setEnabled(_ev_suf_cb.isChecked())
                _ev_suf.setToolTip(f"Суффикс имени выходного файла #{num}.\nОтключен = наследовать от основного ({suffix}).")
                _ev_suf.textChanged.connect(
                    lambda val, _idx=_ev_idx, _fn=fn: self._on_extra_video_affix_changed(_fn, _idx, "suffix", val))
                _ev_suf_cb.toggled.connect(_ev_suf.setEnabled)
                _affix_row.addWidget(_ev_suf)
                _affix_row.addSpacing(4)
                # Кнопка 📁 — открыть папку с этим файлом
                _ev_open_dir = QPushButton("📁")
                _ev_open_dir.setFont(BTN_FONT); _ev_open_dir.setFixedWidth(28)
                _ev_out_dir = ""
                if out_name and _op2 and os.path.isfile(os.path.join(_op2, out_name)):
                    _ev_out_dir = _op2
                elif out_name and _tp2 and os.path.isfile(os.path.join(_tp2, out_name)):
                    _ev_out_dir = _tp2
                _ev_open_dir.setToolTip(f"Открыть папку с результатом:\n{_ev_out_dir}" if _ev_out_dir else "Открыть папку тест/результат")
                tab_widgets[f"open_output_dir_{num}"] = _ev_open_dir
                _ev_open_dir.clicked.connect(
                    lambda _, _on=out_name, _o=_op2, _t=_tp2: self._open_output_dir_for_file(_on, _o, _t))
                _affix_row.addWidget(_ev_open_dir)
                _affix_row.addStretch()
                _v_lay.addLayout(_affix_row)
                # Строка кнопок (под именем)
                _in_test = bool(_tp2 and os.path.isfile(os.path.join(_tp2, out_name)))
                _in_res = bool(_op2 and os.path.isfile(os.path.join(_op2, out_name)))
                _test_sz = _format_file_size_gb(os.path.join(_tp2, out_name)) if _in_test else ""
                _res_sz = _format_file_size_gb(os.path.join(_op2, out_name)) if _in_res else ""
                _btns_row = QHBoxLayout()
                _on = out_name
                _btr = QPushButton(f"{num} В Результат {_test_sz}" if _test_sz else f"{num} В Результат")
                _btr.setIcon(_make_to_result_icon())
                _btr.setIconSize(QSize(32, 16))
                _btr.setStyleSheet("QPushButton{background-color:#ccffcc;} QPushButton:hover{background-color:#99ff99;}")
                _btr.setToolTip(f"Переместить «{out_name}» из тест в результат")
                _btr.setEnabled(_in_test and not _in_res)
                _btr.clicked.connect(lambda _, f=fn, n=_on: self._action_to_result_single(f, n))
                _btns_row.addWidget(_btr)
                _bdt = QPushButton(f"{num} Тест {_test_sz}" if _test_sz else f"{num} Тест")
                _bdt.setIcon(_make_del_video_icon())
                _bdt.setIconSize(QSize(32, 16))
                _bdt.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;}")
                _bdt.setToolTip(f"Удалить «{out_name}» из папки тест")
                _bdt.setEnabled(_in_test)
                _bdt.clicked.connect(lambda _, f=fn, n=_on: self._action_del_test_single(f, n))
                _btns_row.addWidget(_bdt)
                _bdr = QPushButton(f"{num} Результат {_res_sz}" if _res_sz else f"{num} Результат")
                _bdr.setIcon(_make_del_video_icon())
                _bdr.setIconSize(QSize(32, 16))
                _bdr.setStyleSheet("QPushButton{background-color:#ffcccc;} QPushButton:hover{background-color:#ff9999;}")
                _bdr.setToolTip(f"Удалить «{out_name}» из результата")
                _bdr.setEnabled(_in_res)
                _bdr.clicked.connect(lambda _, f=fn, n=_on: self._action_del_result_single(f, n))
                _btns_row.addWidget(_bdr)
                _btns_row.addStretch()
                _v_lay.addLayout(_btns_row)
                _extra_out_layout.addWidget(_v_frame)
                tab_widgets["_extra_out_labels"].append(_v_frame)
            _extra_out_container.setVisible(has_any)
            # Обновить видимость и текст кнопок основного файла (с размером)
            _main_out = tab_output.text()
            _m_in_test = bool(_tp2 and _main_out and os.path.isfile(os.path.join(_tp2, _main_out)))
            _m_in_res = bool(_op2 and _main_out and os.path.isfile(os.path.join(_op2, _main_out)))
            _btn_to_res_1.setEnabled(_m_in_test and not _m_in_res)
            _btn_del_test_1.setEnabled(_m_in_test)
            _btn_del_res_1.setEnabled(_m_in_res)
            if _m_in_test:
                _sz1 = _format_file_size_gb(os.path.join(_tp2, _main_out))
                _btn_to_res_1.setText(f"1 В Результат {_sz1}" if _sz1 else "1 В Результат")
                _btn_del_test_1.setText(f"1 Тест {_sz1}" if _sz1 else "1 Тест")
            if _m_in_res:
                _sz1r = _format_file_size_gb(os.path.join(_op2, _main_out))
                _btn_del_res_1.setText(f"1 Результат {_sz1r}" if _sz1r else "1 Результат")
        tab_widgets["update_extra_output_names"] = _update_extra_output_names
        output_layout.addWidget(_extra_out_container)

        russdub_outer.addWidget(russdub_left, 0)
        # --- Постер справа (сохраняет пропорции, прижат к верху блока russdub) ---
        poster_lbl = AspectRatioLabel()
        poster_lbl.setMinimumWidth(60)
        poster_lbl.setStyleSheet("background: none; border: none;")
        poster_lbl.setToolTip("Постер фильма — загружается из URL в блоке «Данные о фильме»")
        poster_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        tab_widgets["poster_lbl"] = poster_lbl
        poster_url = r.get("poster_url", "")
        # Автозагрузка постера — отложена до создания poster_status (ниже)
        russdub_outer.addWidget(poster_lbl, 1)
        # === Блок "Видео файл (источник)" — ВЫШЕ аудио блока ===
        _ev_init_count = 1 + sum(1 for e in r.get("extra_videos", []) if e.get("video") or e.get("video_full_path"))
        video_src_group = QGroupBox(f"Видео файл (источник) [{_ev_init_count}/5]")
        video_src_group.setStyleSheet("QGroupBox { background-color: #d5f5d5; border: 1px solid #8fbc8f; border-radius: 4px; margin-top: 6px; padding-top: 12px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        video_src_group.setToolTip("Видео файл из папки видео — в него будет вставлена выбранная аудио дорожка\nМакс. 5 видео: 1 основной + 4 дополнительных")
        tab_widgets["video_src_group"] = video_src_group
        video_src_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        video_src_layout = QVBoxLayout(video_src_group)
        video_src_layout.setSpacing(2)
        video_src_layout.setContentsMargins(6, 14, 6, 10)
        # Локальный чекбокс — синхронизирован с глобальным self.show_used_videos_cb
        _show_used_cb = QCheckBox("Показать занятые видео в селекте")
        _show_used_cb.setChecked(self.show_used_videos_cb.isChecked())
        _show_used_cb.setToolTip("Показать в выпадающих списках «Видео файл (источник)»\n"
                                 "файлы, уже назначенные другим записям.\n"
                                 "Они выделены цветом и подписаны папкой-владельцем (не кликабельны).\n"
                                 "Выключить — в списках только свободные файлы.")
        _show_used_cb.toggled.connect(lambda checked: self.show_used_videos_cb.setChecked(checked))
        self.show_used_videos_cb.toggled.connect(_show_used_cb.setChecked)
        tab_widgets["show_used_videos_cb"] = _show_used_cb
        connections.append((self.show_used_videos_cb, _show_used_cb.setChecked))
        video_src_layout.addWidget(_show_used_cb)
        video_src_layout.addLayout(row2b)
        video_src_layout.addWidget(row2b2_widget)
        video_src_layout.addWidget(_ev_container)
        main_layout.addWidget(russdub_group)
        main_layout.addWidget(video_src_group)
        main_layout.addWidget(output_group)

        # === Блок "Данные о фильме" ===
        film_group = QGroupBox("Данные о фильме")
        film_group.setStyleSheet("QGroupBox { background-color: #f0e6f6; border: 1px solid #c4a8d8; border-radius: 4px; margin-top: 6px; padding-top: 12px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        film_main = QVBoxLayout(film_group)
        film_main.setSpacing(6)
        film_main.setContentsMargins(6, 14, 6, 4)
        # Label для ошибки поиска (скрыт по умолчанию)
        film_error_label = QLabel("")
        film_error_label.setStyleSheet("color: red; font-weight: bold;")
        film_error_label.setVisible(False)
        film_main.addWidget(film_error_label)
        tab_widgets["film_error_label"] = film_error_label
        # --- Строка 1: Название + Год ---
        _lt = QLabel("Название:")
        _lt.setToolTip("Название фильма — отображается в колонке «Название» таблицы")
        _lt.setStyleSheet("font-weight:bold; color:#555;")
        film_main.addWidget(_lt)
        row_f1 = QHBoxLayout()
        row_f1.setSpacing(4)
        tab_title = QLineEdit(r["title_entry"].text() if r.get("title_entry") else "")
        self._setup_auto_width(tab_title, 180)
        tab_title.setToolTip("Название фильма — используется для идентификации записи")
        tab_widgets["title_entry"] = tab_title
        row_f1.addWidget(tab_title)
        _ly = QLabel("Год:")
        _ly.setToolTip("Год выпуска фильма — отображается в колонке «Год» таблицы")
        _ly.setStyleSheet("font-weight:bold; color:#555;")
        row_f1.addWidget(_ly)
        tab_year = QLineEdit(r["year_entry"].text() if r.get("year_entry") else "")
        tab_year.setToolTip("Год выпуска фильма")
        tab_year.setMaximumWidth(60)
        setup_year_validation(tab_year)
        tab_widgets["year_entry"] = tab_year
        row_f1.addWidget(tab_year)
        row_f1.addStretch()
        film_main.addLayout(row_f1)
        # --- Строка 2: Постер URL ---
        _lpu = QLabel("Постер:")
        _lpu.setToolTip("URL изображения постера фильма")
        _lpu.setStyleSheet("font-weight:bold; color:#555;")
        film_main.addWidget(_lpu)
        row_f2 = QHBoxLayout()
        row_f2.setSpacing(4)
        tab_poster_url = QLineEdit(r.get("poster_url", ""))
        self._setup_auto_width(tab_poster_url, 200)
        tab_poster_url.setPlaceholderText("https://...poster.jpg")
        tab_poster_url.setToolTip("URL изображения постера фильма — нажмите «Загрузить» для предпросмотра")
        setup_url_validation(tab_poster_url)
        tab_widgets["poster_url_entry"] = tab_poster_url
        row_f2.addWidget(tab_poster_url)
        poster_load_btn = QPushButton("⬇")
        poster_load_btn.setFixedSize(_btn_h, _btn_h)
        poster_load_btn.setToolTip("Загрузить и отобразить постер по указанному URL")
        poster_status = QLabel("")
        poster_status.setStyleSheet("color:#cc0000; font-size:9px;")
        poster_status.setVisible(False)
        poster_status.setToolTip("Статус загрузки постера")
        tab_widgets["poster_status"] = poster_status
        poster_load_btn.clicked.connect(lambda _, lbl=poster_lbl, entry=tab_poster_url, sl=poster_status: (
            self._load_poster(entry.text().strip(), lbl, sl) if entry.text().strip() else None
        ))
        row_f2.addWidget(poster_load_btn)
        row_f2.addWidget(poster_status)
        row_f2.addStretch()
        # Автозагрузка постера при открытии вкладки
        if poster_url:
            self._load_poster(poster_url, poster_lbl, poster_status)
        film_main.addLayout(row_f2)
        # --- Строка 3: Кинопоиск ---
        _lkp = QLabel("Кинопоиск:")
        _lkp.setToolTip("Ссылка на страницу фильма на Кинопоиске")
        _lkp.setStyleSheet("font-weight:bold; color:#555;")
        film_main.addWidget(_lkp)
        row_f3 = QHBoxLayout()
        row_f3.setSpacing(4)
        tab_kinopoisk = QLineEdit(r.get("kinopoisk_url", ""))
        self._setup_auto_width(tab_kinopoisk, 200)
        tab_kinopoisk.setPlaceholderText("https://kinopoisk.ru/...")
        tab_kinopoisk.setToolTip("URL страницы фильма на Кинопоиске — нажмите → чтобы открыть в браузере")
        setup_url_validation(tab_kinopoisk)
        tab_widgets["kinopoisk_entry"] = tab_kinopoisk
        row_f3.addWidget(tab_kinopoisk)
        kb = QPushButton("→"); kb.setFont(BTN_FONT); kb.setFixedSize(_btn_h, _btn_h)
        kb.setToolTip("Открыть страницу фильма на Кинопоиске в браузере")
        kb.clicked.connect(lambda _, f=fn: self._open_kinopoisk_url(f))
        row_f3.addWidget(kb)
        kp_search = QPushButton(); kp_search.setFixedSize(_btn_h, _btn_h)
        _kp_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_icon.png")
        if os.path.isfile(_kp_icon_path):
            kp_search.setIcon(_make_kp_search_icon(_kp_icon_path, 48, mag_scale=0.42))
            kp_search.setIconSize(QSize(20, 20))
        kp_search.setToolTip("Поиск фильма на Кинопоиске по названию и году\nЕсли название не задано — поиск по имени папки")
        kp_search.clicked.connect(lambda _, f=fn: self._search_kinopoisk(f))
        row_f3.addWidget(kp_search)
        row_f3.addStretch()
        film_main.addLayout(row_f3)
        # --- Строка 4: Торрент видео ---
        _ltr = QLabel("Торрент видео:")
        _ltr.setToolTip("Ссылка на торрент с исходным видео файлом для скачивания")
        _ltr.setStyleSheet("font-weight:bold; color:#555;")
        film_main.addWidget(_ltr)
        row_f4 = QHBoxLayout()
        row_f4.setSpacing(4)
        tab_torrent = QLineEdit(r["torrent_entry"].text() if r.get("torrent_entry") else "")
        self._setup_auto_width(tab_torrent, 200)
        tab_torrent.setToolTip("URL торрента с исходным видео — нажмите → чтобы открыть в браузере")
        setup_url_validation(tab_torrent)
        tab_widgets["torrent_entry"] = tab_torrent
        row_f4.addWidget(tab_torrent)
        tb = QPushButton("→"); tb.setFont(BTN_FONT); tb.setFixedSize(_btn_h, _btn_h)
        tb.setToolTip("Открыть ссылку на торрент в браузере")
        tb.clicked.connect(lambda _, f=fn: self._open_torrent_url(f))
        row_f4.addWidget(tb)
        rt_search = QPushButton(); rt_search.setFixedSize(_btn_h, _btn_h)
        _rt_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "rutracker_logo.png")
        if os.path.isfile(_rt_icon_path):
            rt_search.setIcon(_make_kp_search_icon(_rt_icon_path, 48, mag_scale=0.42))
            rt_search.setIconSize(QSize(20, 20))
        rt_search.setToolTip("Поиск фильма на RuTracker по названию и году\nРезультаты отсортированы по размеру (от большего к меньшему)")
        rt_search.clicked.connect(lambda _, f=fn: self._search_rutracker(f))
        row_f4.addWidget(rt_search)
        # Кнопка подтверждения торрента
        _tc = r.get("torrent_confirmed", False)
        torrent_confirm_btn = QPushButton("✓" if _tc else "○")
        torrent_confirm_btn.setFixedSize(_btn_h, _btn_h)
        torrent_confirm_btn.setStyleSheet("color:green;" if _tc else "color:gray;")
        torrent_confirm_btn.setToolTip("Подтвердить торрент — подтверждённый отображается зелёным")
        tab_widgets["torrent_confirm_btn"] = torrent_confirm_btn
        row_f4.addWidget(torrent_confirm_btn)
        def _on_torrent_confirm():
            rr = self._find_row(fn)
            if not rr: return
            cur = rr.get("torrent_confirmed", False)
            rr["torrent_confirmed"] = not cur
            b = tab_widgets["torrent_confirm_btn"]
            b.setText("✓" if not cur else "○")
            b.setStyleSheet("color:green;" if not cur else "color:gray;")
            self.schedule_autosave()
        torrent_confirm_btn.clicked.connect(_on_torrent_confirm)
        # Кнопка "+" — добавить ещё торрент
        _add_torrent_btn = QPushButton("+")
        _add_torrent_btn.setFixedSize(_btn_h, _btn_h)
        _add_torrent_btn.setToolTip("Добавить ссылку на торрент видео (макс. 5)")
        tab_widgets["add_torrent_btn"] = _add_torrent_btn
        row_f4.addWidget(_add_torrent_btn)
        _tc_count_lbl = QLabel(f"[{1 + len(r.get('extra_torrent_urls', []))}/5]")
        _tc_count_lbl.setStyleSheet("color:#666; font-size:10px;")
        _tc_count_lbl.setToolTip("Текущее / макс. кол-во торрент-ссылок")
        tab_widgets["torrent_count_lbl"] = _tc_count_lbl
        row_f4.addWidget(_tc_count_lbl)
        row_f4.addStretch()
        film_main.addLayout(row_f4)
        # --- Контейнер для доп. торрент-строк ---
        extra_torrent_widget = QWidget()
        extra_torrent_lay = QVBoxLayout(extra_torrent_widget)
        extra_torrent_lay.setContentsMargins(0, 0, 0, 0)
        extra_torrent_lay.setSpacing(4)
        tab_widgets["extra_torrent_widget"] = extra_torrent_widget
        tab_widgets["extra_torrent_lay"] = extra_torrent_lay
        tab_widgets["extra_torrent_widgets"] = []
        film_main.addWidget(extra_torrent_widget)

        def _add_extra_torrent_row(url="", confirmed=False):
            existing = tab_widgets["extra_torrent_widgets"]
            if len(existing) >= 4:
                return
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(4)
            inp = QLineEdit(url)
            self._setup_auto_width(inp, 200)
            inp.setPlaceholderText("https://...")
            inp.setToolTip(f"Дополнительная ссылка на торрент видео #{len(existing) + 2}")
            setup_url_validation(inp)
            row_h.addWidget(inp)
            ob = QPushButton("→"); ob.setFont(BTN_FONT); ob.setFixedSize(_btn_h, _btn_h)
            ob.setToolTip("Открыть ссылку на торрент в браузере")
            ob.clicked.connect(lambda _, i=inp: (
                __import__('webbrowser').open(i.text().strip()) if i.text().strip() else None
            ))
            row_h.addWidget(ob)
            cb = QPushButton("✓" if confirmed else "○")
            cb.setFixedSize(_btn_h, _btn_h)
            cb.setStyleSheet("color:green;" if confirmed else "color:gray;")
            cb.setToolTip("Подтвердить торрент")
            row_h.addWidget(cb)
            db = QPushButton("−")
            db.setFixedSize(_btn_h, _btn_h)
            db.setStyleSheet("QPushButton{color:black; background-color:#ffe8e8; border:1px solid #cc9999;} QPushButton:hover{background-color:#ffcccc;}")
            db.setToolTip("Удалить этот торрент")
            row_h.addWidget(db)
            row_h.addStretch()
            entry = {"widget": row_w, "input": inp, "open_btn": ob, "confirm_btn": cb, "delete_btn": db, "confirmed": confirmed}
            existing.append(entry)
            tab_widgets["extra_torrent_lay"].addWidget(row_w)
            tab_widgets["torrent_count_lbl"].setText(f"[{1 + len(existing)}/5]")
            tab_widgets["add_torrent_btn"].setEnabled(len(existing) < 4)
            def toggle_confirm(_, e=entry, b=cb):
                e["confirmed"] = not e["confirmed"]
                b.setText("✓" if e["confirmed"] else "○")
                b.setStyleSheet("color:green;" if e["confirmed"] else "color:gray;")
                self.schedule_autosave()
            cb.clicked.connect(toggle_confirm)
            def delete_row(_, e=entry, w=row_w):
                tab_widgets["extra_torrent_widgets"].remove(e)
                w.setParent(None); w.deleteLater()
                tab_widgets["torrent_count_lbl"].setText(f"[{1 + len(tab_widgets['extra_torrent_widgets'])}/5]")
                tab_widgets["add_torrent_btn"].setEnabled(len(tab_widgets["extra_torrent_widgets"]) < 4)
                self.schedule_autosave()
            db.clicked.connect(delete_row)
            inp.textChanged.connect(lambda _: self.schedule_autosave())

        _add_torrent_btn.clicked.connect(lambda: _add_extra_torrent_row())
        # Восстановить сохранённые доп. торренты
        for _et in r.get("extra_torrent_urls", []):
            _add_extra_torrent_row(_et.get("url", ""), _et.get("confirmed", False))

        # (кнопка "Старые бекапы" перенесена в верхнюю панель — tab_old_backups_btn)
        # film_group будет добавлен на вкладку "Данные" в right_tabs (ниже)

        # === Проверка бэкапа ===
        backup_data = self._load_meta_backup_from_folder(fp)
        has_backup_conflict = backup_data is not None
        meta_path = os.path.join(fp, "_meta.json")
        meta_backup_path = os.path.join(fp, "_meta_backup.json")

        if has_backup_conflict:
            r["has_meta_backup"] = True

        main_layout.addStretch()
        scroll.setWidget(content)
        left_layout.addWidget(scroll)
        tab_root.addWidget(left_container)

        # --- ПРАВАЯ ЧАСТЬ: QTabWidget с вкладками txt и Бэкап ---
        right_tabs = QTabWidget(tab_root)
        right_tabs.setToolTip("Правая панель: txt файл и бэкапы")
        tab_widgets["right_tabs"] = right_tabs

        # == Вкладка "txt" ==
        txt_tab_widget = QWidget()
        txt_lay = QVBoxLayout(txt_tab_widget)
        txt_lay.setContentsMargins(4, 4, 4, 4)
        txt_files = r.get("txt_files", [])
        # Комбобокс выбора txt файла (если несколько)
        tab_txt_combo = QComboBox()
        tab_txt_combo.setToolTip("Выбор txt файла для просмотра и редактирования")
        tab_widgets["txt_combo"] = tab_txt_combo
        if txt_files:
            tab_txt_combo.addItems(sorted(txt_files))
            sel = r.get("selected_txt") or txt_files[0]
            tab_txt_combo.setCurrentText(sel)
        if len(txt_files) <= 1:
            tab_txt_combo.setVisible(False)
        txt_lay.addWidget(tab_txt_combo)
        # Текстовый редактор
        tab_txt_edit = QTextEdit()
        tab_txt_edit.setFont(QFont("Consolas", 10))
        tab_widgets["txt_edit"] = tab_txt_edit
        txt_path = ""
        txt_tab_title = "txt"
        if txt_files:
            sel = tab_txt_combo.currentText()
            txt_path = os.path.join(r.get("folder_path", ""), sel)
            self._load_txt_content(tab_txt_edit, txt_path)
            txt_tab_title = sel
        tab_widgets["_txt_path"] = txt_path
        tab_widgets["_txt_last"] = tab_txt_edit.toPlainText()
        txt_lay.addWidget(tab_txt_edit)

        right_tabs.addTab(txt_tab_widget, txt_tab_title)

        # Смена txt файла в комбобоксе вкладки
        def _on_tab_txt_combo(txt_name):
            if not txt_name:
                return
            # Сохранить текущий txt перед сменой
            self._save_tab_txt(fn)
            rr = self._find_row(fn)
            if not rr:
                return
            new_path = os.path.join(rr.get("folder_path", ""), txt_name)
            self._load_txt_content(tab_txt_edit, new_path)
            tab_widgets["_txt_path"] = new_path
            tab_widgets["_txt_last"] = tab_txt_edit.toPlainText()
            right_tabs.setTabText(0, txt_name)
            # Обновить выбор в таблице
            rr["selected_txt"] = txt_name
            rr["info_btn"].setText(txt_name[:15])
            rr["info_btn"].setStyleSheet("color:#006600; font-weight:bold;")
            rr["info_btn"].setToolTip(f"Выбран: {txt_name}\nПравый клик — выбрать другой txt")
            rr["txt_problem"] = False
            self.schedule_autosave()
        tab_txt_combo.currentTextChanged.connect(_on_tab_txt_combo)

        # == Вкладка "Данные" (данные о фильме) ==
        film_tab_widget = QWidget()
        film_tab_lay = QVBoxLayout(film_tab_widget)
        film_tab_lay.setContentsMargins(4, 4, 4, 4)
        film_tab_lay.addWidget(film_group)
        film_tab_lay.addStretch()
        right_tabs.addTab(film_tab_widget, "Данные о фильме")
        right_tabs.setTabToolTip(1, "Данные о фильме: название, год, постер, ссылки")

        # == Вкладка "Бэкап" (только при активном конфликте) ==
        if has_backup_conflict:
            backup_tab_widget = QWidget()
            backup_lay = QVBoxLayout(backup_tab_widget)
            backup_lay.setContentsMargins(4, 4, 4, 4)
            backup_lay.setSpacing(4)

            # Информация о файлах
            info_text = (
                f"<b>Файлы хранения данных:</b><br>"
                f"<b>1. Общая база:</b> <code>{FILMS_FILE}</code><br>"
                f"&nbsp;&nbsp;&nbsp;Содержит данные ВСЕХ фильмов в одном файле.<br>"
                f"<b>2. Файл в папке фильма:</b> <code>{meta_path}</code><br>"
                f"&nbsp;&nbsp;&nbsp;Копия данных этого фильма.<br>"
                f"<b>3. Бэкап:</b> <code>{meta_backup_path}</code><br>"
                f"&nbsp;&nbsp;&nbsp;Сохраняется при расхождении данных.<br>"
            )
            info_lbl = QLabel(info_text)
            info_lbl.setWordWrap(True)
            info_lbl.setStyleSheet("font-size:9pt; color:#333;")
            info_lbl.setTextFormat(Qt.RichText)
            backup_lay.addWidget(info_lbl)

            # Статус
            backup_date = backup_data.get("_backup_created", backup_data.get("_saved_at", "—"))
            backup_reason = backup_data.get("_backup_reason", "")
            status_lbl = QLabel(f"⚠ Бэкап от: {backup_date}  |  Причина создания: {backup_reason}")
            status_lbl.setStyleSheet("color:#cc0000; font-weight:bold; padding:4px; background:#fff0f0; border:1px solid #ffaaaa; border-radius:3px;")
            status_lbl.setToolTip("Есть расхождение между основными данными и бэкапом. Примите решение.\n\n"
                "Причина записывается автоматически в момент создания бэкапа:\n"
                "— при обнаружении расхождения данных между базой и файлом в папке фильма\n"
                "— при восстановлении из другого бэкапа (текущие данные сохраняются как бэкап)")
            backup_lay.addWidget(status_lbl)

            # Отличия
            diff_fields = []
            for field in self._META_COMPARE_FIELDS:
                cur_val = self._normalize_meta_val(self._get_current_field_value(r, field))
                bk_val = self._normalize_meta_val(backup_data.get(field, ""))
                if cur_val != bk_val:
                    diff_fields.append(field)
            if diff_fields:
                diff_lbl = QLabel(f"Отличия в полях: {', '.join(diff_fields)}")
                diff_lbl.setStyleSheet("color:#a00; font-size:9pt;")
                diff_lbl.setWordWrap(True)
                backup_lay.addWidget(diff_lbl)

            # Таблица сравнения
            fields_display = [
                ("Название", "title"), ("Год", "year"),
                ("Задержка", "delay"), ("Пароль архива", "archive_password"),
                ("Форум russdub", "forum_url"), ("Торрент видео", "torrent_url"),
                ("Торрент аудио", "audio_torrent_url"), ("Постер", "poster_url"),
                ("Кинопоиск", "kinopoisk_url"), ("Абонемент год", "sub_year"),
                ("Абонемент месяц", "sub_month"), ("Приоритет", "sort_priority"),
                ("Дата обработки", "processed_date"),
                ("Видео ожидается", "video_pending"), ("NEW", "is_new"),
                ("Префикс", "custom_prefix"), ("Суффикс", "custom_suffix"),
            ]
            # Заголовки столбцов
            grid_header = QHBoxLayout()
            grid_header.setSpacing(4)
            h1 = QLabel("<b>Поле</b>"); h1.setFixedWidth(110); grid_header.addWidget(h1)
            h2 = QLabel("<b>Бэкап</b>"); h2.setStyleSheet("color:#cc0000;"); grid_header.addWidget(h2)
            h3 = QLabel("<b>Текущее</b>"); h3.setStyleSheet("color:#006600;"); grid_header.addWidget(h3)
            backup_lay.addLayout(grid_header)
            # Сетка значений
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, (label, key) in enumerate(fields_display):
                lbl = QLabel(f"<b>{label}:</b>")
                lbl.setTextFormat(Qt.RichText)
                lbl.setFixedWidth(110)
                grid.addWidget(lbl, i, 0)
                bk_val = str(backup_data.get(key, ""))
                cur_val = self._get_current_field_value(r, key)
                bk_val_n = self._normalize_meta_val(bk_val)
                cur_val_n = self._normalize_meta_val(cur_val)
                bk_le = QLineEdit(bk_val); bk_le.setReadOnly(True)
                bk_le.setToolTip(f"Значение из бэкапа: {label}")
                if bk_val_n != cur_val_n:
                    bk_le.setStyleSheet("background-color:#fff0f0; border:1px solid #ff8888;")
                else:
                    bk_le.setStyleSheet("background-color:#f0fff0; border:1px solid #88cc88;")
                grid.addWidget(bk_le, i, 1)
                cur_le = QLineEdit(cur_val); cur_le.setReadOnly(True)
                cur_le.setToolTip(f"Текущее значение: {label}")
                cur_le.setStyleSheet("background-color:#f8f8f8;")
                grid.addWidget(cur_le, i, 2)
            backup_lay.addLayout(grid)

            # Кнопки
            btn_row = QHBoxLayout()
            btn_row.setSpacing(4)
            restore_btn = QPushButton("Восстановить из бэкапа")
            restore_btn.setStyleSheet("QPushButton{background-color:#c8f0c8; font-weight:bold; padding:4px 12px;} QPushButton:hover{background-color:#99ff99;}")
            restore_btn.setToolTip("Восстановить данные из бэкапа (текущие → архив, бэкап → основные)")
            restore_btn.clicked.connect(lambda _, f=fn: self._restore_backup(f))
            btn_row.addWidget(restore_btn)
            del_btn = QPushButton("Удалить бэкап")
            del_btn.setStyleSheet("QPushButton{background-color:#ffcccc; padding:4px 12px;} QPushButton:hover{background-color:#ff9999;}")
            del_btn.setToolTip("Переместить бэкап в архив старых бэкапов (backup/)")
            del_btn.clicked.connect(lambda _, f=fn: self._delete_backup(f))
            btn_row.addWidget(del_btn)
            btn_row.addStretch()
            backup_lay.addLayout(btn_row)
            backup_lay.addStretch()

            right_tabs.addTab(backup_tab_widget, "⚠ Бэкап")
            _backup_tab_idx = right_tabs.count() - 1  # index 2 (txt=0, Данные=1, Бэкап=2)
            right_tabs.tabBar().setTabTextColor(_backup_tab_idx, QColor("#cc0000"))
            # Сразу открыть вкладку бэкапа при конфликте
            right_tabs.setCurrentIndex(_backup_tab_idx)

        tab_root.addWidget(right_tabs)
        tab_root.setSizes(self._tab_splitter_sizes)
        tab_root.splitterMoved.connect(self._on_tab_splitter_moved)

        # --- Запоминание активной правой вкладки ---
        tab_widgets["_right_tab_idx"] = 0
        def _on_right_tab_changed(idx):
            tab_widgets["_right_tab_idx"] = idx
            self.schedule_autosave()
        right_tabs.currentChanged.connect(_on_right_tab_changed)

        # Восстановить сохранённый индекс правой вкладки
        saved_right_idx = r.get("right_tab_idx", 0)

        # Подключить кнопку "⚠ Бэкап" вверху к переключению на вкладку бэкапа
        if backup_top_btn is not None and has_backup_conflict:
            backup_top_btn.clicked.connect(lambda _, rt=right_tabs, bi=_backup_tab_idx: rt.setCurrentIndex(bi))

        # === Показать вкладку (addTab уже в начале метода) ===
        self.tab_widget.setCurrentIndex(_tab_idx)
        # Подсветка ВСЕЙ вкладки красной рамкой при конфликте бэкапа
        if has_backup_conflict:
            self.tab_widget.tabBar().setTabTextColor(_tab_idx, QColor("#cc0000"))
            left_container.setObjectName("backup_warn_left")
            left_container.setStyleSheet("QWidget#backup_warn_left { border: 3px solid #cc0000; border-radius: 4px; }")
            right_tabs.setObjectName("backup_warn_right")
            right_tabs.setStyleSheet("QTabWidget#backup_warn_right { border: 3px solid #cc0000; border-radius: 4px; }")

        # Восстановить активную правую вкладку (бэкап-конфликт имеет приоритет)
        if not has_backup_conflict and 0 <= saved_right_idx < right_tabs.count():
            right_tabs.setCurrentIndex(saved_right_idx)

        # === Двусторонняя синхронизация: текстовые поля ===
        text_fields = [
            ("title_entry", tab_title),
            ("year_entry", tab_year),
            ("password_entry", tab_password),
            ("torrent_entry", tab_torrent),
            ("forum_entry", tab_forum),
            ("output_entry", tab_output),
            ("prefix_entry", tab_prefix),
            ("suffix_entry", tab_suffix),
        ]
        for rk, tw in text_fields:
            if not r.get(rk):
                continue
            def make_tab_to_table(key):
                def on_change(text):
                    rr = self._find_row(fn)
                    if not rr or not rr.get(key): return
                    rr[key].blockSignals(True)
                    rr[key].setText(text)
                    rr[key].blockSignals(False)
                    self.schedule_autosave()
                return on_change
            tw.textChanged.connect(make_tab_to_table(rk))
            def make_table_to_tab(tab_w):
                def on_change(text):
                    tab_w.blockSignals(True)
                    tab_w.setText(text)
                    tab_w.blockSignals(False)
                return on_change
            slot = make_table_to_tab(tw)
            r[rk].textChanged.connect(slot)
            connections.append((r[rk], slot))

        # Пересчёт имени выходного файла при изменении префикса/суффикса на вкладке
        # (blockSignals в tab→table синке блокирует textChanged таблицы, поэтому _recalc_output_name
        #  не вызывается автоматически — вызываем явно)
        tab_prefix.textChanged.connect(lambda text, f=fn: (self._recalc_output_name(f), _update_extra_output_names()))
        tab_suffix.textChanged.connect(lambda text, f=fn: (self._recalc_output_name(f), _update_extra_output_names()))

        # Синхронизация: video_combo (вкладка → таблица → _on_video_selected)
        def _on_tab_video_changed(text):
            rr = self._find_row(fn)
            if not rr: return
            rr["video_combo"].blockSignals(True)
            rr["video_combo"].setCurrentText(text)
            rr["video_combo"].blockSignals(False)
            self._on_video_selected(fn)
        tab_video.currentTextChanged.connect(_on_tab_video_changed)

        # Синхронизация: audio_combo (вкладка → таблица → перекрёстная синхронизация)
        def _on_tab_audio_changed(idx):
            rr = self._find_row(fn)
            if not rr: return
            data = tab_audio.currentData(Qt.UserRole)
            rr["audio_combo"].blockSignals(True)
            if data:
                for i in range(rr["audio_combo"].count()):
                    if rr["audio_combo"].itemData(i, Qt.UserRole) == data:
                        rr["audio_combo"].setCurrentIndex(i)
                        break
            rr["audio_combo"].blockSignals(False)
            self._sync_audio_combos(rr)
            self._check_row_status(rr)
            _update_audio_status()
            self.schedule_autosave()
        tab_audio.currentIndexChanged.connect(_on_tab_audio_changed)

        # Сигнал: при смене аудио файла — обновить кнопку сканирования (только enabled/disabled, БЕЗ авто-скана)
        def _on_audio_changed_update_scan(idx, f=fn):
            rr = self._find_row(f)
            btn = tab_widgets.get("scan_tracks_btn")
            if btn and rr:
                audio_name = tab_audio.currentData(Qt.UserRole) or ""
                audio_ok = bool(audio_name and not audio_name.startswith("⚠") and
                                os.path.isfile(os.path.join(rr.get("folder_path", ""), audio_name)))
                btn.setEnabled(audio_ok)
        tab_audio.currentIndexChanged.connect(_on_audio_changed_update_scan)

        # Синхронизация: starter_combo (вкладка → таблица → перекрёстная синхронизация)
        def _on_tab_starter_changed(idx):
            rr = self._find_row(fn)
            if not rr or not rr.get("starter_combo"): return
            sc = rr["starter_combo"]
            data = tab_starter.currentData(Qt.UserRole)
            sc.blockSignals(True)
            for i in range(sc.count()):
                if sc.itemData(i, Qt.UserRole) == data:
                    sc.setCurrentIndex(i)
                    break
            sc.blockSignals(False)
            self._sync_audio_combos(rr)
            _update_audio_status()
            self.schedule_autosave()
        tab_starter.currentIndexChanged.connect(_on_tab_starter_changed)

        # Синхронизация: ender_combo (вкладка → таблица → перекрёстная синхронизация)
        def _on_tab_ender_changed(idx):
            rr = self._find_row(fn)
            if not rr or not rr.get("ender_combo"): return
            ec = rr["ender_combo"]
            data = tab_ender.currentData(Qt.UserRole)
            ec.blockSignals(True)
            for i in range(ec.count()):
                if ec.itemData(i, Qt.UserRole) == data:
                    ec.setCurrentIndex(i)
                    break
            ec.blockSignals(False)
            self._sync_audio_combos(rr)
            _update_audio_status()
            self.schedule_autosave()
        tab_ender.currentIndexChanged.connect(_on_tab_ender_changed)

        # Синхронизация: prefix_cb
        if r.get("prefix_cb"):
            def on_tab_prefix_cb(checked):
                rr = self._find_row(fn)
                if rr and rr.get("prefix_cb"): rr["prefix_cb"].setChecked(checked)
                tab_prefix.setEnabled(checked)
            tab_prefix_cb.toggled.connect(on_tab_prefix_cb)
            def on_table_prefix_cb(checked):
                tab_prefix_cb.blockSignals(True)
                tab_prefix_cb.setChecked(checked)
                tab_prefix_cb.blockSignals(False)
                tab_prefix.setEnabled(checked)
            r["prefix_cb"].toggled.connect(on_table_prefix_cb)
            connections.append((r["prefix_cb"], on_table_prefix_cb))

        # Синхронизация: suffix_cb
        if r.get("suffix_cb"):
            def on_tab_suffix_cb(checked):
                rr = self._find_row(fn)
                if rr and rr.get("suffix_cb"): rr["suffix_cb"].setChecked(checked)
                tab_suffix.setEnabled(checked)
            tab_suffix_cb.toggled.connect(on_tab_suffix_cb)
            def on_table_suffix_cb(checked):
                tab_suffix_cb.blockSignals(True)
                tab_suffix_cb.setChecked(checked)
                tab_suffix_cb.blockSignals(False)
                tab_suffix.setEnabled(checked)
            r["suffix_cb"].toggled.connect(on_table_suffix_cb)
            connections.append((r["suffix_cb"], on_table_suffix_cb))

        # Синхронизация: poster_url (нет виджета в таблице, только строковое значение)
        def on_poster_url_change(text):
            rr = self._find_row(fn)
            if rr is not None:
                rr["poster_url"] = text
                self.schedule_autosave()
        tab_poster_url.textChanged.connect(on_poster_url_change)

        # Синхронизация: kinopoisk_url (нет виджета в таблице, только строковое значение)
        def on_kinopoisk_url_change(text):
            rr = self._find_row(fn)
            if rr is not None:
                rr["kinopoisk_url"] = text
                self._update_kp_btn_icon(rr)
                self.schedule_autosave()
        tab_kinopoisk.textChanged.connect(on_kinopoisk_url_change)

        # Синхронизация: audio_torrent_url (нет виджета в таблице, только строковое значение)
        def on_audio_torrent_url_change(text):
            rr = self._find_row(fn)
            if rr is not None:
                rr["audio_torrent_url"] = text
                self.schedule_autosave()
        tab_audio_torrent.textChanged.connect(on_audio_torrent_url_change)

        # Синхронизация: sub_year, sub_month (комбобоксы абонемента)
        for sub_key in ("sub_year", "sub_month"):
            tab_combo = tab_widgets.get(sub_key)
            table_combo = r.get(sub_key)
            if tab_combo and table_combo:
                def make_tab_to_table_combo(key):
                    def on_change(text):
                        rr = self._find_row(fn)
                        if not rr or not rr.get(key): return
                        rr[key].blockSignals(True)
                        rr[key].setCurrentText(text)
                        rr[key].blockSignals(False)
                        self.schedule_autosave()
                    return on_change
                tab_combo.currentTextChanged.connect(make_tab_to_table_combo(sub_key))
                def make_table_to_tab_combo(tw_c):
                    def on_change(text):
                        tw_c.blockSignals(True)
                        tw_c.setCurrentText(text)
                        tw_c.blockSignals(False)
                    return on_change
                slot = make_table_to_tab_combo(tab_combo)
                table_combo.currentTextChanged.connect(slot)
                connections.append((table_combo, slot))

        # Начальное обновление доп. выходных файлов
        _update_extra_output_names()
        # Сохранить данные вкладки
        self._open_tabs[fn] = {
            "widget": tab_root,
            "widgets": tab_widgets,
            "connections": connections,
        }
        # Привести кнопку «Сбросить NEW» в корректное состояние (стиль + enabled)
        self._update_tab_reset_new_btn(fn)
        self._update_select_open_btn()
        self.schedule_autosave()

    def _reconnect_open_tabs(self):
        """Переподключить сигналы открытых вкладок после перестроения таблицы."""
        tabs_to_close = []
        for fn, tab_data in self._open_tabs.items():
            # Отключить старые соединения (виджеты могут быть уничтожены)
            for entry, slot in tab_data.get("connections", []):
                try: entry.textChanged.disconnect(slot)
                except (RuntimeError, TypeError, AttributeError): pass
                try: entry.toggled.disconnect(slot)
                except (RuntimeError, TypeError, AttributeError): pass
                try: entry.currentTextChanged.disconnect(slot)
                except (RuntimeError, TypeError, AttributeError): pass
            tab_data["connections"] = []

            r = self._find_row(fn)
            if not r:
                tabs_to_close.append(fn)
                continue

            tw = tab_data["widgets"]
            connections = []

            # Текстовые поля: таблица → вкладка
            for rk in ["title_entry", "year_entry", "password_entry", "torrent_entry",
                        "forum_entry", "output_entry", "prefix_entry", "suffix_entry"]:
                tab_w = tw.get(rk)
                if not tab_w:
                    continue
                def make_table_to_tab(t_w):
                    def on_change(text):
                        t_w.blockSignals(True)
                        t_w.setText(text)
                        t_w.blockSignals(False)
                    return on_change
                slot = make_table_to_tab(tab_w)
                r[rk].textChanged.connect(slot)
                connections.append((r[rk], slot))

            # Отключить старые tab→table соединения (не накапливать при быстрой сортировке)
            for widget, slot in tab_data.get("_tab_connections", []):
                try: widget.currentTextChanged.disconnect(slot)
                except (RuntimeError, TypeError, AttributeError): pass
            tab_connections = []

            # video_combo: вкладка → таблица (при смене на вкладке → _on_video_selected)
            tab_video = tw.get("video_combo")
            if tab_video:
                def make_tab_video_sync(f_name):
                    def on_tab_video(text):
                        rr = self._find_row(f_name)
                        if rr:
                            rr["video_combo"].setCurrentText(text)
                    return on_tab_video
                slot_v = make_tab_video_sync(fn)
                tab_video.currentTextChanged.connect(slot_v)
                tab_connections.append((tab_video, slot_v))

            # audio_combo: вкладка → таблица
            tab_audio = tw.get("audio_combo")
            if tab_audio:
                def make_tab_audio_sync(f_name):
                    def on_tab_audio(text):
                        rr = self._find_row(f_name)
                        if not rr: return
                        rr["audio_combo"].blockSignals(True)
                        rr["audio_combo"].setCurrentText(text)
                        rr["audio_combo"].blockSignals(False)
                        self._check_row_status(rr)
                        self.schedule_autosave()
                    return on_tab_audio
                slot_a = make_tab_audio_sync(fn)
                tab_audio.currentTextChanged.connect(slot_a)
                tab_connections.append((tab_audio, slot_a))
                # При смене аудио файла — пересканировать дорожки
                slot_at = lambda text, f=fn: self._force_rescan_tracks(f)
                tab_audio.currentTextChanged.connect(slot_at)
                tab_connections.append((tab_audio, slot_at))

            tab_data["_tab_connections"] = tab_connections

            # prefix_cb: таблица → вкладка
            tab_prefix_cb = tw.get("prefix_cb")
            tab_prefix = tw.get("prefix_entry")
            if tab_prefix_cb:
                def make_prefix_sync(tcb, tp):
                    def on_table_prefix_cb(checked):
                        tcb.blockSignals(True)
                        tcb.setChecked(checked)
                        tcb.blockSignals(False)
                        if tp:
                            tp.setEnabled(checked)
                    return on_table_prefix_cb
                slot = make_prefix_sync(tab_prefix_cb, tab_prefix)
                r["prefix_cb"].toggled.connect(slot)
                connections.append((r["prefix_cb"], slot))

            # suffix_cb: таблица → вкладка
            tab_suffix_cb = tw.get("suffix_cb")
            tab_suffix = tw.get("suffix_entry")
            if tab_suffix_cb:
                def make_suffix_sync(tcb, ts):
                    def on_table_suffix_cb(checked):
                        tcb.blockSignals(True)
                        tcb.setChecked(checked)
                        tcb.blockSignals(False)
                        if ts:
                            ts.setEnabled(checked)
                    return on_table_suffix_cb
                slot = make_suffix_sync(tab_suffix_cb, tab_suffix)
                r["suffix_cb"].toggled.connect(slot)
                connections.append((r["suffix_cb"], slot))

            # sub_year / sub_month: таблица → вкладка
            for sub_key in ("sub_year", "sub_month"):
                tab_sub = tw.get(sub_key)
                table_sub = r.get(sub_key)
                if tab_sub and table_sub:
                    def make_sub_sync(t_combo):
                        def on_change(text):
                            t_combo.blockSignals(True)
                            t_combo.setCurrentText(text)
                            t_combo.blockSignals(False)
                        return on_change
                    slot = make_sub_sync(tab_sub)
                    table_sub.currentTextChanged.connect(slot)
                    connections.append((table_sub, slot))

            # Обновить текущие значения из новой строки
            for rk in ["title_entry", "year_entry", "password_entry", "torrent_entry",
                        "forum_entry", "output_entry", "prefix_entry", "suffix_entry"]:
                tab_w = tw.get(rk)
                if tab_w:
                    tab_w.blockSignals(True)
                    tab_w.setText(r[rk].text())
                    tab_w.blockSignals(False)
            if tab_prefix_cb:
                tab_prefix_cb.blockSignals(True)
                tab_prefix_cb.setChecked(r["prefix_cb"].isChecked())
                tab_prefix_cb.blockSignals(False)
            if tab_suffix_cb:
                tab_suffix_cb.blockSignals(True)
                tab_suffix_cb.setChecked(r["suffix_cb"].isChecked())
                tab_suffix_cb.blockSignals(False)

            # Обновить poster_url
            poster_url_w = tw.get("poster_url_entry")
            if poster_url_w:
                poster_url_w.blockSignals(True)
                poster_url_w.setText(r.get("poster_url", ""))
                poster_url_w.blockSignals(False)

            # Обновить kinopoisk_url
            kp_w = tw.get("kinopoisk_entry")
            if kp_w:
                kp_w.blockSignals(True)
                kp_w.setText(r.get("kinopoisk_url", ""))
                kp_w.blockSignals(False)

            # Обновить audio_torrent_url
            at_w = tw.get("audio_torrent_entry")
            if at_w:
                at_w.blockSignals(True)
                at_w.setText(r.get("audio_torrent_url", ""))
                at_w.blockSignals(False)

            # Обновить sub_year / sub_month
            for sub_key in ("sub_year", "sub_month"):
                tab_sub = tw.get(sub_key)
                table_sub = r.get(sub_key)
                if tab_sub and table_sub:
                    tab_sub.blockSignals(True)
                    tab_sub.setCurrentText(table_sub.currentText())
                    tab_sub.blockSignals(False)

            # Обновить задержки на вкладке
            rebuild_fn = tw.get("rebuild_delay_rows")
            if rebuild_fn:
                rebuild_fn()
            update_ds = tw.get("update_delay_status")
            if update_ds:
                update_ds()

            # Обновить трек-комбобокс аудио
            self._populate_audio_tracks(fn)

            # Обновить видео комбо и путь
            tab_video = tw.get("video_combo")
            if tab_video:
                tab_video.blockSignals(True)
                tab_video.clear()
                src = r.get("video_combo")
                if src:
                    for i in range(src.count()):
                        tab_video.addItem(src.itemText(i))
                    tab_video.setCurrentText(src.currentText())
                tab_video.blockSignals(False)
            path_lbl = tw.get("video_path_lbl")
            if path_lbl:
                vfp = r.get("video_full_path", "")
                path_lbl.setText(vfp if vfp and r.get("video_manual") else "")

            # Обновить статус
            status_lbl = tw.get("status_lbl")
            if status_lbl:
                st = r["status_lbl"].text()
                status_lbl.setText(st)
                status_lbl.setStyleSheet(self._status_text_style(st))

            # Обновить кнопки действий (enabled/disabled + цвет)
            for bk in ["btn_play", "btn_unrar", "btn_del_archive", "btn_to_res",
                        "btn_del_test", "btn_del_src", "btn_del_res"]:
                tab_btn = tw.get(bk)
                if tab_btn:
                    active = not r[bk].isHidden()
                    tab_btn.setEnabled(active)
                    bg = tab_btn.property("_active_bg") or "#cce5ff"
                    bc = tab_btn.property("_border_color") or "#99b3cc"
                    # Бледный фон, яркий при hover
                    if bg == "#ffcccc": pale = "#ffe8e8"
                    elif bg == "#ccffcc": pale = "#e8ffe8"
                    elif bg == "#ffe4c4": pale = "#fff0e0"
                    else: pale = "#e6f0ff"
                    tab_btn.setStyleSheet(f"QPushButton{{color:black; background-color:{pale}; border:1px solid {bc}; padding:2px 6px;}} QPushButton:hover{{background-color:{bg};}}" if active else "QPushButton{color:#aaa; background-color:#eee; border:1px solid #ccc; padding:2px 6px;}")

            tab_data["connections"] = connections

        # Закрыть вкладки для удалённых записей
        for fn in tabs_to_close:
            idx = self._find_tab_index(fn)
            if idx >= 0:
                self.tab_widget.removeTab(idx)
            del self._open_tabs[fn]

    def _load_poster(self, url, label, status_lbl=None):
        """Загрузить постер по URL в фоновом потоке."""
        if status_lbl:
            self._sig_poster_error.emit(status_lbl, "загрузка...")
        def _do_load():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                pm = QPixmap()
                pm.loadFromData(data)
                if not pm.isNull():
                    self._sig_poster_loaded.emit(label, pm)
                    if status_lbl:
                        self._sig_poster_error.emit(status_lbl, "")
                else:
                    if status_lbl:
                        self._sig_poster_error.emit(status_lbl, "не изображение")
            except urllib.error.URLError as e:
                reason = str(getattr(e, 'reason', e))
                if 'WinError 10061' in reason or 'Connection refused' in reason:
                    err = "сервер отверг соединение"
                elif 'timed out' in reason:
                    err = "таймаут соединения"
                elif 'Name or service not known' in reason or 'getaddrinfo' in reason:
                    err = "сервер не найден"
                else:
                    err = reason[:60]
                if status_lbl:
                    self._sig_poster_error.emit(status_lbl, err)
            except Exception as e:
                if status_lbl:
                    self._sig_poster_error.emit(status_lbl, str(e)[:60])
        threading.Thread(target=_do_load, daemon=True).start()

    def _on_poster_error(self, label, text):
        """Показать/скрыть ошибку загрузки постера."""
        try:
            if text:
                label.setText(text)
                label.setStyleSheet("color:#cc0000; font-size:9px;")
                label.setVisible(True)
            else:
                label.setText("")
                label.setVisible(False)
        except Exception:
            pass

    def _on_poster_loaded(self, label, pixmap):
        """Обработчик сигнала загрузки постера — масштабирует с сохранением пропорций."""
        try:
            if not label or not pixmap or pixmap.isNull():
                return
            if hasattr(label, 'setOriginalPixmap'):
                label.setOriginalPixmap(pixmap)
            else:
                label.setPixmap(pixmap)
        except Exception:
            pass

    def _sync_tab_video(self, fn):
        """Синхронизировать видео комбо и путь на вкладке после выбора файла."""
        if fn not in self._open_tabs:
            return
        r = self._find_row(fn)
        if not r:
            return
        tw = self._open_tabs[fn]["widgets"]
        # Обновить комбобокс видео
        tab_video = tw.get("video_combo")
        if tab_video:
            tab_video.blockSignals(True)
            tab_video.clear()
            src = r.get("video_combo")
            if src:
                for i in range(src.count()):
                    tab_video.addItem(src.itemText(i))
                tab_video.setCurrentText(src.currentText())
                # Скопировать подсветку и шрифт занятых элементов
                from PySide6.QtGui import QStandardItemModel
                src_model = src.model()
                dst_model = tab_video.model()
                if isinstance(src_model, QStandardItemModel) and isinstance(dst_model, QStandardItemModel):
                    for i in range(min(src_model.rowCount(), dst_model.rowCount())):
                        s_item = src_model.item(i)
                        d_item = dst_model.item(i)
                        if s_item and d_item and "  ← " in (s_item.text() or ""):
                            d_item.setBackground(s_item.background())
                            d_item.setToolTip(s_item.toolTip())
            tab_video.blockSignals(False)
        # Синхронизировать имя выходного файла
        tab_out = tw.get("output_entry")
        if tab_out:
            new_out = r["output_entry"].text()
            if tab_out.text() != new_out:
                tab_out.setText(new_out)
                tab_out.setCursorPosition(0)
        # Обновить полный путь
        path_lbl = tw.get("video_path_lbl")
        if path_lbl:
            vfp = r.get("video_full_path", "")
            if vfp and r.get("video_manual"):
                path_lbl.setText(vfp)
            else:
                path_lbl.setText("")
        # Синхронизировать продолжительность видео
        tab_dur = tw.get("video_dur_lbl")
        if tab_dur:
            src_dur = r.get("video_dur_lbl")
            tab_dur.setText(src_dur.text() if src_dur and hasattr(src_dur, "text") else "")
        # Синхронизировать кнопку "видео в процессе"
        tab_pending = tw.get("video_pending_btn")
        if tab_pending:
            _has_video = bool(r.get("video_full_path"))
            tab_pending.setVisible(not _has_video)
            if r.get("video_pending"):
                tab_pending.setText("⌛")
                tab_pending.setStyleSheet("color:#8e44ad; font-weight:bold;")
            else:
                tab_pending.setText("⏳")
                tab_pending.setStyleSheet("")
        # Обновить кнопку "Удалить источник 1" (размер файла)
        _ds1 = tw.get("del_src_1")
        if _ds1:
            _vfp = r.get("video_full_path", "")
            _exists = bool(_vfp and os.path.isfile(_vfp))
            _ds1.setEnabled(_exists)
            _sz = _format_file_size_gb(_vfp) if _exists else ""
            _ds1.setText(f"Источник {_sz}" if _sz else "Источник")
        # Обновить доп. видео и выходные файлы
        _reb_ev = tw.get("rebuild_extra_videos")
        if _reb_ev: _reb_ev()
        _upd_out = tw.get("update_extra_output_names")
        if _upd_out: _upd_out()
        _upd_preview = tw.get("update_track_preview")
        if _upd_preview: _upd_preview()

    def _sync_tab_txt(self, fn, txt_name):
        """Синхронизировать выбранный txt файл с открытой вкладкой."""
        if fn not in self._open_tabs:
            return
        tw = self._open_tabs[fn]["widgets"]
        combo = tw.get("txt_combo")
        if combo:
            combo.blockSignals(True)
            combo.setCurrentText(txt_name)
            combo.blockSignals(False)
        # Перезагрузить содержимое
        r = self._find_row(fn)
        if not r:
            return
        new_path = os.path.join(r.get("folder_path", ""), txt_name)
        txt_edit = tw.get("txt_edit")
        if txt_edit:
            self._load_txt_content(txt_edit, new_path)
            tw["_txt_path"] = new_path
            tw["_txt_last"] = txt_edit.toPlainText()
        # Обновить заголовок
        # Ищем txt_group — это parent txt_edit
        try:
            parent = txt_edit.parentWidget()
            if isinstance(parent, QGroupBox):
                parent.setTitle(f"txt: {txt_name}")
        except Exception:
            pass

    def _load_txt_content(self, text_edit, path):
        """Загрузить содержимое txt файла в QTextEdit."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                text_edit.setPlainText(f.read())
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="cp1251") as f:
                    text_edit.setPlainText(f.read())
            except Exception:
                text_edit.clear()
        except Exception:
            text_edit.clear()

    def _find_tab_fn_by_index(self, index):
        """Найти folder_name по индексу вкладки (через tabText)."""
        if index <= 0:
            return None
        tab_text = self.tab_widget.tabText(index)
        if tab_text in self._open_tabs:
            return tab_text
        return None

    def _close_record_tab(self, index):
        """Закрыть вкладку записи."""
        if index == 0:
            return  # Таблицу не закрываем
        fn = self._find_tab_fn_by_index(index)
        if fn and fn in self._open_tabs:
            try:
                self._save_tab_txt(fn)
            except Exception:
                pass
            try:
                for entry, slot in self._open_tabs[fn].get("connections", []):
                    try: entry.textChanged.disconnect(slot)
                    except (RuntimeError, TypeError): pass
                    try: entry.toggled.disconnect(slot)
                    except (RuntimeError, TypeError): pass
            except Exception:
                pass
            # del ВСЕГДА, вне try
            del self._open_tabs[fn]
        self.tab_widget.removeTab(index)
        self._update_txt_panel_visibility()
        self._update_select_open_btn()
        self.schedule_autosave()

    def _close_all_record_tabs(self):
        """Закрыть все вкладки с фильмами, оставив только Таблицу."""
        while self.tab_widget.count() > 1:
            self._close_record_tab(self.tab_widget.count() - 1)
        self.tab_widget.setCurrentIndex(0)

    def _select_open_tabs(self):
        """Toggle: отметить/снять чекбоксы всех строк, у которых открыта вкладка."""
        # Если все открытые уже отмечены — снять, иначе — отметить
        all_checked = all(
            self._find_row(fn) and self._find_row(fn)["select_cb"].isChecked()
            for fn in self._open_tabs if self._find_row(fn))
        for fn in self._open_tabs:
            r = self._find_row(fn)
            if r:
                r["select_cb"].setChecked(not all_checked)
        self._update_batch_buttons()

    def _update_select_open_btn(self):
        """Показать кнопку «Выбрать открытые» только на таблице и если есть открытые вкладки."""
        if not hasattr(self, '_select_open_btn'):
            return
        on_table = self.tab_widget.currentIndex() == 0
        has_tabs = bool(self._open_tabs)
        self._select_open_btn.setVisible(on_table and has_tabs)
        if on_table and has_tabs:
            self._reposition_select_open_btn()

    def _reposition_select_open_btn(self):
        """Позиционировать кнопку прямо после последней вкладки."""
        if not hasattr(self, '_select_open_btn') or not self._select_open_btn.isVisible():
            return
        bar = self.tab_widget.tabBar()
        last_idx = bar.count() - 1
        if last_idx < 0:
            return
        rect = bar.tabRect(last_idx)
        # Координаты tabBar → tab_widget (кнопка — child tab_widget)
        bar_pos = bar.mapTo(self.tab_widget, rect.topRight())
        x = bar_pos.x() + 4
        y = bar_pos.y() + (rect.height() - self._select_open_btn.height()) // 2
        self._select_open_btn.move(x, y)
        self._select_open_btn.raise_()

    def _reopen_record_tab(self, fn):
        """Закрыть и переоткрыть вкладку записи для обновления UI."""
        idx = self._find_tab_index(fn)
        if idx >= 0:
            self._close_record_tab(idx)
        self._open_record_tab(fn)

    def _save_tab_txt(self, fn):
        """Сохранить содержимое txt редактора вкладки на диск."""
        tab_data = self._open_tabs.get(fn)
        if not tab_data:
            return
        tw = tab_data["widgets"]
        txt_path = tw.get("_txt_path", "")
        if not txt_path:
            return
        txt_edit = tw.get("txt_edit")
        if not txt_edit:
            return
        content = txt_edit.toPlainText()
        if content == tw.get("_txt_last", ""):
            return
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(content)
            tw["_txt_last"] = content
        except Exception:
            pass

    # ──────────────────────────────────
    #  Действия с файлами
    # ──────────────────────────────────
    def _action_to_result(self, fn):
        r = self._find_row(fn)
        if not r: return
        tp, op = self.test_path_edit.text(), self.output_path_edit.text()
        name = r["output_entry"].text()
        if not tp or not op or not name: return
        src = os.path.join(tp, name)
        dst = os.path.join(op, name)
        if not os.path.exists(src): return
        if QMessageBox.question(self, "Переместить", f"В результат?\n{src}\n→ {dst}") != QMessageBox.Yes: return
        if os.path.exists(dst):
            if QMessageBox.question(self, "Заменить", f"Файл существует. Заменить?") != QMessageBox.Yes: return
            os.remove(dst)
        try:
            shutil.move(src, dst)
            self.log(f"[OK] В результат: {name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()

    def _action_del_test(self, fn):
        r = self._find_row(fn)
        if not r: return
        tp = self.test_path_edit.text(); name = r["output_entry"].text()
        if not tp or not name: return
        path = os.path.join(tp, name)
        if not os.path.exists(path): return
        if QMessageBox.question(self, "Удалить тест", f"Удалить?\n{path}") != QMessageBox.Yes: return
        try: os.remove(path); self.log(f"[DEL] Тест: {name}")
        except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()

    def _action_del_source(self, fn):
        r = self._find_row(fn)
        if not r: return
        path = r.get("video_full_path", "")
        if not path or not os.path.exists(path): return
        vn = r["video_combo"].currentText()
        # Проверить разделяемое видео
        shared_rows = [rr for rr in self.rows if rr is not r and rr.get("video_full_path") == path]
        if shared_rows:
            shared_names = ", ".join(rr["folder_name"] for rr in shared_rows)
            _msg = (f"БЕЗВОЗВРАТНО?\n{path}\n\n"
                    f"Этот файл также используется записями:\n{shared_names}\n"
                    f"Они тоже потеряют видео источник.")
        else:
            _msg = f"БЕЗВОЗВРАТНО?\n{path}"
        if QMessageBox.question(self, "Удалить видео источник", _msg) != QMessageBox.Yes: return
        try: os.remove(path); self.log(f"[DEL] Источник: {vn}")
        except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return
        if vn in self.available_videos: self.available_videos.remove(vn)
        if vn in self.video_files: self.video_files.remove(vn)
        r["video_combo"].blockSignals(True); r["video_combo"].clear(); r["video_combo"].blockSignals(False)
        r["output_entry"].setText(""); r["video_full_path"] = ""; r["prev_video"] = ""
        r["video_duration"] = ""; r["video_dur_lbl"].setText("")
        r["video_pending_btn"].setVisible(True)
        # Каскадное удаление — очистить все записи разделяющие этот файл
        for rr in shared_rows:
            rr["video_combo"].blockSignals(True); rr["video_combo"].clear(); rr["video_combo"].blockSignals(False)
            rr["output_entry"].setText(""); rr["video_full_path"] = ""; rr["prev_video"] = ""
            rr["video_duration"] = ""; rr["video_dur_lbl"].setText("")
            rr["video_pending_btn"].setVisible(True)
            self._check_row_status(rr)
            self.log(f"[DEL] Каскадно очищен источник: {rr['folder_name']}")
        self._check_row_status(r); self._update_all_video_combos(); self.schedule_autosave()
        self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")

    def _action_del_result(self, fn):
        r = self._find_row(fn)
        if not r: return
        op = self.output_path_edit.text(); name = r["output_entry"].text()
        if not op or not name: return
        path = os.path.join(op, name)
        if not os.path.exists(path): return
        if QMessageBox.question(self, "Удалить результат", f"БЕЗВОЗВРАТНО?\n{path}") != QMessageBox.Yes: return
        try: os.remove(path); self.log(f"[DEL] Результат: {name}")
        except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()

    def _action_to_result_single(self, fn, output_name):
        """Переместить конкретный выходной файл из теста в результат."""
        r = self._find_row(fn)
        if not r: return
        tp, op = self.test_path_edit.text(), self.output_path_edit.text()
        if not tp or not op or not output_name: return
        src = os.path.join(tp, output_name)
        dst = os.path.join(op, output_name)
        if not os.path.exists(src): return
        if QMessageBox.question(self, "Переместить", f"В результат?\n{src}\n→ {dst}") != QMessageBox.Yes: return
        if os.path.exists(dst):
            if QMessageBox.question(self, "Заменить", f"Файл существует. Заменить?") != QMessageBox.Yes: return
            os.remove(dst)
        try:
            shutil.move(src, dst)
            self.log(f"[OK] В результат: {output_name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()
        tw = self._open_tabs.get(fn, {}).get("widgets", {})
        upd = tw.get("update_extra_output_names")
        if upd: upd()

    def _action_del_result_single(self, fn, output_name):
        """Удалить конкретный выходной файл из результата."""
        r = self._find_row(fn)
        if not r: return
        op = self.output_path_edit.text()
        if not op or not output_name: return
        path = os.path.join(op, output_name)
        if not os.path.exists(path): return
        if QMessageBox.question(self, "Удалить результат", f"БЕЗВОЗВРАТНО?\n{path}") != QMessageBox.Yes: return
        try:
            os.remove(path)
            self.log(f"[DEL] Результат: {output_name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()
        tw = self._open_tabs.get(fn, {}).get("widgets", {})
        upd = tw.get("update_extra_output_names")
        if upd: upd()

    def _action_del_test_single(self, fn, output_name):
        """Удалить конкретный тестовый файл."""
        r = self._find_row(fn)
        if not r: return
        tp = self.test_path_edit.text()
        if not tp or not output_name: return
        path = os.path.join(tp, output_name)
        if not os.path.exists(path): return
        if QMessageBox.question(self, "Удалить тест", f"Удалить?\n{path}") != QMessageBox.Yes: return
        try:
            os.remove(path)
            self.log(f"[DEL] Тест: {output_name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self._update_counts(); self.schedule_autosave()
        tw = self._open_tabs.get(fn, {}).get("widgets", {})
        upd = tw.get("update_extra_output_names")
        if upd: upd()

    def _action_del_source_single(self, fn, video_path, ev_idx=None):
        """Удалить конкретный видео-источник (основной или дополнительный)."""
        r = self._find_row(fn)
        if not r: return
        if not video_path or not os.path.exists(video_path): return
        # Проверить разделяемое видео (только для основного)
        shared_rows = []
        if ev_idx is None:
            shared_rows = [rr for rr in self.rows if rr is not r and rr.get("video_full_path") == video_path]
        if shared_rows:
            shared_names = ", ".join(rr["folder_name"] for rr in shared_rows)
            _msg = (f"БЕЗВОЗВРАТНО?\n{video_path}\n\n"
                    f"Этот файл также используется записями:\n{shared_names}\n"
                    f"Они тоже потеряют видео источник.")
        else:
            _msg = f"БЕЗВОЗВРАТНО?\n{video_path}"
        if QMessageBox.question(self, "Удалить источник", _msg) != QMessageBox.Yes:
            return
        try:
            os.remove(video_path)
            self.log(f"[DEL] Источник: {os.path.basename(video_path)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e)); return
        if ev_idx is not None:
            # Дополнительное видео — очистить запись
            evs = r.get("extra_videos", [])
            if ev_idx < len(evs):
                evs[ev_idx]["video"] = ""
                evs[ev_idx]["video_full_path"] = ""
                evs[ev_idx]["video_manual"] = False
        else:
            # Основное видео
            vn = r["video_combo"].currentText()
            if vn in self.available_videos: self.available_videos.remove(vn)
            if vn in self.video_files: self.video_files.remove(vn)
            r["video_combo"].blockSignals(True); r["video_combo"].clear(); r["video_combo"].blockSignals(False)
            r["output_entry"].setText(""); r["video_full_path"] = ""; r["prev_video"] = ""
            r["video_duration"] = ""; r["video_dur_lbl"].setText("")
            r["video_pending_btn"].setVisible(True)
            # Каскадное удаление — очистить все записи разделяющие этот файл
            for rr in shared_rows:
                rr["video_combo"].blockSignals(True); rr["video_combo"].clear(); rr["video_combo"].blockSignals(False)
                rr["output_entry"].setText(""); rr["video_full_path"] = ""; rr["prev_video"] = ""
                rr["video_duration"] = ""; rr["video_dur_lbl"].setText("")
                rr["video_pending_btn"].setVisible(True)
                self._check_row_status(rr)
                self.log(f"[DEL] Каскадно очищен источник: {rr['folder_name']}")
            self.video_count_lbl.setText(f"Видео файлов: {len(self.video_files)}")
        self._check_row_status(r); self._update_all_video_combos(); self.schedule_autosave()
        # Обновить вкладку если открыта
        if fn in self._open_tabs:
            tw = self._open_tabs[fn].get("widgets", {})
            reb = tw.get("rebuild_extra_videos")
            if reb: reb()
            upd = tw.get("update_extra_output_names")
            if upd: upd()

    def _action_rename(self, fn):
        r = self._find_row(fn)
        if not r: return
        new_name = r["output_entry"].text()
        if not new_name: return
        if not new_name.lower().endswith('.mkv'): new_name += '.mkv'
        tp, op = self.test_path_edit.text(), self.output_path_edit.text()
        # Сначала ищем файл по имени на диске (output_on_disk), затем по тексту поля
        old_name = r.get("output_on_disk", "") or new_name
        cur_path = loc = ""
        for name_to_find in (old_name, new_name):
            if cur_path: break
            if tp and os.path.isfile(os.path.join(tp, name_to_find)):
                cur_path = os.path.join(tp, name_to_find); loc = "тест"
            elif op and os.path.isfile(os.path.join(op, name_to_find)):
                cur_path = os.path.join(op, name_to_find); loc = "результат"
        if not cur_path:
            QMessageBox.information(self, "Инфо", "Файл не найден ни в тесте, ни в результате"); return
        actual_old_name = os.path.basename(cur_path)
        if actual_old_name == new_name:
            # Имена совпадают — открыть диалог для ввода нового имени
            new_name, ok = QInputDialog.getText(self, "Переименовать", f"Файл в «{loc}»:", text=actual_old_name)
            if not ok or not new_name or new_name == actual_old_name: return
            if not new_name.lower().endswith('.mkv'): new_name += '.mkv'
        new_path = os.path.join(os.path.dirname(cur_path), new_name)
        if os.path.exists(new_path):
            QMessageBox.critical(self, "Ошибка", f"Файл «{new_name}» уже существует"); return
        try:
            os.rename(cur_path, new_path)
            r["output_entry"].setText(new_name)
            r["output_on_disk"] = new_name
            self.log(f"[REN] {actual_old_name} → {new_name}")
        except Exception as e:
            # Ошибка — вернуть старое имя в поле
            r["output_entry"].setText(actual_old_name)
            QMessageBox.critical(self, "Ошибка", str(e)); return
        self._check_row_status(r); self.schedule_autosave()

    # ──────────────────────────────────
    #  Папка / Info / TXT
    # ──────────────────────────────────
    def _create_audio_folder(self):
        ap = self.audio_path_edit.text()
        if not ap or not os.path.isdir(ap):
            QMessageBox.critical(self, "Ошибка", "Укажите папку аудио")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Создать папку для аудио дорожки")
        dlg.setMinimumWidth(620)
        layout = QVBoxLayout(dlg)

        # === Блок russdub ===
        russdub_group = QGroupBox("russdub")
        russdub_group.setStyleSheet("QGroupBox { background-color: #e8f0fe; border: 1px solid #b0c4de; border-radius: 4px; margin-top: 8px; padding-top: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        russdub_layout = QVBoxLayout(russdub_group)
        russdub_layout.setSpacing(4)

        # --- Название папки (обязательное) ---
        name_lbl = QLabel("Название папки: <span style='color:red;'>*</span>")
        name_lbl.setToolTip("Обязательное поле — имя создаваемой подпапки в папке аудио")
        russdub_layout.addWidget(name_lbl)
        name_error_lbl = QLabel("")
        name_error_lbl.setStyleSheet("color: red; font-weight: bold;")
        name_error_lbl.setVisible(False)
        name_error_lbl.setWordWrap(True)
        name_error_lbl.setToolTip("Символы, запрещённые в именах файлов/папок Windows")
        russdub_layout.addWidget(name_error_lbl)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Введите название (обязательно)...")
        name_edit.setToolTip("Обязательное поле — имя создаваемой подпапки в папке аудио")
        _FORBIDDEN = '<>:"/\\|?*'

        def _validate_name(text):
            found = [ch for ch in _FORBIDDEN if ch in text]
            if found:
                chars_str = " ".join(f"«{ch}»" for ch in found)
                name_error_lbl.setText(
                    f"<b>Название папки</b> содержит недопустимые символы: {chars_str}")
                name_error_lbl.setVisible(True)
                name_edit.setStyleSheet("border: 2px solid red;")
            else:
                name_error_lbl.setVisible(False)
                name_edit.setStyleSheet("")
            # Обновить заголовок окна
            t = text.strip()
            if t:
                dlg.setWindowTitle(f"Создать папку: {t}")
            else:
                dlg.setWindowTitle("Создать папку для аудио дорожки")

        name_edit.textChanged.connect(_validate_name)
        russdub_layout.addWidget(name_edit)

        # --- Ошибка (скрыта по умолчанию) ---
        error_lbl = QLabel("")
        error_lbl.setStyleSheet("color: red; font-weight: bold;")
        error_lbl.setVisible(False)
        error_lbl.setToolTip("Ошибка валидации")
        russdub_layout.addWidget(error_lbl)

        # --- Заметки ---
        notes_lbl = QLabel("Заметки:")
        notes_lbl.setToolTip("Содержимое текстового файла, который будет создан в папке")
        russdub_layout.addWidget(notes_lbl)
        notes_hint = QLabel("TXT файл создаётся внутри папки с именем папки")
        notes_hint.setStyleSheet("color: #888; font-size: 10px;")
        notes_hint.setToolTip("Файл <имя_папки>.txt будет создан автоматически внутри новой папки")
        russdub_layout.addWidget(notes_hint)
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Вставьте текст...")
        text_edit.setToolTip("Содержимое .txt файла — создаётся внутри папки с именем папки")
        text_edit.setMinimumHeight(200)
        russdub_layout.addWidget(text_edit)

        class _PasteFilter(QObject):
            def eventFilter(self, obj, event):
                if (event.type() == QEvent.KeyPress and
                        event.key() == Qt.Key_V and
                        event.modifiers() & Qt.ControlModifier):
                    cb = QApplication.clipboard()
                    md = cb.mimeData()
                    if md and md.hasText():
                        obj.textCursor().insertText(md.text())
                        return True
                return False
        _pf = _PasteFilter(text_edit)
        text_edit.installEventFilter(_pf)

        # --- Абонемент (с чекбоксом вкл/выкл) ---
        sub_layout = QHBoxLayout()
        sub_cb = QCheckBox("Абонемент:")
        sub_cb.setChecked(True)
        sub_cb.setToolTip("Записать абонемент при создании папки\nСнимите галочку чтобы не записывать абонемент")
        sub_layout.addWidget(sub_cb)
        sub_year_dlg = QComboBox()
        sub_year_dlg.addItem("—"); sub_year_dlg.addItems(_SUB_YEARS)
        sub_year_dlg.setMaximumWidth(80)
        sub_year_dlg.setToolTip("Год абонемента")
        _now = datetime.now()
        _cur_year = str(_now.year)
        if _cur_year in _SUB_YEARS:
            sub_year_dlg.setCurrentText(_cur_year)
        sub_layout.addWidget(sub_year_dlg)
        sub_month_dlg = QComboBox()
        sub_month_dlg.addItem("—"); sub_month_dlg.addItems(_MONTHS_RU)
        sub_month_dlg.setMaximumWidth(120)
        sub_month_dlg.setToolTip("Месяц абонемента")
        sub_month_dlg.setCurrentText(_MONTHS_RU[_now.month - 1])
        sub_layout.addWidget(sub_month_dlg)
        def _on_sub_cb(checked):
            sub_year_dlg.setEnabled(checked)
            sub_month_dlg.setEnabled(checked)
        sub_cb.toggled.connect(_on_sub_cb)
        sub_layout.addStretch()
        russdub_layout.addLayout(sub_layout)

        # === Блок "Торрент аудио дорожки" ===
        ta_group = QGroupBox("Торрент аудио дорожки:")
        ta_group.setStyleSheet(
            "QGroupBox { border: 1px solid #999; border-radius: 4px; margin-top: 6px; padding-top: 14px; font-weight: bold; }"
            " QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        ta_group_layout = QVBoxLayout(ta_group)
        ta_group_layout.setSpacing(4)
        # --- Ссылка ---
        ta_link_row = QHBoxLayout()
        ta_link_row.addWidget(QLabel("Ссылка:"))
        torrent_audio_edit = QLineEdit()
        torrent_audio_edit.setPlaceholderText("https://...")
        torrent_audio_edit.setToolTip("Ссылка на торрент с аудио дорожкой для скачивания")
        setup_url_validation(torrent_audio_edit)
        ta_link_row.addWidget(torrent_audio_edit, 1)
        ta_group_layout.addLayout(ta_link_row)
        # --- Файл ---
        ta_file_row = QHBoxLayout()
        ta_file_row.addWidget(QLabel("Файл:"))
        _qbt_icon_dlg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "qbittorrent_icon.png")
        torrent_btn = QPushButton("Выбрать торрент файл")
        torrent_btn.setToolTip("Выбрать .torrent файл аудио дорожки — он будет ПЕРЕМЕЩЁН в новую папку")
        if os.path.isfile(_qbt_icon_dlg):
            torrent_btn.setIcon(QIcon(_qbt_icon_dlg))
        ta_file_row.addWidget(torrent_btn)
        torrent_label = QLabel("")
        torrent_label.setVisible(False)
        ta_file_row.addWidget(torrent_label)
        ta_file_row.addStretch()
        torrent_path = {"value": ""}

        def _pick_torrent():
            f, _ = QFileDialog.getOpenFileName(dlg, "Выбрать .torrent файл", "", "Torrent (*.torrent);;Все файлы (*)")
            if f:
                torrent_path["value"] = f
                torrent_btn.setText(os.path.basename(f))
                torrent_btn.setStyleSheet("color:green;")
                torrent_btn.setToolTip(f"Торрент файл аудио дорожки:\n{f}")
                torrent_label.setText("Выбрать другой")
                torrent_label.setStyleSheet("color: #0078d4; text-decoration: underline;")
                torrent_label.setCursor(Qt.PointingHandCursor)
                torrent_label.setToolTip("Нажмите чтобы выбрать другой .torrent файл")
                torrent_label.setVisible(True)
                _needed = torrent_btn.fontMetrics().horizontalAdvance(torrent_btn.text()) + 60
                torrent_btn.setMinimumWidth(_needed)

        def _torrent_btn_clicked():
            if torrent_path["value"] and os.path.isfile(torrent_path["value"]):
                os.startfile(torrent_path["value"])
            else:
                _pick_torrent()

        torrent_btn.clicked.connect(_torrent_btn_clicked)
        torrent_label.mousePressEvent = lambda e: _pick_torrent()
        ta_group_layout.addLayout(ta_file_row)
        russdub_layout.addWidget(ta_group)

        # --- Архив ---
        archive_row = QHBoxLayout()
        _snd_lbl = QLabel("Архив:")
        _snd_lbl.setToolTip("Архив или файл без расширения с аудио дорожкой для фильма\nБудет перемещён в создаваемую папку")
        archive_row.addWidget(_snd_lbl)
        archive_move_btn = QPushButton("Переместить архив с аудио дорожкой")
        archive_move_btn.setIcon(_make_two_notes_icon())
        archive_move_btn.setToolTip("Выбрать архив с аудио дорожкой и переместить в новую папку\nПоддерживаются: .rar, .7z, .zip и файлы без расширения")
        archive_row.addWidget(archive_move_btn)
        archive_dlg_label = QLabel("")
        archive_dlg_label.setVisible(False)
        archive_row.addWidget(archive_dlg_label)
        archive_row.addSpacing(16)
        archive_row.addWidget(QLabel("Пароль:"))
        password_edit = QLineEdit()
        password_edit.setPlaceholderText("пароль...")
        password_edit.setMaximumWidth(150)
        password_edit.setToolTip("Пароль от архива с аудио дорожкой (для расшифровки RAR архива)")
        archive_row.addWidget(password_edit)
        archive_row.addStretch()
        archive_path = {"value": ""}

        def _pick_archive():
            _start = self.download_path_edit.text() if hasattr(self, 'download_path_edit') else ""
            f = _open_archive_dialog(dlg, "Выбрать архив с аудио дорожкой", _start)
            if f:
                archive_path["value"] = f
                archive_move_btn.setText(os.path.basename(f))
                archive_move_btn.setStyleSheet("color:green;")
                archive_move_btn.setToolTip(f"Архив для перемещения в новую папку:\n{f}")
                archive_dlg_label.setText("Выбрать другой")
                archive_dlg_label.setStyleSheet("color: #0078d4; text-decoration: underline;")
                archive_dlg_label.setCursor(Qt.PointingHandCursor)
                archive_dlg_label.setToolTip("Нажмите чтобы выбрать другой архив")
                archive_dlg_label.setVisible(True)
                _needed = archive_move_btn.fontMetrics().horizontalAdvance(archive_move_btn.text()) + 60
                archive_move_btn.setMinimumWidth(_needed)
                _row_need = _needed + _snd_lbl.sizeHint().width() + archive_dlg_label.sizeHint().width() + 80
                if _row_need > dlg.width():
                    dlg.setMinimumWidth(_row_need)
                    dlg.resize(_row_need, dlg.height())

        archive_move_btn.clicked.connect(_pick_archive)
        archive_dlg_label.mousePressEvent = lambda e: _pick_archive()
        russdub_layout.addLayout(archive_row)

        # --- Ссылка на форум ---
        forum_layout = QHBoxLayout()
        forum_layout.addWidget(QLabel("Форум russdub:"))
        forum_edit = QLineEdit()
        forum_edit.setPlaceholderText("https://russdub.ru:22223/viewtopic.php?...")
        forum_edit.setToolTip("Ссылка на тему про этот фильм на форуме russdub")
        setup_url_validation(forum_edit)
        forum_layout.addWidget(forum_edit, 1)
        _forum_go_btn = QPushButton("→")
        _fbh = forum_edit.sizeHint().height()
        _forum_go_btn.setFixedSize(_fbh, _fbh)
        _forum_go_btn.setToolTip("Открыть ссылку на форум russdub в браузере")
        _forum_go_btn.clicked.connect(lambda: (
            __import__('webbrowser').open(forum_edit.text().strip())
            if forum_edit.text().strip().startswith("http") else None
        ))
        forum_layout.addWidget(_forum_go_btn)
        # Чекбокс "короткий линк"
        short_link_cb = QCheckBox("Короткий линк")
        short_link_cb.setChecked(True)
        short_link_cb.setToolTip("Автоматически сокращать ссылку russdub (убирать &p=...&hilit=...#p...)")
        forum_layout.addWidget(short_link_cb)
        def _on_forum_text_changed(txt):
            if short_link_cb.isChecked() and txt:
                shortened = shorten_russdub_url(txt)
                if shortened != txt:
                    forum_edit.blockSignals(True)
                    forum_edit.setText(shortened)
                    forum_edit.blockSignals(False)
        forum_edit.textChanged.connect(_on_forum_text_changed)
        # Кнопка поиска на RussDub
        forum_search_btn = QPushButton(); forum_search_btn.setFixedSize(24, 24)
        _rd_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "russdub_icon.png")
        if os.path.isfile(_rd_icon):
            forum_search_btn.setIcon(_make_kp_search_icon(_rd_icon, 48, mag_scale=0.42))
            forum_search_btn.setIconSize(QSize(20, 20))
        forum_search_btn.setToolTip("Поиск на форуме RussDub\nЗапрос: «название + год + завершен» → russdub.ru/search.php")
        def _search_russdub_dlg():
            t = title_edit.text().strip() or name_edit.text().strip()
            if t:
                y = year_edit.text().strip()
                q = f"{t} {y} завершен" if y else f"{t} завершен"
                webbrowser.open(f"https://russdub.ru:22223/search.php?keywords={urllib.parse.quote(q)}")
            else:
                QMessageBox.warning(dlg, "Поиск на RussDub",
                                    "Не удалось выполнить поиск.\n\n"
                                    "Поле «Название» пустое в блоке «Данные о фильме».\n\n"
                                    "Заполните название и нажмите поиск ещё раз.")
        forum_search_btn.clicked.connect(_search_russdub_dlg)
        forum_layout.addWidget(forum_search_btn)
        russdub_layout.addLayout(forum_layout)
        layout.addWidget(russdub_group)

        # === Блок "Данные о фильме" ===
        film_group = QGroupBox("Данные о фильме")
        film_group.setStyleSheet("QGroupBox { background-color: #f0e6f6; border: 1px solid #c4a8d8; border-radius: 4px; margin-top: 8px; padding-top: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        film_layout = QVBoxLayout(film_group)
        film_layout.setSpacing(4)

        # --- Название и год фильма ---
        title_year_layout = QHBoxLayout()
        title_year_layout.addWidget(QLabel("Название:"))
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("название фильма...")
        title_edit.setToolTip("Название фильма — записывается в колонку «Название»")
        title_year_layout.addWidget(title_edit, 1)
        title_year_layout.addWidget(QLabel("Год:"))
        year_edit = QLineEdit()
        year_edit.setPlaceholderText("год...")
        year_edit.setToolTip("Год выпуска фильма — записывается в колонку «Год»")
        year_edit.setMaximumWidth(70)
        setup_year_validation(year_edit)
        title_year_layout.addWidget(year_edit)
        film_layout.addLayout(title_year_layout)

        # --- Постер URL ---
        poster_layout = QHBoxLayout()
        poster_layout.addWidget(QLabel("Постер:"))
        poster_url_edit = QLineEdit()
        poster_url_edit.setPlaceholderText("https://...poster.jpg")
        poster_url_edit.setToolTip("Ссылка на изображение постера фильма")
        setup_url_validation(poster_url_edit)
        poster_layout.addWidget(poster_url_edit, 1)
        film_layout.addLayout(poster_layout)

        # --- Ссылка на кинопоиск ---
        kp_layout = QHBoxLayout()
        kp_layout.addWidget(QLabel("Кинопоиск:"))
        kinopoisk_edit = QLineEdit()
        kinopoisk_edit.setPlaceholderText("https://www.kinopoisk.ru/film/...")
        kinopoisk_edit.setToolTip("Ссылка на страницу фильма на Кинопоиске")
        setup_url_validation(kinopoisk_edit)
        kp_layout.addWidget(kinopoisk_edit, 1)
        # Кнопка поиска на Кинопоиске
        kp_search_btn = QPushButton(); kp_search_btn.setFixedSize(24, 24)
        _kp_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "kinopoisk_icon.png")
        if os.path.isfile(_kp_icon):
            kp_search_btn.setIcon(_make_kp_search_icon(_kp_icon, 48, mag_scale=0.42))
            kp_search_btn.setIconSize(QSize(20, 20))
        kp_search_btn.setToolTip("Поиск на Кинопоиске по названию фильма\nЕсли название не задано — поиск по имени папки")
        def _search_kp_dlg():
            t = title_edit.text().strip() or name_edit.text().strip()
            y = year_edit.text().strip()
            if t:
                q = f"{t} ({y})" if y else t
                webbrowser.open(f"https://www.kinopoisk.ru/index.php?kp_query={urllib.parse.quote(q)}")
            else:
                QMessageBox.warning(dlg, "Поиск на Кинопоиске",
                                    "Не удалось выполнить поиск.\n\n"
                                    "Поле «Название» пустое в блоке «Данные о фильме».\n\n"
                                    "Заполните название и нажмите поиск ещё раз.")
        kp_search_btn.clicked.connect(_search_kp_dlg)
        kp_layout.addWidget(kp_search_btn)
        film_layout.addLayout(kp_layout)

        # --- Торрент для видео файла (источник) (URL) ---
        tv_layout = QHBoxLayout()
        tv_layout.addWidget(QLabel("Торрент видео:"))
        torrent_video_edit = QLineEdit()
        torrent_video_edit.setPlaceholderText("https://...")
        torrent_video_edit.setToolTip("Ссылка на торрент с исходным видео файлом для скачивания")
        setup_url_validation(torrent_video_edit)
        tv_layout.addWidget(torrent_video_edit, 1)
        # Кнопка поиска на RuTracker
        rt_search_btn = QPushButton(); rt_search_btn.setFixedSize(24, 24)
        _rt_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "rutracker_logo.png")
        if os.path.isfile(_rt_icon):
            rt_search_btn.setIcon(_make_kp_search_icon(_rt_icon, 48, mag_scale=0.42))
            rt_search_btn.setIconSize(QSize(20, 20))
        rt_search_btn.setToolTip("Поиск на RuTracker по названию фильма\nРезультаты отсортированы по размеру (от большего к меньшему)")
        def _search_rt_dlg():
            t = title_edit.text().strip() or name_edit.text().strip()
            y = year_edit.text().strip()
            if t:
                q = f"{t} ({y})" if y else t
                webbrowser.open(f"https://rutracker.org/forum/tracker.php?nm={urllib.parse.quote(q)}&o=7&s=2")
            else:
                QMessageBox.warning(dlg, "Поиск на RuTracker",
                                    "Не удалось выполнить поиск.\n\n"
                                    "Поле «Название» пустое в блоке «Данные о фильме».\n\n"
                                    "Заполните название и нажмите поиск ещё раз.")
        rt_search_btn.clicked.connect(_search_rt_dlg)
        tv_layout.addWidget(rt_search_btn)
        film_layout.addLayout(tv_layout)

        layout.addWidget(film_group)

        # --- Пояснение обязательных полей ---
        req_hint = QLabel("<span style='color:red;'>*</span> — обязательное поле, остальные можно заполнить позже в таблице")
        req_hint.setStyleSheet("color: #888; font-size: 10px;")
        req_hint.setToolTip("Только «Название папки» обязательно для создания")
        layout.addWidget(req_hint)

        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        create_btn = QPushButton("Создать")
        create_btn.setToolTip("Создать папку, текстовый файл и переместить торрент/архив/видео файл")
        create_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        create_btn.setAutoDefault(False)
        create_btn.setDefault(False)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setToolTip("Отменить создание")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        btn_layout.addWidget(create_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        cancel_btn.clicked.connect(dlg.reject)

        # Результат: путь созданной папки и имя
        result = {"folder_path": "", "name": ""}

        def _on_create():
            name = name_edit.text().strip()
            if not name:
                error_lbl.setText("Введите название папки")
                error_lbl.setVisible(True)
                return
            # Блокируем создание если есть запрещённые символы
            forbidden = [ch for ch in _FORBIDDEN if ch in name]
            if forbidden:
                name_edit.setFocus()
                return
            # Проверка URL-полей
            _url_fields = [
                (poster_url_edit, "Постер"),
                (kinopoisk_edit, "Кинопоиск"),
                (torrent_video_edit, "Торрент видео"),
                (torrent_audio_edit, "Торрент аудио"),
                (forum_edit, "Форум russdub"),
            ]
            _bad_urls = []
            for _uf, _ul in _url_fields:
                if not validate_url_field(_uf):
                    _bad_urls.append(_ul)
            if _bad_urls:
                error_lbl.setText(f"Неверный формат ссылки: {', '.join(_bad_urls)}")
                error_lbl.setVisible(True)
                return
            folder_path = os.path.join(ap, name)
            if os.path.exists(folder_path):
                error_lbl.setText(f"Папка «{name}» уже существует — измените название")
                error_lbl.setVisible(True)
                name_edit.setFocus()
                name_edit.selectAll()
                return
            try:
                os.makedirs(folder_path)
                # Создаём .txt файл с содержимым из формы
                txt_content = text_edit.toPlainText()
                with open(os.path.join(folder_path, f"{name}.txt"), "w", encoding="utf-8") as f:
                    f.write(txt_content)
                # Перемещаем .torrent если выбран
                torrent_src = torrent_path["value"]
                if torrent_src and os.path.isfile(torrent_src):
                    shutil.move(torrent_src, os.path.join(folder_path, os.path.basename(torrent_src)))
                # Перемещаем архив если выбран
                archive_src = archive_path["value"]
                if archive_src and os.path.isfile(archive_src):
                    shutil.move(archive_src, os.path.join(folder_path, os.path.basename(archive_src)))
                result["folder_path"] = folder_path
                result["name"] = name
                dlg.accept()
            except Exception as e:
                error_lbl.setText(str(e))
                error_lbl.setVisible(True)

        create_btn.clicked.connect(_on_create)

        # Скрыть ошибку при редактировании названия
        name_edit.textChanged.connect(lambda: error_lbl.setVisible(False))

        if dlg.exec() != QDialog.Accepted:
            return

        name = result["name"]
        folder_path = result["folder_path"]

        # Перемещение торрента и видео файла залогируем
        torrent_src = torrent_path["value"]
        if torrent_src:
            self.log(f"[NEW] Торрент перемещён: {os.path.basename(torrent_src)}")
        self.log(f"[NEW] Папка создана: {name}")

        # Собрать данные из формы СЕЙЧАС (до пересканирования)
        form_data = {
            "title": title_edit.text().strip(),
            "year": year_edit.text().strip(),
            "password": password_edit.text().strip(),
            "forum": forum_edit.text().strip(),
            "poster_url": poster_url_edit.text().strip(),
            "kinopoisk_url": kinopoisk_edit.text().strip(),
            "torrent_video": torrent_video_edit.text().strip(),
            "torrent_audio": torrent_audio_edit.text().strip(),
            "sub_year": sub_year_dlg.currentText() if sub_cb.isChecked() else "—",
            "sub_month": sub_month_dlg.currentText() if sub_cb.isChecked() else "—",
            "delay": "0",
            "video": "",
        }

        # Просканировать аудио файлы только в ЭТОЙ новой папке
        try:
            audio_files = [f for f in os.listdir(folder_path)
                           if os.path.isfile(os.path.join(folder_path, f)) and self._is_audio(f)]
        except OSError:
            audio_files = []

        folder_data = {"name": name, "path": folder_path, "files": audio_files}

        # Добавить в audio_folders (поддерживая сортировку по имени)
        self.audio_folders.append(folder_data)
        self.audio_folders.sort(key=lambda x: x["name"])
        total = sum(len(f["files"]) for f in self.audio_folders)
        self.audio_count_lbl.setText(f"Папок: {len(self.audio_folders)}, аудио файлов: {total}")

        # Инкрементально добавить одну строку (без полной пересборки таблицы)
        self._add_single_row(folder_data, form_data)

        filled = [k for k, v in form_data.items() if v and v != "—" and v != "0" and v != "— не выбирать —"]
        self.log(f"[NEW] Данные записаны в «{name}»: {', '.join(filled) if filled else 'только имя'}")

        self._save_config()

        # Открыть вкладку созданного фильма
        self._open_record_tab(name)

    def _handle_info(self, fn):
        """Загрузить txt для записи. Возвращает True если файл загружен."""
        r = self._find_row(fn)
        if not r: return False
        self._save_current_txt()
        if not r["txt_files"]:
            name = f"{r['folder_name']}.txt"
            path = os.path.join(r["folder_path"], name)
            if not os.path.exists(path):
                try:
                    with open(path, "w", encoding="utf-8") as f: f.write("")
                    r["txt_files"] = [name]; r["txt_problem"] = False
                    r["info_btn"].setText(name[:15])
                    r["info_btn"].setStyleSheet("color:#006600; font-weight:bold;")
                    self.log(f"Создан: {name}")
                    self._check_row_status(r)
                except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return False
            self._open_txt(path, name)
            self._sync_tab_txt(fn, name)
            return True
        elif len(r["txt_files"]) == 1:
            sel = r["txt_files"][0]
            self._open_txt(os.path.join(r["folder_path"], sel), sel)
            self._sync_tab_txt(fn, sel)
            return True
        else:
            # Несколько txt — показать меню выбора
            menu = QMenu(self)
            menu.setToolTipsVisible(True)
            for tf in sorted(r["txt_files"]):
                act = menu.addAction(tf)
                act.setToolTip(f"Открыть и редактировать {tf}")
                act.setData(tf)
            chosen = menu.exec(r["info_btn"].mapToGlobal(r["info_btn"].rect().bottomLeft()))
            if chosen:
                tf = chosen.data()
                r["selected_txt"] = tf
                r["info_btn"].setText(tf[:15])
                r["info_btn"].setStyleSheet("color:#006600; font-weight:bold;")
                r["info_btn"].setToolTip(f"Выбран: {tf}\nПравый клик — выбрать другой txt")
                r["txt_problem"] = False
                self._check_row_status(r)
                self._open_txt(os.path.join(r["folder_path"], tf), tf)
                self._sync_tab_txt(fn, tf)
                self.schedule_autosave()
                return True
            return False

    def _open_txt(self, path, filename):
        try:
            with open(path, "r", encoding="utf-8") as f: content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="cp1251") as f: content = f.read()
            except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return
        except Exception as e: QMessageBox.critical(self, "Ошибка", str(e)); return
        self.current_txt_path = path; self.txt_last_content = content
        self.txt_edit.setPlainText(content)
        self.txt_group.setTitle(f"Редактирование: {filename}")
        self.txt_status_lbl.setText("")

    def _save_current_txt(self):
        if not self.current_txt_path: return
        content = self.txt_edit.toPlainText()
        if content == self.txt_last_content: return
        try:
            with open(self.current_txt_path, "w", encoding="utf-8") as f: f.write(content)
            self.txt_last_content = content
            self.txt_status_lbl.setText("OK Сохранено"); self.txt_status_lbl.setStyleSheet("color:green;")
        except Exception:
            self.txt_status_lbl.setText("ОШИБКА"); self.txt_status_lbl.setStyleSheet("color:red;")

    def _txt_autosave_tick(self):
        if self._readonly:
            return
        if self.current_txt_path:
            if self.txt_edit.toPlainText() != self.txt_last_content:
                self._save_current_txt()
        # Сохранить txt со всех открытых вкладок фильмов
        for fn in list(self._open_tabs.keys()):
            self._save_tab_txt(fn)

    # ──────────────────────────────────
    #  TXT панель внизу (toggle)
    # ──────────────────────────────────
    def _toggle_txt_panel(self, fn):
        """Переключить видимость TXT панели внизу."""
        # Если панель открыта для этой же строки → закрыть
        if self.txt_group.isVisible() and self._active_txt_fn == fn:
            self._close_txt_panel()
            return
        # Иначе → загрузить и показать
        if self._handle_info(fn):
            self._show_txt_panel(fn)

    def _show_txt_panel(self, fn):
        """Показать TXT панель и обвести кнопку рамкой."""
        self.txt_group.setVisible(True)
        w = self.bottom_splitter.width()
        self.bottom_splitter.setSizes([w // 2, w // 2])
        # Обводка на кнопке
        self._remove_txt_btn_border()
        r = self._find_row(fn)
        if r and r.get("info_btn"):
            self._active_txt_btn = r["info_btn"]
            self._active_txt_fn = fn
            r["info_btn"].setStyleSheet(r["info_btn"].styleSheet() + " border: 2px solid #0078d4;")

    def _close_txt_panel(self):
        """Закрыть TXT панель и убрать рамку."""
        self._save_current_txt()
        self.txt_group.setVisible(False)
        self._remove_txt_btn_border()
        self._active_txt_fn = None
        self.current_txt_path = None

    def _remove_txt_btn_border(self):
        """Убрать рамку с активной TXT кнопки."""
        if self._active_txt_btn:
            style = self._active_txt_btn.styleSheet().replace(" border: 2px solid #0078d4;", "")
            self._active_txt_btn.setStyleSheet(style)
            self._active_txt_btn = None

    # ──────────────────────────────────
    #  Обработка mkvmerge
    # ──────────────────────────────────
    def _start_processing(self):
        mkvmerge = self.mkvmerge_path_edit.text()
        if not mkvmerge or not os.path.exists(mkvmerge):
            QMessageBox.critical(self, "Ошибка", "Укажите mkvmerge.exe"); return
        tp = self.test_path_edit.text()
        if not tp or not os.path.isdir(tp):
            QMessageBox.critical(self, "Ошибка", "Укажите папку тест"); return
        op = self.output_path_edit.text()
        task_refs = []
        for r in self.rows:
            an = self._audio_filename(r); vn = r["video_combo"].currentText()
            on = r["output_entry"].text()
            if not an or not vn or vn == "— снять выбор —" or not on: continue
            if op and os.path.exists(os.path.join(op, on)): continue
            if os.path.exists(os.path.join(tp, on)): continue
            af = os.path.join(r["folder_path"], an)
            vf = r.get("video_full_path") or (os.path.join(self.video_path_edit.text(), vn) if self.video_path_edit.text() else "")
            if not os.path.exists(af) or not os.path.exists(vf): continue
            starter = self._starter_filename(r)
            starter_path = ""
            if starter:
                sp = os.path.join(r["folder_path"], starter)
                if os.path.isfile(sp):
                    starter_path = sp
            ender = self._ender_filename(r)
            ender_path = ""
            if ender:
                ep = os.path.join(r["folder_path"], ender)
                if os.path.isfile(ep):
                    ender_path = ep
            task_refs.append({"folder_name": r["folder_name"],
                              "audio_path": af, "video_path": vf,
                              "output_path": os.path.join(tp, on),
                              "delete_other_audio": self.batch_del_audio_cb.isChecked(),
                              "starter_path": starter_path,
                              "ender_path": ender_path})
        if not task_refs:
            QMessageBox.information(self, "Инфо", "Нет заданий"); return
        self.log(f"=== ОБРАБОТКА: {len(task_refs)} файлов ===")
        self._save_config()
        threading.Thread(target=self._process_tasks, args=(task_refs, mkvmerge), daemon=True).start()

    def _on_sig_read_ui(self):
        """Читает delay, delays, track_name и selected_audio_tracks из UI (главный поток)."""
        fn = self._pending_read_fn
        r = self._find_row(fn)
        if r:
            self._read_result["delay"] = r.get("delay_value", "0")
            self._read_result["track_name"] = self._get_track_name(r)
            self._read_result["delays"] = r.get("delays", [{"value": r.get("delay_value", "0"), "confirmed": False}])
            self._read_result["selected_audio_tracks"] = r.get("selected_audio_tracks")
        else:
            self._read_result["delay"] = "0"
            self._read_result["track_name"] = self.track_name_edit.text()
            self._read_result["delays"] = [{"value": "0", "confirmed": False}]
            self._read_result["selected_audio_tracks"] = None
        self._read_event.set()

    def _set_row_date(self, folder_name, date_str):
        """Устанавливает дату обработки (вызывается в главном потоке)."""
        r = self._find_row(folder_name)
        if r:
            r["processed_date"] = date_str
            r["date_lbl"].setText(date_str)
            self.schedule_autosave()

    def _on_file_done(self, folder_name):
        """Вызывается в главном потоке когда один файл обработан — пересчитать статус."""
        r = self._find_row(folder_name)
        if not r: return
        # Сбросить NEW после обработки
        if r.get("is_new"):
            r["is_new"] = False
            self._update_tab_reset_new_btn(folder_name)
            self._update_reset_new_btn()
            self.log(f"Пометка NEW сброшена после обработки: {folder_name}")
        self._check_row_status(r)
        self._update_batch_buttons()
        self.schedule_autosave()

    def _reset_new_flags(self):
        """Сбросить пометки NEW. В режиме фильма — только для текущего. Иначе: для выбранных или всех."""
        # Режим фильма — сброс только для текущего фильма
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        if current_tab > 0:
            fn = self.tab_widget.tabText(current_tab)
            self._reset_new_single(fn)
            return
        selected = [r for r in self.rows if r["select_cb"].isChecked() and r.get("is_new") and not self.table.isRowHidden(r["row_index"])]
        targets = selected if selected else [r for r in self.rows if r.get("is_new")]
        count = 0
        for r in targets:
            r["is_new"] = False
            self._check_row_status(r)
            self._update_tab_reset_new_btn(r["folder_name"])
            count += 1
        has_new = any(r.get("is_new") for r in self.rows)
        self._update_reset_new_btn()
        if selected:
            self.log(f"Пометки NEW сброшены для выбранных ({count})")
        else:
            self.log(f"Пометки NEW сброшены ({count})")
        self._sort_table()
        self.schedule_autosave()

    def _reset_new_single(self, fn):
        """Сбросить пометку NEW для одной записи (из вкладки фильма)."""
        r = self._find_row(fn)
        if not r or not r.get("is_new"):
            return
        r["is_new"] = False
        self._check_row_status(r)
        self._update_tab_reset_new_btn(fn)
        has_new = any(r.get("is_new") for r in self.rows)
        self._update_reset_new_btn()
        self.log(f"Пометка NEW сброшена: {fn}")
        self._sort_table()
        self.schedule_autosave()

    def _update_tab_reset_new_btn(self, fn):
        """Обновить состояние кнопки 'Сбросить NEW' во вкладке фильма."""
        if fn not in self._open_tabs:
            return
        tw = self._open_tabs[fn].get("widgets", {})
        btn = tw.get("reset_new_btn")
        if not btn:
            return
        r = self._find_row(fn)
        is_new = r.get("is_new", False) if r else False
        btn.setEnabled(is_new)
        btn.setStyleSheet(
            "QPushButton{background-color:#ffd699; padding:2px 6px;} QPushButton:hover{background-color:#f0be60;}"
            if is_new else
            "QPushButton{background-color:#e0e0e0; color:#888; padding:2px 6px;}"
        )

    # ──────────────────────────────────
    #  RAR архивы — распаковка и удаление
    # ──────────────────────────────────
    def _action_unrar(self, fn):
        """Распаковать RAR архив используя пароль."""
        self.log(f"[UNRAR] Запуск распаковки: {fn}")
        r = self._find_row(fn)
        if not r:
            self.log(f"[UNRAR] ОШИБКА: строка не найдена для «{fn}»")
            return
        archive = r.get("archive_file")
        if not archive:
            self.log(f"[UNRAR] Архив не найден в папке «{fn}» (archive_file пуст)")
            QMessageBox.information(self, "Инфо", "Архив не найден в папке")
            return
        pw = r["password_entry"].text().strip()
        archive_path = os.path.join(r["folder_path"], archive)
        if not os.path.isfile(archive_path):
            self.log(f"[UNRAR] Файл не существует: {archive_path}")
            QMessageBox.critical(self, "Ошибка", f"Файл архива не найден:\n{archive_path}")
            return
        r["status_lbl"].setText("Распаковка...")
        r["status_lbl"].setStyleSheet("color:#8B4513; font-weight:bold;")
        r["btn_unrar"].setEnabled(False)
        self.log(f"[UNRAR] Начало: {fn} → {archive}")
        threading.Thread(target=self._unrar_worker, args=(fn, archive_path, pw, r["folder_path"]), daemon=True).start()

    def _find_unrar_paths(self):
        """Найти пути к UnRAR.exe и 7z.exe. Приоритет — путь из настроек."""
        candidates = []
        # 1. Путь из настроек (наивысший приоритет)
        custom = self.config.get("unrar_path", "").strip()
        if custom and os.path.isfile(custom):
            candidates.append(custom)
        # 2. WinRAR — стандартные пути установки
        for prog in [os.environ.get("ProgramFiles", r"C:\Program Files"),
                      os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]:
            if prog:
                candidates.append(os.path.join(prog, "WinRAR", "UnRAR.exe"))
                candidates.append(os.path.join(prog, "WinRAR", "Rar.exe"))
        # 3. 7-Zip — стандартные пути установки
        for prog in [os.environ.get("ProgramFiles", r"C:\Program Files"),
                      os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]:
            if prog:
                candidates.append(os.path.join(prog, "7-Zip", "7z.exe"))
        # 4. Из PATH
        candidates.extend(["unrar", "rar", "7z"])
        return candidates

    def _unrar_worker(self, fn, archive_path, password, extract_to):
        """Рабочий поток: распаковка через UnRAR/7z с выводом прогресса в лог приложения."""
        paths = self._find_unrar_paths()
        archive_path = os.path.abspath(archive_path)
        extract_to = os.path.abspath(extract_to)
        os.makedirs(extract_to, exist_ok=True)
        created_links = []  # жёсткие ссылки для оригинальных имён томов

        # Спецсимволы в пароле, ломающие -p на командной строке Windows
        _pw_has_special = password and any(c in password for c in '"<>|&^')

        def _run_exe(exe, archive_override=None, pw_escape="list"):
            """Запуск одного инструмента, вернуть (returncode, output_lines).
            archive_override — альтернативный путь к архиву.
            pw_escape — способ передачи пароля:
              'list' — через list2cmdline (стандартный, \" внутри кавычек)
              'dblquote' — строка с "" вместо \" (альтернативный стандарт Windows)
              'stdin' — пароль через stdin pipe (последний резерв)
            """
            arc = archive_override or archive_path
            exe_lower = os.path.basename(exe).lower()
            work_dir = extract_to
            use_stdin = (pw_escape == "stdin")

            if pw_escape == "dblquote" and password and '"' in password:
                # Формируем командную строку СТРОКОЙ с "" вместо \"
                # MS C runtime: внутри "...", пара "" = литеральная "
                def _ql(s):
                    """Квотирование через list2cmdline для одного аргумента."""
                    return subprocess.list2cmdline([s])
                esc_pw = password.replace('"', '""')
                pw_part = f'"-p{esc_pw}"'
                if "7z" in exe_lower:
                    cmd_str = f'{_ql(exe)} x {pw_part} {_ql(arc)} -o{_ql(extract_to)} -y -bsp1'
                else:
                    cmd_str = f'{_ql(exe)} x {pw_part} -y {_ql(arc)} {_ql(extract_to + os.sep)}'
                self._sig_unrar_progress.emit(fn,
                    f'CMD: {cmd_str.replace(pw_part, "-p***")}  [пароль: dblquote]')
                proc = subprocess.Popen(
                    cmd_str,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=work_dir,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
            else:
                # Стандартная команда как список
                if "7z" in exe_lower:
                    cmd = [exe, "x", arc, f"-o{extract_to}", "-y", "-bsp1"]
                    if password and not use_stdin:
                        cmd.insert(2, f"-p{password}")
                else:
                    cmd = [exe, "x", "-y", arc, extract_to + os.sep]
                    if password and not use_stdin:
                        cmd.insert(2, f"-p{password}")
                pw_mode = "stdin" if use_stdin else f"-p({len(password)})" if password else "нет"
                cmd_log = [c if not c.startswith("-p") else "-p***" for c in cmd]
                self._sig_unrar_progress.emit(fn,
                    f"CMD: {subprocess.list2cmdline(cmd_log)}  [пароль: {pw_mode}]")
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=work_dir,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                if use_stdin and password:
                    try:
                        proc.stdin.write(password.encode('utf-8') + b'\r\n')
                        proc.stdin.flush()
                    except OSError:
                        pass
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            # --- Мониторинг прогресса по I/O-счётчикам процесса ---
            # UnRAR буферизует stdout (CRT), прогресс приходит только в конце.
            # Вместо файлового размера используем GetProcessIoCounters —
            # считает реально записанные байты (не зависит от SetEndOfFile).
            try:
                arc_size = os.path.getsize(arc)
            except OSError:
                arc_size = 0
            _stop_monitor = threading.Event()

            class _IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            def _io_monitor():
                """Поллинг I/O-счётчиков процесса для отображения прогресса."""
                _last_pct = -1
                h = getattr(proc, '_handle', None)
                if h is None:
                    return
                counters = _IO_COUNTERS()
                while not _stop_monitor.is_set():
                    try:
                        if ctypes.windll.kernel32.GetProcessIoCounters(
                                ctypes.wintypes.HANDLE(h), ctypes.byref(counters)):
                            written = counters.WriteTransferCount
                            if arc_size > 0 and written > 0:
                                pct = min(99, int(written * 100 / arc_size))
                                if pct != _last_pct:
                                    _last_pct = pct
                                    self._sig_unrar_progress.emit(fn, f"{pct}%")
                    except (OSError, ValueError):
                        break
                    _stop_monitor.wait(10)

            mon_thread = threading.Thread(target=_io_monitor, daemon=True)
            if arc_size > 100_000 and sys.platform == "win32":
                mon_thread.start()

            # --- Чтение stdout ---
            lines = []
            for raw_line in proc.stdout:
                decoded = raw_line.decode("cp866", errors="replace").strip()
                if not decoded:
                    continue
                # Убрать управляющие символы: \b (backspace), \r и прочие
                # UnRAR использует \b для стирания процентов в консоли
                decoded = re.sub(r'[\x00-\x09\x0b-\x1f]', '', decoded)
                # Убрать проценты (прогресс уже от I/O-монитора)
                if re.search(r'\d+%', decoded):
                    decoded = re.sub(r'\s*\d+%', '', decoded)
                    decoded = re.sub(r'\s{2,}', ' ', decoded).strip()
                    if not decoded:
                        continue
                # Убрать полные пути — оставить только имена файлов
                # "F:\Movies\long path\folder\file.thd" → "file.thd"
                decoded = re.sub(r'[A-Za-z]:[/\\].+[/\\]', '', decoded)
                decoded = re.sub(r'\s{2,}', ' ', decoded).strip()
                if decoded:
                    self._sig_unrar_progress.emit(fn, decoded)
                    lines.append(decoded)

            # Остановить мониторинг
            _stop_monitor.set()
            if mon_thread.is_alive():
                mon_thread.join(timeout=3)

            # Дождаться завершения процесса
            if use_stdin:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._sig_unrar_progress.emit(fn, "stdin: процесс завис, завершаем...")
                    proc.kill()
                    proc.wait()
                    return -1, lines
            else:
                proc.wait()
            return proc.returncode, lines

        def _find_missing_volume(output_lines):
            """Из вывода UnRAR найти путь файла 'Невозможно открыть <path>'."""
            for line in output_lines:
                for prefix in ["Невозможно открыть ", "Cannot open "]:
                    if prefix in line:
                        return line.split(prefix, 1)[1].strip()
            return None

        _last_output = []
        _last_rc = -1
        try:
            for exe in paths:
                try:
                    rc, lines = _run_exe(exe)
                    if rc == 0:
                        self._sig_unrar_done.emit(fn, True, "")
                        return
                    # Проверяем: UnRAR не нашёл том по оригинальному имени?
                    missing = _find_missing_volume(lines)
                    if missing and rc == 10:
                        # Создать жёсткую ссылку с оригинальным именем тома
                        # и запустить UnRAR уже НА ЭТОМ ФАЙЛЕ (имя совпадёт с заголовком)
                        full_missing = os.path.join(extract_to, missing)
                        if not os.path.exists(full_missing):
                            try:
                                os.makedirs(os.path.dirname(full_missing), exist_ok=True)
                                os.link(archive_path, full_missing)
                                created_links.append(full_missing)
                                self._sig_unrar_progress.emit(fn,
                                    f"Создана ссылка {missing} → {os.path.basename(archive_path)}")
                            except OSError as e:
                                self._sig_unrar_progress.emit(fn, f"Не удалось создать ссылку: {e}")
                                continue
                        # Повтор 1: с -p (list2cmdline, \" экранирование)
                        self._sig_unrar_progress.emit(fn,
                            f"Повтор из {missing} (оригинальное имя тома)...")
                        rc2, lines2 = _run_exe(exe, archive_override=full_missing)
                        if rc2 == 0:
                            self._sig_unrar_done.emit(fn, True, "")
                            return
                        # Повтор 2: с -p через "" экранирование (альт. стандарт Windows)
                        if rc2 == 10 and _pw_has_special:
                            self._sig_unrar_progress.emit(fn,
                                'Повтор с "" экранированием пароля...')
                            rc3, lines3 = _run_exe(exe, archive_override=full_missing, pw_escape="dblquote")
                            if rc3 == 0:
                                self._sig_unrar_done.emit(fn, True, "")
                                return
                    # Если нет missing volume, но код 10 и спецсимволы
                    elif rc == 10 and _pw_has_special:
                        self._sig_unrar_progress.emit(fn,
                            'Повтор с "" экранированием пароля...')
                        rc2, lines2 = _run_exe(exe, pw_escape="dblquote")
                        if rc2 == 0:
                            self._sig_unrar_done.emit(fn, True, "")
                            return
                    _last_output = lines
                    _last_rc = rc
                    self._sig_unrar_progress.emit(fn,
                        f"{os.path.basename(exe)}: код {rc}, пробуем следующий...")
                    continue
                except FileNotFoundError:
                    continue
                except Exception as e:
                    continue
            # Собрать вывод последней утилиты для диагностики
            _detail = "\n".join(_last_output[-10:]) if _last_output else ""
            _err_msg = f"Все инструменты завершились с ошибкой (код возврата: {_last_rc}).\n{_detail}"
            self._sig_unrar_done.emit(fn, False, _err_msg)
        finally:
            for lnk in created_links:
                try:
                    os.remove(lnk)
                except OSError:
                    pass
                # Удалить пустые родительские каталоги до extract_to
                try:
                    d = os.path.dirname(lnk)
                    while d and os.path.normcase(d) != os.path.normcase(extract_to):
                        if os.path.isdir(d) and not os.listdir(d):
                            os.rmdir(d)
                            d = os.path.dirname(d)
                        else:
                            break
                except OSError:
                    pass

    def _on_unrar_progress(self, fn, text):
        """Обновить статус строки и вывести прогресс в лог."""
        r = self._find_row(fn)
        if not r: return
        stripped = text.strip()
        # Чистые проценты (от мониторинга размера файлов) — статус + лог
        if re.fullmatch(r'\d+%', stripped):
            r["status_lbl"].setText(f"Распаковка {stripped}")
            r["status_lbl"].setToolTip(f"Прогресс распаковки: {stripped}")
            self.log(f"[UNRAR] {fn}: {stripped}")
            return
        # Строки с процентом и текстом (имя файла + OK) — в статус и лог
        if "%" in text or "OK" in text:
            r["status_lbl"].setText(f"Распаковка {text}")
        else:
            r["status_lbl"].setText("Распаковка...")
        self.log(f"[UNRAR] {fn}: {text}")

    def _on_unrar_done(self, fn, success, error):
        """Обработчик результата распаковки (главный поток)."""
        r = self._find_row(fn)
        if not r: return
        r["btn_unrar"].setEnabled(True)
        if success:
            r["_password_error"] = False  # Сброс ошибки пароля при успешной распаковке
            self.log(f"[UNRAR] OK: {fn}")
            # Пересканировать папку — обновит audio/starter combo в таблице и на вкладке
            self._rescan_single_folder(fn)
        else:
            self.log(f"[UNRAR] ОШИБКА ({fn}): {error}")
            err_lo = error.lower()
            is_password_error = any(kw in err_lo for kw in (
                "wrong password", "incorrect password", "data error in encrypted",
                "неверный пароль", "ошибка данных", "код возврата: 11",
            ))
            if is_password_error:
                r["status_lbl"].setText("Неверный пароль")
                r["status_lbl"].setToolTip("Пароль от архива неверный — введите правильный пароль и попробуйте снова")
                r["_password_error"] = True
                r["sort_priority"] = 5
            else:
                r["status_lbl"].setText("Ошибка распаковки")
                r["status_lbl"].setToolTip(f"Ошибка: {error[:200]}")
                r["_password_error"] = False
            r["status_lbl"].setStyleSheet("color:red; font-weight:bold;")
            self._set_row_bg(r, COLOR_ERROR)

    def _on_password_changed(self, r):
        """Неверный пароль сбрасывается ТОЛЬКО при успешной распаковке."""
        pass

    def _move_torrent_to_folder(self, fn):
        """Выбрать и переместить .torrent файл в папку аудио дорожки."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r["folder_path"]
        if not os.path.isdir(fp):
            QMessageBox.critical(self, "Ошибка", f"Папка не существует:\n{fp}")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Выбрать .torrent файл для перемещения", "",
            "Torrent (*.torrent);;Все файлы (*)")
        if not src or not os.path.isfile(src):
            return
        dest = os.path.join(fp, os.path.basename(src))
        if os.path.exists(dest):
            QMessageBox.warning(self, "Файл существует",
                f"Файл «{os.path.basename(src)}» уже есть в папке назначения")
            return
        try:
            shutil.move(src, dest)
            self.log(f"[TORRENT] Перемещён: {os.path.basename(src)} → {fp}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка перемещения", str(e))
            return
        self._rescan_single_folder(fn)

    def _move_archive_to_folder(self, fn):
        """Переместить архив из внешней папки в папку аудио дорожки."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r["folder_path"]
        if not os.path.isdir(fp):
            QMessageBox.critical(self, "Ошибка", f"Папка не существует:\n{fp}")
            return
        _start = self.download_path_edit.text() if hasattr(self, 'download_path_edit') else ""
        src = _open_archive_dialog(self, "Выбрать архив для перемещения", _start)
        if not src or not os.path.isfile(src):
            return
        dest = os.path.join(fp, os.path.basename(src))
        if os.path.exists(dest):
            QMessageBox.warning(self, "Файл существует",
                f"Файл «{os.path.basename(src)}» уже есть в папке назначения")
            return
        try:
            shutil.move(src, dest)
            self.log(f"[ARCHIVE] Перемещён: {os.path.basename(src)} → {fp}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка перемещения", str(e))
            return
        # Явно пометить архив (файл только что перемещён — точно существует)
        r["archive_file"] = os.path.basename(src)
        # Пересканировать папку (обновит аудио, txt, статус)
        self._rescan_single_folder(fn)
        # Принудительно обновить вкладку (если _check_row_status не обнаружил по magic bytes)
        if fn in self._open_tabs:
            tw = self._open_tabs[fn].get("widgets", {})
            arc_lbl = tw.get("archive_label")
            arc_name = r.get("archive_file", "")
            if arc_lbl and arc_name:
                arc_lbl.setText(arc_name)
                arc_lbl.setStyleSheet("font-family: Consolas, monospace; color:#8B4513; font-weight:bold;")
                arc_lbl.setToolTip(f"Файл архива:\n{os.path.join(fp, arc_name)}")
            arc_btn = tw.get("archive_btn")
            if arc_btn:
                arc_btn.setVisible(not bool(arc_name))

    def _action_del_archive(self, fn):
        """Удалить архив из папки (после расшифровки)."""
        r = self._find_row(fn)
        if not r: return
        archive = r.get("archive_file")
        if not archive: return
        path = os.path.join(r["folder_path"], archive)
        if not os.path.isfile(path): return
        try:
            size_mb = os.path.getsize(path) // 1024 // 1024
        except OSError:
            size_mb = 0
        ans = QMessageBox.question(self, "Удалить архив",
            f"Удалить архив «{archive}» ({size_mb} МБ)?")
        if ans != QMessageBox.Yes: return
        try:
            os.remove(path)
            r["archive_file"] = ""
            self.log(f"[DEL] Архив удалён: {archive}")
            self._check_row_status(r)
            self._update_archive_btn_count()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_tab_old_backups_click(self):
        """Обработчик кнопки «Старые бекапы» в верхней панели (для текущей вкладки фильма)."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self._show_old_backups(self.tab_widget.tabText(idx))

    def _on_tab_copy_click(self):
        """Обработчик кнопки «Копировать» в верхней панели (для текущей вкладки фильма)."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self._copy_folder_dialog(self.tab_widget.tabText(idx))

    def _on_tab_rename_click(self):
        """Обработчик кнопки «Переименовать» в верхней панели (для текущей вкладки фильма)."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self._rename_folder_dialog(self.tab_widget.tabText(idx))

    def _on_tab_delfolder_click(self):
        """Обработчик кнопки «Удалить папку» в верхней панели (для текущей вкладки фильма)."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self._rmdir_with_confirm(self.tab_widget.tabText(idx))

    def _rename_folder_dialog(self, fn):
        """Диалог переименования папки фильма."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        parent_dir = os.path.dirname(fp)
        if not fp or not os.path.isdir(fp):
            QMessageBox.warning(self, "Ошибка", f"Папка «{fn}» не найдена на диске:\n{fp}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Переименовать папку")
        dlg.setMinimumWidth(450)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel(f"Текущее имя: <b>{fn}</b>"))

        # Предложение из "Данные о фильме": Название + Год
        _title = r["title_entry"].text().strip()
        _year = r["year_entry"].text().strip()
        _suggested = f"{_title} {_year}".strip() if _title else ""
        # Удалить запрещённые символы из предложения
        for _fc in r'\/:*?"<>|':
            _suggested = _suggested.replace(_fc, "")

        # Кнопка подстановки если имя папки отличается от "Название Год"
        if _suggested and _suggested != fn:
            lay.addWidget(QLabel("Предложение из данных о фильме:"))
            suggest_btn = QPushButton(_suggested)
            suggest_btn.setStyleSheet("QPushButton{background-color:#e8f5e9; font-weight:bold; text-align:left; padding:6px 10px;} "
                                       "QPushButton:hover{background-color:#c8e6c9;}")
            suggest_btn.setToolTip("Нажмите чтобы подставить в поле ввода")
            lay.addWidget(suggest_btn)

        lay.addWidget(QLabel("Новое имя:"))
        name_edit = QLineEdit(fn)
        name_edit.selectAll()
        lay.addWidget(name_edit)

        if _suggested and _suggested != fn:
            suggest_btn.clicked.connect(lambda: (name_edit.setText(_suggested), name_edit.selectAll()))

        error_lbl = QLabel("")
        error_lbl.setStyleSheet("color:red; font-weight:bold; padding:4px 0;")
        error_lbl.setWordWrap(True)
        error_lbl.setVisible(False)
        lay.addWidget(error_lbl)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        ok_btn = QPushButton("Переименовать")
        ok_btn.setStyleSheet("QPushButton{background-color:#e0e8ff;} QPushButton:hover{background-color:#c0d0ff;}")
        cancel_btn = QPushButton("Отмена")
        btn_lay.addWidget(ok_btn)
        btn_lay.addWidget(cancel_btn)
        lay.addLayout(btn_lay)

        cancel_btn.clicked.connect(dlg.reject)

        _invalid_chars = r'\/:*?"<>|'

        def _do_rename():
            new_name = name_edit.text().strip()
            # Валидация
            if not new_name:
                error_lbl.setText("Имя не может быть пустым")
                error_lbl.setVisible(True)
                return
            if new_name == fn:
                error_lbl.setText("Имя не изменилось")
                error_lbl.setVisible(True)
                return
            bad = [c for c in _invalid_chars if c in new_name]
            if bad:
                error_lbl.setText(f"Недопустимые символы: {' '.join(bad)}\nНельзя использовать: {_invalid_chars}")
                error_lbl.setVisible(True)
                return
            new_path = os.path.join(parent_dir, new_name)
            if os.path.exists(new_path):
                error_lbl.setText(f"Папка «{new_name}» уже существует!")
                error_lbl.setVisible(True)
                return
            # Закрыть вкладку перед переименованием (снять блокировки файлов Windows)
            had_tab = fn in self._open_tabs
            if had_tab:
                tab_idx = self._find_tab_index(fn)
                if tab_idx >= 0:
                    self.tab_widget.removeTab(tab_idx)
                del self._open_tabs[fn]
            import gc; gc.collect()
            # Переименование
            try:
                os.rename(fp, new_path)
            except Exception as e:
                # Откат: вернуть вкладку если была
                if had_tab:
                    self._open_record_tab(fn)
                error_lbl.setText(f"Ошибка переименования: {e}")
                error_lbl.setVisible(True)
                return
            # Обновить данные записи
            r["folder_name"] = new_name
            r["folder_path"] = new_path
            # Обновить ячейку таблицы
            fi = self.table.item(r["row_index"], COL_FOLDER)
            if fi:
                fi.setText(new_name)
                fi.setToolTip(f"Папка: {new_path}")
            self.log(f"[RENAME] «{fn}» → «{new_name}»")
            dlg.accept()
            # Открыть вкладку с новым именем
            self._open_record_tab(new_name)

        ok_btn.clicked.connect(_do_rename)
        name_edit.returnPressed.connect(_do_rename)
        dlg.exec()

    def _copy_folder_dialog(self, fn):
        """Диалог копирования папки фильма — создаёт новую папку с теми же настройками."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        parent_dir = os.path.dirname(fp)
        if not fp or not os.path.isdir(fp):
            QMessageBox.warning(self, "Ошибка", f"Папка «{fn}» не найдена на диске:\n{fp}")
            return
        if not parent_dir or not os.path.isdir(parent_dir):
            QMessageBox.warning(self, "Ошибка", f"Родительская папка не найдена:\n{parent_dir}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Копирование папки")
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)

        # --- Базовое имя (редактируемое) ---
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Базовое имя:"))
        base_edit = QLineEdit(fn)
        base_edit.setToolTip("Базовое имя — от него строятся оба варианта.\n"
                             "Кнопки суффиксов дополняют это имя")
        base_row.addWidget(base_edit)
        lay.addLayout(base_row)

        # --- Чекбокс переименования текущей папки ---
        rename_cb = QCheckBox("Переименовать текущую папку")
        rename_cb.setToolTip("Если включено — текущая папка будет переименована\n"
                             "(например, добавить суффикс «Театр» или «Режиссер»)")
        lay.addWidget(rename_cb)

        # --- Имя текущей папки (с кнопками) ---
        cur_lbl = QLabel("Текущая:")
        cur_lbl.setEnabled(False)
        current_name_edit = QLineEdit(fn)
        current_name_edit.setEnabled(False)
        current_name_edit.setToolTip("Новое имя для текущей папки")
        cur_row = QHBoxLayout()
        cur_row.addWidget(cur_lbl)
        cur_row.addWidget(current_name_edit)
        lay.addLayout(cur_row)

        # Кнопки суффиксов — общая логика
        _sfx_style_ver = "QPushButton{background-color:#e8f5e9; padding:3px 7px;} QPushButton:hover{background-color:#c8e6c9;}"
        _sfx_style_lang = "QPushButton{background-color:#e0e8ff; padding:3px 7px;} QPushButton:hover{background-color:#c0d0ff;}"

        _version_suffixes = ["Театр", "Режиссер", "Copy"]
        _lang_suffixes = ["RUS", "ENG"]
        _all_suffixes = _version_suffixes + _lang_suffixes

        def _set_suffix(edit, sfx, group):
            """Заменить суффикс в группе (версия или язык). Внутри группы — взаимоисключающие."""
            base = base_edit.text().strip()
            txt = edit.text().strip()
            # Убрать из текста все суффиксы этой группы
            for old in group:
                txt = txt.replace(f" {old}", "")
            txt = txt.rstrip()
            # Найти позицию: суффиксы версии идут до суффиксов языка
            # Разобрать текущий текст на части: база + версия? + язык?
            cur_ver = ""
            cur_lang = ""
            rest = txt
            for lsfx in _lang_suffixes:
                if rest.endswith(f" {lsfx}"):
                    cur_lang = lsfx
                    rest = rest[:-(len(lsfx) + 1)].rstrip()
                    break
            for vsfx in _version_suffixes:
                if rest.endswith(f" {vsfx}"):
                    cur_ver = vsfx
                    rest = rest[:-(len(vsfx) + 1)].rstrip()
                    break
            # Собрать заново
            if group is _version_suffixes:
                cur_ver = sfx
            else:
                cur_lang = sfx
            result = rest
            if cur_ver:
                result += f" {cur_ver}"
            if cur_lang:
                result += f" {cur_lang}"
            edit.setText(result)

        # --- Суффиксы для текущей папки ---
        cur_sfx_lay = QHBoxLayout()
        cur_sfx_lay.addSpacing(cur_lbl.sizeHint().width() + cur_row.spacing())
        cur_sfx_lbl = QLabel("Суффиксы:")
        cur_sfx_lbl.setEnabled(False)
        cur_sfx_lay.addWidget(cur_sfx_lbl)

        cur_ver_btns = []
        for s in _version_suffixes:
            btn = QPushButton(s)
            btn.setStyleSheet(_sfx_style_ver)
            btn.setEnabled(False)
            btn.setToolTip(f"Версия « {s}» — заменяет другие версии (Театр/Режиссер/Copy)")
            btn.clicked.connect(lambda checked, sfx=s: _set_suffix(current_name_edit, sfx, _version_suffixes))
            cur_sfx_lay.addWidget(btn)
            cur_ver_btns.append(btn)

        _cur_sep = QLabel("│")
        _cur_sep.setEnabled(False)
        cur_sfx_lay.addWidget(_cur_sep)

        cur_lang_btns = []
        for s in _lang_suffixes:
            btn = QPushButton(s)
            btn.setStyleSheet(_sfx_style_lang)
            btn.setEnabled(False)
            btn.setToolTip(f"Язык « {s}» — заменяет другие языки (RUS/ENG)")
            btn.clicked.connect(lambda checked, sfx=s: _set_suffix(current_name_edit, sfx, _lang_suffixes))
            cur_sfx_lay.addWidget(btn)
            cur_lang_btns.append(btn)

        cur_sfx_lay.addStretch()
        lay.addLayout(cur_sfx_lay)

        # Управление доступностью секции текущей папки
        def _toggle_rename(checked):
            cur_lbl.setEnabled(checked)
            current_name_edit.setEnabled(checked)
            cur_sfx_lbl.setEnabled(checked)
            _cur_sep.setEnabled(checked)
            for b in cur_ver_btns + cur_lang_btns:
                b.setEnabled(checked)

        rename_cb.toggled.connect(_toggle_rename)

        lay.addSpacing(6)

        # --- Имя новой папки (с кнопками) ---
        new_row = QHBoxLayout()
        new_row.addWidget(QLabel("Новая:"))
        new_name_edit = QLineEdit(f"{fn} Copy")
        new_name_edit.selectAll()
        new_name_edit.setToolTip("Имя для новой папки-копии")
        new_row.addWidget(new_name_edit)
        lay.addLayout(new_row)

        # Суффиксы для новой папки
        new_sfx_lay = QHBoxLayout()
        new_sfx_lay.addSpacing(QLabel("Новая:").sizeHint().width() + new_row.spacing())
        new_sfx_lay.addWidget(QLabel("Суффиксы:"))

        for s in _version_suffixes:
            btn = QPushButton(s)
            btn.setStyleSheet(_sfx_style_ver)
            btn.setToolTip(f"Версия « {s}» — заменяет другие версии (Театр/Режиссер/Copy)")
            btn.clicked.connect(lambda checked, sfx=s: _set_suffix(new_name_edit, sfx, _version_suffixes))
            new_sfx_lay.addWidget(btn)

        new_sfx_lay.addWidget(QLabel("│"))

        for s in _lang_suffixes:
            btn = QPushButton(s)
            btn.setStyleSheet(_sfx_style_lang)
            btn.setToolTip(f"Язык « {s}» — заменяет другие языки (RUS/ENG)")
            btn.clicked.connect(lambda checked, sfx=s: _set_suffix(new_name_edit, sfx, _lang_suffixes))
            new_sfx_lay.addWidget(btn)

        new_sfx_lay.addStretch()
        lay.addLayout(new_sfx_lay)

        # --- Ошибка ---
        error_lbl = QLabel("")
        error_lbl.setStyleSheet("color:red; font-weight:bold; padding:4px 0;")
        error_lbl.setWordWrap(True)
        error_lbl.setVisible(False)
        lay.addWidget(error_lbl)

        # --- Кнопки ---
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        ok_btn = QPushButton("Копировать")
        ok_btn.setStyleSheet("QPushButton{background-color:#e0e8ff;} QPushButton:hover{background-color:#c0d0ff;}")
        ok_btn.setToolTip("Создать новую папку с копией настроек")
        cancel_btn = QPushButton("Отмена")
        btn_lay.addWidget(ok_btn)
        btn_lay.addWidget(cancel_btn)
        lay.addLayout(btn_lay)

        cancel_btn.clicked.connect(dlg.reject)

        _invalid_chars = r'\/:*?"<>|'

        # --- Валидация в реальном времени ---
        def _validate_live():
            """Проверить имена в реальном времени и управлять кнопкой Копировать."""
            new_name = new_name_edit.text().strip()
            cur_name = current_name_edit.text().strip() if rename_cb.isChecked() else fn
            err = ""
            if not new_name:
                err = "Имя новой папки не может быть пустым"
            elif new_name == cur_name:
                err = "Имена текущей и новой папки совпадают"
            elif not rename_cb.isChecked() and new_name == fn:
                err = "Имя новой папки совпадает с текущей"
            elif rename_cb.isChecked() and cur_name == fn and new_name == fn:
                err = "Ни одно имя не изменилось"
            # Проверка запрещённых символов
            if not err:
                bad_new = [c for c in _invalid_chars if c in new_name]
                if bad_new:
                    err = f"Недопустимые символы в имени новой папки: {' '.join(bad_new)}"
            if not err and rename_cb.isChecked():
                bad_cur = [c for c in _invalid_chars if c in cur_name]
                if bad_cur:
                    err = f"Недопустимые символы в имени текущей папки: {' '.join(bad_cur)}"
            if err:
                error_lbl.setText(err)
                error_lbl.setVisible(True)
                ok_btn.setEnabled(False)
            else:
                error_lbl.setVisible(False)
                ok_btn.setEnabled(True)

        new_name_edit.textChanged.connect(lambda: _validate_live())
        current_name_edit.textChanged.connect(lambda: _validate_live())
        rename_cb.toggled.connect(lambda: _validate_live())

        # При изменении базового имени — обновить оба поля
        def _on_base_changed(text):
            base = text.strip()
            # Вычислить текущий суффикс в полях (часть после оригинального базового имени)
            cur_text = current_name_edit.text()
            new_text = new_name_edit.text()
            # Найти суффикс: всё что после старого базового имени
            old_base = _on_base_changed._prev_base
            cur_sfx = cur_text[len(old_base):] if cur_text.startswith(old_base) else ""
            new_sfx = new_text[len(old_base):] if new_text.startswith(old_base) else ""
            current_name_edit.setText(base + cur_sfx)
            new_name_edit.setText(base + new_sfx)
            _on_base_changed._prev_base = base

        _on_base_changed._prev_base = fn
        base_edit.textChanged.connect(_on_base_changed)

        # Начальная валидация
        _validate_live()

        def _do_copy():
            new_name = new_name_edit.text().strip()
            do_rename = rename_cb.isChecked()
            cur_new_name = current_name_edit.text().strip() if do_rename else ""

            # Валидация нового имени
            if not new_name:
                error_lbl.setText("Имя новой папки не может быть пустым")
                error_lbl.setVisible(True)
                return
            bad = [c for c in _invalid_chars if c in new_name]
            if bad:
                error_lbl.setText(f"Недопустимые символы в имени новой папки: {' '.join(bad)}")
                error_lbl.setVisible(True)
                return
            if new_name == fn and not do_rename:
                error_lbl.setText("Имя новой папки совпадает с текущей")
                error_lbl.setVisible(True)
                return
            new_path = os.path.join(parent_dir, new_name)
            if os.path.exists(new_path):
                error_lbl.setText(f"Папка «{new_name}» уже существует!")
                error_lbl.setVisible(True)
                return

            # Валидация переименования текущей (если включено)
            if do_rename:
                if not cur_new_name:
                    error_lbl.setText("Имя для текущей папки не может быть пустым")
                    error_lbl.setVisible(True)
                    return
                if cur_new_name == fn:
                    error_lbl.setText("Имя текущей папки не изменилось — снимите ☑ или введите другое имя")
                    error_lbl.setVisible(True)
                    return
                bad2 = [c for c in _invalid_chars if c in cur_new_name]
                if bad2:
                    error_lbl.setText(f"Недопустимые символы в имени текущей папки: {' '.join(bad2)}")
                    error_lbl.setVisible(True)
                    return
                cur_new_path = os.path.join(parent_dir, cur_new_name)
                if cur_new_name == new_name:
                    error_lbl.setText("Имена текущей и новой папки совпадают!")
                    error_lbl.setVisible(True)
                    return
                if os.path.exists(cur_new_path):
                    error_lbl.setText(f"Папка «{cur_new_name}» уже существует!")
                    error_lbl.setVisible(True)
                    return

            # === Выполнение ===
            actual_source_name = fn

            # 1. Переименовать текущую папку если нужно
            if do_rename:
                cur_new_path = os.path.join(parent_dir, cur_new_name)
                had_tab = fn in self._open_tabs
                if had_tab:
                    tab_idx = self._find_tab_index(fn)
                    if tab_idx >= 0:
                        self.tab_widget.removeTab(tab_idx)
                    del self._open_tabs[fn]
                import gc; gc.collect()
                try:
                    os.rename(fp, cur_new_path)
                except Exception as e:
                    if had_tab:
                        self._open_record_tab(fn)
                    error_lbl.setText(f"Ошибка переименования текущей папки: {e}")
                    error_lbl.setVisible(True)
                    return
                r["folder_name"] = cur_new_name
                r["folder_path"] = cur_new_path
                fi = self.table.item(r["row_index"], COL_FOLDER)
                if fi:
                    fi.setText(cur_new_name)
                    fi.setToolTip(f"Папка: {cur_new_path}")
                for af in self.audio_folders:
                    if af["name"] == fn:
                        af["name"] = cur_new_name
                        af["path"] = cur_new_path
                        break
                self.log(f"[COPY/RENAME] «{fn}» → «{cur_new_name}»")
                actual_source_name = cur_new_name
                if had_tab:
                    self._open_record_tab(cur_new_name)

            # 2. Создать новую папку на диске
            new_path = os.path.join(parent_dir, new_name)
            try:
                os.makedirs(new_path)
            except Exception as e:
                error_lbl.setText(f"Ошибка создания папки: {e}")
                error_lbl.setVisible(True)
                return

            # 3. Создать .txt файл (копия из текущей папки если есть)
            source_r = self._find_row(actual_source_name)
            if source_r and source_r.get("txt_files"):
                src_txt = source_r["txt_files"][0]
                src_txt_path = os.path.join(source_r["folder_path"], src_txt)
                if os.path.isfile(src_txt_path):
                    try:
                        txt_content = ""
                        try:
                            with open(src_txt_path, "r", encoding="utf-8") as f:
                                txt_content = f.read()
                        except UnicodeDecodeError:
                            with open(src_txt_path, "r", encoding="cp1251") as f:
                                txt_content = f.read()
                        with open(os.path.join(new_path, f"{new_name}.txt"), "w", encoding="utf-8") as f:
                            f.write(txt_content)
                    except Exception:
                        with open(os.path.join(new_path, f"{new_name}.txt"), "w", encoding="utf-8") as f:
                            f.write("")
                else:
                    with open(os.path.join(new_path, f"{new_name}.txt"), "w", encoding="utf-8") as f:
                        f.write("")
            else:
                with open(os.path.join(new_path, f"{new_name}.txt"), "w", encoding="utf-8") as f:
                    f.write("")

            # 4. Собрать метаданные для копирования
            form_data = {
                "title": source_r["title_entry"].text().strip() if source_r else "",
                "year": source_r["year_entry"].text().strip() if source_r else "",
                "password": source_r["password_entry"].text().strip() if source_r else "",
                "forum": source_r["forum_entry"].text().strip() if source_r else "",
                "poster_url": source_r.get("poster_url", "") if source_r else "",
                "kinopoisk_url": source_r.get("kinopoisk_url", "") if source_r else "",
                "torrent_video": source_r["torrent_entry"].text().strip() if source_r else "",
                "torrent_audio": source_r.get("audio_torrent_url", "") if source_r else "",
                "sub_year": source_r["sub_year"].currentText() if source_r else "—",
                "sub_month": source_r["sub_month"].currentText() if source_r else "—",
                "delay": "0",
                "video": "",
            }

            # 5. Добавить папку в audio_folders
            folder_data = {"name": new_name, "path": new_path, "files": []}
            self.audio_folders.append(folder_data)
            self.audio_folders.sort(key=lambda x: x["name"])
            total = sum(len(f["files"]) for f in self.audio_folders)
            self.audio_count_lbl.setText(f"Папок: {len(self.audio_folders)}, аудио файлов: {total}")

            # 6. Добавить строку в таблицу
            self._add_single_row(folder_data, form_data)

            # 7. Дополнительные метаданные которые не входят в form_data
            new_r = self._find_row(new_name)
            if new_r and source_r:
                if source_r["prefix_cb"].isChecked():
                    new_r["prefix_cb"].setChecked(True)
                    new_r["prefix_entry"].setText(source_r["prefix_entry"].text())
                if source_r["suffix_cb"].isChecked():
                    new_r["suffix_cb"].setChecked(True)
                    new_r["suffix_entry"].setText(source_r["suffix_entry"].text())
                if source_r.get("custom_track_name_enabled"):
                    new_r["custom_track_name_enabled"] = True
                    new_r["custom_track_name"] = source_r.get("custom_track_name", "")
                new_r["sort_priority"] = source_r.get("sort_priority", 1)

            self.log(f"[COPY] Папка «{fn}» → «{new_name}» (настройки скопированы)")

            self._save_config()
            dlg.accept()

            # Открыть вкладку нового фильма
            self._open_record_tab(new_name)

        ok_btn.clicked.connect(_do_copy)
        dlg.exec()

    def _rmdir_with_confirm(self, fn):
        """Удалить папку фильма со всеми файлами и убрать запись из таблицы."""
        r = self._find_row(fn)
        if not r:
            return
        fp = r.get("folder_path", "")
        if not fp or not os.path.isdir(fp):
            QMessageBox.warning(self, "Папка не найдена",
                f"Папка «{fn}» не существует на диске:\n{fp}")
            return

        # Собираем список файлов с размерами
        file_entries = []
        total_size = 0
        try:
            for entry in os.scandir(fp):
                if entry.is_file():
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        sz = 0
                    total_size += sz
                    file_entries.append((entry.name, sz))
                elif entry.is_dir():
                    sub_size = 0
                    sub_count = 0
                    for root, _, files in os.walk(entry.path):
                        for f in files:
                            sub_count += 1
                            try:
                                sub_size += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
                    total_size += sub_size
                    file_entries.append((f"{entry.name}/ ({sub_count} файлов)", sub_size))
        except OSError:
            pass

        def _fmt_sz(b):
            if b >= 1024 ** 3:
                return f"{b / (1024 ** 3):.2f} ГБ"
            elif b >= 1024 ** 2:
                return f"{b / (1024 ** 2):.1f} МБ"
            elif b >= 1024:
                return f"{b / 1024:.0f} КБ"
            return f"{b} Б"

        sz_str = _fmt_sz(total_size)

        # Список файлов с размерами
        lines = []
        for name, sz in sorted(file_entries)[:20]:
            lines.append(f"  • {name}  ({_fmt_sz(sz)})")
        if len(file_entries) > 20:
            lines.append(f"  ... и ещё {len(file_entries) - 20}")

        msg = QMessageBox(self)
        msg.setWindowTitle("Удалить папку")
        # Большой красный крестик ✖ как иконка диалога
        from PySide6.QtGui import QPainter, QPixmap, QColor
        _cross_pm = QPixmap(48, 48)
        _cross_pm.fill(Qt.transparent)
        _cp = QPainter(_cross_pm)
        _cp.setPen(QColor("red"))
        _cp.setFont(QFont("Arial", 36, QFont.Bold))
        _cp.drawText(0, 0, 48, 48, Qt.AlignCenter, "✖")
        _cp.end()
        msg.setIconPixmap(_cross_pm)
        msg.setText(f"БЕЗВОЗВРАТНО удалить папку <b>{fn}</b> и все файлы?")
        msg.setInformativeText(
            f"Папка: {fn}\n"
            f"Путь: {fp}\n"
            f"Файлов: {len(file_entries)},  размер: {sz_str}\n\n"
            + "\n".join(lines)
            + "\n\nЗапись будет удалена из таблицы."
        )
        btn_del = msg.addButton("Удалить", QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("Отмена", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec()
        if msg.clickedButton() != btn_del:
            return

        try:
            shutil.rmtree(fp)
            self.log(f"[DEL] Папка удалена: {fp} ({len(file_entries)} файлов, {sz_str})")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить папку:\n{e}")
            return

        self._remove_single_row(fn)
        self._update_counts()
        self.schedule_autosave()

    def _update_archive_btn_count(self):
        """Обновить счётчики кнопок архивов (заглушка, кнопки удалены)."""
        pass

    def _unrar_all(self):
        """Распаковать архивы последовательно. Если выделены чекбоксами — только их (видимых)."""
        selected = [r for r in self.rows if r["select_cb"].isChecked() and not self.table.isRowHidden(r["row_index"])]
        pool = selected if selected else self.rows
        targets = []
        skipped_no_archive = 0
        skipped_has_audio = 0
        for r in pool:
            if not r.get("archive_file"):
                skipped_no_archive += 1; continue
            if self._has_main_audio(r):  # >= 1 ГБ, маленькие — стартовые
                skipped_has_audio += 1; continue
            targets.append(r)
        if not targets:
            reasons = []
            if skipped_no_archive:
                reasons.append(f"нет архива: {skipped_no_archive}")
            if skipped_has_audio:
                reasons.append(f"уже распаковано: {skipped_has_audio}")
            scope = "выбранных" if selected else "всех"
            self.log(f"[UNRAR] Нечего распаковывать из {scope} ({len(pool)}) — " + ", ".join(reasons) if reasons else f"[UNRAR] Нечего распаковывать")
            return
        scope_label = f"выбранных ({len(targets)})" if selected else f"{len(targets)}"
        ans = QMessageBox.question(self, "Распаковать архивы",
            f"Распаковать {scope_label} архив(ов) последовательно?")
        if ans != QMessageBox.Yes: return
        queue = []
        for r in targets:
            fn = r["folder_name"]
            archive = r["archive_file"]
            pw = r["password_entry"].text().strip()
            archive_path = os.path.join(r["folder_path"], archive)
            if not os.path.isfile(archive_path):
                continue
            r["status_lbl"].setText("В очереди...")
            r["status_lbl"].setStyleSheet("color:#8B4513; font-weight:bold;")
            r["btn_unrar"].setEnabled(False)
            queue.append((fn, archive_path, pw, r["folder_path"]))
        if not queue: return
        self.log(f"[UNRAR] Очередь: {len(queue)} архив(ов)")
        threading.Thread(target=self._unrar_all_worker, args=(queue,), daemon=True).start()

    def _unrar_all_worker(self, queue):
        """Последовательная распаковка всех архивов из очереди."""
        for i, (fn, archive_path, pw, extract_to) in enumerate(queue, 1):
            self._sig_log.emit(f"[UNRAR] ({i}/{len(queue)}) Начало: {fn}")
            self._sig_unrar_progress.emit(fn, "")
            self._unrar_worker(fn, archive_path, pw, extract_to)

    def _del_all_decoded_archives(self):
        """Удалить все архивы в папках где уже есть расшифрованные аудио файлы."""
        targets = [(r, r["archive_file"]) for r in self.rows
                   if r.get("archive_file") and r["audio_files"]]
        if not targets: return
        ans = QMessageBox.question(self, "Удалить расшифрованные архивы",
            f"Удалить {len(targets)} архив(ов) из папок где уже есть аудио файлы?")
        if ans != QMessageBox.Yes: return
        deleted = 0
        for r, archive in targets:
            path = os.path.join(r["folder_path"], archive)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    r["archive_file"] = ""
                    deleted += 1
                    self.log(f"[DEL] Архив удалён: {archive}")
            except Exception as e:
                self.log(f"[DEL] Ошибка удаления {archive}: {e}")
        self.log(f"[DEL] Удалено архивов: {deleted} из {len(targets)}")
        self._check_all_statuses()
        self._update_archive_btn_count()

    def _build_task_refs(self, r, tp, op, delete_other_audio, auto_best_track):
        """Собрать M task_refs (по одному на видео), каждый с N аудио вариантами внутри.
        Основной аудио файл — один для всех вариантов.
        Варианты отличаются только стартовыми/конечными файлами."""
        fp = r["folder_path"]
        vp = self.video_path_edit.text()
        # Основной аудио файл — один для всех
        an = self._audio_filename(r)
        af = os.path.join(fp, an) if an else ""
        if not an or not af or not os.path.isfile(af):
            return []
        # Собрать варианты стартовых/конечных (основной = вариант 1)
        audio_variants = []
        starter = self._starter_filename(r)
        starter_path = os.path.join(fp, starter) if starter and os.path.isfile(os.path.join(fp, starter)) else ""
        ender = self._ender_filename(r)
        ender_path = os.path.join(fp, ender) if ender and os.path.isfile(os.path.join(fp, ender)) else ""
        audio_variants.append({"audio_path": af, "starter_path": starter_path,
                               "ender_path": ender_path, "variant_idx": 1})
        for ev_idx, ev in enumerate(r.get("extra_audio_variants", [])):
            ev_sp = ""
            if ev.get("starter_audio"):
                _sp = os.path.join(fp, ev["starter_audio"])
                if os.path.isfile(_sp): ev_sp = _sp
            ev_ep = ""
            if ev.get("ender_audio"):
                _ep = os.path.join(fp, ev["ender_audio"])
                if os.path.isfile(_ep): ev_ep = _ep
            # Пропускаем только если это ТОЧНЫЙ дубликат уже добавленного варианта
            _combo = (ev_sp, ev_ep)
            _is_dup = any((av.get("starter_path", "") == ev_sp and av.get("ender_path", "") == ev_ep)
                          for av in audio_variants)
            if _is_dup:
                continue  # дубликат — пропускаем
            audio_variants.append({"audio_path": af, "starter_path": ev_sp,
                                   "ender_path": ev_ep, "variant_idx": ev_idx + 2})
        # Собрать видео (с per-video настройками)
        vn = r["video_combo"].currentText()
        vf = r.get("video_full_path") or (os.path.join(vp, vn) if vp and vn and vn != "— снять выбор —" else "")
        video_variants = []
        if vn and vn != "— снять выбор —" and vf and os.path.isfile(vf):
            video_variants.append({"video_path": vf, "video_name": vn, "_ev": None})
        for ev in r.get("extra_videos", []):
            ev_v = ev.get("video", "")
            ev_vfp = ev.get("video_full_path", "")
            if not ev_vfp: ev_vfp = os.path.join(vp, ev_v) if vp and ev_v else ""
            if ev_vfp and os.path.isfile(ev_vfp):
                video_variants.append({"video_path": ev_vfp, "video_name": ev_v or os.path.basename(ev_vfp), "_ev": ev})
        if not audio_variants or not video_variants:
            return []
        # Формирование M task_refs — по одному на видео, все аудио внутри
        _main_prefix = self._get_prefix(r)
        _main_suffix = self._get_suffix(r)
        _main_fps = r.get("video_fps", "авто")
        task_refs = []
        for vv in video_variants:
            ev = vv.get("_ev")
            # Per-video: если есть override в extra_video — использовать, иначе наследовать
            _prefix = (ev.get("prefix", "") if ev and ev.get("prefix_cb") else _main_prefix) if ev else _main_prefix
            _suffix = (ev.get("suffix", "") if ev and ev.get("suffix_cb") else _main_suffix) if ev else _main_suffix
            _fps = (ev.get("fps") or _main_fps) if ev else _main_fps
            video_base = os.path.splitext(vv["video_name"])[0]
            out_name = f"{_prefix}{video_base}{_suffix}.mkv"
            out_path = os.path.join(tp, out_name)
            if op and os.path.isfile(os.path.join(op, out_name)): continue
            if os.path.isfile(out_path): continue
            task_refs.append({
                "folder_name": r["folder_name"],
                "video_path": vv["video_path"],
                "video_name": vv["video_name"],
                "output_path": out_path,
                "delete_other_audio": delete_other_audio,
                "auto_best_track": auto_best_track,
                "audio_variants": audio_variants,
                "video_fps": _fps,
            })
        return task_refs

    def _process_single(self, fn):
        """Обработать одну запись по кнопке ▶."""
        r = self._find_row(fn)
        if not r: return
        mkvmerge = self.mkvmerge_path_edit.text()
        if not mkvmerge or not os.path.exists(mkvmerge):
            QMessageBox.critical(self, "Ошибка", "Укажите mkvmerge.exe"); return
        tp = self.test_path_edit.text()
        if not tp or not os.path.isdir(tp):
            QMessageBox.critical(self, "Ошибка", "Укажите папку тест"); return
        op = self.output_path_edit.text()
        an = self._audio_filename(r); vn = r["video_combo"].currentText()
        on = r["output_entry"].text()
        if not an or not vn or vn == "— снять выбор —" or not on:
            QMessageBox.information(self, "Инфо", "Не заполнены поля"); return
        # Флаги всегда из единой батч-панели
        delete_other_audio = self.batch_del_audio_cb.isChecked()
        auto_best_track = self.batch_best_track_cb.isChecked()
        task_refs = self._build_task_refs(r, tp, op, delete_other_audio, auto_best_track)
        if not task_refs:
            QMessageBox.information(self, "Инфо", "Нет заданий для обработки\n(файлы не найдены или уже обработаны)"); return
        # Проверка ограничений мультивыбора
        n_audio = len(task_refs[0].get("audio_variants", [])) if task_refs else 1
        n_video = len(task_refs)
        n_delays = len(r.get("delays", [{"value": "0"}]))
        n_tracks_per_file = n_audio * n_delays
        if n_video > 25:
            QMessageBox.warning(self, "Слишком много файлов",
                                f"{n_video} видео файлов.\nМаксимум 25."); return
        if n_video > 5:
            ans = QMessageBox.question(self, "Много файлов",
                                       f"{n_video} видео файлов, в каждом {n_tracks_per_file} дорожек.\nПродолжить?",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes: return
        _log_extra = ""
        if n_video > 1 or n_audio > 1:
            _log_extra = f" ({n_video} файлов × {n_tracks_per_file} дорожек: {n_audio} вар. × {n_delays} зад.)"
        self.log(f"=== ОБРАБОТКА: {r['folder_name']}{_log_extra} ===")
        self._save_config()
        threading.Thread(target=self._process_tasks, args=(task_refs, mkvmerge), daemon=True).start()

    def _process_tasks(self, task_refs, mkvmerge):
        """Рабочий поток обработки (использует сигналы для доступа к UI).
        Каждый task_ref — один выходной файл (видео), содержащий ВСЕ аудио варианты × задержки."""
        import time as _time
        total = len(task_refs)
        batch_start = _time.monotonic()
        for i, ref in enumerate(task_refs):
            cur = i + 1; name = os.path.basename(ref["output_path"])
            self._sig_log.emit(f"[{cur}/{total}] {name}")
            # Чтение UI-данных из главного потока
            self._read_result = {}
            self._read_event.clear()
            self._pending_read_fn = ref["folder_name"]
            self._sig_read_ui.emit()
            self._read_event.wait()
            delay = self._read_result.get("delay", "0")
            track_name = self._read_result.get("track_name", "ATMOS")
            delays = self._read_result.get("delays", [{"value": delay, "confirmed": False}])
            selected_tids = self._read_result.get("selected_audio_tracks")
            no_audio_flag = "--no-audio " if ref.get("delete_other_audio") else ""
            audio_variants = ref.get("audio_variants", [])
            # Авто-сканирование (по первому варианту)
            if selected_tids is None and ref.get("auto_best_track") and audio_variants:
                tracks = self._scan_audio_tracks(audio_variants[0]["audio_path"])
                if len(tracks) > 1:
                    best = self._auto_select_best_track(tracks)
                    selected_tids = [best]
            # Фильтр аудио дорожек
            if selected_tids and len(selected_tids) > 0:
                tids_str = ",".join(str(t) for t in sorted(selected_tids))
                audio_filter = f"--audio-tracks {tids_str} "
            else:
                audio_filter = ""
                selected_tids = None
            tids_to_flag = sorted(selected_tids) if selected_tids else [0]
            n_sel_tracks = len(tids_to_flag)
            is_multi_variant = len(audio_variants) > 1
            is_multi_delay = len(delays) > 1
            # Формирование блоков аудио: вариант × задержка × дорожка
            all_audio_blocks = []
            global_block_idx = 0  # для default-track-flag: только первый блок = yes
            for av in audio_variants:
                v_idx = av["variant_idx"]
                for idx_d, d in enumerate(delays):
                    _raw_d = d.get("value", "0")
                    # Явно передавать знак в mkvmerge: "500" → "+500", "-500" → "-500", "0" → "0"
                    try:
                        _d_int = int(_raw_d)
                        d_val = f"+{_d_int}" if _d_int > 0 else str(_d_int)
                    except (ValueError, TypeError):
                        d_val = _raw_d
                    # Формирование имени дорожки: v{N}_{delay}_{track_name}[_{seq}]
                    name_parts = []
                    if is_multi_variant:
                        name_parts.append(f"v{v_idx}")
                    if is_multi_delay or is_multi_variant:
                        name_parts.append(str(d_val))
                    name_parts.append(track_name)
                    t_name = "_".join(name_parts)
                    # Per-track флаги
                    per_track_flags = ""
                    for ti, tid in enumerate(tids_to_flag):
                        dflag = "yes" if (global_block_idx == 0 and ti == 0) else "no"
                        t_name_full = f"{t_name}_{ti + 1}" if n_sel_tracks > 1 else t_name
                        per_track_flags += f'--language {tid}:und --track-name "{tid}:{t_name_full}" --sync "{tid}:{d_val}" --default-track-flag {tid}:{dflag} '
                    block = f'{audio_filter}{per_track_flags}"{av["audio_path"]}"'
                    # Стартовый файл — prepend (+)
                    starter_path = av.get("starter_path", "")
                    if starter_path:
                        starter_flags = ""
                        for ti, tid in enumerate(tids_to_flag):
                            dflag = "yes" if (global_block_idx == 0 and ti == 0) else "no"
                            t_name_full = f"{t_name}_{ti + 1}" if n_sel_tracks > 1 else t_name
                            starter_flags += f'--language {tid}:und --track-name "{tid}:{t_name_full}" --sync "{tid}:0" --default-track-flag {tid}:{dflag} '
                        starter_block = f'{audio_filter}{starter_flags}"{starter_path}"'
                        block = f'{starter_block} + {block}'
                    # Конечный файл — append (+)
                    ender_path = av.get("ender_path", "")
                    if ender_path:
                        ender_flags = ""
                        for ti, tid in enumerate(tids_to_flag):
                            dflag = "no"
                            t_name_full = f"{t_name}_{ti + 1}" if n_sel_tracks > 1 else t_name
                            ender_flags += f'--language {tid}:und --track-name "{tid}:{t_name_full}" --sync "{tid}:0" --default-track-flag {tid}:{dflag} '
                        ender_block = f'{audio_filter}{ender_flags}"{ender_path}"'
                        block = f'{block} + {ender_block}'
                    all_audio_blocks.append(block)
                    global_block_idx += 1
            audio_cmd = " ".join(all_audio_blocks)
            # Логирование
            _n_tracks = len(all_audio_blocks)
            _av_log = f" | Аудио вариантов: {len(audio_variants)}" if is_multi_variant else ""
            _tid_log = f" | Аудио дорожки: {','.join(str(t) for t in tids_to_flag)}" if selected_tids else ""
            self._sig_log.emit(f"  Задержки: {len(delays)} | Дорожек: {_n_tracks} | Удалить аудио оригинала: {'Да' if no_audio_flag else 'Нет'} | Имя: {track_name}{_av_log}{_tid_log}")
            # Лог размеров входных файлов
            _sz_parts = [f"Видео: {_format_file_size_gb(ref['video_path']) or 'н/д'}"]
            for av in audio_variants:
                _av_sz = _format_file_size_gb(av['audio_path']) or 'н/д'
                _av_lbl = f"Аудио v{av['variant_idx']}" if is_multi_variant else "Аудио"
                _sz_parts.append(f"{_av_lbl}: {_av_sz}")
                if av.get("starter_path"):
                    _sz_parts.append(f"Старт v{av['variant_idx']}: {_format_file_size_gb(av['starter_path']) or 'н/д'}")
                if av.get("ender_path"):
                    _sz_parts.append(f"Конец v{av['variant_idx']}: {_format_file_size_gb(av['ender_path']) or 'н/д'}")
            self._sig_log.emit(f"  Размеры: {' | '.join(_sz_parts)}")
            # FPS видео (--default-duration)
            _fps_val = ref.get("video_fps", "авто")
            _fps_flag = f'--default-duration 0:{_fps_val}fps ' if _fps_val and _fps_val != "авто" else ""
            if _fps_flag:
                self._sig_log.emit(f"  FPS: {_fps_val} (--default-duration 0:{_fps_val}fps)")
            # Лог полной команды
            _mkvmerge_cmd = f'"{mkvmerge}" -o "{ref["output_path"]}" {audio_cmd} {no_audio_flag}{_fps_flag}"{ref["video_path"]}"'
            self._sig_log.emit(f"  CMD: {_mkvmerge_cmd}")
            ps = f'''
$ErrorActionPreference="Continue"
try{{$k=Add-Type -MemberDefinition '[DllImport("kernel32.dll")]public static extern IntPtr GetStdHandle(int h);[DllImport("kernel32.dll")]public static extern bool GetConsoleMode(IntPtr h,out uint m);[DllImport("kernel32.dll")]public static extern bool SetConsoleMode(IntPtr h,uint m);' -Name K -Namespace QE -PassThru;$h=$k::GetStdHandle(-10);$m=0;$null=$k::GetConsoleMode($h,[ref]$m);$null=$k::SetConsoleMode($h,($m -band (-bnot 0x0040)) -bor 0x0080)}}catch{{}}
Write-Host "=== Файл {cur}/{total}: {name} ({_n_tracks} дорожек) ===" -ForegroundColor Yellow
& "{mkvmerge}" -o "{ref["output_path"]}" {audio_cmd} {no_audio_flag}{_fps_flag}"{ref["video_path"]}"
if($LASTEXITCODE -eq 0){{Write-Host "OK" -ForegroundColor Green}}
elseif($LASTEXITCODE -eq 1){{Write-Host "WARN" -ForegroundColor Yellow}}
else{{Write-Host "ERROR $LASTEXITCODE" -ForegroundColor Red; Read-Host}}
'''
            file_start = _time.monotonic()
            _MKVMERGE_TIMEOUT = 7200
            try:
                p = subprocess.Popen(["powershell", "-Command", ps], creationflags=subprocess.CREATE_NEW_CONSOLE)
                try:
                    p.wait(timeout=_MKVMERGE_TIMEOUT)
                except subprocess.TimeoutExpired:
                    self._sig_log.emit(f"  [TIMEOUT] mkvmerge не завершился за {_MKVMERGE_TIMEOUT // 60} мин — принудительное завершение")
                    p.kill()
                    try: p.wait(timeout=30)
                    except: pass
                    code = -1
                else:
                    code = p.returncode
                elapsed = _time.monotonic() - file_start
                mins, secs = divmod(int(elapsed), 60)
                if code == -1:
                    self._sig_log.emit(f"  [TIMEOUT] — {mins}м {secs}с")
                else:
                    self._sig_log.emit(f"  [{'OK' if code==0 else 'WARN' if code==1 else f'ERR:{code}'}] — {mins}м {secs}с")
                    if code in (0, 1):
                        self._sig_set_date.emit(ref["folder_name"], datetime.now().strftime("%d.%m.%y %H:%M:%S"))
                        self._sig_file_done.emit(ref["folder_name"])
            except Exception as e:
                self._sig_log.emit(f"  [ERR] {e}")
        batch_elapsed = _time.monotonic() - batch_start
        bm, bs = divmod(int(batch_elapsed), 60)
        if total > 1:
            self._sig_log.emit(f"=== ГОТОВО: {total} файлов за {bm}м {bs}с ===")
        else:
            self._sig_log.emit(f"=== ГОТОВО за {bm}м {bs}с ===")
        self._sig_processing_done.emit()

    # ──────────────────────────────────
    #  Утилиты
    # ──────────────────────────────────
    def log(self, msg):
        ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")

    def _presort_audio_folders(self):
        """Предсортировка audio_folders по данным конфига до построения таблицы.
        Если порядок совпадёт с результатом _sort_table, _visual_sort не будет вызван."""
        mappings = self.config.get("mappings", [])
        if not mappings:
            return
        m_map = {m.get("folder", ""): m for m in mappings}
        col = self.sort_column
        rev = self.sort_reverse

        def sort_key(af):
            name = af["name"]
            m = m_map.get(name, {})
            is_new = m.get("is_new", False)
            sp = m.get("sort_priority", 1)
            # Группы: NEW=0, В тесте=1, остальные=2
            group = 0 if is_new else (1 if sp == -1 else 2)
            # Значение сортировки внутри группы
            if col == "folder":
                val = name.lower()
            elif col == "title":
                val = m.get("title", "").lower()
            elif col == "year":
                try:
                    val = int(m.get("year", "0") or "0")
                except (ValueError, TypeError):
                    val = 0
            elif col == "status":
                val = sp
            elif col == "date":
                val = m.get("processed_date", "") or ""
            elif col == "date_created":
                val = m.get("folder_created", "") or ""
            elif col == "delay":
                try:
                    val = int(m.get("delay", "0") or "0")
                except (ValueError, TypeError):
                    val = 0
            elif col == "output":
                val = m.get("output", "").lower()
            elif col == "suffix":
                val = m.get("custom_suffix", "").lower() if m.get("custom_suffix_enabled") else ""
            else:
                val = name.lower()
            # Пустые значения — в конец группы 2
            is_empty = False
            if group == 2 and col:
                if col in ("title", "output", "suffix"):
                    is_empty = not val
                elif col == "year":
                    is_empty = val == 0
                elif col == "date":
                    is_empty = not val
                elif col == "date_created":
                    is_empty = not val
            # Подгруппа: непустые=0, пустые=1
            sub = 1 if is_empty else 0
            return (group, sub, val)

        self.audio_folders.sort(key=sort_key, reverse=False)
        # Обратный порядок только для непустых значений внутри группы 2
        if rev and col:
            # Перегруппировать: group 0, group 1 — без изменений; group 2 sub 0 — reverse, sub 1 — без
            g0 = [af for af in self.audio_folders if sort_key(af)[0] == 0]
            g1 = [af for af in self.audio_folders if sort_key(af)[0] == 1]
            g2_normal = [af for af in self.audio_folders if sort_key(af)[0] == 2 and sort_key(af)[1] == 0]
            g2_empty = [af for af in self.audio_folders if sort_key(af)[0] == 2 and sort_key(af)[1] == 1]
            g2_normal.sort(key=sort_key, reverse=True)
            self.audio_folders = g0 + g1 + g2_normal + g2_empty

    def _deferred_status_check(self):
        """Отложенная проверка статусов с I/O — запускается после отрисовки окна."""
        self.setUpdatesEnabled(False)
        for r in self.rows:
            # Вычислить длительность видео если не сохранена
            if not r["video_dur_lbl"].text() and r.get("video_full_path"):
                vfp = r["video_full_path"]
                if os.path.isfile(vfp):
                    dur_text = self._get_video_duration(vfp)
                    r["video_dur_lbl"].setText(dur_text)
            self._check_row_status(r)
            # Показать NEW только если _check_row_status НЕ сбросил is_new
            # (is_new сбрасывается при статусах К обработке, Готово, В тесте)
            if r.get("is_new"):
                r["status_lbl"].setText("✦ NEW")
                r["status_lbl"].setStyleSheet(f"color:#006600; font-weight:bold; background-color:{COLOR_NEW};")
                r["status_lbl"].setToolTip(self._STATUS_TOOLTIPS.get("✦ NEW", ""))
                self._set_row_bg(r, COLOR_NEW)
                # Синхронизировать NEW статус на вкладку
                fn = r["folder_name"]
                if fn in self._open_tabs:
                    slbl = self._open_tabs[fn]["widgets"].get("status_lbl")
                    if slbl:
                        slbl.setText("✦ NEW")
                        slbl.setStyleSheet(self._status_text_style("✦ NEW"))
        # Обновить продолжительность на открытых вкладках
        for fn, tab_info in self._open_tabs.items():
            r = self._find_row(fn)
            if not r:
                continue
            tw = tab_info["widgets"]
            tab_dur = tw.get("video_dur_lbl")
            if tab_dur:
                tab_dur.setText(r["video_dur_lbl"].text())
            tab_pending = tw.get("video_pending_btn")
            if tab_pending:
                _has_video = bool(r.get("video_full_path"))
                tab_pending.setVisible(not _has_video)
                if r.get("video_pending"):
                    tab_pending.setText("⌛")
                    tab_pending.setStyleSheet("color:#8e44ad; font-weight:bold;")
                else:
                    tab_pending.setText("⏳")
                    tab_pending.setStyleSheet("")
        self.setUpdatesEnabled(True)
        self._update_archive_btn_count()
        self._update_batch_buttons()
        self._update_process_button()
        # Активировать кнопку «Сбросить NEW» если есть NEW записи
        if any(r.get("is_new") for r in self.rows):
            self._update_reset_new_btn()
        self._update_status_filter_counts()
        # Убедиться что колонки влезают в окно (actions мог расшириться)
        QTimer.singleShot(0, self._ensure_columns_fit)
        self.log("Статусы обновлены (фоновая проверка)")

    def _initial_load(self):
        # Показать лейбл загрузки вместо таблицы (QStackedWidget, index 1)
        self._table_stack.setCurrentIndex(1)
        self._loading_label.setText("Загрузка...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            self._scan_audio_silent()
            self._scan_video_silent()
            # Предсортировка audio_folders по конфигу — чтобы _sort_table
            # в _restore_mappings не вызвал _visual_sort (лишнюю перестановку)
            self._presort_audio_folders()
            # Построение таблицы БЕЗ проверки статусов (I/O не нужен)
            self._build_table(skip_status_check=True)
            self.setUpdatesEnabled(False)
            self._restore_mappings()
            self.setUpdatesEnabled(True)
            self._update_counts()
            # Восстановить скрытые колонки из конфига
            for col_idx in self.config.get("hidden_columns", []):
                if 0 <= col_idx < NUM_COLS:
                    self.table.setColumnHidden(col_idx, True)
                    if col_idx < len(self._col_checkboxes) and self._col_checkboxes[col_idx]:
                        self._col_checkboxes[col_idx].blockSignals(True)
                        self._col_checkboxes[col_idx].setChecked(False)
                        self._col_checkboxes[col_idx].blockSignals(False)
            # Восстановить ширины колонок из конфига
            saved_widths = self.config.get("column_widths", [])
            if len(saved_widths) == NUM_COLS:
                for i, w in enumerate(saved_widths):
                    if w > 0:
                        self.table.setColumnWidth(i, w)
            # Восстановить порядок колонок
            saved_order = self.config.get("column_order", [])
            if len(saved_order) == NUM_COLS:
                hdr = self.table.horizontalHeader()
                hdr.blockSignals(True)
                for logical_idx in range(NUM_COLS):
                    target_visual = saved_order[logical_idx]
                    current_visual = hdr.visualIndex(logical_idx)
                    if current_visual != target_visual:
                        hdr.moveSection(current_visual, target_visual)
                hdr.blockSignals(False)
            # Восстановить открытые вкладки (с блокировкой перерисовки + CBT-хук)
            saved_tabs = self.config.get("open_tabs", [])
            if saved_tabs:
                self.setUpdatesEnabled(False)
                _unhook = self._install_anti_flash_hook()
                try:
                    for tab_fn in saved_tabs:
                        rr = self._find_row(tab_fn)
                        if rr:
                            try:
                                self._create_record_tab(tab_fn, rr)
                            except Exception:
                                pass
                finally:
                    _unhook()
                    self.setUpdatesEnabled(True)
        except Exception as e:
            self.log(f"Ошибка загрузки: {e}")
            import traceback; self.log(traceback.format_exc())
        finally:
            self._loading = False  # Разрешить autosave
            # Показать таблицу вместо лейбла загрузки (QStackedWidget, index 0)
            self._table_stack.setCurrentIndex(0)
            # Отложенная проверка статусов с I/O — ПОСЛЕ отрисовки окна
            QTimer.singleShot(100, self._deferred_status_check)


# ═══════════════════════════════════════════════
#  Глобальный фильтр: блокировка колёсика мыши для всех QComboBox
# ═══════════════════════════════════════════════
class _ComboWheelBlocker(QObject):
    """Блокирует прокрутку колёсиком мыши во всех QComboBox.
    Предотвращает случайную смену выбора при скролле страницы."""
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, QComboBox):
            event.ignore()
            return True
        return False


# ═══════════════════════════════════════════════
#  Точка входа
# ═══════════════════════════════════════════════
def main():
    # Консоль уже скрыта в начале файла до импортов

    # --no-save: запуск в режиме только чтение (autosave отключён)
    _readonly = "--no-save" in sys.argv
    _argv = [a for a in sys.argv if a != "--no-save"]

    app = QApplication(_argv)
    app.setStyle("Fusion")
    f = app.font(); f.setPointSize(9); app.setFont(f)

    # Блокировка колёсика мыши для всех комбобоксов
    _wheel_blocker = _ComboWheelBlocker(app)
    app.installEventFilter(_wheel_blocker)

    # Подавить системные диалоги Windows при обращении к несуществующим дискам
    # (B:/, F:/, G:/ и т.д.) — они мелькают как маленькие окна при запуске
    try:
        import ctypes
        _SEM_FAILCRITICALERRORS = 0x0001
        _SEM_NOOPENFILEERRORBOX = 0x8000
        ctypes.windll.kernel32.SetErrorMode(_SEM_FAILCRITICALERRORS | _SEM_NOOPENFILEERRORBOX)
    except Exception:
        pass

    try:
        window = MKVMergeApp(readonly=_readonly)
        # Показать окно с лейблом "Загрузка...", потом грузить данные
        window.show(); window.raise_(); window.activateWindow()
        QApplication.processEvents()
        window._initial_load()
        sys.exit(app.exec())
    except Exception as e:
        import traceback; err = traceback.format_exc(); print(f"\n[v2] ОШИБКА:\n{err}")
        log_path = os.path.join(_SCRIPT_DIR, "crash_log.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as fh: fh.write(err)
        except Exception: pass
        try: QMessageBox.critical(None, "Ошибка", f"{e}\n\n{log_path}")
        except Exception: pass
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback; traceback.print_exc()
        input("\n--- Нажми Enter ---")