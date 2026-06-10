from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    # models
    model1: str = "openai/gpt-oss-120b"
    model2: str = "llama-3.3-70b-versatile"
    model3: str = "openai/gpt-oss-20b"
    model4: str = "openai/gpt-oss-120b:free"

    # langsmith / langchain (optional)
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_PROJECT: str = "CodeGuard"

    # tuning
    max_iterations: int = 3
    max_improvement_loops: int = 3
    min_gain: float = 0.05

    openai_api_base: str = "https://openrouter.ai/api/v1"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,   
        extra="ignore",       
    )


def get_settings() -> Settings:
    return Settings()