from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    bot_token: str

    # LLM (OpenAI-compatible)
    llm_api_key: str
    llm_base_url: str = "https://inference.canopywave.io/v1"
    llm_model: str = "moonshot/kimi-k2.6"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Sandbox
    sandbox_timeout: int = 60
    sandbox_memory_limit: str = "512m"
    sandbox_cpu_limit: str = "1.0"

    # App
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
