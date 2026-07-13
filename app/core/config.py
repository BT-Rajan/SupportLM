from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "knowledgelm"
    db_user: str = "knowledgelm_user"
    db_password: str = ""

    llm_api_key: str = ""
    llm_embedding_model: str = "text-embedding-3-small"
    llm_chat_model: str = "gpt-4o-mini"

    app_secret_key: str = "dev-only-change-me"
    app_env: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
