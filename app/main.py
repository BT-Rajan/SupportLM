from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.api import chat, documents

app = FastAPI(title="KnowledgeLM", version="0.1.0")

app.include_router(chat.router)
app.include_router(documents.router)

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
