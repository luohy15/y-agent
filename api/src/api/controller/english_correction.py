import json
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.controller.inline import INLINE_BOT_NAME, INLINE_MAX_TOKENS, INLINE_TIMEOUT
from storage.service import bot_config as bot_service
from storage.service import english_correction as eng_service
from storage.util import generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp

router = APIRouter(prefix="/english")

REFINE_CHAT_ID = "refine"
REFINE_MAX_CHARS = 2000
REFINE_SYSTEM_PROMPT = (
    "You refine English (or Chinese-to-English) with a minimal edit that preserves meaning. "
    "Refine the grammar and wording while preserving the original meaning.\n"
    "Rules:\n"
    "- Prefer the smallest change that makes the sentence grammatical and natural. "
    "Do not rewrite for style or formality when the original is already grammatical.\n"
    "- If the original is already natural, do not invent a better version. "
    "Set changed=false, copy the original into corrected, use an empty categories list, "
    "and explain in 1-2 sentences that it is already natural.\n"
    "- If you change the text, set changed=true. Emit one or more free-form lowercase "
    "category strings (e.g. tense, article, preposition, word choice) and a 1-2 sentence "
    "explanation of the grammar or wording issue.\n"
    "- Preserve Chinese characters the user intends to keep. Correct only English spans "
    "unless the user is clearly asking for an English rendering of Chinese.\n"
    "Return ONLY a JSON object, no markdown fences, no extra text, with keys "
    "changed (boolean), corrected (string), categories (array of strings), explanation (string)."
)
_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class AddCorrectionRequest(BaseModel):
    chat_id: str
    message_id: str
    message_at: str
    message_at_unix: int
    original_text: str
    corrected_text: str
    error_categories: List[str] = Field(default_factory=list)
    explanation: str


class DismissRequest(BaseModel):
    correction_id: str


class MarkScannedRequest(BaseModel):
    scanned_through_unix: int


class RefineRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=REFINE_MAX_CHARS)


class RefineResponse(BaseModel):
    changed: bool
    corrected: str
    categories: List[str]
    explanation: str
    correction_id: Optional[str] = None


def _parse_refine_json(raw: str) -> dict:
    """Lenient JSON object parse: strip fences, then take the first {...} span."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    if text.startswith("```"):
        text = _FENCE_OPEN_RE.sub("", text, count=1)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in LLM response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM JSON is not an object")
    return data


def _normalize_refine_result(original: str, data: dict) -> tuple[bool, str, List[str], str]:
    corrected = data.get("corrected")
    if corrected is None:
        corrected = data.get("corrected_text")
    if not isinstance(corrected, str) or not corrected.strip():
        raise ValueError("missing corrected text")
    corrected = corrected.strip()

    explanation = data.get("explanation")
    if not isinstance(explanation, str):
        raise ValueError("missing explanation")
    explanation = explanation.strip()

    cats = data.get("categories")
    if cats is None:
        cats = data.get("error_categories")
    if cats is None:
        cats = []
    if isinstance(cats, str):
        cats = [cats]
    if not isinstance(cats, list):
        raise ValueError("categories is not a list")
    categories = [str(c).strip() for c in cats if str(c).strip()]

    changed = corrected != original
    if not changed:
        corrected = original
        if not explanation:
            explanation = "Already natural."
        categories = []
    elif not explanation:
        raise ValueError("missing explanation")
    return changed, corrected, categories, explanation


@router.get("/list")
async def list_corrections(
    request: Request,
    dismissed: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    rows = eng_service.list_corrections(
        user_id,
        dismissed=dismissed,
        category=category,
        query=query,
        limit=limit,
        offset=offset,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
    )
    return [r.to_dict() for r in rows]


@router.get("/detail")
async def get_correction(request: Request, correction_id: str = Query(...)):
    user_id = _get_user_id(request)
    row = eng_service.get_correction(user_id, correction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Correction not found")
    return row.to_dict()


@router.post("")
async def add_correction(req: AddCorrectionRequest, request: Request):
    user_id = _get_user_id(request)
    row = eng_service.add_correction(
        user_id,
        chat_id=req.chat_id,
        message_id=req.message_id,
        message_at=req.message_at,
        message_at_unix=req.message_at_unix,
        original_text=req.original_text,
        corrected_text=req.corrected_text,
        error_categories=req.error_categories,
        explanation=req.explanation,
    )
    return row.to_dict()


@router.post("/dismiss")
async def dismiss_correction(req: DismissRequest, request: Request):
    user_id = _get_user_id(request)
    row = eng_service.dismiss_correction(user_id, req.correction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Correction not found")
    return row.to_dict()


@router.get("/pending")
async def list_pending(
    request: Request,
    limit: int = Query(50),
    since: Optional[int] = Query(default=None, description="Unix ms lower bound (exclusive)"),
):
    user_id = _get_user_id(request)
    # FastAPI injects Query defaults; when called directly in unit tests the
    # default may be a Query object — normalize to a plain int/None.
    since_unix = since if isinstance(since, int) else None
    return eng_service.list_pending(user_id, since_unix=since_unix, limit=limit)


@router.post("/mark-scanned")
async def mark_scanned(req: MarkScannedRequest, request: Request):
    user_id = _get_user_id(request)
    return eng_service.set_watermark(user_id, req.scanned_through_unix)


@router.post("/refine", response_model=RefineResponse)
async def refine_text(req: RefineRequest, request: Request) -> RefineResponse:
    user_id = _get_user_id(request)
    original = (req.text or "").strip()
    if not original:
        raise HTTPException(status_code=400, detail="text is required")
    if len(original) > REFINE_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"text exceeds {REFINE_MAX_CHARS} characters")

    bot_config = bot_service.get_config(user_id, INLINE_BOT_NAME)
    if not bot_config or not bot_config.api_key or not bot_config.model:
        raise HTTPException(
            status_code=502,
            detail=f"Bot {INLINE_BOT_NAME!r} is not configured for this user (api_key and model required)",
        )

    from agent.openai_chat import openai_chat_completion
    try:
        raw, _ = await openai_chat_completion(
            [{"role": "user", "content": original}],
            bot_config,
            max_tokens=INLINE_MAX_TOKENS,
            system_prompt=REFINE_SYSTEM_PROMPT,
            timeout=INLINE_TIMEOUT,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")

    try:
        payload = _parse_refine_json(raw or "")
        changed, corrected, categories, explanation = _normalize_refine_result(original, payload)
    except (ValueError, json.JSONDecodeError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"LLM parse failed: {e}")

    correction_id = None
    if changed:
        now = get_utc_iso8601_timestamp()
        row = eng_service.add_correction(
            user_id,
            chat_id=REFINE_CHAT_ID,
            message_id=generate_message_id(),
            message_at=now,
            message_at_unix=get_unix_timestamp(),
            original_text=original,
            corrected_text=corrected,
            error_categories=categories,
            explanation=explanation,
        )
        correction_id = row.correction_id

    return RefineResponse(
        changed=changed,
        corrected=corrected,
        categories=categories,
        explanation=explanation,
        correction_id=correction_id,
    )
