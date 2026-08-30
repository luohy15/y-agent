import json
import os
import uvicorn
from dotenv import load_dotenv
from storage.global_config import load_global_config

load_dotenv()
load_global_config()
from typing import Any
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


class UnicodeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")

from api.controller.auth import router as auth_router
from api.controller.chat import router as chat_router
from api.controller.todo import router as todo_router
from api.controller.calendar_event import router as calendar_router
from api.controller.vm_config import router as vm_config_router
from api.controller.link import router as link_router
from api.controller.email import router as email_router
from api.controller.terminal import router as terminal_router
from api.controller.model_usage import router as model_usage_router
from api.controller.telegram import router as telegram_router
from api.controller.git import router as git_router
from api.controller.dev_worktree import router as dev_worktree_router
from api.controller.tg_topic import router as tg_topic_router
from api.controller.trace import router as trace_router
from api.controller.link_todo_relation import router as link_todo_relation_router
from api.controller.note import router as note_router
from api.controller.reminder import router as reminder_router
from api.controller.routine import router as routine_router
from api.controller.english_correction import router as english_correction_router
from api.controller.english_word import router as english_word_router
from api.controller.rss_feed import router as rss_feed_router
from api.controller.entity import router as entity_router
from api.controller.entity_note_relation import router as entity_note_relation_router
from api.controller.entity_rss_relation import router as entity_rss_relation_router
from api.controller.entity_link_relation import router as entity_link_relation_router
from api.controller.user_preference import router as user_preference_router
from api.controller.cookies import router as cookies_router
from api.controller.inline import router as inline_router
from api.controller.health import router as health_router
from api.controller.provider_status import router as provider_status_router
from api.controller.module import router as module_router
from api.middleware.auth import AuthMiddleware
from api.middleware.api_latency import ApiLatencyMiddleware
from api.middleware.provider_status_access_log import install_provider_status_access_log_filter

install_provider_status_access_log_filter()
app = FastAPI(title="y-agent API", default_response_class=UnicodeJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(todo_router)
api_router.include_router(calendar_router)
api_router.include_router(vm_config_router)
api_router.include_router(link_router)
api_router.include_router(email_router)
api_router.include_router(terminal_router)
api_router.include_router(model_usage_router)
api_router.include_router(telegram_router)
api_router.include_router(git_router)
api_router.include_router(dev_worktree_router)
api_router.include_router(tg_topic_router)
api_router.include_router(trace_router)
api_router.include_router(link_todo_relation_router)
api_router.include_router(note_router)
api_router.include_router(reminder_router)
api_router.include_router(routine_router)
api_router.include_router(english_correction_router)
api_router.include_router(english_word_router)
api_router.include_router(rss_feed_router)
api_router.include_router(entity_router)
api_router.include_router(entity_note_relation_router)
api_router.include_router(entity_rss_relation_router)
api_router.include_router(entity_link_relation_router)
api_router.include_router(user_preference_router)
api_router.include_router(cookies_router)
api_router.include_router(inline_router)
api_router.include_router(health_router)
api_router.include_router(provider_status_router)
api_router.include_router(module_router)
app.include_router(api_router)

# Module request-path dispatcher (phase 3 / D13). Mounted AFTER the management
# APIRouter so /api/module/list|publish|… win; non-reserved slugs fall through
# to the raw ASGI app which loads the active API half lazily.
from api.module_runtime.dispatcher import module_dispatcher  # noqa: E402

app.mount("/api/module", module_dispatcher)

# Added last so it is outermost, including auth failures and module dispatch.
app.add_middleware(ApiLatencyMiddleware, routes=lambda: app.routes)


def main():
    port = int(os.environ.get("API_PORT", 8001))
    uvicorn.run("api.app:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()
