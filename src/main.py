import asyncio
import logging

from src.config import settings


async def main():
    logging.basicConfig(level=settings.log_level)
    # TODO: initialize dispatcher and bot
    pass


if __name__ == "__main__":
    asyncio.run(main())
