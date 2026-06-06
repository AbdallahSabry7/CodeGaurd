from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # required
    GROQ_API_KEY: str
    OPENROUTER_API_KEY: str
    model1: str
    model2: str
    model3: str

    # optional / defaulted
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_PROJECT: str = "CodeGuard"
    model4: str = ""
    max_iterations: int = 3
    openai_api_base: str = "https://openrouter.ai/api/v1"

    model_config = SettingsConfigDict(env_file=".env")

def get_settings():
    return Settings()