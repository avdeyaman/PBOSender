import logging


def setup_logging(module_name: str):
    """Создаёт и возвращает логгер для конкретного модуля.

    Parameters
    ----------
    module_name : str
        имя модуля Python

    Returns
    -------
    Logger
        логгер модуля
    """

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('pbo_sender.log', encoding='utf-8')
        ]
    )

    return logging.getLogger(module_name)