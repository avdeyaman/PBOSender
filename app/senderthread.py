import asyncio

import json

import app.logger as logger

from os import getenv, walk, path, remove

from hashlib import sha256

from zipfile import ZipFile, ZIP_DEFLATED

from aiohttp import ClientSession

from PyQt6.QtCore import QThread
from PyQt6.QtCore import pyqtSignal

from pathlib import Path


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

        zip_files: list[set] = self.zip_files_for_send(changed_pbo_files)
        if not zip_files:
            return 'error'

        self.status_changed.emit('Запуск процесса отправки...')
        self.logger.info('Запуск процесса отправки...')

        async with ClientSession() as session:
            await self.send_files(session, zip_files)

        self.logger.info('Файлы отправлены')

        self.delete_temp_zip_files(zip_files)
        self.save_files_hash()

        return 'success'


    async def send_files(self, session, files_data: list[set]):
        """Отправляет указанный список файлов используя Discord Webhook.

        Parameters
        ----------
        session
            открытая сессия соединения
        files_data : list[set]
            список данных о файлах
        """

        send_tasks = []

        for file_data in files_data:
            file_hash = self.files_hash.get(file_data['file_name'])
            send_task = self.send_file(session, f'SHA256: {file_hash}', file_data['path'])
            send_tasks.append(send_task)
            self.status_changed.emit(f'Отправка {file_data['file_name']}...')
            await asyncio.sleep(0.3)

        await asyncio.gather(*send_tasks, return_exceptions=False)


    async def send_file(self, session, content: str, file_path: str) -> bool:
        """Отправляет указанный файл ввиде сообщения используя метод POST
        по адресу Discord WebHook из окружения.

        Parameters
        ----------
        session
            открытая сессия соединения
        content : str
            содержание сообщения
        file_path : str

        Returns
        -------
        bool
            True если отправлено успешно, иначе False
        """

        WEBHOOK_URL = getenv('DISCORD_FILES_WEBHOOK_URL')

        file_name = path.basename(file_path)
        opened_file = open(file_path, 'rb')

        data = {
            'content': content,
            'file': opened_file
        }

        try:
            async with session.post(WEBHOOK_URL, data=data) as response:
                if response.status != 200:
                    self.logger.error(f'Ошибка {response.status} при отправке файла {file_name}. Ответ:\n{await response.text()}')
                    return False

                self.logger.info(f'Файл {file_name} отправлен')
                return True
        except Exception as e:
            self.logger.error(f'Ошибка при отправке файла {file_name}! Ошибка:\n{str(e)}')
            return False
        finally:
            opened_file.close()


    def read_files_hash(self):
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

            self.status_label.setText('Хэш файлов сохранён')
            self.logger.info('Хэш файлов сохранён')
        except Exception as e:
            self.status_label.setText('Ошибка сохранения хэшей. Детали в файле .log')
            self.logger.info(f'Ошибка при сохранении файла хэшей! Ошибка:\n{str(e)}')


    def get_all_files(self) -> list[str]:
        """Возвращает все файлы из указанной в конфигруации папке.

        Returns
        -------
        list[str]
            список имён файлов в папке
        """

        search_path = self.user_config['search_folder']

        files: list[str] = []

        for (_dir_path, _dir_names, file_names) in walk(search_path):
            files.extend(file_names)
            break

        return files


    def get_files_with_prefix(self, files: list[str], prefix: str) -> list[str]:
        """Возвращает файлы с указанным префиксом и расширением .pbo

        Example
        -------------------
        Параметры:<br/>
        <code>
        files = ['Jango_Altis.pbo', 'UTF_Vanilla_Altis.pbo', 'Jango_Stratis.pbo']<br/>
        prefix = 'UTF'
        </code>

        Результат:<br/>
        <code>result_files = ['UTF_Vanilla_Altis.pbo']</code>

        Parameters
        ----------
        files : list[str]
            список имён файлов
        prefix : str
            префикс

        Returns
        -------
        list[str]
            список найденых файлов
        """

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
        """Находит и возвращает список изменённых файлов.
        Проверка осуществляется через хэш SHA256."""

        SEARCH_FOLDER_PATH = self.user_config['search_folder']
        changed_files: list[str] = []

        self.logger.info(f'Начато сравнение файлов {files}')

        for file_name in files:
            self.logger.info(f'{SEARCH_FOLDER_PATH}\\{file_name}')

            file_path = f'{SEARCH_FOLDER_PATH}\\{file_name}'

            file_hash = self.files_hash.get(file_name, '')

            self.logger.info(f'Начато сравнение файла {file_path} {file_hash}')
            if self.is_cur_file_equals_prev(file_path, file_hash):
                continue

            changed_files.append(file_name)
            self.files_hash[file_name] = self.hash_file(file_path)

        return changed_files


    def is_cur_file_equals_prev(self, current_file_path: str, prev_sha256_hash: str):
        """Сверяет файлы используя хэш SHA256.

        Parameters
        ----------
        current_file_path : str
            путь к текущему файлу
        prev_sha256_hash : str
            хэш предыдущего файла

        Returns
        -------
        bool
            True, если текущий файл равен предыдущему, иначе False
        """

        current_sha256_hash: str = self.hash_file(current_file_path)

        return current_sha256_hash == prev_sha256_hash


    def zip_files_for_send(self, files: list[str]) -> list[set]:
        """Архивирует указанный список файлов в ZIP архивы.

        Parameters
        ----------
        files : list[str]
            список файлов для архивации

        Returns
        -------
        list[set]
            список данных об архивах
        """

        SEARCH_FOLDER_PATH = self.user_config['search_folder']
        zip_files: list[set] = []

        for file_name in files:
            file_path = str(Path(SEARCH_FOLDER_PATH) / file_name)

            if not path.exists(file_path):
                self.logger.warning(f'Файл {file_name} не найден!')
                continue

            zip_file_name: str = f'{file_name}.zip'
            zip_file_path: str = f'{path.dirname(__file__)}\\{zip_file_name}'

            zip_result_path = self.zip_file(file_path, zip_file_path)
            if not zip_result_path:
                continue

            zip_file_data = {
                'path': zip_result_path,
                'file_name': file_name
            }

            zip_files.append(zip_file_data)

        return zip_files


    def zip_file(self, source_path: str, zip_path: str) -> str | None:
        """Создаёт ZIP архив с указанным файлом.
        В случае ошибки, вернёт None.

        Parameters
        ----------
        source_path : str
            файл для архивации
        zip_path : str
            путь по которому будет записан архив

        Returns
        -------
        str
            путь к записанному архиву или None
        """

        file_basename = path.basename(source_path)

        try:
            with ZipFile(zip_path, 'w', ZIP_DEFLATED) as archive:
                archive.write(source_path, file_basename)

            original_size = path.getsize(source_path) / (1024 * 1024)
            compresed_size = path.getsize(zip_path) / (1024 * 1024)
            compression_ratio = (1 - (compresed_size / original_size)) * 100

            self.logger.info(f'Файл {file_basename} сжат: {original_size}MB -> {compresed_size}MB ({compression_ratio}%)')
            return zip_path
        except Exception as e:
            self.logger.error(f'Ошибка при создания ZIP архива для {file_basename}. Ошибка:\n{str(e)}')
            return None


    def hash_file(self, file_path: str) -> str:
        """Создаёт хэш SHA256 для указанного файла.

        Parameters
        ----------
        file_path : str
            путь к файлу

        Returns
        -------
        str
            хэш SHA256
        """

        BUF_SIZE = 65536

        sha256_file_hash = sha256()

        with open(file_path, 'rb') as f:
            while True:
                data = f.read(BUF_SIZE)

                if not data:
                    break

                sha256_file_hash.update(data)

        return sha256_file_hash.hexdigest()


    def delete_temp_zip_files(self, files_data: list[set]):
        """Удаляет временные ZIP файлы.

        Parameters
        ----------
        files_data : list[set]
            данные файлов для удаления
        """

        for file_data in files_data:
            file_name = file_data['file_name']
            file_path = file_data['path']

            try:
                remove(file_path)
                self.logger.info(f'Временный ZIP файл {file_name} удалён')
            except Exception as e:
                self.logger.error(f'Ошибка при удалении временного ZIP файла {file_name}! Ошибка:\n{str(e)}')