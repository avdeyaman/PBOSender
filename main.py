import sys

from PyQt6.QtWidgets import QApplication

from app.windows.mainwindow import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if QApplication.instance() is not None:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())