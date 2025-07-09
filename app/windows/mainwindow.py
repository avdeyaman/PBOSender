import json

import app.logger as logger

from os import getenv, path

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer

from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon
from PyQt6.QtWidgets import QWidget, QMenu
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QPushButton, QSpinBox, QLineEdit
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtCore import QSysInfo
from PyQt6.QtGui import QIcon

from PyQt6.QtGui import QIcon

from app.senderthread import SenderThread


class MainWindow(QMainWindow):
    """Главное окно приложения. Наследует <code>QMainWindow</code>."""

    def __init__(self):
        super().__init__()

        self.logger = logger.setup_logging(__name__)

        self.logger.info('---- ПРИЛОЖЕНИЕ ЗАПУЩЕНО ----')

        self.CONFIG_FILE_PATH = 'pbo_sender.json'
        self.DEFAULT_USER_CONFIG = {
            'webhook_url': '',
            'search_folder': f'{getenv('LOCALAPPDATA')}\\Arma 3\\MPMissionsCache',
            'target_files_prefix': 'UTF',
            'max_file_size_mb': 8,
            'check_interval': 60
        }

        self.user_config = self.read_user_config()

        self.setWindowTitle('PBO Sender')
        self.setWindowIcon(QIcon('favicon.ico'))
        if QSysInfo.productType() == 'macos':
            self.setFixedSize(500, 220)  # Для macOS
        else:
            self.setFixedSize(500, 170)  # Для Windows и других ОС

        self.next_check_time = self.calc_next_check_time()

        self.init_ui()
        self.init_timers()
        self.init_system_tray()


    def init_ui(self):
        """Инициализирует элементы интерфейса."""

        self.logger.info('Инициализация элементов интерфейса...')

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

        # Folder Layout
        folder_layout = QHBoxLayout()

        self.folder_label = QLabel(f'Папка для проверки: {self.user_config['search_folder']}')
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label, 1)

        self.browse_button = QPushButton('Обзор...')
        self.browse_button.clicked.connect(self.on_browse_button_clicked)
        folder_layout.addWidget(self.browse_button)

        main_layout.addLayout(folder_layout)

        # Webhook Layout
        webhook_layout = QHBoxLayout()

        webhook_layout.addWidget(QLabel('Webhook URL:'))

        self.webhook_lineedit = QLineEdit()
        self.webhook_lineedit.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook_lineedit.setText(self.user_config['webhook_url'])
        self.webhook_lineedit.textChanged.connect(self.on_webhook_lineedit_text_changed)
        webhook_layout.addWidget(self.webhook_lineedit)

        main_layout.addLayout(webhook_layout)

        # Interval Layout
        interval_layout = QHBoxLayout()

        interval_layout.addWidget(QLabel('Интервал проверки (мин):'))

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(1, 1440)
        self.interval_spinbox.setValue(self.user_config['check_interval'])
        self.interval_spinbox.valueChanged.connect(self.on_interval_spin_box_value_changed)
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

        self.logger.info('Инициализация элементов интерфейса завершена')


    def init_timers(self):
        """Инициализирует таймеры."""

        self.logger.info('Инициализация таймеров...')

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.on_update_timer_timeout)
        self.update_timer.start(1000)

        self.logger.info('Инициализация таймеров завершена')


    def init_system_tray(self):
        """Инициализирует трэй иконку."""

        self.logger.info('Инициализация иконки в трэе...')

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('favicon.ico'))

        tray_menu = QMenu()
        show_window_action = tray_menu.addAction('Показать')
        show_window_action.triggered.connect(self.on_show_window_action_triggered)

        exit_action = tray_menu.addAction('Выход')
        exit_action.triggered.connect(self.on_exit_action_triggered)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.logger.info('Инициализация иконки в трэе завершена')

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage('PBOSender', 'Приложение свёрнуто в трэй и будет работать в фоне', QSystemTrayIcon.MessageIcon.Information, 3000)

    def on_browse_button_clicked(self):
        """Обработчик события, когда нажата кнопка выбора папки для поиска."""

        self.show_browse_dialog()


    def on_save_config_button_clicked(self):
        """Обработчик события, когда нажата кнопка сохранения конфигурации."""

        self.disable_buttons()
        self.save_user_config()
        self.enable_buttons()


    def on_send_button_clicked(self):
        """Обработчик события, когда нажата кнопка отправки."""

        self.disable_buttons()
        self.sender_thread = SenderThread(self.user_config)
        self.sender_thread.finished.connect(self.on_files_send_finished)
        self.sender_thread.status_changed.connect(self.on_status_changed)
        self.sender_thread.start()


    def on_webhook_lineedit_text_changed(self):
        """Обработчик события, когда изменен текст поля ввода Webhook."""

        text: str = self.webhook_lineedit.text()
        self.user_config['webhook_url'] = text


    def on_interval_spin_box_value_changed(self, value: int):
        """Обработчик события, когда изменёно значение интервала.

        Parameters
        ----------
        value : int
            новое значение
        """

        self.user_config['check_interval'] = value


    def on_update_timer_timeout(self):
        """Обработчик события, когда истек таймер обновления времени проверки."""

        current_time = datetime.now()
        if current_time >= self.next_check_time:
            self.update_next_check_label_text('Начинается проверка...')
            self.run_auto_check_pbo_files()
            return

        delta = self.next_check_time - current_time
        minutes = delta.seconds // 60
        seconds = delta.seconds % 60

        self.update_next_check_label_text(f'Проверка через: {minutes}:{seconds}')


    def on_show_window_action_triggered(self):
        """Обработчик события, когда сработало действие на показ главного окна."""

        self.show_main_window()


    def on_exit_action_triggered(self):
        """Обработчик события, когда сработало действие на выход из приложения."""

        self.exit_from_app()


    def on_auto_check_pbo_files_finished(self, result):
        pass


    def on_files_send_finished(self, result):
        """"""

        # TODO
        self.status_label.setText(result['message'])
        self.enable_buttons()


    def on_status_changed(self, message):
        """Обработчик события, когда статус отправки изменён."""

        self.status_label.setText(message)


    def show_main_window(self):
        """Показывает главное окно приложения."""

        self.logger.info('Показ главного окна')

        self.show()
        self.activateWindow()
        self.raise_()


    def exit_from_app(self):
        """Полностью закрывает приложение и убирает трэй иконку."""

        self.logger.info('Выход из приложения...')

        self.tray_icon.hide()
        QApplication.quit()


    def run_auto_check_pbo_files(self):
        """Запускает автоматическую проверку файлов .pbo."""

        self.logger.info('Запущена автоматическая проверка файлов .pbo')

        self.next_check_time = self.calc_next_check_time()
        self.status_label.setText('Автоматическая проверка файлов...')

        self.auto_check_thread = SenderThread(self.user_config)
        self.auto_check_thread.finished.connect(self.on_files_send_finished)
        self.auto_check_thread.start()


    def read_user_config(self):
        """Считывает данные из конфига пользователя в формате JSON."""

        self.logger.info('Чтение файла конфигурации...')

        try:
            if not path.exists(self.CONFIG_FILE_PATH):
                self.logger.warning('Файл конфигурации отсутствует')
                return self.DEFAULT_USER_CONFIG

            with open(self.CONFIG_FILE_PATH, 'r', encoding='utf-8') as config_file:
                self.logger.info('Файл конфигурации считан')
                return json.load(config_file)
        except Exception as e:
            self.logger.error(f'Ошибка при чтении файла конфигурации! Будет загружена стандартная конфигурация. Ошибка:\n{str(e)}')
            return self.DEFAULT_USER_CONFIG


    def save_user_config(self):
        """Записывает данные в файл конфига в формате JSON."""

        self.logger.info('Сохранение файла конфигруации...')

        try:
            with open(self.CONFIG_FILE_PATH, 'w', encoding='utf-8') as config_file:
                json.dump(self.user_config, config_file, indent=2, ensure_ascii=False)

            self.status_label.setText('Конфигруация сохранена')
            self.logger.info('Файл конфигурации сохранён')
        except Exception as e:
            self.status_label.setText('Ошибка сохранения. Детали в файле .log')
            self.logger.info(f'Ошибка при сохранении файла конфигурации! Ошибка:\n{str(e)}')


    def show_browse_dialog(self):
        """Показывает диалог выбора папки с файлами .pbo миссий."""

        self.logger.info('Запуск выбора папки с файлами .pbo миссий')

        folder = QFileDialog.getExistingDirectory(self, 'Выберите папку с файлами .pbo миссий', self.user_config['search_folder'])
        if folder:
            self.folder_label.setText(f'Папка для проверки: {folder}')
            self.logger.info(f'Папка с файлами .pbo миссий выбрана. Путь: {folder}')


    def enable_buttons(self):
        """Включает все кнопки."""

        self.send_button.setDisabled(False)
        self.save_config_button.setDisabled(False)

        self.logger.info('Все кнопки включены')


    def disable_buttons(self):
        """Выключает все кнопки."""

        self.send_button.setDisabled(True)
        self.save_config_button.setDisabled(True)

        self.logger.info('Все кнопки выключены')


    def update_next_check_label_text(self, text: str):
        """Обновялет текст лэйбла таймера следующей проверки.

        Parameters
        ----------
        text : str
            текст
        """

        self.next_check_label.setText(text)


    def calc_next_check_time(self) -> datetime:
        """Расчитывает и возвращает время следующей проверки файлов.

        Returns
        -------
        datetime
            время следующей проверки
        """

        check_interval_minutes = self.user_config['check_interval']
        return datetime.now() + timedelta(minutes=check_interval_minutes)