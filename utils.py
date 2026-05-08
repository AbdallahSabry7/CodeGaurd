# utils.py
import time
import logging
from groq import BadRequestError

logger = logging.getLogger(__name__)

def invoke_with_retry(llm, messages, max_retries: int = 5, base_delay: float = 0.5):
    """
    Retries LLM invocation on Groq's intermittent tool-name error.
    Uses exponential backoff with jitter.
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            return llm.invoke(messages)

        except BadRequestError as e:
            error_msg = str(e)
            is_tool_name_error = "Tools should have a name" in error_msg

            if not is_tool_name_error:
                raise  # don't retry unrelated 400 errors

            last_error = e
            delay = base_delay * (2 ** (attempt - 1))  # 0.5 → 1 → 2 → 4 → 8s
            jitter = delay * 0.2                        # ±20% jitter
            sleep_time = delay + (jitter * (2 * __import__('random').random() - 1))

            logger.warning(
                f"[Groq tool-name error] attempt {attempt}/{max_retries} "
                f"— retrying in {sleep_time:.2f}s"
            )
            time.sleep(sleep_time)

    raise last_error