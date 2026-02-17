import json
import uvicorn
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
app.include_router(api_router)

def main():
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
