from pathlib import Path
from pydantic_settings import BaseSettings

# Resolve the project root .env regardless of where uvicorn is launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sec_analyst"
    sec_user_agent: str = "SEC Analyst App contact@example.com"
    qwen_base_url: str = "https://ws-0exjku32k70c5ir6.ap-southeast-1.maas.aliyuncs.com/api/v1"
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    prefetch_enabled: bool = True
    environment: str = "production"

    class Config:
        env_file = str(_ENV_FILE)


settings = Settings()
