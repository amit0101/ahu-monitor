"""
api/assistant.py — GPT-4o powered aQ Assistant endpoint.

Receives the full chat history (with injected system context) and
streams or returns a single completion.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/assistant")
async def chat_assistant(body: ChatRequest):
    """Forward chat to OpenAI GPT-4o and return assistant reply."""
    if not settings.openai_api_key:
        return {
            "content": (
                "⚠ OpenAI API key not configured. Add OPENAI_API_KEY to backend/.env "
                "and restart the server to enable the aQ Assistant."
            )
        }

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": m.role, "content": m.content} for m in body.messages],
            max_tokens=500,
            temperature=0.3,  # Low temp: factual, engineering-focused
        )
        content = response.choices[0].message.content or ""
        return {"content": content}

    except Exception as exc:
        logger.error("OpenAI error: %s", exc)
        return {"content": f"⚠ Assistant error: {exc}"}
