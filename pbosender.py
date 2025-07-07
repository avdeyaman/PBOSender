import os
import zipfile
import requests
from datetime import datetime, timezone, timedelta
import json
import time
import logging
import sys
import asyncio
import aiohttp
from pathlib import Path

# Fix for PyInstaller
if hasattr(sys, '_MEIPASS'):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ['PATH']

# Safe stdout/stderr reconfigure
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    # Fallback for Python < 3.7 or frozen env
    sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), 'w', encoding='utf-8', buffering=1)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QLabel, QComboBox, QFileDialog, QWidget, 
                            QSystemTrayIcon, QMenu, QProgressBar, QSpinBox)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from dotenv import load_dotenv

load_dotenv()

appdata_path = os.getenv('APPDATA')
local_appdata_path = os.getenv('LOCALAPPDATA')

arma_missions_path = str(Path(local_appdata_path) / 'Arma 3' / 'MPMissionsCache')

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('file_sender1.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

DEFAULT_CONFIG = {
    "SEARCH_FOLDER": os.getenv("SEARCH_FOLDER", arma_missions_path),
    "TARGET_FILES": [
        "UTF_Vanilla.Altis.pbo",
        "UTF_Vanilla.Stratis.pbo",
        "UTF_Vanilla.Malden.pbo"
    ],
    "MAX_FILE_SIZE_MB": 8,
    "MODE": "normal",
    "FIXED_DELAY": 0.3,
    "CHECK_INTERVAL": 60
}

CONFIG_FILE = "file_sender_config1.json"

class FileSenderThread(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str, int)
    file_sent = pyqtSignal(str)
    operation_type = "auto"

    def __init__(self, config, force_mode=False, manual_mode=False):
        super().__init__()
        self.config = {
            **config,
            "MAIN_WEBHOOK_URL": os.getenv("MAIN_WEBHOOK_URL"),
            "LOG_WEBHOOK_URL": os.getenv("LOG_WEBHOOK_URL"),
            "ROLE_MENTION": os.getenv("ROLE_MENTION"),
            "USER_MENTION": os.getenv("USER_MENTION")
        }
        self.force_mode = force_mode
        if manual_mode:
            self.operation_type = "manual"

    def run(self):
        try:
            self.progress.emit("Подготовка к отправке...", 0)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.async_find_and_process_files())
            loop.close()
            
            if result:
                msg = "Файлы успешно отправлены" + (" (вручную)" if self.operation_type == "manual" else "")
                self.finished.emit(True, msg)
            else:
                msg = "Ошибка при отправке файлов" + (" (вручную)" if self.operation_type == "manual" else "")
                self.finished.emit(False, msg)
        except Exception as e:
            msg = f"Критическая ошибка: {str(e)}" + (" (вручную)" if self.operation_type == "manual" else "")
            self.finished.emit(False, msg)

    async def async_find_and_process_files(self):
        logger.info(f"Начало {'ручной' if self.operation_type == 'manual' else 'автоматической'} проверки файлов")
        self.progress.emit("Поиск файлов...", 10)
        
        tracking_data = self.load_tracking_data()
        current_data = {}
        files_to_send = []
        skipped_files = []
        too_large_files = []
        errors = []
        
        for filename in self.config["TARGET_FILES"]:
            filepath = os.path.join(self.config["SEARCH_FOLDER"], filename)
            
            if not os.path.exists(filepath):
                error_msg = f"{filename} - не найден"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
            
            mod_date, mod_time = self.get_file_modification_time(filepath)
            if not mod_date:
                error_msg = f"{filename} - ошибка при проверке времени изменения"
                errors.append(error_msg)
                continue
            
            file_key = filename.lower()
            last_known_mod = tracking_data.get(file_key, {}).get('mod_time')
            current_mod = f"{mod_date} {mod_time}"
            
            if not self.force_mode and last_known_mod == current_mod:
                skipped_files.append(filename)
                current_data[file_key] = tracking_data[file_key]
                logger.info(f"Файл {filename} не изменился с последней проверки")
                continue
            
            zip_filename = f"{filename}.zip"
            zip_path = os.path.join(os.path.dirname(__file__), zip_filename)
            
            if not self.zip_file(filepath, zip_path):
                error_msg = f"{filename} - ошибка при создании ZIP архива"
                errors.append(error_msg)
                continue
            
            zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            
            if zip_size_mb > self.config["MAX_FILE_SIZE_MB"]:
                too_large_msg = f"{filename} (размер после сжатия: {zip_size_mb:.1f} МБ)"
                too_large_files.append(too_large_msg)
                try:
                    os.remove(zip_path)
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла {zip_path}: {str(e)}")
                continue
            
            files_to_send.append({
                'path': zip_path,
                'filename': filename,
                'date': mod_date,
                'time': mod_time,
                'size': f"{zip_size_mb:.1f}MB"
            })
            current_data[file_key] = {
                'mod_time': current_mod,
                'last_check': datetime.now().strftime("%d.%m %H:%M")
            }

        self.progress.emit("Подготовка к отправке в Discord...", 30)
        
        async with aiohttp.ClientSession() as session:
            if errors:
                error_description = "```\n" + "\n".join(errors) + "\n```"
                if not await self.send_discord_embed(
                    session,
                    webhook_url=self.config["LOG_WEBHOOK_URL"],
                    title="❌ Ошибки при обработке файлов",
                    description=error_description,
                    color=0xff0000,
                    mention=self.config["USER_MENTION"],
                    include_mention=True
                ):
                    logger.error("Не удалось отправить сообщение об ошибках")
            
            if too_large_files:
                too_large_description = "```\n" + "\n".join(too_large_files) + "\n```"
                if not await self.send_discord_embed(
                    session,
                    webhook_url=self.config["LOG_WEBHOOK_URL"],
                    title="⚠ Файлы не отправлены (слишком большие)",
                    description=too_large_description,
                    color=0xffa500,
                    mention=self.config["USER_MENTION"],
                    include_mention=True
                ):
                    logger.error("Не удалось отправить сообщение о больших файлах")
            
            if skipped_files and not self.force_mode:
                skipped_description = "```\n" + "\n".join(skipped_files) + "\n```"
                if not await self.send_discord_embed(
                    session,
                    webhook_url=self.config["LOG_WEBHOOK_URL"],
                    title="ℹ Файлы не изменились",
                    description=f"Следующие файлы не были отправлены, так как не изменились с прошлой проверки:\n{skipped_description}",
                    color=0xffa500,
                    mention=self.config["USER_MENTION"],
                    include_mention=False
                ):
                    logger.error("Не удалось отправить сообщение о пропущенных файлах")
            
            if files_to_send:
                self.progress.emit("Отправка файлов...", 50)
                send_results = await self.send_all_files(session, files_to_send)
                
                if any(send_results):
                    mode = "принудительной" if self.force_mode else "обычной"
                    op_type = "ручной" if self.operation_type == "manual" else "автоматической"
                    files_field = [{"name": f"{f['filename']}", "value": f"Размер: {f['size']}\nИзменен: {f['date']} {f['time']}"} for f in files_to_send]
                    
                    await self.send_discord_embed(
                        session,
                        webhook_url=self.config["LOG_WEBHOOK_URL"],
                        title=f"📤 Отправка файлов завершена ({op_type})",
                        description=f"Успешно отправлено {len(files_to_send)} файлов в режиме {mode} отправки",
                        color=0x00ff00,
                        fields=files_field,
                        mention=self.config["USER_MENTION"],
                        include_mention=False
                    )
                
                self.progress.emit("Завершение отправки...", 90)
                
                for file_info in files_to_send:
                    try:
                        os.remove(file_info['path'])
                        logger.info(f"Временный файл {file_info['path']} удален")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении временного файла {file_info['path']}: {str(e)}")
                
                self.save_tracking_data(current_data)
                return all(send_results)
            else:
                self.progress.emit("Нет файлов для отправки", 100)
                logger.info(f"Нет новых файлов для {'ручной' if self.operation_type == 'manual' else 'автоматической'} отправки")
                if not self.force_mode and not errors and not too_large_files:
                    if not await self.send_discord_embed(
                        session,
                        webhook_url=self.config["LOG_WEBHOOK_URL"],
                        title="ℹ Нет изменений",
                        description="Нет новых файлов для отправки, все файлы актуальны",
                        color=0xffff00,
                        mention=self.config["USER_MENTION"],
                        include_mention=False
                    ):
                        logger.error("Не удалось отправить сообщение об отсутствии изменений")
                return True

    async def send_all_files(self, session, files_info):
        if not files_info:
            return []
        
        tasks = []
        send_results = []
        
        file_list = "\n".join([f"{info['filename']} - {info['date']} {info['time']}" for info in files_info])
        first_message = f"{self.config['ROLE_MENTION']}\n{file_list}"
        tasks.append(self.send_message_with_file(session, self.config["MAIN_WEBHOOK_URL"], first_message, None))
        
        for i, file_info in enumerate(files_info):
            await asyncio.sleep(self.config["FIXED_DELAY"])
            task = self.send_message_with_file(session, self.config["MAIN_WEBHOOK_URL"], "", file_info['path'])
            tasks.append(task)
            self.file_sent.emit(file_info['filename'])
            progress = 50 + int(40 * (i + 1) / len(files_info))
            self.progress.emit(f"Отправка {file_info['filename']}...", progress)
        
        send_results = await asyncio.gather(*tasks, return_exceptions=True)
        return [False if isinstance(r, Exception) else r for r in send_results]

    async def send_discord_embed(self, session, webhook_url, title, description, color, fields=None, mention=None, include_mention=True):
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": fields or []
        }
        
        data = {
            "embeds": [embed],
            "content": mention if (mention and include_mention) else ""
        }
        
        try:
            async with session.post(webhook_url, json=data) as response:
                if response.status == 204:
                    logger.info(f"Embed '{title}' успешно обработан (204)")
                    return True
                if response.status != 200:
                    logger.error(f"Ошибка {response.status} при отправке embed: {await response.text()}")
                    return False
                logger.info(f"Embed сообщение '{title}' успешно отправлено")
                return True
        except Exception as e:
            logger.error(f"Ошибка при отправке embed сообщения: {str(e)}")
            return False

    async def send_message_with_file(self, session, webhook_url, content, file_path=None, mention=None):
        data = {'content': content} if content else {}
        files = {}
        
        try:
            if file_path:
                if not os.path.exists(file_path):
                    logger.error(f"Файл {os.path.basename(file_path)} не найден для отправки")
                    return False
                
                files['file'] = open(file_path, 'rb')
                data['file'] = files['file']
            
            if mention:
                data['content'] = f"{mention} {content}" if content else mention
            
            async with session.post(webhook_url, data=data) as response:
                if response.status == 204:
                    logger.info(f"Сообщение с файлом {os.path.basename(file_path) if file_path else 'текстом'} успешно обработано (204)")
                    return True
                if response.status != 200:
                    logger.error(f"Ошибка {response.status} при отправке: {await response.text()}")
                    return False
                logger.info(f"Сообщение с файлом {os.path.basename(file_path) if file_path else 'текстом'} успешно отправлено")
                return True
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {str(e)}")
            return False
        finally:
            for f in files.values():
                f.close()

    def get_file_modification_time(self, filepath):
        try:
            mod_time = os.path.getmtime(filepath)
            dt = datetime.fromtimestamp(mod_time)
            return dt.strftime("%d.%m"), dt.strftime("%H:%M")
        except Exception as e:
            logger.error(f"Ошибка при получении времени изменения файла {os.path.basename(filepath)}: {str(e)}")
            return None, None

    def zip_file(self, source_path, zip_path):
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(source_path, os.path.basename(source_path))
            
            original_size = os.path.getsize(source_path) / (1024 * 1024)
            compressed_size = os.path.getsize(zip_path) / (1024 * 1024)
            compression_ratio = (1 - (compressed_size / original_size)) * 100
            
            logger.info(f"Файл {os.path.basename(source_path)} сжат: {original_size:.2f}MB -> {compressed_size:.2f}MB ({compression_ratio:.1f}%)")
            return True
        except Exception as e:
            logger.error(f"Ошибка при создании ZIP архива для {os.path.basename(source_path)}: {str(e)}")
            return False

    def load_tracking_data(self):
        try:
            if os.path.exists("file_tracker.json"):
                with open("file_tracker.json", 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла конфигурации: {str(e)}")
            return {}

    def save_tracking_data(self, data):
        try:
            with open("file_tracker.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Данные о последних изменениях успешно сохранены")
        except Exception as e:
            logger.error(f"Ошибка при сохранении файла конфигурации: {str(e)}")

class FileSenderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Discord File Sender")
        self.setWindowIcon(QIcon("icon.png"))
        self.resize(500, 250)
        
        self.config = self.load_config()
        self.next_check_time = datetime.now() + timedelta(minutes=self.config["CHECK_INTERVAL"])
        
        self.init_ui()
        self.init_timers()
        self.init_system_tray()
        
    def init_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout()
        
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Готов к работе")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label, 70)
        
        self.next_check_label = QLabel()
        self.next_check_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_layout.addWidget(self.next_check_label, 30)
        layout.addLayout(status_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)
        
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Папка для проверки:"))
        self.folder_label = QLabel(self.config["SEARCH_FOLDER"])
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label, 1)
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(browse_btn)
        layout.addLayout(folder_layout)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Режим работы:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Обычный", "Принудительный"])
        self.mode_combo.setCurrentIndex(0 if self.config["MODE"] == "normal" else 1)
        mode_layout.addWidget(self.mode_combo)
        layout.addLayout(mode_layout)
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Интервал проверки (мин):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(self.config["CHECK_INTERVAL"])
        interval_layout.addWidget(self.interval_spin)
        layout.addLayout(interval_layout)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Сохранить настройки")
        save_btn.clicked.connect(self.save_config)
        btn_layout.addWidget(save_btn)
        
        send_btn = QPushButton("Отправить сейчас")
        send_btn.clicked.connect(self.send_now)
        btn_layout.addWidget(send_btn)
        layout.addLayout(btn_layout)
        
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)
        
        self.update_next_check_time()
        
    def init_timers(self):
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.run_auto_check)
        self.check_timer.start(60 * 1000)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_next_check_time)
        self.update_timer.start(1000)
        
    def init_system_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Показать")
        show_action.triggered.connect(self.show_normal)
        
        exit_action = tray_menu.addAction("Выход")
        exit_action.triggered.connect(self.close_app)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
    def show_normal(self):
        self.show()
        self.activateWindow()
        self.raise_()
        
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Discord File Sender", 
            "Приложение продолжает работать в фоне\nПроверка будет выполняться автоматически",
            QSystemTrayIcon.MessageIcon.Information, 
            3000
        )
        
    def close_app(self):
        self.tray_icon.hide()
        QApplication.quit()
        
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", self.config["SEARCH_FOLDER"])
        if folder:
            self.config["SEARCH_FOLDER"] = folder
            self.folder_label.setText(folder)
        
    def save_config(self):
        self.config["MODE"] = "normal" if self.mode_combo.currentIndex() == 0 else "force"
        self.config["CHECK_INTERVAL"] = self.interval_spin.value()
        try:
            safe_config = {
                k: v for k, v in self.config.items()
                if k not in ["MAIN_WEBHOOK_URL", "LOG_WEBHOOK_URL", "ROLE_MENTION", "USER_MENTION"]
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(safe_config, f, indent=2, ensure_ascii=False)
            self.status_label.setText("Настройки сохранены")
            self.progress_bar.setValue(0)
            logger.info("Конфигурация сохранена")
            
            self.next_check_time = datetime.now() + timedelta(minutes=self.config["CHECK_INTERVAL"])
        except Exception as e:
            self.status_label.setText(f"Ошибка сохранения: {str(e)}")
            logger.error(f"Ошибка при сохранении конфигурации: {str(e)}")

    def send_now(self):
        force_mode = self.mode_combo.currentIndex() == 1
        self.status_label.setText("Отправка файлов...")
        self.progress_bar.setValue(0)
        
        self.sender_thread = FileSenderThread(self.config, force_mode, manual_mode=True)
        self.sender_thread.finished.connect(self.on_send_finished)
        self.sender_thread.progress.connect(self.update_progress)
        self.sender_thread.file_sent.connect(self.on_file_sent)
        self.sender_thread.start()
        
    def run_auto_check(self):
        if datetime.now() >= self.next_check_time:
            self.next_check_time = datetime.now() + timedelta(minutes=self.config["CHECK_INTERVAL"])
            self.status_label.setText("Автоматическая проверка файлов...")
            self.progress_bar.setValue(0)
            
            self.auto_check_thread = FileSenderThread(self.config, False)
            self.auto_check_thread.finished.connect(self.on_auto_check_finished)
            self.auto_check_thread.start()
        
    def update_next_check_time(self):
        now = datetime.now()
        if now >= self.next_check_time:
            self.next_check_label.setText("Проверка скоро...")
        else:
            delta = self.next_check_time - now
            minutes = delta.seconds // 60
            seconds = delta.seconds % 60
            self.next_check_label.setText(f"След. проверка: {minutes:02d}:{seconds:02d}")
    
    def update_progress(self, message, percent):
        self.status_label.setText(message)
        self.progress_bar.setValue(percent)
        
    def on_file_sent(self, filename):
        self.tray_icon.showMessage(
            "Discord File Sender", 
            f"Файл {filename} отправлен",
            QSystemTrayIcon.MessageIcon.Information, 
            2000
        )

    def on_send_finished(self, success, message):
        self.status_label.setText(message)
        self.progress_bar.setValue(100 if success else 0)
        if not success:
            self.tray_icon.showMessage(
                "Discord File Sender", 
                message,
                QSystemTrayIcon.MessageIcon.Warning, 
                3000
            )
        
    def on_auto_check_finished(self, success, message):
        logger.info(f"Автопроверка завершена: {message}")
        self.status_label.setText("Готов к работе" if success else "Ошибка при проверке")
        self.progress_bar.setValue(0)
        if not success:
            self.tray_icon.showMessage(
                "Discord File Sender", 
                message,
                QSystemTrayIcon.MessageIcon.Warning, 
                3000
            )

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    full_config = {
                        **DEFAULT_CONFIG,
                        **config,
                        "MAIN_WEBHOOK_URL": os.getenv("MAIN_WEBHOOK_URL"),
                        "LOG_WEBHOOK_URL": os.getenv("LOG_WEBHOOK_URL"),
                        "ROLE_MENTION": os.getenv("ROLE_MENTION"),
                        "USER_MENTION": os.getenv("USER_MENTION")
                    }
                    return full_config
            return {
                **DEFAULT_CONFIG,
                "MAIN_WEBHOOK_URL": os.getenv("MAIN_WEBHOOK_URL"),
                "LOG_WEBHOOK_URL": os.getenv("LOG_WEBHOOK_URL"),
                "ROLE_MENTION": os.getenv("ROLE_MENTION"),
                "USER_MENTION": os.getenv("USER_MENTION")
            }
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {str(e)}")
            return {
                **DEFAULT_CONFIG,
                "MAIN_WEBHOOK_URL": os.getenv("MAIN_WEBHOOK_URL"),
                "LOG_WEBHOOK_URL": os.getenv("LOG_WEBHOOK_URL"),
                "ROLE_MENTION": os.getenv("ROLE_MENTION"),
                "USER_MENTION": os.getenv("USER_MENTION")
            }

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    if QApplication.instance() is not None:
        window = FileSenderApp()
        window.show()
        sys.exit(app.exec())
    else:
        logger.error("Не удалось запустить приложение")