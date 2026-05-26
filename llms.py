import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

LLM2 = ChatOpenAI(
    model="openrouter/owl-alpha",
    openai_api_key=os.environ["OPENROUTER_API_KEY"],
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0,
)

LLM3 = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.getenv("GROQ_API_KEY"),
)
