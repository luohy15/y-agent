from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.entity.dto import Chat, Message
from storage.service import bot_config as bot_service
from storage.repository import chat as chat_repo
from storage.util import generate_id, generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp

router = APIRouter(prefix="/inline")

# Inline rewrites use a dedicated bot config (by convention named "inline"),
# so the user can pin a fast model — typically Gemini Flash via OpenRouter —
# independent of whatever the main agent backend is set to. The endpoint
# speaks OpenAI's /chat/completions shape; pick a bot whose base_url is
# compatible (OpenRouter, OpenAI itself, Google's OpenAI-compat endpoint…).
INLINE_BOT_NAME = "inline"
INLINE_TOPIC = "inline"
INLINE_MAX_TOKENS = 2000
INLINE_TIMEOUT = 30.0

SYSTEM_PROMPT = (
    "You are an inline writing assistant. The user has selected a piece of text "
    "and given an instruction. Apply the instruction to the selection and return "
    "ONLY the transformed text — no explanations, no quotes, no prefatory remarks. "
    "If the selection is empty, treat the instruction as a standalone request and "
    "answer concisely."
)


class InlineRequest(BaseModel):
    selection: str = ""
    instruction: str


class InlineResponse(BaseModel):
    result: str


def _message(role: str, content: str, *, provider: str = None, model: str = None) -> Message:
    return Message(
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        id=generate_message_id(),
        provider=provider,
        model=model,
    )


async def _persist_inline_chat(user_id: int, bot_config, user_content: str, result: str) -> None:
    timestamp = get_utc_iso8601_timestamp()
    chat = Chat(
        id=generate_id(),
        create_time=timestamp,
        update_time=timestamp,
        messages=[
            _message("user", user_content),
            _message("assistant", result, provider="openai", model=bot_config.model),
        ],
        backend="openai",
        bot_name=bot_config.name,
        topic=INLINE_TOPIC,
        skill=INLINE_TOPIC,
    )
    await chat_repo.save_chat(user_id, chat)


@router.post("", response_model=InlineResponse)
async def inline(req: InlineRequest, request: Request) -> InlineResponse:
    user_id = request.state.user_id
    bot_config = bot_service.get_config(user_id, INLINE_BOT_NAME)
    if not bot_config or not bot_config.api_key or not bot_config.model:
        raise HTTPException(
            status_code=502,
            detail=f"Bot {INLINE_BOT_NAME!r} is not configured for this user (api_key and model required)",
        )

    user_content = (
        f"<selection>\n{req.selection}\n</selection>\n\n"
        f"<instruction>\n{req.instruction}\n</instruction>"
    )

    from agent.openai_chat import openai_chat_completion
    try:
        result, _ = await openai_chat_completion(
            [{"role": "user", "content": user_content}],
            bot_config,
            max_tokens=INLINE_MAX_TOKENS,
            system_prompt=SYSTEM_PROMPT,
            timeout=INLINE_TIMEOUT,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")

    result = (result or "").strip()
    await _persist_inline_chat(user_id, bot_config, user_content, result)
    return InlineResponse(result=result)
