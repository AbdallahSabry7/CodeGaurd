import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from helpers.config import get_settings, Settings

settings = get_settings()

LLM = chatGroq = ChatGroq(
    model= settings.model3,
    api_key=settings.GROQ_API_KEY,
    temperature=0.2,
)

LLM2 = ChatOpenAI(
    model= settings.model1,
    openai_api_key=settings.OPENROUTER_API_KEY,
    openai_api_base=settings.openai_api_base,
    temperature=0.2,
    default_headers={
        "HTTP-Referer": "http://localhost:3000",  # localhost is fine
        "X-Title": "CodeGuard",
    },
)

LLM3 = ChatGroq(
    model= settings.model2,
    api_key=settings.GROQ_API_KEY,
    temperature=0.1,
)

architect_llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=settings.GROQ_API_KEY,
    temperature=0,
    max_retries=2,
)
