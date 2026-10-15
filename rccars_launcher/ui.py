from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QRunnable, QThreadPool, QObject, Signal, QSize, Slot, QTimer
from PySide6.QtGui import QIcon, QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressDialog, QPushButton,
    QScrollArea, QSlider, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QStyle, QSizePolicy, QLayout,
)

from . import services
from .modmanager import (
    ModRecord, apply_mods, import_mod_archives, normalize_order, save_mod_settings,
    scan_mods,
)

APP_VERSION = "0.1.4"

RU = {
    "Home": "Главная", "Instances": "Копии игры", "Game Settings": "Настройки игры",
    "Game Setup": "Подготовка игры", "Graphics": "Графика и фикс", "Mod Manager": "Менеджер модов", "Tools": "Инструменты",
    "Settings & Updates": "Настройки и обновления", "RC Cars Launcher": "Лаунчер RC Cars",
    "Select instance": "Выбрать копию", "Launch Game": "Запустить игру", "Refresh": "Обновить",
    "No game instance selected": "Копия игры не выбрана", "Active game copy": "Активная копия игры",
    "Add Instance": "Добавить копию", "Edit": "Изменить", "Remove": "Удалить",
    "Set Active": "Сделать активной", "Name": "Название", "Game folder": "Папка игры",
    "Store": "Источник", "Icon": "Иконка", "Browse…": "Обзор…", "Select game folder": "Выбрать папку игры",
    "Select icon": "Выбрать иконку", "Cancel": "Отмена", "Save": "Сохранить", "Add": "Добавить",
    "Folder": "Папка", "Steam": "Steam", "Standalone": "Отдельная копия", "Detected status": "Состояние",
    "Pack archive": "Архив Pack", "WidescreenFix": "WidescreenFix", "ASI Loader": "ASI Loader",
    "Large Address Aware": "Large Address Aware", "Unpacked": "Распакован", "Packed": "Упакован",
    "Not detected": "Не обнаружен", "Installed": "Установлен", "Not installed": "Не установлен",
    "Unknown": "Не определено", "Quick status": "Состояние копии", "Open game folder": "Открыть папку игры",
    "Install WidescreenFix (GitHub)": "Установить WidescreenFix (GitHub)",
    "Install ASI Loader (GitHub)": "Установить ASI Loader (GitHub)",
    "Install WidescreenFix + ASI Loader": "Установить / обновить WidescreenFix + ASI Loader",
    "Installing / updating WidescreenFix + ASI Loader": "Установка / обновление WidescreenFix + ASI Loader",
    "Extract RCCars.pack into game root": "Распаковать RCCars.pack в корень игры",
    "This extracts all packed files directly into the game root. After successful extraction, RCCars.pack is renamed to _RCCars.pack so the game uses loose files while the original archive stays in place.": "Все файлы будут извлечены прямо в корень игры. После распаковки RCCars.pack переименовывается в _RCCars.pack: оригинал остаётся на месте, а игра использует распакованные файлы.",
    "Game configuration": "Настройки игры", "Fog": "Туман", "Gamma changes": "Изменение гаммы",
    "Play intro video": "Проигрывать вступительный ролик", "Language in game (registry)": "Язык игры (реестр)",
    "Apply game settings": "Применить настройки игры", "RCCars.crs is patched only if it exists. The launcher backs it up before modifying it.": "RCCars.crs изменяется только при наличии файла. Перед изменением лаунчер создаёт резервную копию.",
    "Resolution": "Разрешение", "Fix FOV automatically": "Автоматически корректировать FOV",
    "Custom FOV": "Пользовательский FOV", "Fix HUD": "Исправление HUD", "Legacy HUD fix": "Legacy-исправление HUD",
    "FPS limit (0 = monitor refresh rate)": "Лимит FPS (0 = частота монитора)", "Prevent minimize on focus loss": "Не сворачивать игру при потере фокуса",
    "Save graphics settings": "Сохранить настройки графики", "Settings are written to RCCars_WidescreenFix.ini. Resolution is also patched in RCCars.crs when the file exists.": "Настройки записываются в RCCars_WidescreenFix.ini. Если существует RCCars.crs, разрешение также меняется в нём.",
    "Enable Large Address Aware in RCCars.exe": "Включить Large Address Aware для RCCars.exe",
    "Restore original Steam EXE": "Восстановить оригинальный EXE Steam",
    "LAA patch unavailable for Steam": "LAA отключён для Steam-версии",
    "Core game actions": "Основные действия с игрой",
    "Pack is already unpacked": "Pack уже распакован",
    "The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first.": "Менеджер модов доступен только после распаковки RCCars.pack. Сначала распакуйте Pack на главной странице.",
    "This sets the PE Large Address Aware flag and keeps a backup of the original EXE. On 64-bit Windows, this allows a 32-bit process to use more than 2 GB of virtual address space.": "Устанавливает флаг Large Address Aware в PE-заголовке и сохраняет исходный EXE. В 64-битной Windows это позволяет 32-битному процессу использовать более 2 ГБ виртуального адресного пространства.",
    "Mods folder": "Папка модов", "Add archive(s)…": "Добавить архив(ы)…", "Remove archive": "Удалить архив",
    "Move up": "Выше", "Move down": "Ниже", "Apply enabled mods": "Применить включённые моды",
    "Open Mods folder": "Открыть папку Mods", "Enabled": "Включён", "Archive": "Архив",
    "Type": "Тип", "Order": "Порядок", "Later mods override files from earlier mods. Archives must contain game-relative paths, e.g. Textures1/file.dds.": "Поздние моды перекрывают одноимённые файлы ранних. Внутри архива должны быть пути относительно игры, например Textures1/file.dds.",
    "Add tools by copying .exe, .py, .bat, .cmd or .ps1 files into the Tools folder beside the launcher.": "Добавляйте инструменты, копируя файлы .exe, .py, .bat, .cmd или .ps1 в папку Tools рядом с лаунчером.",
    "Run selected tool": "Запустить выбранный инструмент", "Open Tools folder": "Открыть папку Tools",
    "Refresh list": "Обновить список", "Launch with -dev argument": "Запускать игру с аргументом -dev",
    "Set launcher language": "Язык лаунчера", "English": "Английский", "Russian": "Русский",
    "Drag ZIP/7z archives here to add mods": "Перетащите сюда архивы ZIP/7z, чтобы добавить моды",
    "Check for launcher updates": "Проверить обновления лаунчера", "Install latest WidescreenFix": "Установить последнюю версию WidescreenFix",
    "GitHub repository for launcher releases": "GitHub-репозиторий релизов лаунчера", "Edit social links file": "Изменить файл ссылок на соцсети",
    "Open application data folder": "Открыть папку данных лаунчера", "About": "О программе",
    "Add your social links to social_links.json beside the launcher EXE. This file is intentionally separate so it can be customized without editing Python code.": "Добавьте ссылки на соцсети в social_links.json рядом с EXE лаунчера. Этот файл можно менять без редактирования Python-кода.",
    "No instance": "Нет копии игры", "Choose a valid game folder containing RCCars.exe.": "Выберите папку игры, в которой находится RCCars.exe.",
    "Select a game instance first.": "Сначала выберите копию игры.", "Warning": "Предупреждение", "Error": "Ошибка",
    "Success": "Готово", "Confirm": "Подтвердить", "Remove this instance from the list? The game files will not be deleted.": "Удалить копию из списка? Файлы игры не будут удалены.",
    "This will extract files into the game directory and rename RCCars.pack to _RCCars.pack. Existing loose files will be backed up first. Continue?": "Файлы будут извлечены в каталог игры, а RCCars.pack переименован в _RCCars.pack. Перед заменой существующие файлы будут сохранены. Продолжить?",
    "This will update RCCars.crs and Config.gm, and set the game-language registry value. Continue?": "Будут изменены RCCars.crs и Config.gm, а также параметр языка игры в реестре. Продолжить?",
    "Version": "Версия", "Latest release": "Последний релиз", "Release page": "Страница релиза",
    "Launcher update repository isn't configured. Edit launcher_config.json and set launcher_update_repo to owner/repository.": "Репозиторий обновлений лаунчера не задан. Откройте launcher_config.json и укажите launcher_update_repo в формате owner/repository.",
    "Already enabled": "Уже включено", "This executable already has the Large Address Aware flag.": "В этом EXE уже установлен флаг Large Address Aware.",
    "The selected game copy is missing RCCars.pack.": "В выбранной копии отсутствует RCCars.pack.", "There are no mod archives in Mods yet.": "В папке Mods пока нет архивов модов.",
    "Select one or more ZIP/7z mod archives": "Выберите один или несколько архивов модов ZIP/7z", "Mod archives (*.zip *.7z);;All files (*.*)": "Архивы модов (*.zip *.7z);;Все файлы (*.*)",
    "The mod archive will be removed from the Mods folder. Continue?": "Архив мода будет удалён из папки Mods. Продолжить?",
    "Select a tool": "Выберите инструмент", "Python scripts require Python to be installed on the system when the launcher is packaged as EXE.": "Для запуска Python-скриптов при использовании EXE лаунчера в системе должен быть установлен Python.",
    "Game is running": "Игра запущена", "Game process started.": "Игра запущена.", "Original files and settings backups are stored under the launcher application-data directory.": "Резервные копии файлов и настроек хранятся в каталоге данных лаунчера.",
    "Could not find a compiled WidescreenFix .asi in the latest GitHub release.": "В последнем релизе GitHub не найден скомпилированный WidescreenFix .asi.",
    "Installed": "Установлено", "Settings saved.": "Настройки сохранены.", "Files": "Файлы", "Ready": "Готово",
}


def qss() -> str:
    return """
    QWidget { background: #11151c; color: #e5eaf2; font-family: 'Segoe UI', 'Arial'; font-size: 10pt; }
    QMainWindow { background: #11151c; }
    QLabel#Title { font-size: 19pt; font-weight: 700; color: #f7f9fc; }
    QLabel#Subtitle { color: #9ba8bb; font-size: 9pt; }
    QLabel#SectionTitle { font-size: 15pt; font-weight: 650; color: #f0f4fb; }
    QLabel#Muted { color: #97a3b6; }
    QLabel#StatusValue { font-size: 12pt; font-weight: 650; }
    QFrame#Header { background: #171d27; border-bottom: 1px solid #283140; }
    QFrame#Sidebar { background: #151a23; border-right: 1px solid #283140; }
    QFrame#Card { background: #191f2b; border: 1px solid #283447; border-radius: 10px; }
    QFrame#Panel { background: #171d27; border: 1px solid #283447; border-radius: 10px; }
    QPushButton { background: #252e3d; border: 1px solid #354258; border-radius: 7px; padding: 9px 13px; color: #e5eaf2; }
    QPushButton:hover { background: #303c4f; border-color: #536680; }
    QPushButton:pressed { background: #202a38; }
    QPushButton:disabled { color: #778294; background: #202630; border-color: #29303b; }
    QPushButton#Primary { background: #d45a35; color: white; border: 1px solid #ee7956; font-weight: 700; }
    QPushButton#Primary:hover { background: #eb6842; }
    QPushButton#Nav { background: transparent; text-align: left; border: none; border-radius: 7px; padding: 12px 13px; color: #b9c4d4; }
    QPushButton#Nav:hover { background: #202936; color: #f0f4fb; }
    QPushButton#Nav:checked { background: #2a3444; color: #ffb29c; border: 1px solid #414e62; }
    QLineEdit, QComboBox, QSpinBox { background: #10151d; border: 1px solid #354258; border-radius: 6px; padding: 7px 8px; min-height: 18px; selection-background-color: #a7472c; }
    QComboBox::drop-down { border: 0; width: 24px; }
    QComboBox QAbstractItemView { background: #1a202a; selection-background-color: #35435a; border: 1px solid #354258; }
    QCheckBox { spacing: 8px; }
    QCheckBox::indicator { width: 17px; height: 17px; }
    QCheckBox::indicator:unchecked { background: #10151d; border: 1px solid #536077; border-radius: 4px; }
    QCheckBox::indicator:checked { background: #d45a35; border: 1px solid #ee7956; border-radius: 4px; }
    QSlider::groove:horizontal { height: 5px; background: #303a4a; border-radius: 2px; }
    QSlider::handle:horizontal { background: #f07853; width: 15px; margin: -6px 0; border-radius: 7px; }
    QTableWidget { background: #151b24; alternate-background-color: #191f2a; border: 1px solid #2e394a; border-radius: 8px; gridline-color: #263141; selection-background-color: #344259; selection-color: #fff; }
    QHeaderView::section { background: #222a37; color: #b8c4d5; border: none; border-bottom: 1px solid #354258; padding: 8px; font-weight: 600; }
    QGroupBox { border: 1px solid #2e394a; border-radius: 8px; margin-top: 12px; padding: 12px 10px 9px 10px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #c5cfde; }
    QProgressDialog { background: #171d27; }
    QToolTip { background: #202938; color: #f6f8fc; border: 1px solid #44536a; padding: 4px; }
    QScrollArea#PageScrollArea { border: none; }
    QScrollBar:vertical { background: #151b24; width: 12px; margin: 2px 1px 2px 1px; border-radius: 5px; }
    QScrollBar::handle:vertical { background: #46546b; min-height: 28px; border-radius: 5px; }
    QScrollBar::handle:vertical:hover { background: #60738f; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    """


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)


class TaskWorker(QRunnable):
    def __init__(self, function: Callable[[Callable[[int, str], None]], Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function(lambda value, message="": self.signals.progress.emit(int(value), str(message)))
            self.signals.succeeded.emit(result)
        except Exception as exc:
            self.signals.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


class TaskRelay(QObject):
    """Receives worker signals on the GUI thread and performs UI updates safely."""
    def __init__(self, window: "LauncherWindow", worker: TaskWorker, dialog: QProgressDialog, on_success: Callable[[Any], None]):
        super().__init__(window)
        self.window = window
        self.worker = worker
        self.dialog = dialog
        self.callback = on_success

    @Slot(int, str)
    def on_progress(self, value: int, message: str) -> None:
        self.dialog.setValue(max(0, min(100, value)))
        if message:
            self.dialog.setLabelText(message)

    @Slot(object)
    def on_success_result(self, result: Any) -> None:
        self.window._workers.discard(self.worker)
        self.window._task_dialogs.discard(self.dialog)
        self.window._relays.discard(self)
        self.dialog.close()
        try:
            self.callback(result)
        except Exception as exc:
            QMessageBox.critical(self.window, self.window.t("Error"), str(exc))
        self.window.refresh_everything()
        self.deleteLater()

    @Slot(str)
    def on_failure(self, message: str) -> None:
        self.window._workers.discard(self.worker)
        self.window._task_dialogs.discard(self.dialog)
        self.window._relays.discard(self)
        self.dialog.close()
        short = message.split("\n\n", 1)[0]
        QMessageBox.critical(self.window, self.window.t("Error"), f"{short}\n\nFull details were available in the task output.")
        self.window.refresh_everything()
        self.deleteLater()


class InstanceDialog(QDialog):
    def __init__(self, parent: QWidget, instance: Optional[dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle(parent.t("Edit") if instance else parent.t("Add Instance"))
        self.setMinimumWidth(580)
        self.setStyleSheet(qss())
        self.instance = instance or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(str(self.instance.get("name", "")))
        self.path_edit = QLineEdit(str(self.instance.get("path", "")))
        self.icon_edit = QLineEdit(str(self.instance.get("icon", "")))
        folder_row = QHBoxLayout(); folder_row.addWidget(self.path_edit, 1)
        browse_folder = QPushButton(parent.t("Browse…")); browse_folder.clicked.connect(self.pick_folder); folder_row.addWidget(browse_folder)
        icon_row = QHBoxLayout(); icon_row.addWidget(self.icon_edit, 1)
        browse_icon = QPushButton(parent.t("Browse…")); browse_icon.clicked.connect(self.pick_icon); icon_row.addWidget(browse_icon)
        form.addRow(parent.t("Name"), self.name_edit)
        form.addRow(parent.t("Game folder"), folder_row)
        form.addRow(parent.t("Icon (optional)"), icon_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(parent.t("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(parent.t("Cancel"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select game folder", self.path_edit.text() or str(Path.home()))
        if folder:
            self.path_edit.setText(folder)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(folder).name)

    def pick_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select icon", str(Path.home()), "Images and icons (*.ico *.png *.jpg *.jpeg *.bmp);;All files (*.*)")
        if path:
            self.icon_edit.setText(path)

    def values(self) -> dict[str, str]:
        return {"name": self.name_edit.text().strip(), "path": self.path_edit.text().strip(), "icon": self.icon_edit.text().strip()}


class _ArchiveDropMixin:
    """Shared drag-and-drop handling for the mod page and archive table."""

    def _dropped_archive_paths(self, mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in {".zip", ".7z"}:
                paths.append(str(path))
        return paths

    def dragEnterEvent(self, event) -> None:
        if self.isEnabled() and self._dropped_archive_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self.isEnabled() and self._dropped_archive_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = self._dropped_archive_paths(event.mimeData())
        if self.isEnabled() and paths:
            self.archivesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class ModArchiveDropPage(QWidget, _ArchiveDropMixin):
    archivesDropped = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        _ArchiveDropMixin.dragEnterEvent(self, event)

    def dragMoveEvent(self, event) -> None:
        _ArchiveDropMixin.dragMoveEvent(self, event)

    def dropEvent(self, event) -> None:
        _ArchiveDropMixin.dropEvent(self, event)


class ModArchiveDropTable(QTableWidget, _ArchiveDropMixin):
    archivesDropped = Signal(list)

    def __init__(self, rows: int, columns: int, parent: Optional[QWidget] = None):
        super().__init__(rows, columns, parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def dragEnterEvent(self, event) -> None:
        _ArchiveDropMixin.dragEnterEvent(self, event)

    def dragMoveEvent(self, event) -> None:
        _ArchiveDropMixin.dragMoveEvent(self, event)

    def dropEvent(self, event) -> None:
        _ArchiveDropMixin.dropEvent(self, event)


class LauncherWindow(QMainWindow):
    NAV_KEYS = ["Home", "Instances", "Game Settings", "Mod Manager", "Tools", "Settings & Updates"]
    NAV_SYMBOLS = {"Home": "⌂", "Instances": "▣", "Game Settings": "◐", "Mod Manager": "▤", "Tools": "⌘", "Settings & Updates": "↻"}

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RC Cars Launcher {APP_VERSION}")
        self.setMinimumSize(960, 620)
        self.resize(1180, 780)
        self.setStyleSheet(qss())
        self.pool = QThreadPool.globalInstance()
        self._workers: set[TaskWorker] = set()
        self._task_dialogs: set[QProgressDialog] = set()
        self.app_dir = services.runtime_dir()
        self.data_dir = services.user_data_dir()
        try:
            services.migrate_legacy_user_data(self.data_dir)
        except OSError:
            # The portable data directory remains the configured destination; errors
            # will be surfaced if a later operation actually needs the inaccessible files.
            pass
        self.prefs_file = self.data_dir / "launcher.json"
        self.prefs = services.read_json(self.prefs_file, {"instances": [], "active_instance_id": "", "language": "en", "dev_mode": False})
        self.prefs.setdefault("instances", [])
        self.prefs.setdefault("language", "en")
        self.prefs.setdefault("active_instance_id", "")
        self.prefs.setdefault("dev_mode", False)
        self.app_config_path = self.app_dir / "launcher_config.json"
        if not self.app_config_path.exists():
            services.write_json(self.app_config_path, {
                "launcher_update_repo": "",
                "homepage_url": "https://github.com/Aeralise/RCCars_WidescreenFix",
            })
        self.app_config = services.read_json(self.app_config_path, {"launcher_update_repo": ""})
        self.social_links_path = self.app_dir / "social_links.json"
        if not self.social_links_path.exists():
            services.write_json(self.social_links_path, {"links": [
                {"label": "WidescreenFix GitHub", "url": "https://github.com/Aeralise/RCCars_WidescreenFix"},
                {"label": "ASI Loader GitHub", "url": "https://github.com/ThirteenAG/Ultimate-ASI-Loader"},
            ]})
        self.current_page_key = "Home"
        self.active_instance_id = self.prefs.get("active_instance_id", "")
        self.instances = list(self.prefs.get("instances", []))
        self._graphics_instance_id: Optional[str] = None
        self.widgets: dict[str, Any] = {}
        self.mod_records: list[ModRecord] = []
        self.mod_state: dict[str, Any] = {}
        self._relays: set[TaskRelay] = set()
        self._build_ui()
        self._sync_active_combo()
        # Show the window before doing filesystem scans and instance detection.
        # The one-directory build below also avoids PyInstaller one-file extraction at startup.
        QTimer.singleShot(120, self.refresh_startup_state)

    def t(self, text: str) -> str:
        if self.prefs.get("language", "en") == "ru":
            return RU.get(text, text)
        return text

    def save_prefs(self) -> None:
        self.prefs["instances"] = self.instances
        self.prefs["active_instance_id"] = self.active_instance_id
        services.write_json(self.prefs_file, self.prefs)

    def current_instance(self) -> Optional[dict[str, Any]]:
        return next((item for item in self.instances if item.get("id") == self.active_instance_id), None)

    def current_root(self) -> Optional[Path]:
        item = self.current_instance()
        if not item:
            return None
        return Path(item["path"]).expanduser()

    def current_backup_root(self) -> Optional[Path]:
        item = self.current_instance()
        if not item:
            return None
        path = self.data_dir / "backups" / str(item["id"])
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_launcher_icon(self) -> QIcon:
        """Load the optional custom icon from bundled resources or beside the launcher."""
        roots: list[Path] = []
        bundled_dir = getattr(sys, "_MEIPASS", None)
        if bundled_dir:
            roots.append(Path(bundled_dir))
        roots.append(self.app_dir)
        roots.append(self.app_dir / "assets")
        for folder in roots:
            for name in ("launcher_icon.ico", "launcher_icon.png", "launcher_icon.jpg", "launcher_icon.jpeg"):
                candidate = folder / name
                if candidate.is_file():
                    icon = QIcon(str(candidate))
                    if not icon.isNull():
                        return icon
        return QIcon()

    def _build_ui(self) -> None:
        self.widgets = {}
        self.pages = {}
        old = self.centralWidget()
        if old:
            self.setCentralWidget(QWidget())
            old.deleteLater()
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame(); header.setObjectName("Header")
        header_layout = QHBoxLayout(header); header_layout.setContentsMargins(22, 14, 22, 14)
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(42, 42)
        launcher_icon = self._resolve_launcher_icon()
        if not launcher_icon.isNull():
            logo.setPixmap(launcher_icon.pixmap(QSize(42, 42)))
            logo.setStyleSheet("background:transparent;")
            self.setWindowIcon(launcher_icon)
        else:
            # Do not show the old orange placeholder; use a neutral system icon
            # until launcher_icon.ico is supplied in the project root.
            logo.setPixmap(self.style().standardIcon(QStyle.SP_ComputerIcon).pixmap(QSize(42, 42)))
            logo.setStyleSheet("background:transparent;")
        brand_box = QVBoxLayout(); brand_box.setSpacing(1)
        brand = QLabel(self.t("RC Cars Launcher")); brand.setObjectName("Title")
        subtitle = QLabel(f"Community mod manager  ·  v{APP_VERSION}"); subtitle.setObjectName("Subtitle")
        brand_box.addWidget(brand); brand_box.addWidget(subtitle)
        header_layout.addWidget(logo); header_layout.addSpacing(10); header_layout.addLayout(brand_box)
        header_layout.addStretch(1)
        header_layout.addWidget(QLabel(self.t("Active game copy")))
        self.active_combo = QComboBox(); self.active_combo.setMinimumWidth(220); self.active_combo.currentIndexChanged.connect(self._active_combo_changed)
        header_layout.addWidget(self.active_combo)
        refresh_btn = QPushButton(self.t("Refresh")); refresh_btn.clicked.connect(self.refresh_everything)
        header_layout.addWidget(refresh_btn)
        self.launch_btn = QPushButton(self.t("Launch Game")); self.launch_btn.setObjectName("Primary"); self.launch_btn.clicked.connect(self.launch_active_game)
        header_layout.addWidget(self.launch_btn)
        root_layout.addWidget(header)

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar); sidebar_layout.setContentsMargins(12, 18, 12, 14); sidebar_layout.setSpacing(5)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key in self.NAV_KEYS:
            btn = QPushButton(f"{self.NAV_SYMBOLS[key]}    {self.t(key)}")
            btn.setObjectName("Nav"); btn.setCheckable(True); btn.clicked.connect(lambda checked=False, k=key: self.show_page(k))
            sidebar_layout.addWidget(btn); self.nav_buttons[key] = btn
        sidebar_layout.addStretch(1)
        note = QLabel("RC Cars (2003)\nModding toolkit")
        note.setObjectName("Muted"); note.setWordWrap(True); note.setContentsMargins(8, 10, 8, 0)
        sidebar_layout.addWidget(note)
        body.addWidget(sidebar)

        self.stack = QStackedWidget(); self.stack.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.stack, 1)
        root_layout.addLayout(body, 1)
        self.setCentralWidget(central)

        self._build_home_page()
        self._build_instances_page()
        self._build_game_settings_page()
        self._build_mods_page()
        self._build_tools_page()
        self._build_settings_page()
        self.show_page(self.current_page_key)

    def _scroll_page(self) -> tuple[QScrollArea, QVBoxLayout]:
        """Create a page with a vertical scrollbar instead of compressing its contents."""
        scroll = QScrollArea()
        scroll.setObjectName("PageScrollArea")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(26, 24, 26, 24)
        outer.setSpacing(18)
        outer.setSizeConstraint(QLayout.SetMinimumSize)
        scroll.setWidget(content)
        return scroll, outer

    def _heading(self, layout: QVBoxLayout, title: str, subtitle: str = "") -> None:
        title_label = QLabel(self.t(title)); title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        if subtitle:
            sub = QLabel(self.t(subtitle)); sub.setObjectName("Muted"); sub.setWordWrap(True)
            layout.addWidget(sub)

    def _panel(self, title: Optional[str] = None) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame(); panel.setObjectName("Panel")
        layout = QVBoxLayout(panel); layout.setContentsMargins(17, 15, 17, 15); layout.setSpacing(12)
        if title:
            label = QLabel(self.t(title)); label.setStyleSheet("font-weight:650;color:#f0f4fb;font-size:11pt;")
            layout.addWidget(label)
        return panel, layout

    def _status_card(self, title: str, key: str, icon: str) -> QFrame:
        frame = QFrame(); frame.setObjectName("Card")
        layout = QVBoxLayout(frame); layout.setContentsMargins(15, 14, 15, 14); layout.setSpacing(5)
        row = QHBoxLayout(); row.addWidget(QLabel(icon)); title_label = QLabel(self.t(title)); title_label.setObjectName("Muted"); row.addWidget(title_label); row.addStretch(1)
        layout.addLayout(row)
        value = QLabel("—"); value.setObjectName("StatusValue"); layout.addWidget(value)
        self.widgets[key] = value
        return frame

    def _build_home_page(self) -> None:
        page, layout = self._scroll_page()
        self._heading(layout, "Home", "Manage separate RC Cars installations, install fixes, configure graphics, and control update-folder mods.")
        selected_panel, selected_layout = self._panel("Active game copy")
        top = QHBoxLayout()
        self.widgets["home_instance_name"] = QLabel(self.t("No instance")); self.widgets["home_instance_name"].setStyleSheet("font-size:15pt;font-weight:700;")
        self.widgets["home_instance_path"] = QLabel(self.t("Select a game instance first.")); self.widgets["home_instance_path"].setObjectName("Muted"); self.widgets["home_instance_path"].setWordWrap(True)
        text_col = QVBoxLayout(); text_col.addWidget(self.widgets["home_instance_name"]); text_col.addWidget(self.widgets["home_instance_path"])
        top.addLayout(text_col, 1)
        open_btn = QPushButton(self.t("Open game folder")); open_btn.clicked.connect(self.open_game_folder)
        top.addWidget(open_btn)
        selected_layout.addLayout(top)
        layout.addWidget(selected_panel)
        grid = QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        grid.addWidget(self._status_card("Pack archive", "home_pack", "▦"), 0, 0)
        grid.addWidget(self._status_card("WidescreenFix", "home_wsf", "◫"), 0, 1)
        grid.addWidget(self._status_card("ASI Loader", "home_loader", "↪"), 0, 2)
        grid.addWidget(self._status_card("Large Address Aware", "home_laa", "▣"), 1, 0)
        grid.addWidget(self._status_card("Store", "home_store", "▤"), 1, 1)
        grid.addWidget(self._status_card("Graphics INI", "home_ini", "⚙"), 1, 2)
        layout.addLayout(grid)
        actions_panel, actions_layout = self._panel("Core game actions")
        actions_row = QHBoxLayout()
        self.pack_btn = QPushButton(self.t("Extract RCCars.pack into game root"))
        self.pack_btn.setObjectName("Primary")
        self.pack_btn.clicked.connect(self.extract_pack)
        self.install_components_home_btn = QPushButton(self.t("Install WidescreenFix + ASI Loader"))
        self.install_components_home_btn.setObjectName("Primary")
        self.install_components_home_btn.clicked.connect(self.install_compatibility)
        self.laa_btn = QPushButton(self.t("Enable Large Address Aware in RCCars.exe"))
        self.laa_btn.clicked.connect(self.enable_laa)
        actions_row.addWidget(self.pack_btn, 1)
        actions_row.addWidget(self.install_components_home_btn, 1)
        actions_row.addWidget(self.laa_btn, 1)
        actions_layout.addLayout(actions_row)
        pack_hint = QLabel(self.t("This extracts all packed files directly into the game root. After successful extraction, RCCars.pack is renamed to _RCCars.pack so the game uses loose files while the original archive stays in place."))
        pack_hint.setWordWrap(True); pack_hint.setObjectName("Muted")
        actions_layout.addWidget(pack_hint)
        laa_hint = QLabel(self.t("Standalone copies can be patched for LAA. Steam-managed executables are intentionally not modified because Steam may reject them."))
        laa_hint.setWordWrap(True); laa_hint.setObjectName("Muted")
        actions_layout.addWidget(laa_hint)
        layout.addWidget(actions_panel)
        links_panel, links_layout = self._panel("Community links")
        self.social_links_layout = QHBoxLayout(); self.social_links_layout.addStretch(1)
        links_layout.addLayout(self.social_links_layout)
        layout.addWidget(links_panel)
        layout.addStretch(1)
        self.stack.addWidget(page)
        self.pages = getattr(self, "pages", {})
        self.pages["Home"] = page

    def _build_instances_page(self) -> None:
        page, layout = self._scroll_page()
        self._heading(layout, "Instances", "Keep multiple clean, modded, Steam, or test installations in one launcher profile.")
        panel, box = self._panel("Registered game copies")
        self.instance_table = QTableWidget(0, 4)
        self.instance_table.setHorizontalHeaderLabels([self.t("Name"), self.t("Game folder"), self.t("Store"), self.t("Pack")])
        self.instance_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.instance_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.instance_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.instance_table.setAlternatingRowColors(True)
        self.instance_table.verticalHeader().setVisible(False)
        self.instance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.instance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.instance_table.itemDoubleClicked.connect(self._activate_table_instance)
        box.addWidget(self.instance_table, 1)
        row = QHBoxLayout()
        for label, callback in [("Add Instance", self.add_instance), ("Edit", self.edit_instance), ("Remove", self.remove_instance), ("Set Active", self.set_active_from_table)]:
            btn = QPushButton(self.t(label)); btn.clicked.connect(callback)
            if label == "Set Active": btn.setObjectName("Primary")
            row.addWidget(btn)
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(panel, 1)
        self.stack.addWidget(page); self.pages["Instances"] = page

    def _build_game_settings_page(self) -> None:
        page, layout = self._scroll_page()
        self._heading(layout, "Game Settings", "Configure graphics fixes and the game configuration stored in Config.gm, RCCars.crs, and the Windows registry.")
        panel, box = self._panel("Display and aspect ratio")
        form = QFormLayout()
        self.resolution_combo = QComboBox(); self.resolution_combo.setMinimumWidth(240)
        for width, height in services.available_resolutions():
            self.resolution_combo.addItem(f"{width} × {height}", (width, height))
        self.custom_resolution = QCheckBox("Custom resolution")
        self.custom_resolution.setToolTip("Enable this checkbox only to enter a non-listed width and height manually.")
        self.width_spin = QSpinBox(); self.width_spin.setRange(320, 16384); self.width_spin.setValue(1920)
        self.height_spin = QSpinBox(); self.height_spin.setRange(240, 16384); self.height_spin.setValue(1080)
        res_widget = QWidget(); res_layout = QVBoxLayout(res_widget); res_layout.setContentsMargins(0, 0, 0, 0); res_layout.setSpacing(8)
        res_layout.addWidget(self.resolution_combo)
        customrow = QHBoxLayout(); customrow.addWidget(self.custom_resolution); customrow.addWidget(QLabel("W")); customrow.addWidget(self.width_spin); customrow.addWidget(QLabel("H")); customrow.addWidget(self.height_spin); customrow.addStretch(1)
        res_layout.addLayout(customrow)
        self.custom_resolution.toggled.connect(self._toggle_custom_resolution)
        self.resolution_combo.currentIndexChanged.connect(self._resolution_changed)
        form.addRow(self.t("Resolution"), res_widget)
        box.addLayout(form)
        layout.addWidget(panel)

        panel, box = self._panel("FOV and HUD")
        self.fix_fov = QCheckBox(self.t("Fix FOV automatically")); self.fix_fov.setChecked(True)
        fovrow = QHBoxLayout(); fovrow.addWidget(self.fix_fov); fovrow.addStretch(1); fovrow.addWidget(QLabel(self.t("Custom FOV")))
        self.fov_slider = QSlider(Qt.Horizontal); self.fov_slider.setRange(1, 120); self.fov_slider.setValue(80); self.fov_slider.setMinimumWidth(230)
        self.fov_spin = QSpinBox(); self.fov_spin.setRange(1, 120); self.fov_spin.setValue(80)
        self.fov_slider.valueChanged.connect(self.fov_spin.setValue); self.fov_spin.valueChanged.connect(self.fov_slider.setValue)
        fovrow.addWidget(self.fov_slider); fovrow.addWidget(self.fov_spin)
        self.fix_fov.toggled.connect(lambda on: (self.fov_slider.setEnabled(not on), self.fov_spin.setEnabled(not on)))
        box.addLayout(fovrow)
        self.fix_hud = QCheckBox(self.t("Fix HUD")); self.fix_hud.setChecked(True)
        self.legacy_fix_hud = QCheckBox(self.t("Legacy HUD fix")); self.legacy_fix_hud.setChecked(True)
        row = QHBoxLayout(); row.addWidget(self.fix_hud); row.addWidget(self.legacy_fix_hud); row.addStretch(1); box.addLayout(row)
        layout.addWidget(panel)

        panel, box = self._panel("Performance and window behavior")
        fpsrow = QHBoxLayout(); fpsrow.addWidget(QLabel(self.t("FPS limit (0 = monitor refresh rate)")))
        self.fps_spin = QSpinBox(); self.fps_spin.setRange(0, 600); self.fps_spin.setValue(0); fpsrow.addWidget(self.fps_spin); fpsrow.addStretch(1); box.addLayout(fpsrow)
        self.no_minimize = QCheckBox(self.t("Prevent minimize on focus loss")); box.addWidget(self.no_minimize)
        save_btn = QPushButton(self.t("Save graphics settings")); save_btn.setObjectName("Primary"); save_btn.clicked.connect(self.save_graphics_settings)
        box.addWidget(save_btn, 0, Qt.AlignLeft)
        layout.addWidget(panel)
        note = QLabel(self.t("Settings are written to RCCars_WidescreenFix.ini. Resolution is also patched in RCCars.crs when the file exists.")); note.setObjectName("Muted"); note.setWordWrap(True); layout.addWidget(note)

        cfg_panel, cfg_layout = self._panel("Game configuration")
        self.cfg_fog = QCheckBox(self.t("Fog"))
        self.cfg_gamma = QCheckBox(self.t("Gamma changes"))
        self.cfg_intro = QCheckBox(self.t("Play intro video"))
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(self.cfg_fog); cfg_row.addWidget(self.cfg_gamma); cfg_row.addWidget(self.cfg_intro); cfg_row.addStretch(1)
        cfg_layout.addLayout(cfg_row)
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(self.t("Language in game (registry)")))
        self.game_language_combo = QComboBox()
        self.game_language_combo.addItems(["English", "Russian", "Polish"])
        lang_row.addWidget(self.game_language_combo); lang_row.addStretch(1)
        cfg_layout.addLayout(lang_row)
        crs_note = QLabel(self.t("RCCars.crs is patched only if it exists. The launcher backs it up before modifying it."))
        crs_note.setObjectName("Muted"); crs_note.setWordWrap(True); cfg_layout.addWidget(crs_note)
        self.apply_game_cfg_btn = QPushButton(self.t("Apply game settings"))
        self.apply_game_cfg_btn.setObjectName("Primary")
        self.apply_game_cfg_btn.clicked.connect(self.apply_game_settings)
        cfg_layout.addWidget(self.apply_game_cfg_btn, 0, Qt.AlignLeft)
        layout.addWidget(cfg_panel)

        layout.addStretch(1)
        self.stack.addWidget(page); self.pages["Game Settings"] = page

    def _build_mods_page(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("PageScrollArea")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        page = ModArchiveDropPage()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(page); layout.setContentsMargins(26, 24, 26, 24); layout.setSpacing(18)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        page.archivesDropped.connect(self.handle_dropped_mod_archives)
        scroll.setWidget(page)
        self._heading(layout, "Mod Manager", "Manage file-replacement mods via Ultimate ASI Loader's update/ overlay.")
        note = QLabel(self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first.") + "\n" + self.t("Later mods override files from earlier mods. Archives must contain game-relative paths, e.g. Textures1/file.dds.")); note.setObjectName("Muted"); note.setWordWrap(True); layout.addWidget(note)
        drop_hint = QLabel(self.t("Drag ZIP/7z archives here to add mods")); drop_hint.setObjectName("Muted"); drop_hint.setAlignment(Qt.AlignCenter); layout.addWidget(drop_hint)
        panel, box = self._panel("Mods folder")
        self.mods_table = ModArchiveDropTable(0, 4)
        self.mods_table.archivesDropped.connect(self.handle_dropped_mod_archives)
        self.mods_table.setHorizontalHeaderLabels([self.t("Enabled"), self.t("Archive"), self.t("Type"), self.t("Order")])
        self.mods_table.verticalHeader().setVisible(False); self.mods_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.mods_table.setSelectionMode(QAbstractItemView.SingleSelection); self.mods_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.mods_table.setAlternatingRowColors(True)
        self.mods_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.mods_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch); self.mods_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents); self.mods_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        box.addWidget(self.mods_table, 1)
        actions = QHBoxLayout()
        self.add_mods_btn = QPushButton(self.t("Add archive(s)…")); self.add_mods_btn.clicked.connect(self.add_mod_archives)
        self.remove_mod_btn = QPushButton(self.t("Remove archive")); self.remove_mod_btn.clicked.connect(self.remove_mod_archive)
        self.mod_up_btn = QPushButton(self.t("Move up")); self.mod_up_btn.clicked.connect(lambda: self.move_mod(-1))
        self.mod_down_btn = QPushButton(self.t("Move down")); self.mod_down_btn.clicked.connect(lambda: self.move_mod(1))
        self.open_mods_btn = QPushButton(self.t("Open Mods folder")); self.open_mods_btn.clicked.connect(self.open_mods_folder)
        actions.addWidget(self.add_mods_btn); actions.addWidget(self.remove_mod_btn); actions.addWidget(self.mod_up_btn); actions.addWidget(self.mod_down_btn); actions.addStretch(1); actions.addWidget(self.open_mods_btn)
        box.addLayout(actions)
        apply_btn = QPushButton(self.t("Apply enabled mods")); apply_btn.setObjectName("Primary"); apply_btn.clicked.connect(self.apply_mods)
        box.addWidget(apply_btn, 0, Qt.AlignLeft)
        layout.addWidget(panel, 1)
        self.stack.addWidget(scroll); self.pages["Mod Manager"] = scroll

    def _build_tools_page(self) -> None:
        page, layout = self._scroll_page()
        self._heading(layout, "Tools", "Run local modding utilities from a dedicated folder beside the launcher.")
        panel, box = self._panel("Local tools")
        note = QLabel(self.t("Add tools by copying .exe, .py, .bat, .cmd or .ps1 files into the Tools folder beside the launcher.")); note.setObjectName("Muted"); note.setWordWrap(True); box.addWidget(note)
        self.dev_checkbox = QCheckBox(self.t("Launch with -dev argument")); self.dev_checkbox.setChecked(bool(self.prefs.get("dev_mode", False))); self.dev_checkbox.toggled.connect(self._save_dev_mode)
        box.addWidget(self.dev_checkbox)
        self.tools_table = QTableWidget(0, 2); self.tools_table.setHorizontalHeaderLabels([self.t("Name"), self.t("Type")]); self.tools_table.verticalHeader().setVisible(False); self.tools_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.tools_table.setSelectionMode(QAbstractItemView.SingleSelection); self.tools_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.tools_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.tools_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tools_table.itemDoubleClicked.connect(lambda *_: self.run_selected_tool())
        box.addWidget(self.tools_table, 1)
        row = QHBoxLayout()
        run_btn = QPushButton(self.t("Run selected tool")); run_btn.setObjectName("Primary"); run_btn.clicked.connect(self.run_selected_tool)
        open_btn = QPushButton(self.t("Open Tools folder")); open_btn.clicked.connect(self.open_tools_folder)
        refresh_btn = QPushButton(self.t("Refresh list")); refresh_btn.clicked.connect(self.refresh_tools)
        row.addWidget(run_btn); row.addWidget(open_btn); row.addWidget(refresh_btn); row.addStretch(1); box.addLayout(row)
        layout.addWidget(panel, 1)
        self.stack.addWidget(page); self.pages["Tools"] = page

    def _build_settings_page(self) -> None:
        page, layout = self._scroll_page()
        self._heading(layout, "Settings & Updates", "Launcher preferences, GitHub release checks, and customizable social links.")
        panel, box = self._panel("Launcher language")
        row = QHBoxLayout(); row.addWidget(QLabel(self.t("Set launcher language")))
        self.launcher_language_combo = QComboBox(); self.launcher_language_combo.addItem(self.t("English"), "en"); self.launcher_language_combo.addItem(self.t("Russian"), "ru")
        idx = self.launcher_language_combo.findData(self.prefs.get("language", "en")); self.launcher_language_combo.setCurrentIndex(max(0, idx)); row.addWidget(self.launcher_language_combo)
        self.launcher_language_combo.currentIndexChanged.connect(lambda _index: self.apply_launcher_language())
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(panel)

        panel, box = self._panel("Launcher self-update")
        self.update_repo_edit = QLineEdit(str(self.app_config.get("launcher_update_repo", "")))
        form = QFormLayout(); form.addRow(self.t("GitHub repository for launcher releases"), self.update_repo_edit); box.addLayout(form)
        row = QHBoxLayout(); save_repo_btn = QPushButton(self.t("Save")); save_repo_btn.clicked.connect(self.save_launcher_repo)
        check_update_btn = QPushButton(self.t("Check for launcher updates")); check_update_btn.setObjectName("Primary"); check_update_btn.clicked.connect(self.check_launcher_updates)
        row.addWidget(save_repo_btn); row.addWidget(check_update_btn); row.addStretch(1); box.addLayout(row)
        layout.addWidget(panel)

        panel, box = self._panel("Social links")
        note = QLabel(self.t("Add your social links to social_links.json beside the launcher EXE. This file is intentionally separate so it can be customized without editing Python code.")); note.setWordWrap(True); note.setObjectName("Muted"); box.addWidget(note)
        edit_links_btn = QPushButton(self.t("Edit social links file")); edit_links_btn.clicked.connect(self.open_social_links)
        open_data_btn = QPushButton(self.t("Open application data folder")); open_data_btn.clicked.connect(self.open_data_folder)
        row = QHBoxLayout(); row.addWidget(edit_links_btn); row.addWidget(open_data_btn); row.addStretch(1); box.addLayout(row)
        layout.addWidget(panel)
        panel, box = self._panel("About")
        info = QLabel(f"RC Cars Launcher {APP_VERSION}\n{self.t('Original files and settings backups are stored under the launcher application-data directory.')}\n\n{self.app_dir}\n\n{self.data_dir}")
        info.setObjectName("Muted"); info.setWordWrap(True); box.addWidget(info)
        layout.addWidget(panel)
        layout.addStretch(1)
        self.stack.addWidget(page); self.pages["Settings & Updates"] = page

    def show_page(self, key: str) -> None:
        if key == "Mod Manager" and hasattr(self, "pages") and not self._mods_available():
            key = "Home"
        self.current_page_key = key
        if key in getattr(self, "pages", {}):
            self.stack.setCurrentWidget(self.pages[key])
        for name, btn in getattr(self, "nav_buttons", {}).items():
            btn.setChecked(name == key)
        if key == "Instances": self.refresh_instances_table()
        if key == "Mod Manager": self.refresh_mods_table()
        if key == "Tools": self.refresh_tools()
        if key == "Game Settings":
            self.load_game_settings()
            self.load_graphics_settings()

    def _sync_active_combo(self) -> None:
        if not hasattr(self, "active_combo"):
            return
        self.active_combo.blockSignals(True)
        self.active_combo.clear()
        for instance in self.instances:
            self.active_combo.addItem(instance.get("name", "RC Cars"), instance.get("id"))
        index = self.active_combo.findData(self.active_instance_id)
        if index < 0 and self.instances:
            index = 0
            self.active_instance_id = self.active_combo.itemData(index)
        self.active_combo.setCurrentIndex(index)
        self.active_combo.setEnabled(bool(self.instances))
        self.active_combo.blockSignals(False)
        self.save_prefs()

    def _active_combo_changed(self, index: int) -> None:
        if index < 0:
            self.active_instance_id = ""
        else:
            self.active_instance_id = str(self.active_combo.itemData(index) or "")
        self.save_prefs()
        self.refresh_everything()

    def _get_required_instance(self, feature: str = "") -> Optional[tuple[dict[str, Any], Path, Path]]:
        instance = self.current_instance()
        if not instance:
            QMessageBox.warning(self, self.t("Warning"), self.t("Select a game instance first."))
            return None
        root = Path(instance["path"]).expanduser()
        backup = self.current_backup_root()
        assert backup is not None
        if feature in ("exe", "launch"):
            try:
                services.locate_game_exe(root)
            except FileNotFoundError as exc:
                QMessageBox.warning(self, self.t("Warning"), str(exc))
                return None
        return instance, root, backup

    def refresh_startup_state(self) -> None:
        """Refresh only visible/essential data on startup; other tabs load on demand."""
        self._sync_active_combo()
        self.refresh_instances_table()
        self.refresh_home_status()
        self.refresh_mod_access()
        self.refresh_social_links()

    def refresh_everything(self) -> None:
        self._sync_active_combo()
        self.refresh_instances_table()
        self.refresh_tools()
        self.refresh_home_status()
        self.refresh_mod_access()
        self.refresh_mods_table()
        self.load_game_settings()
        self.load_graphics_settings()
        self.refresh_social_links()

    def refresh_home_status(self) -> None:
        instance = self.current_instance()
        root = self.current_root()
        if not instance or root is None:
            self.widgets["home_instance_name"].setText(self.t("No instance"))
            self.widgets["home_instance_path"].setText(self.t("Select a game instance first."))
            for key in ("home_pack", "home_wsf", "home_loader", "home_laa", "home_store", "home_ini"):
                self.widgets[key].setText("—")
            self.launch_btn.setEnabled(False)
            self.pack_btn.setEnabled(False); self.pack_btn.setText(self.t("Extract RCCars.pack into game root"))
            self.laa_btn.setEnabled(False)
            self.laa_btn.setText(self.t("Enable Large Address Aware in RCCars.exe"))
            return
        details = services.detect_instance(root)
        self.widgets["home_instance_name"].setText(instance.get("name", root.name))
        self.widgets["home_instance_path"].setText(str(root))
        self.widgets["home_pack"].setText(self.t({"packed": "Packed", "unpacked": "Unpacked", "unknown": "Unknown"}[details["pack_status"]]))
        self.widgets["home_wsf"].setText(self.t("Installed") if details["widescreen_fix"] else self.t("Not installed"))
        self.widgets["home_loader"].setText(self.t("Installed") if details["asi_loader"] else self.t("Not installed"))
        self.widgets["home_laa"].setText(self.t("Enabled") if details["large_address_aware"] else self.t("Not detected"))
        self.widgets["home_store"].setText(self.t("Steam") if details["steam"] else self.t("Standalone"))
        self.widgets["home_ini"].setText(self.t("Present") if details["ini_file"] else self.t("Not detected"))
        self.launch_btn.setEnabled(details["valid_exe"])
        if details["pack_status"] == "unpacked":
            self.pack_btn.setText(self.t("Pack is already unpacked"))
            self.pack_btn.setEnabled(False)
        else:
            self.pack_btn.setText(self.t("Extract RCCars.pack into game root"))
            self.pack_btn.setEnabled(details["pack_file"])
        if details["steam"]:
            backup_root = self.data_dir / "backups" / str(instance["id"])
            try:
                relative_exe = Path(details["exe"]).resolve().relative_to(root.resolve())
                has_exe_backup = (backup_root / relative_exe).is_file()
            except (ValueError, OSError):
                has_exe_backup = False
            if details["large_address_aware"] and has_exe_backup:
                self.laa_btn.setText(self.t("Restore original Steam EXE"))
                self.laa_btn.setEnabled(True)
            else:
                self.laa_btn.setText(self.t("LAA patch unavailable for Steam"))
                self.laa_btn.setEnabled(False)
        else:
            self.laa_btn.setText(self.t("Enable Large Address Aware in RCCars.exe"))
            self.laa_btn.setEnabled(details["valid_exe"] and not details["large_address_aware"])

    def _mods_available(self) -> bool:
        root = self.current_root()
        if root is None:
            return False
        try:
            return services.detect_instance(root)["pack_status"] == "unpacked"
        except OSError:
            return False

    def refresh_mod_access(self) -> None:
        if not hasattr(self, "nav_buttons") or "Mod Manager" not in self.nav_buttons:
            return
        available = self._mods_available()
        button = self.nav_buttons["Mod Manager"]
        button.setEnabled(available)
        button.setToolTip("" if available else self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first."))
        page = self.pages.get("Mod Manager")
        if page is not None:
            page.setEnabled(available)
        if not available and self.current_page_key == "Mod Manager":
            self.show_page("Home")

    def refresh_instances_table(self) -> None:
        if not hasattr(self, "instance_table"):
            return
        self.instance_table.setRowCount(0)
        for instance in self.instances:
            row = self.instance_table.rowCount(); self.instance_table.insertRow(row)
            name_item = QTableWidgetItem(instance.get("name", "RC Cars"))
            icon_path = instance.get("icon", "")
            if icon_path and Path(icon_path).is_file():
                name_item.setIcon(QIcon(icon_path))
            else:
                name_item.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
            name_item.setData(Qt.UserRole, instance.get("id"))
            self.instance_table.setItem(row, 0, name_item)
            self.instance_table.setItem(row, 1, QTableWidgetItem(instance.get("path", "")))
            try:
                instance_details = services.detect_instance(Path(instance["path"]))
                steam = bool(instance_details["steam"])
                pack_status = instance_details["pack_status"]
            except Exception:
                steam = False
                pack_status = "unknown"
            store_item = QTableWidgetItem(self.t("Steam") if steam else self.t("Standalone"))
            if instance.get("id") == self.active_instance_id:
                store_item.setText("● " + store_item.text())
            self.instance_table.setItem(row, 2, store_item)
            pack_label = {"packed": self.t("Packed"), "unpacked": self.t("Unpacked"), "unknown": self.t("Unknown")}[pack_status]
            self.instance_table.setItem(row, 3, QTableWidgetItem(pack_label))

    def add_instance(self) -> None:
        dialog = InstanceDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values["path"]:
            QMessageBox.warning(self, self.t("Warning"), self.t("Choose a valid game folder containing RCCars.exe.")); return
        path = Path(values["path"]).expanduser()
        try:
            services.locate_game_exe(path)
        except FileNotFoundError:
            QMessageBox.warning(self, self.t("Warning"), self.t("Choose a valid game folder containing RCCars.exe.")); return
        instance = services.new_instance(values["name"] or path.name, path, values["icon"])
        self.instances.append(instance)
        if not self.active_instance_id:
            self.active_instance_id = instance["id"]
        self.save_prefs(); self._sync_active_combo(); self.refresh_everything()

    def _selected_table_instance(self) -> Optional[dict[str, Any]]:
        row = self.instance_table.currentRow()
        if row < 0:
            return None
        item = self.instance_table.item(row, 0)
        if not item:
            return None
        instance_id = item.data(Qt.UserRole)
        return next((x for x in self.instances if x.get("id") == instance_id), None)

    def edit_instance(self) -> None:
        instance = self._selected_table_instance()
        if not instance:
            return
        dialog = InstanceDialog(self, instance)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        path = Path(values["path"]).expanduser()
        try:
            services.locate_game_exe(path)
        except FileNotFoundError:
            QMessageBox.warning(self, self.t("Warning"), self.t("Choose a valid game folder containing RCCars.exe.")); return
        instance.update({"name": values["name"] or path.name, "path": str(path.resolve()), "icon": values["icon"]})
        self.save_prefs(); self._sync_active_combo(); self.refresh_everything()

    def remove_instance(self) -> None:
        instance = self._selected_table_instance()
        if not instance:
            return
        answer = QMessageBox.question(self, self.t("Confirm"), self.t("Remove this instance from the list? The game files will not be deleted."))
        if answer != QMessageBox.Yes:
            return
        self.instances = [x for x in self.instances if x.get("id") != instance.get("id")]
        if self.active_instance_id == instance.get("id"):
            self.active_instance_id = self.instances[0]["id"] if self.instances else ""
        self.save_prefs(); self._sync_active_combo(); self.refresh_everything()

    def set_active_from_table(self) -> None:
        instance = self._selected_table_instance()
        if instance:
            self.active_instance_id = instance["id"]
            self.save_prefs(); self._sync_active_combo(); self.refresh_everything()

    def _activate_table_instance(self, *_args) -> None:
        self.set_active_from_table()
        self.show_page("Home")

    def open_game_folder(self) -> None:
        root = self.current_root()
        if root and root.exists():
            self.open_path(root)

    @staticmethod
    def open_path(path: Path) -> None:
        path = Path(path)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def run_task(self, title: str, task: Callable[[Callable[[int, str], None]], Any], on_success: Callable[[Any], None]) -> None:
        dialog = QProgressDialog(title, "", 0, 100, self)
        dialog.setWindowTitle(self.t("Working…")); dialog.setCancelButton(None); dialog.setWindowModality(Qt.WindowModal); dialog.setMinimumDuration(0); dialog.setValue(0); dialog.show()
        worker = TaskWorker(task)
        relay = TaskRelay(self, worker, dialog, on_success)
        self._workers.add(worker); self._task_dialogs.add(dialog); self._relays.add(relay)
        worker.signals.progress.connect(relay.on_progress)
        worker.signals.succeeded.connect(relay.on_success_result)
        worker.signals.failed.connect(relay.on_failure)
        self.pool.start(worker)

    def _task_finished(self, worker: TaskWorker, relay: "TaskRelay", dialog: QProgressDialog) -> None:
        self._workers.discard(worker)
        self._task_dialogs.discard(dialog)
        self._relays.discard(relay)
        dialog.close()
        self.refresh_everything()

    def extract_pack(self) -> None:
        item = self._get_required_instance()
        if not item: return
        instance, root, backup = item
        pack = root / "RCCars.pack"
        if not pack.is_file():
            QMessageBox.information(self, self.t("Warning"), self.t("The selected game copy is missing RCCars.pack.")); return
        answer = QMessageBox.question(self, self.t("Confirm"), self.t("This will extract files into the game directory and rename RCCars.pack to _RCCars.pack. Existing loose files will be backed up first. Continue?"))
        if answer != QMessageBox.Yes: return
        self.run_task(self.t("Extracting RCCars.pack"),
                      lambda report: services.extract_pack_to_game_root(pack, root, backup, report),
                      lambda count: QMessageBox.information(self, self.t("Success"), f"Extracted {count} files into:\n{root}\n\nRCCars.pack was renamed to _RCCars.pack in the game folder."))

    def install_compatibility(self) -> None:
        item = self._get_required_instance()
        if not item: return
        _instance, root, backup = item
        self.run_task(self.t("Installing / updating WidescreenFix + ASI Loader"),
                      lambda report: services.install_compatibility_components(root, backup, report),
                      lambda message: QMessageBox.information(self, self.t("Success"), message))

    def enable_laa(self) -> None:
        item = self._get_required_instance("exe")
        if not item: return
        instance, root, backup = item
        exe = Path(services.locate_game_exe(root))
        details = services.detect_instance(root)
        if details["steam"]:
            if details["large_address_aware"]:
                try:
                    relative_exe = exe.resolve().relative_to(root.resolve())
                    original_backup = backup / relative_exe
                except ValueError:
                    original_backup = backup / exe.name
                if original_backup.is_file():
                    answer = QMessageBox.question(
                        self, self.t("Confirm"),
                        self.t("Steam EXE modification is blocked") + "\n\n" +
                        self.t("Steam may reject a modified executable. If this launcher has an original EXE backup, it can restore it. Otherwise use Steam → Properties → Installed Files → Verify integrity of game files.") + "\n\n" + self.t("Restore original Steam EXE") + "?"
                    )
                    if answer != QMessageBox.Yes: return
                    try:
                        services.restore_original_exe(exe, root, backup)
                    except Exception as exc:
                        QMessageBox.critical(self, self.t("Error"), str(exc)); return
                    QMessageBox.information(self, self.t("Success"), self.t("Original Steam executable restored from the launcher's backup."))
                    self.refresh_everything()
                    return
            QMessageBox.warning(
                self, self.t("Steam EXE modification is blocked"),
                self.t("Steam may reject a modified executable. If this launcher has an original EXE backup, it can restore it. Otherwise use Steam → Properties → Installed Files → Verify integrity of game files.")
            )
            return
        try:
            changed = services.enable_large_address_aware(exe, root, backup)
        except Exception as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc)); return
        if changed:
            QMessageBox.information(self, self.t("Success"), self.t("Large Address Aware flag enabled. Original executable backed up."))
        else:
            QMessageBox.information(self, self.t("Success"), self.t("This executable already has the Large Address Aware flag."))
        self.refresh_everything()

    def _toggle_custom_resolution(self, enabled: bool) -> None:
        self.width_spin.setEnabled(enabled); self.height_spin.setEnabled(enabled)
        self.resolution_combo.setEnabled(not enabled)

    def _resolution_changed(self, index: int) -> None:
        if index < 0 or self.custom_resolution.isChecked(): return
        resolution = self.resolution_combo.itemData(index)
        if resolution:
            self.width_spin.blockSignals(True); self.height_spin.blockSignals(True)
            self.width_spin.setValue(int(resolution[0])); self.height_spin.setValue(int(resolution[1]))
            self.width_spin.blockSignals(False); self.height_spin.blockSignals(False)

    def load_graphics_settings(self) -> None:
        root = self.current_root()
        if root is None or not hasattr(self, "resolution_combo"): return
        instance = self.current_instance()
        instance_id = str(instance.get("id", "")) if instance else ""
        preserve_custom_choice = (
            self._graphics_instance_id == instance_id
            and self.custom_resolution.isChecked()
        )
        ini = root / "RCCars_WidescreenFix.ini"
        width = int(services.read_ini_value(ini, "MAIN", "Width", str(services.current_display_resolution()[0])) or 1920)
        height = int(services.read_ini_value(ini, "MAIN", "Height", str(services.current_display_resolution()[1])) or 1080)
        idx = self.resolution_combo.findData((width, height))
        self.custom_resolution.blockSignals(True); self.resolution_combo.blockSignals(True)
        if idx < 0:
            # The INI may contain a valid resolution not advertised as a current display mode.
            # Add it to the combo instead of silently enabling the user's Custom checkbox.
            label = f"{width} × {height} (current)"
            self.resolution_combo.addItem(label, (width, height))
            idx = self.resolution_combo.findData((width, height))
        self.resolution_combo.setCurrentIndex(idx)
        self.custom_resolution.setChecked(preserve_custom_choice)
        self.width_spin.setValue(max(320, width)); self.height_spin.setValue(max(240, height))
        self.resolution_combo.blockSignals(False); self.custom_resolution.blockSignals(False)
        self._graphics_instance_id = instance_id
        self._toggle_custom_resolution(preserve_custom_choice)
        self.fix_fov.setChecked(services.read_ini_value(ini, "MAIN", "FixFOV", "1") == "1")
        custom_fov = services.read_ini_value(ini, "MAIN", "CustomFOV", "80")
        try: custom_fov_value = int(float(custom_fov))
        except ValueError: custom_fov_value = 80
        self.fov_spin.setValue(max(1, min(120, custom_fov_value)))
        self.fov_slider.setValue(max(1, min(120, custom_fov_value)))
        self.fix_hud.setChecked(services.read_ini_value(ini, "MAIN", "FixHUD", "1") == "1")
        self.legacy_fix_hud.setChecked(services.read_ini_value(ini, "MAIN", "LegacyFixHUD", "1") == "1")
        try: fps = int(services.read_ini_value(ini, "FPS", "Limit", "0"))
        except ValueError: fps = 0
        self.fps_spin.setValue(max(0, min(600, fps)))
        self.no_minimize.setChecked(services.read_ini_value(ini, "DEBUG", "NoMinimize", "0") == "1")

    def save_graphics_settings(self) -> None:
        item = self._get_required_instance()
        if not item: return
        _instance, root, backup = item
        if self.custom_resolution.isChecked():
            width, height = self.width_spin.value(), self.height_spin.value()
        else:
            data = self.resolution_combo.currentData()
            width, height = data if data else (self.width_spin.value(), self.height_spin.value())
        def task(report):
            report(10, "Updating WidescreenFix INI…")
            path = services.update_graphics_ini(root, int(width), int(height), self.fix_fov.isChecked(), self.fov_spin.value(), self.fix_hud.isChecked(), self.legacy_fix_hud.isChecked(), self.fps_spin.value(), self.no_minimize.isChecked(), backup)
            report(75, "Checking the game settings file…")
            crs_message = services.patch_crs_file_if_present(root, int(width), int(height), backup)
            report(100, "Settings saved")
            return str(path), crs_message
        def success(result):
            QMessageBox.information(self, self.t("Success"), f"{self.t('Settings saved.')}\n{result[0]}\n{result[1]}")
        self.run_task(self.t("Saving graphics settings"), task, success)

    def _read_gm_flag(self, game_root: Path, key: str, default: bool = True) -> bool:
        path = game_root / "Config.gm"
        if not path.is_file(): return default
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="cp1252", errors="replace")
        match = re.search(r"(?im)^\s*Set\s+[\"']?" + re.escape(key) + r"[\"']?\s+[\"']?([01])[\"']?", text)
        return bool(int(match.group(1))) if match else default

    def load_game_settings(self) -> None:
        root = self.current_root()
        if root is None or not hasattr(self, "cfg_fog"): return
        self.cfg_fog.setChecked(self._read_gm_flag(root, "VIDEO_UseFog", True))
        self.cfg_gamma.setChecked(self._read_gm_flag(root, "Gamma_Changes", True))
        self.cfg_intro.setChecked(self._read_gm_flag(root, "AutoRunIntro", True))
        current = services.get_game_language()
        index = self.game_language_combo.findText(current, Qt.MatchFixedString)
        if index >= 0: self.game_language_combo.setCurrentIndex(index)

    def apply_game_settings(self) -> None:
        item = self._get_required_instance()
        if not item: return
        _instance, root, backup = item
        answer = QMessageBox.question(self, self.t("Confirm"), self.t("This will update RCCars.crs and Config.gm, and set the game-language registry value. Continue?"))
        if answer != QMessageBox.Yes: return
        flags = {"VIDEO_UseFog": self.cfg_fog.isChecked(), "Gamma_Changes": self.cfg_gamma.isChecked(), "AutoRunIntro": self.cfg_intro.isChecked()}
        language = self.game_language_combo.currentText()
        def task(report):
            report(15, "Updating Config.gm…")
            gm_message = services.patch_config_gm(root, flags, backup)
            report(40, "Patching RCCars.crs if present…")
            if hasattr(self, "width_spin"):
                if self.custom_resolution.isChecked(): width, height = self.width_spin.value(), self.height_spin.value()
                else:
                    res = self.resolution_combo.currentData(); width, height = res if res else (self.width_spin.value(), self.height_spin.value())
            else: width, height = services.current_display_resolution()
            crs_message = services.patch_crs_file_if_present(root, int(width), int(height), backup)
            report(70, "Updating the Windows game-language setting…")
            registry_message = services.set_game_language(language)
            report(100, "Game settings applied")
            return gm_message, crs_message, registry_message
        self.run_task(self.t("Applying game settings"), task,
                      lambda result: QMessageBox.information(self, self.t("Success"), "\n".join(result)))

    def refresh_mods_table(self) -> None:
        if not hasattr(self, "mods_table"): return
        root = self.current_root(); instance = self.current_instance()
        self.mod_records = []; self.mod_state = {}
        self.mods_table.setRowCount(0)
        if root is None or instance is None or not self._mods_available(): return
        try:
            self.mod_records, self.mod_state = scan_mods(root, str(instance["id"]))
        except OSError as exc:
            QMessageBox.warning(self, self.t("Error"), str(exc)); return
        for row, record in enumerate(self.mod_records):
            self.mods_table.insertRow(row)
            enabled = QCheckBox(); enabled.setChecked(record.enabled); enabled.setStyleSheet("margin-left:12px;")
            enabled.toggled.connect(lambda checked, rec=record: self._mod_enabled_changed(rec, checked))
            self.mods_table.setCellWidget(row, 0, enabled)
            name_item = QTableWidgetItem(record.name); name_item.setData(Qt.UserRole, record.archive.name)
            self.mods_table.setItem(row, 1, name_item)
            self.mods_table.setItem(row, 2, QTableWidgetItem(record.kind))
            self.mods_table.setItem(row, 3, QTableWidgetItem(str(row + 1)))
        self.mods_table.resizeRowsToContents()

    def _mod_enabled_changed(self, record: ModRecord, enabled: bool) -> None:
        record.enabled = bool(enabled)
        instance = self.current_instance()
        if instance:
            self.mod_state = save_mod_settings(str(instance["id"]), self.mod_records, self.mod_state)

    def add_mod_archives(self) -> None:
        if not self._mods_available():
            QMessageBox.information(self, self.t("No Pack extraction"), self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first.")); return
        item = self._get_required_instance()
        if not item: return
        _instance, root, _backup = item
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("Select one or more ZIP/7z mod archives"), str(Path.home()), self.t("Mod archives (*.zip *.7z);;All files (*.*)"))
        if not paths: return
        try:
            import_mod_archives([Path(p) for p in paths], root)
            self.refresh_mods_table()
        except Exception as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc))

    def handle_dropped_mod_archives(self, paths: list[str]) -> None:
        """Import supported archives dropped anywhere in the Mod Manager page or table."""
        if not self._mods_available():
            QMessageBox.information(self, self.t("No Pack extraction"), self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first."))
            return
        item = self._get_required_instance()
        if not item:
            return
        _instance, root, _backup = item
        candidates = [Path(path) for path in paths]
        try:
            imported = import_mod_archives(candidates, root)
            self.refresh_mods_table()
            if not imported:
                QMessageBox.information(self, self.t("Warning"), self.t("No supported ZIP/7z archives were dropped."))
        except Exception as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc))

    def remove_mod_archive(self) -> None:
        row = self.mods_table.currentRow()
        if row < 0 or row >= len(self.mod_records): return
        record = self.mod_records[row]
        if QMessageBox.question(self, self.t("Confirm"), self.t("The mod archive will be removed from the Mods folder. Continue?")) != QMessageBox.Yes:
            return
        try:
            record.archive.unlink(missing_ok=True)
            self.refresh_mods_table()
        except OSError as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc))

    def move_mod(self, delta: int) -> None:
        row = self.mods_table.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < len(self.mod_records)): return
        self.mod_records[row], self.mod_records[target] = self.mod_records[target], self.mod_records[row]
        normalize_order(self.mod_records)
        instance = self.current_instance()
        if instance:
            self.mod_state = save_mod_settings(str(instance["id"]), self.mod_records, self.mod_state)
        self.refresh_mods_table(); self.mods_table.selectRow(target)

    def apply_mods(self) -> None:
        if not self._mods_available():
            QMessageBox.information(self, self.t("No Pack extraction"), self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first.")); return
        item = self._get_required_instance()
        if not item: return
        instance, root, backup = item
        records = list(self.mod_records)
        if not records:
            if not (root / "update").is_dir():
                QMessageBox.information(self, self.t("Warning"), self.t("There are no mod archives in Mods yet.")); return
            # An empty profile is meaningful: Apply can restore files from mods that were removed.
        instance_id = str(instance["id"])
        self.run_task(self.t("Applying enabled mods"), lambda report: apply_mods(root, instance_id, records, backup, report),
                      lambda result: QMessageBox.information(self, self.t("Success"), f"Enabled mods: {result[0]}\nFiles in update/: {result[1]}"))

    def open_mods_folder(self) -> None:
        if not self._mods_available():
            QMessageBox.information(self, self.t("No Pack extraction"), self.t("The Mod Manager is available only after RCCars.pack has been extracted. Use the Home page to extract Pack first.")); return
        root = self.current_root()
        if root:
            path = root / "Mods"; path.mkdir(parents=True, exist_ok=True); self.open_path(path)

    def _tools_dir(self) -> Path:
        path = self.app_dir / "Tools"; path.mkdir(parents=True, exist_ok=True); return path

    def refresh_tools(self) -> None:
        if not hasattr(self, "tools_table"): return
        self.tools_table.setRowCount(0)
        try:
            files = sorted([p for p in self._tools_dir().iterdir() if p.is_file() and p.suffix.lower() in (".exe", ".py", ".bat", ".cmd", ".ps1")], key=lambda p: p.name.casefold())
        except OSError:
            files = []
        for path in files:
            row = self.tools_table.rowCount(); self.tools_table.insertRow(row)
            name_item = QTableWidgetItem(path.name); name_item.setData(Qt.UserRole, str(path)); self.tools_table.setItem(row, 0, name_item)
            self.tools_table.setItem(row, 1, QTableWidgetItem(path.suffix[1:].upper()))

    def _selected_tool_path(self) -> Optional[Path]:
        row = self.tools_table.currentRow()
        if row < 0: return None
        item = self.tools_table.item(row, 0)
        if not item: return None
        return Path(str(item.data(Qt.UserRole)))

    def run_selected_tool(self) -> None:
        path = self._selected_tool_path()
        if not path or not path.exists(): return
        root = self.current_root() or self.app_dir
        suffix = path.suffix.lower()
        try:
            if suffix == ".exe":
                command = [str(path)]
            elif suffix in (".bat", ".cmd"):
                command = ["cmd.exe", "/c", str(path)] if os.name == "nt" else ["/bin/sh", str(path)]
            elif suffix == ".ps1":
                command = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(path)]
            elif suffix == ".py":
                if getattr(sys, "frozen", False):
                    python_launcher = shutil.which("py")
                    python = shutil.which("python")
                    if python_launcher: command = [python_launcher, "-3", str(path)]
                    elif python: command = [python, str(path)]
                    else:
                        QMessageBox.warning(self, self.t("Warning"), self.t("Python scripts require Python to be installed on the system when the launcher is packaged as EXE.")); return
                else:
                    command = [sys.executable, str(path)]
            else:
                return
            subprocess.Popen(command, cwd=str(root), close_fds=False)
        except Exception as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc))

    def open_tools_folder(self) -> None:
        self.open_path(self._tools_dir())

    def _save_dev_mode(self, checked: bool) -> None:
        self.prefs["dev_mode"] = bool(checked); self.save_prefs()

    def launch_active_game(self) -> None:
        item = self._get_required_instance("launch")
        if not item: return
        _instance, root, _backup = item
        try:
            services.launch_game(root, bool(self.prefs.get("dev_mode", False)))
            self.statusBar().showMessage(self.t("Game process started."), 5000)
        except Exception as exc:
            QMessageBox.critical(self, self.t("Error"), str(exc))

    def save_launcher_repo(self) -> None:
        self.app_config["launcher_update_repo"] = self.update_repo_edit.text().strip()
        services.write_json(self.app_config_path, self.app_config)
        QMessageBox.information(self, self.t("Success"), self.t("Settings saved."))

    def check_launcher_updates(self) -> None:
        self.app_config["launcher_update_repo"] = self.update_repo_edit.text().strip()
        services.write_json(self.app_config_path, self.app_config)
        repo = self.app_config.get("launcher_update_repo", "").strip()
        try:
            details = services.check_launcher_update(repo)
        except Exception as exc:
            QMessageBox.warning(self, self.t("Warning"), str(exc))
            return
        def version_tuple(value: str) -> tuple[int, ...]:
            parts = re.findall(r"\d+", value)
            return tuple(int(part) for part in parts) or (0,)
        if version_tuple(details["tag"]) <= version_tuple(APP_VERSION):
            QMessageBox.information(self, self.t("Success"), self.t("The launcher is already up to date."))
            return
        text = f"{self.t('Latest release')}: {details['tag']}\n{details['asset_name']}\n{details['asset_size'] // (1024*1024)} MB"
        if QMessageBox.question(self, self.t("Launcher self-update"), text + "\n\nDownload and replace the current launcher?") != QMessageBox.Yes:
            webbrowser.open(details["url"]); return
        if not getattr(sys, "frozen", False):
            webbrowser.open(details["url"])
            QMessageBox.information(self, self.t("About"), "The launcher is running from Python source; download the portable package from the release page and replace the launcher folder manually.")
            return
        def task(report):
            staged, bat = services.prepare_self_update(details["asset_url"], details["asset_name"], report)
            return staged, bat
        def complete(result):
            QMessageBox.information(self, self.t("Success"), "Update downloaded. The launcher will close and restart with the new version.")
            services.apply_app_update(result[1])
            QApplication.quit()
        self.run_task(self.t("Downloading launcher update"), task, complete)

    def apply_launcher_language(self) -> None:
        combo = getattr(self, "launcher_language_combo", None)
        if combo is None:
            return
        language = combo.currentData()
        if not language or language == self.prefs.get("language", "en"):
            return
        self.prefs["language"] = language
        self.save_prefs()
        page_key = self.current_page_key
        if page_key == "Graphics":
            page_key = "Game Settings"
        elif page_key == "Game Setup":
            page_key = "Home"
        self._build_ui()
        self._sync_active_combo()
        # Show the window before doing filesystem scans and instance detection.
        # The one-directory build below also avoids PyInstaller one-file extraction at startup.
        QTimer.singleShot(120, self.refresh_startup_state)
        self.show_page(page_key)

    def open_social_links(self) -> None:
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad.exe", str(self.social_links_path)])
            else:
                self.open_path(self.social_links_path)
        except Exception:
            self.open_path(self.app_dir)

    def open_data_folder(self) -> None:
        self.open_path(self.data_dir)

    def refresh_social_links(self) -> None:
        if not hasattr(self, "social_links_layout"): return
        while self.social_links_layout.count():
            item = self.social_links_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        data = services.read_json(self.social_links_path, {"links": []})
        for link in data.get("links", []):
            label = str(link.get("label", "Link"))
            url = str(link.get("url", ""))
            if url.startswith("https://") or url.startswith("http://"):
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, u=url: webbrowser.open(u))
                self.social_links_layout.addWidget(button)
        self.social_links_layout.addStretch(1)

    def closeEvent(self, event) -> None:
        self.save_prefs()
        super().closeEvent(event)
