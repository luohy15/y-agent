import json
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()
from typing import Any
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


class UnicodeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")

from api.controller.auth import router as auth_router
from api.controller.chat import router as chat_router
from api.controller.file import router as file_router
from api.controller.todo import router as todo_router
from api.controller.calendar_event import router as calendar_router
from api.controller.vm_config import router as vm_config_router
from api.controller.link import router as link_router
from api.controller.email import router as email_router
from api.controller.finance import router as finance_router
from api.controller.terminal import router as terminal_router
from api.controller.bot_config import router as bot_config_router
from api.controller.telegram import router as telegram_router
from api.controller.git import router as git_router
from api.controller.dev_worktree import router as dev_worktree_router
from api.controller.tg_topic import router as tg_topic_router
from api.middleware.auth import AuthMiddleware

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
api_router.include_router(file_router)
api_router.include_router(todo_router)
api_router.include_router(calendar_router)
api_router.include_router(vm_config_router)
api_router.include_router(link_router)
api_router.include_router(email_router)
api_router.include_router(finance_router)
api_router.include_router(terminal_router)
api_router.include_router(bot_config_router)
api_router.include_router(telegram_router)
api_router.include_router(git_router)
api_router.include_router(dev_worktree_router)
api_router.include_router(tg_topic_router)
app.include_router(api_router)

def main():
    port = int(os.environ.get("API_PORT", 8001))
    uvicorn.run("api.app:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()
