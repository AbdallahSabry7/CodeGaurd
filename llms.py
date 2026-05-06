import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from tools import analysis_tools, validator_tool


LLM = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY")
).bind_tools(analysis_tools)

LLM2 = ChatOpenAI(
    model="inclusionai/ling-2.6-1t:free",
    openai_api_key=os.environ["OPENROUTER_API_KEY"],
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0
)

LLM3 = ChatOpenAI(
    model="openrouter/owl-alpha",
    openai_api_key=os.environ["OPENROUTER_API_KEY"],
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0
).bind_tools(validator_tool)

