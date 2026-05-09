import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from tools import analysis_tools, validator_tool


LLM = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature = 0,
    max_retries = 2
).bind_tools(analysis_tools, parallel_tool_calls=False)

LLM2 = ChatOpenAI(
    model="poolside/laguna-m.1:free",
    openai_api_key=os.environ["OPENROUTER_API_KEY"],
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0,
)

LLM3 = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.getenv("GROQ_API_KEY"),
).bind_tools(validator_tool, parallel_tool_calls=False)
