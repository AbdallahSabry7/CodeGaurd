import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from helpers.config import get_settings, Settings

settings = get_settings()

LLM2 = ChatOpenAI(
    model= settings.model1,
    openai_api_key=settings.OPENROUTER_API_KEY,
    openai_api_base=settings.openai_api_base,
    temperature=0.2,
)

LLM3 = ChatGroq(
    model= settings.model2,
    api_key=settings.GROQ_API_KEY,
    temperature=0.1,
)
