"""Tests for the internal bearer token auth bypass (testing-only)."""

from unittest.mock import patch

import pytest


@pytest.mark.journey_system
class TestInternalBearerToken:
    """_verify_internal_bearer_token bypasses Google OAuth for a configured token."""

    def test_correct_token_returns_access_token(self) -> None:
        from mcp_robinhood.server.app import _verify_internal_bearer_token

        with patch("mcp_robinhood.server.app._cfg", return_value="secret-test-token"):
            result = _verify_internal_bearer_token("secret-test-token")
        assert result is not None
        assert (result.claims or {}).get("auth_method") == "internal_bearer"

    def test_wrong_token_returns_none(self) -> None:
        from mcp_robinhood.server.app import _verify_internal_bearer_token

        with patch("mcp_robinhood.server.app._cfg", return_value="secret-test-token"):
            assert _verify_internal_bearer_token("wrong") is None

    def test_empty_token_returns_none(self) -> None:
        from mcp_robinhood.server.app import _verify_internal_bearer_token

        with patch("mcp_robinhood.server.app._cfg", return_value="secret-test-token"):
            assert _verify_internal_bearer_token("") is None

    def test_unconfigured_returns_none(self) -> None:
        # No token configured in Vault/settings -> bypass disabled.
        from mcp_robinhood.server.app import _verify_internal_bearer_token

        with patch("mcp_robinhood.server.app._cfg", return_value=""):
            assert _verify_internal_bearer_token("anything") is None
