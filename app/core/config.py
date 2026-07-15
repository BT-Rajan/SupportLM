from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "knowledgelm"
    db_user: str = "knowledgelm_user"
    db_password: str = ""

    llm_api_key: str = ""
    llm_chat_model: str = "deepseek-chat"
    embedding_model_name: str = "all-MiniLM-L6-v2"

    # --- Phase 4 — 2.0: global fallback credentials for OpenAI/Anthropic.
    # Used only when a tenant has no tenant_llm_config row (or has one
    # with provider='deepseek', which reuses llm_api_key/llm_chat_model
    # above rather than duplicating a third "deepseek" pair here).
    # Same fallback contract as branding: explicit per-tenant override,
    # sane global default otherwise.
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_chat_model: str = "claude-3-5-sonnet-20241022"

    app_secret_key: str = "dev-only-change-me"
    app_env: str = "development"

    # --- SMTP (Phase 2 WBS 4.2: anonymous chat transcript email) ---
    # smtp_host empty = not configured; send_transcript_email() fails
    # loudly rather than pretending to send (see
    # app/services/transcript_email.py).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.com"
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
