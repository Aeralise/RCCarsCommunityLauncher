from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from rccars_launcher.ui import LauncherWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RC Cars Launcher")
    app.setOrganizationName("Aeralise")
    app.setFont(QFont("Segoe UI", 10))
    window = LauncherWindow()
    app.setWindowIcon(window.windowIcon())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
