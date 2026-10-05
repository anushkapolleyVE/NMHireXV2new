from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """NM-HireX application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # ---------------------------------------------------------
    # DATABASE
    # ---------------------------------------------------------
    DATABASE_URL: str

    # ---------------------------------------------------------
    # EXISTING AI SETTINGS
    # Kept for the legacy JD/CV ingestion functions that remain
    # in tools_function.py. They are NOT used for the new external
    # matching -> outreach flow.
    # ---------------------------------------------------------
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    OPENAI_API_KEY: str = ""

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    EXTRACTION_MODEL: str = "openai/gpt-oss-120b"
    EVALUATION_MODEL: str = "openai/gpt-oss-120b"

    TOP_K_VECTOR: int = 150
    SEMANTIC_TOP_K: int = 100
    TOP_N: int = 50

    RESUME_DIR: str = "data/resumes"
    JD_DIR: str = "data/job_descriptions"

    # ---------------------------------------------------------
    # EXTERNAL RESUME MATCHING API
    # This API owns VEREQ/JD matching, Sheela ranking and score.
    # ---------------------------------------------------------
    RESUME_MATCHING_BASE_URL: str = (
        "https://d4u8k6edt3njs.cloudfront.net/api/public/resume-matching/v1"
    )
    RESUME_MATCHING_API_KEY: str = ""
    RESUME_MATCHING_TIMEOUT_SECONDS: int = 60
    RESUME_MATCHING_POLL_MAX_ATTEMPTS: int = 6
    RESUME_MATCHING_POLL_DEFAULT_WAIT_SECONDS: int = 5

    # Top candidates that NM-HireX will consider for outreach.
    OUTREACH_TOP_N: int = 50

    # ---------------------------------------------------------
    # NMVE WHATSAPP
    # ---------------------------------------------------------
    WHATSAPP_API_KEY: str = ""
    WHATSAPP_BASE_URL: str = (
        "https://nmve.io/whatsapp/api/integrations/whatsapp/messages"
    )
    WHATSAPP_STAGE_NUMBER: str = ""
    WHATSAPP_CALLBACK_URL: str = (
        "https://nmhirex.onrender.com/api/webhooks/whatsapp"
    )
    WHATSAPP_TEMPLATE_NAME: str = "hello_world"
    WHATSAPP_TEMPLATE_LANGUAGE: str = "en_US"

    # ---------------------------------------------------------
    # FRONTEND / SCHEDULING
    # ---------------------------------------------------------
    FRONTEND_URL: str = "http://localhost:5173"

    # Optional webhook verification. Leave empty when NMVE does not
    # support/send a matching custom header yet.
    WEBHOOK_SECRET: str = ""


settings = Settings()
