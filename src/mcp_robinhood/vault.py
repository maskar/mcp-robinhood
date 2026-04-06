"""Vault client — fetch Robinhood credentials at startup, cache in memory."""

import os

import hvac
from loguru import logger

_secrets: dict[str, str] = {}


def fetch_secrets() -> dict[str, str]:
    """Fetch secrets from Vault KV v2 and cache in memory."""
    global _secrets

    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")

    if not vault_addr or not vault_token:
        logger.debug("Vault not configured — skipping secret fetch")
        return _secrets

    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
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
