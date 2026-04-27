"""Session management for Robin Stocks authentication."""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import robin_stocks.robinhood as rh
import robin_stocks.robinhood.helper as rh_helper

from mcp_robinhood.logging_config import logger


# URL fragments that legitimately need to return 401/403 bodies for parsing
# (login + Robinhood's verification workflow endpoints). robin_stocks' login()
# expects to read the body of these responses to discover MFA challenges.
_AUTH_ENDPOINT_FRAGMENTS = (
    "/oauth2/",
    "/pathfinder/",
    "/push/",
    "/challenge/",
    "/auth/",
)


def _raise_on_auth_failure(response: Any, *args: Any, **kwargs: Any) -> None:
    """Raise on 401/403 so robin_stocks can't swallow expired-token responses.

    Without this, an expired Robinhood session returns empty data on data
    endpoints instead of an exception, and the retry/re-auth path in
    execute_with_retry never fires.

    Skipped for login/verification endpoints — robin_stocks parses 401/403
    bodies on those to handle MFA workflows.
    """
    if response.status_code not in (401, 403):
        return
    url = (response.request.url or "") if response.request else ""
    if any(fragment in url for fragment in _AUTH_ENDPOINT_FRAGMENTS):
        return
    response.raise_for_status()


if _raise_on_auth_failure not in rh_helper.SESSION.hooks.get("response", []):
    rh_helper.SESSION.hooks.setdefault("response", []).append(_raise_on_auth_failure)


class SessionManager:
    """Manages Robin Stocks authentication session lifecycle."""

    def __init__(self, session_timeout_hours: int = 23, max_failed_attempts: int = 3):
        self.session_timeout_hours = session_timeout_hours
        self.max_failed_attempts = max_failed_attempts
        self.login_time: datetime | None = None
        self.last_successful_call: datetime | None = None
        self.username: str | None = None
        self.password: str | None = None
        self.mfa_code: str | None = None
        self.mfa_secret: str | None = None
        self._lock = asyncio.Lock()
        self._is_authenticated = False
        self._failed_login_attempts = 0

    def set_credentials(
        self,
        username: str,
        password: str,
        mfa_code: str | None = None,
        mfa_secret: str | None = None,
    ) -> None:
        """Store credentials for authentication."""
        self.username = username
        self.password = password
        self.mfa_code = mfa_code
        self.mfa_secret = mfa_secret
        self._failed_login_attempts = 0

    def is_session_valid(self) -> bool:
        if not self._is_authenticated or not self.login_time:
            return False
        age = datetime.now() - self.login_time
        if age >= timedelta(hours=self.session_timeout_hours):
            logger.info(
                f"Session aged {age} >= {self.session_timeout_hours}h timeout, "
                "marking invalid"
            )
            self._is_authenticated = False
            return False
        return True

    def update_last_successful_call(self) -> None:
        self.last_successful_call = datetime.now()

    def _get_pickle_file_path(self, pickle_name: str = "robinhood") -> Path:
        return Path.home() / ".tokens" / f"{pickle_name}.pickle"

    def _clear_pickle_file(self, pickle_name: str = "robinhood") -> bool:
        try:
            pickle_path = self._get_pickle_file_path(pickle_name)
            if pickle_path.exists():
                pickle_path.unlink()
                logger.info(f"Cleared pickle file: {pickle_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear pickle file: {e}")
            return False

    def _increment_failed_attempts(self) -> None:
        self._failed_login_attempts += 1
        logger.warning(
            f"Login attempt {self._failed_login_attempts}/{self.max_failed_attempts} failed"
        )
        if self._failed_login_attempts >= self.max_failed_attempts:
            logger.error("Max failed attempts reached, clearing session cache")
            self._clear_pickle_file()

    def _resolve_mfa_code(self) -> str | None:
        """Resolve MFA code from direct code, TOTP secret, or environment."""
        # 1. Direct code (e.g. from 1Password CLI)
        code = self.mfa_code or os.getenv("ROBINHOOD_MFA_CODE")
        if code:
            return code.strip()

        # 2. TOTP secret — generate code
        secret = self.mfa_secret or os.getenv("ROBINHOOD_MFA_SECRET")
        if secret:
            try:
                import pyotp

                return pyotp.TOTP(secret.strip()).now()
            except Exception as exc:
                logger.warning(f"TOTP generation failed: {exc}")

        return None

    async def ensure_authenticated(self) -> bool:
        async with self._lock:
            if self.is_session_valid():
                return True
            return await self._authenticate()

    async def _attempt_login(self) -> bool:
        """One login + probe attempt. Returns True only when probe succeeds."""
        loop = asyncio.get_event_loop()
        try:
            login_result = await asyncio.wait_for(
                loop.run_in_executor(None, self._do_login),
                timeout=25,
            )
        except TimeoutError:
            logger.error("Authentication timed out after 25 seconds")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

        if not login_result:
            return False

        # Probe with a real API call — robin_stocks may have loaded a cached
        # session that "succeeded" locally but holds a token Robinhood already
        # invalidated. The 401 response hook turns that into an exception here.
        try:
            user_profile = await loop.run_in_executor(None, rh.load_user_profile)
        except Exception as e:
            logger.warning(f"Login probe failed (likely stale cached session): {e}")
            return False

        if not user_profile:
            logger.warning("Login probe returned empty user profile")
            return False

        self.login_time = datetime.now()
        self._is_authenticated = True
        logger.info(f"Authenticated user: {self.username}")
        return True

    async def _authenticate(self) -> bool:
        if not self.username or not self.password:
            logger.error("No credentials available for authentication")
            return False

        logger.info(f"Authenticating user: {self.username}")

        if await self._attempt_login():
            self._failed_login_attempts = 0
            return True

        # First attempt failed. If a cached session file exists, it's likely
        # stale — clear it and try one fresh login before counting a failure.
        if self._get_pickle_file_path().exists():
            logger.warning("Auth failed with cached session; clearing and retrying fresh")
            self._clear_pickle_file()
            if await self._attempt_login():
                self._failed_login_attempts = 0
                return True

        self._increment_failed_attempts()
        return False

    def _do_login(self) -> bool:
        """Perform the actual robin_stocks login call."""
        try:
            mfa_code = self._resolve_mfa_code()
            result = rh.login(
                self.username,
                self.password,
                mfa_code=mfa_code,
                store_session=True,
            )
            if isinstance(result, dict) and "access_token" in result:
                logger.info("Login successful")
                return True

            logger.error(
                "Login failed — rh.login returned %s without access_token",
                type(result).__name__,
            )
            return False

        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    async def refresh_session(self) -> bool:
        async with self._lock:
            logger.info("Refreshing session")
            self._is_authenticated = False
            self.login_time = None
            return await self._authenticate()

    def get_session_info(self) -> dict[str, Any]:
        return {
            "is_authenticated": self._is_authenticated,
            "is_valid": self.is_session_valid(),
            "username": self.username,
            "login_time": self.login_time.isoformat() if self.login_time else None,
            "last_successful_call": (
                self.last_successful_call.isoformat()
                if self.last_successful_call
                else None
            ),
            "failed_login_attempts": self._failed_login_attempts,
            "max_failed_attempts": self.max_failed_attempts,
        }

    async def logout(self) -> None:
        async with self._lock:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, rh.logout)
                logger.info("Logged out")
            except Exception as e:
                logger.error(f"Logout error: {e}")
            finally:
                self._is_authenticated = False
                self.login_time = None
                self.last_successful_call = None
                self._failed_login_attempts = 0

    def clear_session_cache(self) -> bool:
        return self._clear_pickle_file()

    async def force_fresh_login(self) -> bool:
        async with self._lock:
            logger.info("Forcing fresh login")
            self._is_authenticated = False
            self.login_time = None
            self.last_successful_call = None
            self._clear_pickle_file()
            self._failed_login_attempts = 0
            return await self._authenticate()


# Global instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


async def ensure_authenticated_session() -> tuple[bool, str | None]:
    manager = get_session_manager()
    try:
        success = await manager.ensure_authenticated()
        return (True, None) if success else (False, "Authentication failed")
    except Exception as e:
        logger.error(f"Session authentication error: {e}")
        return False, str(e)


async def force_fresh_authentication() -> tuple[bool, str | None]:
    manager = get_session_manager()
    try:
        success = await manager.force_fresh_login()
        return (True, None) if success else (False, "Fresh authentication failed")
    except Exception as e:
        logger.error(f"Fresh authentication error: {e}")
        return False, str(e)
