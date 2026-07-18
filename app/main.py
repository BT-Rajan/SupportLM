import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.api import agent_config, analytics, api_keys, audit, auth, categories, chat, documents, llm_config, prompt_versions, support_config
from app.core.tenant_scope import resolve_tenant
from app.core.theme import resolve_theme

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supportlm")

app = FastAPI(title="SupportLM", version="0.2.0")

# WBS 3.1/3.2: every tenant-scoped route lives under /t/{tenant_slug}/...
# Each router declares its own resolve_tenant / resolve_tenant_for_admin
# dependency (see app/core/tenant_scope.py) matching what that router's
# routes actually need — not a single blanket dependency here, since
# some routes are anonymous (chat, category listing) and some require
# the logged-in admin to be linked to that specific tenant (documents,
# category writes). `/health` is the only unscoped route — it's infra,
# not tenant data.
TENANT_PREFIX = "/t/{tenant_slug}"

app.include_router(chat.router, prefix=TENANT_PREFIX)
app.include_router(documents.router, prefix=TENANT_PREFIX)
app.include_router(categories.router, prefix=TENANT_PREFIX)
app.include_router(auth.router, prefix=TENANT_PREFIX)
app.include_router(api_keys.router, prefix=TENANT_PREFIX)
app.include_router(llm_config.router, prefix=TENANT_PREFIX)
app.include_router(prompt_versions.router, prefix=TENANT_PREFIX)
app.include_router(support_config.router, prefix=TENANT_PREFIX)
app.include_router(analytics.router, prefix=TENANT_PREFIX)
app.include_router(audit.router, prefix=TENANT_PREFIX)
app.include_router(agent_config.router, prefix=TENANT_PREFIX)


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
def root():
    # No tenant in the URL here — nothing to resolve. Point at the
    # tenant-scoped shape rather than guessing or serving a default.
    raise HTTPException(
        status_code=404,
        detail="Specify a tenant, e.g. /t/{your-tenant-slug}/",
    )


@app.get("/t/{tenant_slug}/")
def index(request: Request, tenant_slug: str, tenant_id: int = Depends(resolve_tenant)):
    # Anonymous page (the chat widget) — resolve_tenant, not the admin
    # variant: 404/403 for an unknown/suspended tenant, no session
    # required, same as the /api/chat route this page calls into.
    theme = resolve_theme(tenant_id)
    return templates.TemplateResponse(
        "chat.html", {"request": request, "tenant_slug": tenant_slug, "theme": theme}
    )


@app.get("/t/{tenant_slug}/admin")
def admin(request: Request, tenant_slug: str, tenant_id: int = Depends(resolve_tenant)):
    # Also resolve_tenant, not resolve_tenant_for_admin: this route just
    # serves the HTML shell (login form + dashboard markup) — the page
    # itself decides client-side whether to show the login form or the
    # dashboard. Requiring admin+membership here would 401 a visitor
    # before they ever see the login form. The actual admin data lives
    # behind /api/documents and the write endpoints on /api/categories,
    # which DO require resolve_tenant_for_admin.
    return templates.TemplateResponse("admin.html", {"request": request, "tenant_slug": tenant_slug})
