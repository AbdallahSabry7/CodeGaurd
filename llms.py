import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from tools import analysis_tools, validator_tool


LLM = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY")
).bind_tools(analysis_tools)

LLM2 = ChatOpenAI(
    model="poolside/laguna-m.1:free",
    openai_api_key=os.environ["OPENROUTER_API_KEY"],
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0
)

LLM3 = ChatGroq(
    model="qwen/qwen3-32b",
    api_key=os.getenv("GROQ_API_KEY")
).bind_tools(validator_tool)

