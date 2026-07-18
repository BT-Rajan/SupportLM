"""Per-tenant theme resolution (WBS 4.1-4.3).

The "pluggable" part of branding isn't more color inputs — it's that a
tenant supplies exactly ONE accent color and this module derives a
cohesive palette from it, the same relationship the current default
emerald theme already has:

    --accent      #0e7c66  (base)
    --accent-ink  #0b5f4f  (darker — hover/active states)
    --accent-soft #dcefe9  (light tint — chips, the ticket-stub notch)

A tenant who could only pick one color and got three independent
pickers would likely produce something that clashes; deriving the
other two from HSL math keeps every tenant's theme internally
consistent without asking them to be a designer.

Lightness is clamped so a tenant can't pick a pale accent that breaks
white-on-accent contrast for buttons (`.composer-send`, `.msg-user`) —
the quality floor holds regardless of what a tenant enters.
"""
import colorsys
import re

from app.db.pool import get_cursor

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Exactly today's look — a tenant with no branding row, or no accent_hex
# set, gets this untouched (WBS 4.3).
DEFAULT_THEME = {
    "display_name": "Support",
    "agent_name": "Assistant",
    "tone": None,  # Phase 8 — 3.1/3.2: no forced default — None means no tone instruction added
    "logo_url": None,
    "accent": "#0e7c66",
    "accent_ink": "#0b5f4f",
    "accent_soft": "#dcefe9",
}

# Keep white button/bubble text readable and the color recognizably a
# "brand accent" rather than washed out or near-black.
_MIN_LIGHTNESS = 0.28
_MAX_LIGHTNESS = 0.62


def is_valid_hex(value: str) -> bool:
    return bool(_HEX_RE.match(value))


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in rgb)


def derive_palette(accent_hex: str) -> dict:
    """Given one validated `#rrggbb` accent color, derive accent_ink
    (darker, for hover/active) and accent_soft (light desaturated tint,
    for chips/tags/the ticket-stub notch), clamping lightness so the
    base accent always works with white text on top of it."""
    r, g, b = _hex_to_rgb(accent_hex)
    h, l, s = colorsys.rgb_to_hls(r, g, b)  # note: HLS order, not HSL

    l = max(_MIN_LIGHTNESS, min(_MAX_LIGHTNESS, l))
    accent = _rgb_to_hex(colorsys.hls_to_rgb(h, l, s))

    ink_l = max(0.16, l - 0.12)
    accent_ink = _rgb_to_hex(colorsys.hls_to_rgb(h, ink_l, s))

    soft_l = 0.92
    soft_s = s * 0.6
    accent_soft = _rgb_to_hex(colorsys.hls_to_rgb(h, soft_l, soft_s))

    return {"accent": accent, "accent_ink": accent_ink, "accent_soft": accent_soft}


def resolve_theme(tenant_id: int) -> dict:
    """Look up tenant_branding and fill in every field that isn't set,
    field-by-field — a tenant can customize just a logo and still get
    the default accent, etc. A tenant with no branding row at all, or
    no value for a given field, gets exactly today's look (WBS 4.3) —
    including the generic "Support" display name, not an
    auto-branded version of the tenant's internal org name (that name
    may not be customer-facing copy at all, e.g. "Acme Corp LLC
    (Trial)"). Branding is opt-in via tenant_branding, not inferred.
    Returns a dict ready to inject into the chat template."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT display_name, agent_name, logo_url, accent_hex, tone FROM tenant_branding WHERE tenant_id = %s",
            (tenant_id,),
        )
        row = cur.fetchone()

    theme = dict(DEFAULT_THEME)

    if row:
        if row["display_name"]:
            theme["display_name"] = row["display_name"]
        if row["agent_name"]:
            theme["agent_name"] = row["agent_name"]
        if row["logo_url"]:
            theme["logo_url"] = row["logo_url"]
        if row["accent_hex"] and is_valid_hex(row["accent_hex"]):
            theme.update(derive_palette(row["accent_hex"]))
        if row["tone"]:
            theme["tone"] = row["tone"]

    theme["monogram"] = (theme["display_name"] or "S").strip()[:1].upper() or "S"
    return theme
