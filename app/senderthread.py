import asyncio
import json
import os
from datetime import datetime
from hashlib import sha256
from os import walk, path, remove
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import aiohttp
from PyQt6.QtCore import QThread, pyqtSignal

import app.logger as logger


class SenderThread(QThread):
    """Класс процесса отправщика файлов. Наследует <code>QThread</code>."""

    finished = pyqtSignal(dict)
    status_changed = pyqtSignal(str)

    def __init__(self, user_config: dict):
        """Инициализирует новый экземпляр процесса отправщика.

        Parameters
        ----------
        user_config : dict
            конфигурация пользователя
        """

        super().__init__()
        self.logger = logger.setup_logging(__name__)
        self.HASH_FILE_PATH = 'pbo_sender_files_hash.json'
        self.user_config = user_config
        self.files_hash = self.read_files_hash()


    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.async_find_and_send_files())
            loop.close()

            match result:
                case 'success':
                    self.finished.emit({'successful': True, 'message': 'Файлы успешно отправлены'})
                case 'no_files':
                    self.finished.emit({'successful': True, 'message': 'Нет новых файлов для отправки'})
                case _:
                    self.finished.emit({'successful': False, 'message': f'Ошибка при отправке файлов. {str(result)}'})
        except Exception as e:
            self.finished.emit({'successful': False, 'message': f'Критическая ошибка: {str(e)}'})
            self.logger.error(f'Критическая ошибка: {str(e)}')


    async def async_find_and_send_files(self) -> str:
        """Запускает процесс поиска и отправки файлов."""

        self.logger.info('Начат процесс поиска и отправки файлов')

        self.logger.info('Поиск нужных файлов...')
        all_files: list[str] = self.get_all_files()
        pbo_files: list[str] = self.get_files_with_prefix(all_files, self.user_config['target_files_prefix'])

        self.status_changed.emit('Сравнение файлов...')
        self.logger.info('Начато сравнение файлов через SHA256')

        changed_pbo_files: list[str] = self.get_changed_files(pbo_files)

        if not changed_pbo_files:
            self.logger.info('Нет новых файлов для отправки')
            return 'no_files'

        self.status_changed.emit(f'Найдено для отправки: {len(changed_pbo_files)}')
        self.logger.info(f'Найдено новых файлов для отправки: {len(changed_pbo_files)}')

        zip_files: list[dict] = self.zip_files_for_send(changed_pbo_files)
        if not zip_files:
            return 'error'

        self.status_changed.emit('Запуск процесса отправки...')
        self.logger.info('Запуск процесса отправки...')

        async with aiohttp.ClientSession() as session:
            await self.send_files(session, zip_files)

        self.logger.info('Файлы отправлены')
        self.delete_temp_zip_files(zip_files)
        self.save_files_hash()

        return 'success'


    async def send_files(self, session, files_data: list[dict]):
        """Отправляет указанный список файлов используя Discord Webhook.

        Parameters
        ----------
        session : ClientSession
            сессия aiohttp
        files_data : list[dict]
            список данных о файлах
        """

        send_tasks = []
        oversized_files = []

        for file_data in files_data:
            file_name: str = file_data['file_name']

            if file_data['compressed_size'] > self.user_config['max_file_size_mb']:
                self.status_changed.emit(f'Пропуск {file_name} (большой размер)')
                self.logger.info(f'Пропуск отправки файла {file_name}. Превышает допустимый размер')
                oversized_files.append(file_data)
                continue

            send_task = self.send_file(session, file_data['path'])
            send_tasks.append(send_task)

            self.status_changed.emit(f'Отправка {file_name}...')

            await asyncio.sleep(0.5)

        if oversized_files:
            admin_id: str = self.user_config['discord_admin_id']

            send_message_task = self.send_message_about_oversized_files(session, admin_id, oversized_files)
            send_tasks.append(send_message_task)

        if send_tasks:
            await asyncio.gather(*send_tasks, return_exceptions=False)


    async def send_file(self, session, file_path: str) -> bool:
        """Отправляет файл на сервер через Discord Webhook.

        Parameters
        ----------
        session : ClientSession
            сессия aiohttp
        file_path : str
            путь к файлу

        Returns
        -------
        bool
            True если отправка успешна, иначе False
        """

        try:
            zip_filename = os.path.basename(file_path)
            original_filename = zip_filename.replace('.zip', '')

            timestamp = datetime.fromtimestamp(os.path.getmtime(file_path))
            timestamp_str = timestamp.strftime('%d.%m %H:%M')

            with open(file_path, "rb") as file_for_send:
                file_message_data = self.make_message_data(
                    text=f'{original_filename} — {timestamp_str}',
                    opened_file=file_for_send
                )

                response: bool = await self.send_message(session, file_message_data)
                if not response:
                    self.status_changed.emit(f'Ошибка при отправке файла {original_filename}')

                return response
        except Exception as e:
            self.status_changed.emit(f"Ошибка при отправке файла {original_filename}: {str(e)}")
            return False


    async def send_message(self, session, message_data: dict) -> bool:
        """Отправляет сообщение с указанными данным используя Discrod Webhook.

        Parameters
        ----------
        session : ClientSession
            сессия aiohttp
        message_data : dict
            данные сообщения
        """

        async with session.post(self.user_config['webhook_url'], data=message_data) as resp:
            if resp.status != 200:
                self.logger.error(f'Ошибка {resp.status} при отправке сообщения!')
                return False

            return True


    async def send_message_about_oversized_files(self, session, admin_id: str, oversized_files: list):
        """Отправляет сообщение о файлах, привыщающий допустимый для отправки размер.

        Parameters
        ----------
        session : ClientSession
            сессия aiohttp
        admin_id : str
            идентификатор Discord администратора
        oversized_files : list
            список файлов, которые при
        """

        embed_description = ''
        for big_file in oversized_files:
            embed_description += f'{big_file['file_name']} ({big_file['compressed_size']:.2f} MB)\n'

        oversized_files_message_data = self.make_message_data(
            text=f'<@{admin_id}> Следующие файлы превышают допустимый размер:',
            embeds=[{'description': embed_description}]
        )

        response: bool = await self.send_message(session, oversized_files_message_data)
        if not response:
            self.status_changed.emit(f'Ошибка при отправке сообщения администратору')
            self.logger.error('Ошибка при отправке сообщения администратору!')


    def make_message_data(self, text: str, embeds: list = None, opened_file = None):
        """Создаёт и возвращает данные сообщения в формате JSON.\n
        Поддерживает добавление Embeds и файлов.

        Parameters
        ----------
        text : str
            текст сообщения
        embeds : list
            эмбеды
        opened_file
            содержит считанный файл
        """

        message_data = {'content': text}
        if embeds:
            message_data['embeds'] = embeds
        if opened_file:
            message_data['file'] = opened_file

        return message_data


    def read_files_hash(self) -> dict:
        """Считывает хэш файлов из файла в формате JSON."""

        self.logger.info('Чтение хэша файлов...')

        try:
            if not path.exists(self.HASH_FILE_PATH):
                self.logger.warning('Файл хэшей отсутствует')
                return {}

            with open(self.HASH_FILE_PATH, 'r', encoding='utf-8') as hash_file:
                self.logger.info('Файл хэшей считан')
                return json.load(hash_file)
        except Exception as e:
            self.logger.error(f'Ошибка при чтении файла хэшей! Ошибка:\n{str(e)}')
            return {}


    def save_files_hash(self):
        """Записывает хэш файлов в файл формата JSON."""

        self.logger.info('Сохранение хэша файлов...')

        try:
            with open(self.HASH_FILE_PATH, 'w', encoding='utf-8') as hash_file:
                json.dump(self.files_hash, hash_file, indent=2, ensure_ascii=False)
            self.logger.info('Хэш файлов сохранён')
        except Exception as e:
            self.logger.error(f'Ошибка сохранения хэшей: {str(e)}')


    def get_all_files(self) -> list[str]:
        """Возвращает все файлы из указанной в конфигруации папке."""

        search_path = self.user_config['search_folder']
        files: list[str] = []

        for (_, _, file_names) in walk(search_path):
            files.extend(file_names)
            break

        return files


    def get_files_with_prefix(self, files: list[str], prefix: str) -> list[str]:
        """Возвращает файлы с указанным префиксом и расширением .pbo"""

        pbo_files: list[str] = []

        for file_name in files:
            if not file_name.startswith(prefix):
                self.logger.warning(f'Пропуск файла {file_name}: не имеет префикса {prefix}')
                continue
            if not file_name.endswith('.pbo'):
                self.logger.warning(f'Пропуск файла {file_name}: не имеет формата .pbo')
                continue

            pbo_files.append(file_name)

        return pbo_files


    def get_changed_files(self, files: list[str]) -> list[str]:
        """Находит и возвращает список изменённых файлов."""

        SEARCH_FOLDER_PATH = self.user_config['search_folder']
        changed_files: list[str] = []

        for file_name in files:
            file_path = str(Path(SEARCH_FOLDER_PATH) / file_name)
            file_hash = self.files_hash.get(file_name, '')

            if self.is_cur_file_equals_prev(file_path, file_hash):
                continue

            changed_files.append(file_name)
            self.files_hash[file_name] = self.hash_file(file_path)

        return changed_files


    def is_cur_file_equals_prev(self, current_file_path: str, prev_sha256_hash: str) -> bool:
        """Сверяет файлы используя хэш SHA256."""

        current_sha256_hash: str = self.hash_file(current_file_path)
        return current_sha256_hash == prev_sha256_hash


    def zip_files_for_send(self, files: list[str]) -> list[dict]:
        """Архивирует указанный список файлов в ZIP архивы."""

        SEARCH_FOLDER_PATH = self.user_config['search_folder']
        zip_files: list[dict] = []

        for file_name in files:
            file_path = str(Path(SEARCH_FOLDER_PATH) / file_name)

            if not path.exists(file_path):
                self.logger.warning(f'Файл {file_name} не найден!')
                continue

            zip_file_name = f'{file_name}.zip'
            zip_file_path = str(Path(SEARCH_FOLDER_PATH) / zip_file_name)
            zip_result_path = self.zip_file(file_path, zip_file_path)

            if not zip_result_path:
                continue

            compressed_size = path.getsize(zip_result_path) / (1024 * 1024)

            zip_files.append({
                'path': zip_result_path,
                'file_name': file_name,
                'compressed_size': compressed_size
            })

        return zip_files


    def zip_file(self, source_path: str, zip_path: str) -> str | None:
        """Создаёт ZIP архив с указанным файлом."""

        file_basename = path.basename(source_path)

        try:
            with ZipFile(zip_path, 'w', ZIP_DEFLATED) as archive:
                archive.write(source_path, file_basename)

            original_size = path.getsize(source_path) / (1024 * 1024)
            compressed_size = path.getsize(zip_path) / (1024 * 1024)
            compression_ratio = (1 - (compressed_size / original_size)) * 100

            self.logger.info(f'Файл {file_basename} сжат: {original_size:.2f}MB -> {compressed_size:.2f}MB ({compression_ratio:.1f}%)')
            return zip_path
        except Exception as e:
            self.logger.error(f'Ошибка при создании ZIP архива для {file_basename}. Ошибка:\n{str(e)}')
            return None


    def hash_file(self, file_path: str) -> str:
        """Создаёт хэш SHA256 для указанного файла."""

        BUF_SIZE = 65536
        sha256_file_hash = sha256()

        with open(file_path, 'rb') as f:
            while True:
                data = f.read(BUF_SIZE)
                if not data:
                    break
                sha256_file_hash.update(data)

        return sha256_file_hash.hexdigest()


    def delete_temp_zip_files(self, files_data: list[dict]):
        """Удаляет временные ZIP файлы."""

        for file_data in files_data:
            try:
                remove(file_data['path'])
                self.logger.info(f'Временный ZIP файл {file_data["file_name"]} удалён')
            except Exception as e:
                self.logger.error(f'Ошибка при удалении временного ZIP файла {file_data["file_name"]}! Ошибка:\n{str(e)}')