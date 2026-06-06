from pydantic_settings import BaseSettings , SettingsConfigDict

class Settings(BaseSettings):
    GROQ_API_KEY: str
    HUGGINGFACE_API_KEY: str
    LANGSMITH_API_KEY: str
    SERPAPI_API_KEY: str
    OPENROUTER_API_KEY: str
    LANGCHAIN_TRACING_V2: str
    LANGCHAIN_ENDPOINT: str
    LANGCHAIN_PROJECT: str


    model1: str
    model2: str
    model3: str
    model4: str
    max_iterations: int
    openai_api_base : str

    model_config = SettingsConfigDict(env_file=".env")

def get_settings():
    return Settings()