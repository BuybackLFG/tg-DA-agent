import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.bot.handlers import router as bot_router


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def validate_settings() -> None:
    """Validate critical settings before starting the bot."""
    errors: list[str] = []

    if not settings.bot_token or "your" in settings.bot_token.lower():
        errors.append("BOT_TOKEN не настроен (указан placeholder в .env?)")

    if not settings.llm_api_key or "your" in settings.llm_api_key.lower():
        errors.append("LLM_API_KEY не настроен (указан placeholder в .env?)")

    if not settings.llm_base_url:
        errors.append("LLM_BASE_URL не настроен")

    if errors:
        raise RuntimeError(
            "\n".join(["❌ Ошибка конфигурации:"] + errors + ["", "Проверьте файл .env и перезапустите бота."])
        )


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        validate_settings()
    except RuntimeError as exc:
        logger.critical(str(exc))
        raise

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(bot_router)

    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
