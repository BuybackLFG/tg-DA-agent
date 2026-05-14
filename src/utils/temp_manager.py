import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_TEMP_DIR = Path("tmp")


def get_chat_temp_dir(chat_id: int) -> Path:
    """Return (and create if needed) the temporary directory for a given chat."""
    directory = BASE_TEMP_DIR / str(chat_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cleanup_chat_temp(chat_id: int) -> None:
    """Remove all temporary files for a specific chat."""
    directory = BASE_TEMP_DIR / str(chat_id)
    if directory.exists():
        shutil.rmtree(directory)
        logger.info("Cleaned up temp dir for chat %s", chat_id)


def cleanup_all() -> None:
    """Remove the entire temporary directory tree."""
    if BASE_TEMP_DIR.exists():
        shutil.rmtree(BASE_TEMP_DIR)
        logger.info("Cleaned up all temp directories")
