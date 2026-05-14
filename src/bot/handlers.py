import logging
from pathlib import Path

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Document, BufferedInputFile

from src.bot.states import AnalysisStates
from src.utils.dataset_io import load_dataset, profile_dataset, profile_to_text
from src.utils.temp_manager import get_chat_temp_dir, cleanup_chat_temp
from src.agent.react_loop import run_analysis

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

TELEGRAM_MAX_MESSAGE_LENGTH = 4000


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
async def skip_context(message: Message, state: FSMContext, bot: Bot) -> None:
    """Allow user to skip providing context."""
    await state.update_data(user_context="")
    await _start_analysis(message, state, bot)


@router.message(AnalysisStates.waiting_context)
async def handle_context(message: Message, state: FSMContext, bot: Bot) -> None:
    """Receive user instructions/context for the analysis."""
    user_context = message.text or ""
    await state.update_data(user_context=user_context)
    await _start_analysis(message, state, bot)


async def _start_analysis(message: Message, state: FSMContext, bot: Bot) -> None:
    """Trigger the analysis pipeline."""
    data = await state.get_data()
    file_path = data.get("file_path")
    profile = data.get("profile")
    user_context = data.get("user_context", "")

    if not file_path or not profile:
        await message.answer("Ошибка: данные о файле потеряны. Начни заново с /start.")
        await state.clear()
        return

    status_message = await message.answer("🚀 Начинаю анализ данных...")
    await state.set_state(AnalysisStates.analyzing)

    try:
        report, output_files = await run_analysis(
            bot=bot,
            chat_id=message.chat.id,
            dataset_path=file_path,
            profile=profile,
            user_context=user_context,
            status_message=status_message,
        )
    except Exception as exc:
        logger.error("Analysis failed for chat %s: %s", message.chat.id, exc)
        await status_message.edit_text(f"❌ Анализ завершился с ошибкой:\n<pre>{exc}</pre>")
        await state.clear()
        cleanup_chat_temp(message.chat.id)
        return

    # Send report
    await _send_report(bot, message.chat.id, report, status_message)

    # Send output files (plots)
    if output_files:
        await _send_output_files(bot, message.chat.id, output_files, status_message)

    await state.clear()
    cleanup_chat_temp(message.chat.id)
    logger.info("Analysis completed for chat %s", message.chat.id)


async def _send_report(
    bot: Bot,
    chat_id: int,
    report: str,
    status_message: Message,
) -> None:
    """Send the final report, splitting if too long."""
    if not report.strip():
        await status_message.edit_text("✅ Анализ завершён, но отчёт пуст.")
        return

    # If report is short enough, edit the status message
    if len(report) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        await status_message.edit_text(f"📊 <b>Отчёт по анализу</b>\n\n{report}")
        return

    # Otherwise send as new messages
    await status_message.edit_text("📊 <b>Отчёт по анализу</b> (слишком длинный, отправляю частями):")
    for i in range(0, len(report), TELEGRAM_MAX_MESSAGE_LENGTH):
        chunk = report[i:i + TELEGRAM_MAX_MESSAGE_LENGTH]
        await bot.send_message(chat_id, chunk)


async def _send_output_files(
    bot: Bot,
    chat_id: int,
    output_files: dict[str, bytes],
    status_message: Message,
) -> None:
    """Send generated plots and files to the user."""
    for filename, filedata in output_files.items():
        try:
            input_file = BufferedInputFile(file=filedata, filename=filename)
            if filename.lower().endswith(".png"):
                await bot.send_photo(chat_id, photo=input_file, caption=f"📈 {filename}")
            else:
                await bot.send_document(chat_id, document=input_file, caption=f"📎 {filename}")
        except Exception as exc:
            logger.error("Failed to send file %s: %s", filename, exc)
            await bot.send_message(chat_id, f"⚠️ Не удалось отправить файл {filename}: {exc}")


@router.message(AnalysisStates.analyzing)
async def handle_while_analyzing(message: Message) -> None:
    """Inform user that analysis is in progress."""
    await message.answer("Анализ уже выполняется. Пожалуйста, подожди завершения.")
