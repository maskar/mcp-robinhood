"""Configuration via Pydantic settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    # Server
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080

    # Vault
    vault_addr: str = ""
    vault_token: str = ""

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_email: str = ""
    public_hostname: str = ""

    # Robinhood (fallback when Vault unavailable)
    robinhood_username: str = ""
    robinhood_password: str = ""
    robinhood_mfa_code: str = ""
    robinhood_mfa_secret: str = ""

    # Logging
    log_level: str = "INFO"


settings = Settings()
