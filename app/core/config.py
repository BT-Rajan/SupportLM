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

    # --- Phase 4 — 2.0: global fallback API keys for OpenAI/Anthropic.
    # Used only when a tenant has no tenant_llm_config row (or has one
    # with provider='deepseek', which reuses llm_api_key/llm_chat_model
    # above rather than duplicating a third "deepseek" pair here). No
    # matching *_chat_model fallback settings — set_llm_config()
    # (app/api/llm_config.py) always requires an explicit model from
    # the admin, so there's nothing for a model-name default to ever
    # be read by; two such settings existed here previously and were
    # removed as confirmed-dead config once audited.
    openai_api_key: str = ""
    anthropic_api_key: str = ""

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
