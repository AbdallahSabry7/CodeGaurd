import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from helpers.config import get_settings, Settings
from schemas.characterization import CharacterizationSpec

settings = get_settings()

translator_llm = ChatGroq(
    model= settings.model1,
    api_key=settings.GROQ_API_KEY,
    temperature=0.2,
)

refactor_llm = ChatGroq(
    model= settings.model1,
    api_key=settings.GROQ_API_KEY,
    temperature=0.1,
)

characterize_llm = ChatGroq(
    model= settings.model2,
    api_key=settings.GROQ_API_KEY,
    temperature=0.1,
)


characterize_structured = characterize_llm.with_structured_output(
    CharacterizationSpec, method="json_mode", include_raw=True
)

_OPENAI_BASE = getattr(settings, "openai_api_base", None) or os.getenv(
    "openai_api_base", "https://openrouter.ai/api/v1"
)

architect_llm = ChatOpenAI(
    model=settings.model4 or "openai/gpt-oss-120b:free",
    openai_api_key=settings.OPENROUTER_API_KEY,
    openai_api_base=_OPENAI_BASE,
    temperature=0.2,
    default_headers={
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "CodeGuard",
    },
)

report_llm = ChatGroq(
	model=settings.model3,          
	api_key=settings.GROQ_API_KEY,
	temperature=0.2,
)


