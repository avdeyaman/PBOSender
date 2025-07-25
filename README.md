# PBOSender

Приложение на Python (PyQt6), которое автоматически находит `.pbo` файлы в указанной папке, сжимает их в архивы и отправляет на Discord через Webhook. Программа предназначена для регулярной отправки игровых миссий Arma 3 с уведомлениями о статусе операций.

---

## 🛠️ Основной функционал

- Мониторинг указанных по префиксу `.pbo` файлов в выбранной директории
- Автоматическая и ручная отправка измененных файлов в Discord
- Уведомления об ошибках и слишком больших файлах
- Логирование событий и отправок
- Графический интерфейс с треем
- Хранение истории изменений

---

## 🧩 Зависимости

- Python 3.8+
- pipenv
- PyQt6
- aiohttp
- PyInstaller

---

## ⚙️ Развёртывание проекта

- Загрузите и установите Python 3.8+
- Средствами консоли установите pipenv (если у вас не установлен) введя команду:
```
pip install pipenv
```
- Дале требуется установка всех зависимостей. Для этого введите команду в папке проекта:
```
pipenv install
```
- Запустите приложение проекта командой:
```
pipenv run main
```
- Для сборки проекта используйте команду:
```
pyinstaller --name "PBOSender" --icon=favicon.ico --add-data="favicon.ico;." --noconsole --onefile main.py
```

---

## 🧑‍💻 Использование приложения

- [Скачайте архив с приложением](https://github.com/avdeyaman/PBOSender);
- Распакуйте приложение в отдельную папку. В процессе работы будут созданы несколько файлов, нужных для работы программы;
- Запустите приложение через `pbosender.exe`;
- Выполните настройки с обязательным указанием Webhook URL и сохраните их;
- Нажмите кнопку "Отправить сейчас" или дождитесь автоматической проверки.

> [!WARNING]
> Если у вас появились ошибки и что-то не работает, пожалуйста, напишите в раздел [Issues](https://github.com/avdeyaman/PBOSender/issues) с указанием файла `.log`.