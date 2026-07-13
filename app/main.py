import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.api import auth, categories, chat, documents

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supportlm")

app = FastAPI(title="KnowledgeLM", version="0.1.0")

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(categories.router)
app.include_router(auth.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Safety net for any route that doesn't already catch its own errors.
    Without this, Starlette's default 500 response is plain text, which
    breaks any client doing `await res.json()` and hides the real error
    from server logs entirely."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/admin")
def admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})
