import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.service import bot_config as bot_service

router = APIRouter(prefix="/inline")

# Inline rewrites use a dedicated bot config (by convention named "inline"),
# so the user can pin a fast model — typically Gemini Flash via OpenRouter —
# independent of whatever the main agent backend is set to. The endpoint
# speaks OpenAI's /chat/completions shape; pick a bot whose base_url is
# compatible (OpenRouter, OpenAI itself, Google's OpenAI-compat endpoint…).
INLINE_BOT_NAME = "inline"
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

    payload = {
        "model": bot_config.model,
        "max_tokens": INLINE_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    url = f"{bot_config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {bot_config.api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=INLINE_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")

    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"LLM error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        result = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail=f"Unexpected LLM response: {data}")

    return InlineResponse(result=(result or "").strip())
