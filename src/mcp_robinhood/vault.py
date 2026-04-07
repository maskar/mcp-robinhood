"""Vault client — AppRole auth, fetch secrets at startup, cache in memory."""

import os

import hvac
from loguru import logger

_secrets: dict[str, str] = {}


def _authenticate(client: hvac.Client) -> bool:
    """Authenticate via AppRole or static token."""
    role_id = os.getenv("VAULT_ROLE_ID")
    secret_id = os.getenv("VAULT_SECRET_ID")

    if role_id and secret_id:
        resp = client.auth.approle.login(role_id=role_id, secret_id=secret_id)
        client.token = resp["auth"]["client_token"]
        logger.info("Vault: authenticated via AppRole")
        return True

    if os.getenv("VAULT_TOKEN"):
        client.token = os.getenv("VAULT_TOKEN")
        if client.is_authenticated():
            logger.info("Vault: authenticated via static token")
            return True

    return False


def fetch_secrets() -> dict[str, str]:
    """Fetch secrets from Vault KV v2 and cache in memory."""
    global _secrets

    vault_addr = os.getenv("VAULT_ADDR")
    if not vault_addr:
        logger.debug("Vault not configured — skipping secret fetch")
        return _secrets

    try:
        client = hvac.Client(url=vault_addr)
        if not _authenticate(client):
            logger.error("Vault authentication failed")
            return _secrets

        response = client.secrets.kv.v2.read_secret_version(
            path="mcp-robinhood",
            mount_point="secret",
            raise_on_deleted_version=True,
        )
        _secrets = response["data"]["data"]
        logger.info("Fetched {} secrets from Vault", len(_secrets))
    except hvac.exceptions.InvalidPath:
        logger.warning("Vault path secret/mcp-robinhood not found")
    except Exception as e:
        logger.warning("Failed to fetch secrets from Vault: {}", e)

    return _secrets


def get_secret(key: str, default: str = "") -> str:
    """Get a cached secret by key."""
    return _secrets.get(key, default)
