from typing import Optional
from openai import AsyncOpenAI

from app.config import settings


client = AsyncOpenAI(
    base_url=settings.qwen_base_url,
    api_key=settings.qwen_api_key,
)


async def call_qwen(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    if not settings.qwen_api_key:
        return "LLM not configured."

    try:
        response = await client.chat.completions.create(
            model=settings.qwen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        if not response.choices:
            return "LLM returned no choices."
        message = response.choices[0].message
        if message is None:
            return "LLM returned no message."
        return message.content or ""
    except Exception as e:
        return f"LLM request failed: {type(e).__name__}: {e}"
