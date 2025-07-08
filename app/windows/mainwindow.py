import json

from os import getenv, path

from PyQt6.QtCore import Qt, QTimer

from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon
from PyQt6.QtWidgets import QWidget, QMenu
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtWidgets import QLabel, QProgressBar
from PyQt6.QtWidgets import QPushButton, QComboBox, QSpinBox
from PyQt6.QtWidgets import QFileDialog

from PyQt6.QtGui import QIcon


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.CONFIG_FILE_PATH = 'pbo_sender.json'
        self.DEFAULT_USER_CONFIG = {
            'search_folder': f'{getenv('LOCALAPPDATA')}\\Arma 3\\MPMissionsCache',
            'target_files_prefix': 'UTF',
            'max_file_size_mb': 8,
            'current_mode': 0,
            'fixed_delay': 0.3,
            'check_interval': 60
        }

        self.user_config = self.read_user_config()

        self.setWindowTitle('PBO Sender')
        self.setWindowIcon(QIcon('icon.png'))
        self.setFixedSize(500, 190)

        self.init_ui()
        self.init_timers()
        self.init_system_tray()


    def init_ui(self):
        """Инициализирует элементы интерфейса."""

        main_widget = QWidget()

        main_layout = QVBoxLayout()

        # Status Layout
        status_layout = QHBoxLayout()
        self.status_label = QLabel('Ожидание...')
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet('font-weight: bold;')
        status_layout.addWidget(self.status_label, 70)

        self.next_check_label = QLabel()
        self.next_check_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_layout.addWidget(self.next_check_label, 30)

        main_layout.addLayout(status_layout)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        main_layout.addWidget(self.progress_bar)

        # Folder Layout
        folder_layout = QHBoxLayout()

        self.folder_label = QLabel(f'Папка для проверки: {self.user_config['search_folder']}')
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label, 1)

        self.browse_button = QPushButton('Обзор...')
        self.browse_button.clicked.connect(self.on_browse_button_clicked)
        folder_layout.addWidget(self.browse_button)

        main_layout.addLayout(folder_layout)

        # Mode Layout
        mode_layout = QHBoxLayout()

        mode_layout.addWidget(QLabel('Режим работы:'))

        self.mode_combobox = QComboBox()
        self.mode_combobox.addItems(['Обычный', 'Принудительный'])
        self.mode_combobox.setCurrentIndex(0)
        mode_layout.addWidget(self.mode_combobox)

        main_layout.addLayout(mode_layout)

        # Interval Layout
        interval_layout = QHBoxLayout()

        interval_layout.addWidget(QLabel('Интервал проверки (мин):'))

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(1, 1440)
        self.interval_spinbox.setValue(1)
        interval_layout.addWidget(self.interval_spinbox)

        main_layout.addLayout(interval_layout)

        # Buttons Layout
        buttons_layout = QHBoxLayout()

        self.save_config_button = QPushButton('Сохранить конфигурацию')
        self.save_config_button.clicked.connect(self.on_save_config_button_clicked)
        buttons_layout.addWidget(self.save_config_button)

        self.send_button = QPushButton('Отправить сейчас')
        self.send_button.clicked.connect(self.on_send_button_clicked)
        buttons_layout.addWidget(self.send_button)

        main_layout.addLayout(buttons_layout)

        main_widget.setLayout(main_layout)

        self.setCentralWidget(main_widget)


    def init_timers(self):
        """Инициализирует таймеры."""

        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.on_check_timer_timeout)
        self.check_timer.start(60 * 1000)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.on_update_timer_timeout)
        self.update_timer.start(1000)


    def init_system_tray(self):
        """Инициализирует трэй иконку."""

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.png'))

        tray_menu = QMenu()
        show_window_action = tray_menu.addAction('Показать')
        show_window_action.triggered.connect(self.on_show_window_action_triggered)

        exit_action = tray_menu.addAction('Выход')
        exit_action.triggered.connect(self.on_exit_action_triggered)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()


    def on_browse_button_clicked(self):
        """Обработчик события, когда нажата кнопка выбора папки для поиска."""

        self.show_browse_dialog()


    def on_save_config_button_clicked(self):
        """Обработчик события, когда нажата кнопка сохранения конфигурации."""

        self.disable_buttons()
        self.save_user_config()
        self.enable_buttons()


    def on_send_button_clicked(self):
        pass


    def on_check_timer_timeout(self):
        pass


    def on_update_timer_timeout(self):
        pass


    def on_show_window_action_triggered(self):
        """Обработчик события, когда сработало действие на показ главного окна."""

        self.show_main_window()


    def on_exit_action_triggered(self):
        """Обработчик события, когда сработало действие на выход из приложения."""

        self.exit_from_app()


    def read_user_config(self):
        """Считывает данные из конфига пользователя в формате JSON."""

        try:
            if not path.exists(self.CONFIG_FILE_PATH):
                return self.DEFAULT_USER_CONFIG

            with open(self.CONFIG_FILE_PATH, 'r', encoding='utf-8') as config_file:
                return json.load(config_file)
        except Exception as e:
            # TODO: logger
            return self.DEFAULT_USER_CONFIG


    def save_user_config(self):
        """Записывает данные в файл конфига в формате JSON."""

        try:
            with open(self.CONFIG_FILE_PATH, 'w', encoding='utf-8') as config_file:
                json.dump(self.user_config, config_file, indent=2, ensure_ascii=False)

            self.status_label.setText('Настройки сохранены')
        except Exception as e:
            self.status_label.setText(f'Ошибка сохранения: {str(e)}')
            # TODO: Logger


    def show_main_window(self):
        """Показывает главное окно приложения."""

        self.show()
        self.activateWindow()
        self.raise_()


    def exit_from_app(self):
        """Полностью закрывает приложение и убирает трэй иконку."""

        self.tray_icon.hide()
        QApplication.quit()


    def show_browse_dialog(self):
        """Показывает диалог выбора папки с файлами .pbo миссий."""

        folder = QFileDialog.getExistingDirectory(self, 'Выберите папку с файлами .pbo миссий', self.user_config['search_folder'])
        if folder:
            self.folder_label.setText(f'Папка для проверки: {folder}')


    def enable_buttons(self):
        """Включает все кнопки."""

        self.send_button.setDisabled(False)
        self.save_config_button.setDisabled(False)


    def disable_buttons(self):
        """Выключает все кнопки."""

        self.send_button.setDisabled(True)
        self.save_config_button.setDisabled(True)