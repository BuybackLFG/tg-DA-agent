import logging
from pathlib import Path

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Document

from src.bot.states import AnalysisStates
from src.utils.dataset_io import load_dataset, profile_dataset, profile_to_text
from src.utils.temp_manager import get_chat_temp_dir

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start: reset state and ask for a dataset."""
    await state.clear()
    await message.answer(
        "Привет! Я агент для анализа данных.\n\n"
        "Отправь мне файл датасета (CSV или Excel), чтобы начать анализ."
    )
    await state.set_state(AnalysisStates.waiting_file)


@router.message(
    AnalysisStates.waiting_file,
    F.document,
)
async def handle_document(message: Message, state: FSMContext, bot: Bot) -> None:
    """Handle dataset file upload."""
    document: Document = message.document
    file_name = document.file_name or "dataset"
    file_path = Path(file_name)
    ext = file_path.suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        await message.answer(
            f"Неподдерживаемый формат: {ext}. Пожалуйста, отправь CSV или Excel файл."
        )
        return

    temp_dir = get_chat_temp_dir(message.chat.id)
    local_path = temp_dir / file_name

    try:
        await bot.download(document, destination=local_path)
        logger.info("Downloaded file from chat %s to %s", message.chat.id, local_path)
    except Exception as exc:
        logger.error("Failed to download file: %s", exc)
        await message.answer("Не удалось загрузить файл. Попробуй ещё раз.")
        return

    # Load and profile the dataset
    try:
        df = load_dataset(local_path)
        profile = profile_dataset(df)
        profile_text = profile_to_text(profile)
        logger.info("Profiled dataset for chat %s: %s rows", message.chat.id, profile["shape"]["rows"])
    except Exception as exc:
        logger.error("Failed to profile dataset: %s", exc)
        await message.answer("Файл загружен, но не удалось прочитать датасет. Проверь формат файла.")
        return

    await state.update_data(
        file_path=str(local_path),
        file_name=file_name,
        profile=profile,
    )

    await message.answer(
        f"Файл <b>{file_name}</b> получен.\n\n"
        f"<pre>{profile_text}</pre>\n\n"
        "Теперь напиши, что именно нужно проанализировать — контекст, вопросы, на что обратить внимание. "
        "Или отправь /skip, если хочешь, чтобы я сам выбрал направление анализа."
    )
    await state.set_state(AnalysisStates.waiting_context)


@router.message(AnalysisStates.waiting_file)
async def handle_non_file(message: Message) -> None:
    """Remind user to send a file when in waiting_file state."""
    await message.answer("Пожалуйста, отправь файл датасета (CSV или Excel).")


@router.message(AnalysisStates.waiting_context, Command("skip"))
async def skip_context(message: Message, state: FSMContext) -> None:
    """Allow user to skip providing context."""
    await state.update_data(user_context="")
    await message.answer("Контекст не указан. Начинаю анализ...")
    await state.set_state(AnalysisStates.analyzing)
    # TODO: trigger analysis pipeline (Step 7+)


@router.message(AnalysisStates.waiting_context)
async def handle_context(message: Message, state: FSMContext) -> None:
    """Receive user instructions/context for the analysis."""
    user_context = message.text or ""
    await state.update_data(user_context=user_context)
    await message.answer("Контекст получен. Начинаю анализ данных...")
    await state.set_state(AnalysisStates.analyzing)
    # TODO: trigger analysis pipeline (Step 7+)


@router.message(AnalysisStates.analyzing)
async def handle_while_analyzing(message: Message) -> None:
    """Inform user that analysis is in progress."""
    await message.answer("Анализ уже выполняется. Пожалуйста, подожди завершения.")
