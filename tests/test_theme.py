"""Tests for WBS 4.1-4.3: the color-derivation engine (pure, no DB) and
theme resolution/fallback behavior (DB-backed, skips cleanly if no DB
is configured)."""
import pytest

from app.core.theme import DEFAULT_THEME, derive_palette, is_valid_hex

try:
    from app.db.pool import get_conn

    with get_conn() as _conn:
        pass
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False


# ---- Pure color math: no DB needed ----------------------------------

def test_is_valid_hex():
    assert is_valid_hex("#7c3aed")
    assert not is_valid_hex("7c3aed")  # missing #
    assert not is_valid_hex("#abc")  # too short
    assert not is_valid_hex("#zzzzzz")  # not hex digits
    assert not is_valid_hex("not-a-color")


def test_derive_palette_returns_three_distinct_colors():
    palette = derive_palette("#7c3aed")
    assert set(palette) == {"accent", "accent_ink", "accent_soft"}
    assert len({palette["accent"], palette["accent_ink"], palette["accent_soft"]}) == 3


def test_derive_palette_clamps_near_black_to_a_usable_accent():
    """A near-black input must not produce an unusably dark button —
    white text on top needs to stay readable."""
    import colorsys

    from app.core.theme import _hex_to_rgb

    palette = derive_palette("#111111")  # raw lightness ~0.067
    _, l, _ = colorsys.rgb_to_hls(*_hex_to_rgb(palette["accent"]))
    assert l >= 0.28 - 0.01  # clamped up to the min-lightness floor (allowing for hex quantization rounding)


def test_derive_palette_clamps_pale_input_darker_for_contrast():
    import colorsys

    from app.core.theme import _hex_to_rgb

    palette = derive_palette("#fdf6e3")  # very pale cream, raw lightness ~0.94
    _, l, _ = colorsys.rgb_to_hls(*_hex_to_rgb(palette["accent"]))
    assert l <= 0.62 + 0.01  # clamped to the max-lightness ceiling (allowing for hex quantization rounding)


def test_derive_palette_ink_is_darker_than_accent():
    palette = derive_palette("#1d4ed8")
    # crude luminance proxy: sum of RGB channels
    accent_luma = sum(int(palette["accent"][i : i + 2], 16) for i in (1, 3, 5))
    ink_luma = sum(int(palette["accent_ink"][i : i + 2], 16) for i in (1, 3, 5))
    assert ink_luma < accent_luma


# ---- Theme resolution: DB-backed ----------------------------------

pytestmark_db = pytest.mark.skipif(
    not _DB_AVAILABLE, reason="requires a configured, reachable DB (see .env.example)"
)


def _ensure_tenant(slug: str) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, 'active')", (slug, slug)
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


@pytestmark_db
def test_tenant_with_no_branding_row_gets_exact_default_theme():
    from app.core.theme import resolve_theme
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-theme-no-branding")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        cur.close()

    theme = resolve_theme(tenant_id)
    assert theme["display_name"] == DEFAULT_THEME["display_name"]
    assert theme["agent_name"] == DEFAULT_THEME["agent_name"]
    assert theme["logo_url"] is None
    assert theme["accent"] == DEFAULT_THEME["accent"]
    assert theme["monogram"] == "S"


@pytestmark_db
def test_partial_branding_only_overrides_set_fields():
    """A tenant who only sets a logo must still get the default accent
    and display name — fields are independently optional."""
    from app.core.theme import resolve_theme
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-theme-partial")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        cur.execute(
            "INSERT INTO tenant_branding (tenant_id, logo_url) VALUES (%s, %s)",
            (tenant_id, "https://example.com/logo.png"),
        )
        cur.close()

    theme = resolve_theme(tenant_id)
    assert theme["logo_url"] == "https://example.com/logo.png"
    assert theme["display_name"] == DEFAULT_THEME["display_name"]
    assert theme["accent"] == DEFAULT_THEME["accent"]


@pytestmark_db
def test_full_branding_overrides_everything_and_derives_palette():
    from app.core.theme import resolve_theme
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-theme-full")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        cur.execute(
            "INSERT INTO tenant_branding (tenant_id, display_name, agent_name, logo_url, accent_hex) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant_id, "Acme Support", "Ava", "https://example.com/acme.png", "#7c3aed"),
        )
        cur.close()

    theme = resolve_theme(tenant_id)
    assert theme["display_name"] == "Acme Support"
    assert theme["agent_name"] == "Ava"
    assert theme["logo_url"] == "https://example.com/acme.png"
    assert theme["accent"] == "#7c3aed"
    assert theme["monogram"] == "A"


@pytestmark_db
def test_invalid_stored_accent_hex_falls_back_to_default_rather_than_crashing():
    """Defensive check on the read path: even if bad data somehow got
    into the DB, resolve_theme must not 500 the whole widget page."""
    from app.core.theme import resolve_theme
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-theme-bad-accent")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        cur.execute(
            "INSERT INTO tenant_branding (tenant_id, accent_hex) VALUES (%s, %s)",
            (tenant_id, "notahex"),
        )
        cur.close()

    theme = resolve_theme(tenant_id)
    assert theme["accent"] == DEFAULT_THEME["accent"]
