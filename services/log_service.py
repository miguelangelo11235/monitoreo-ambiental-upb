import os
import logging
from core.config import settings


def setup_logger(name: str = "monitoring", level: str = None) -> logging.Logger:
    log_level = level or settings.log_level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    if not logger.handlers:
        # Formato de logs
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )

        # Handler consola
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Handler archivo
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "monitoring.log"), encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class LogService:
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        return setup_logger(name)
