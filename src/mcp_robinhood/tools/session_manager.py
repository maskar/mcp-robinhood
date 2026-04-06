"""Session management for Robin Stocks authentication."""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import robin_stocks.robinhood as rh

from mcp_robinhood.logging_config import logger


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
        elapsed = datetime.now() - self.login_time
        if elapsed > timedelta(hours=self.session_timeout_hours):
            logger.info(f"Session expired after {elapsed}")
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

    async def _authenticate(self) -> bool:
        if not self.username or not self.password:
            logger.error("No credentials available for authentication")
            return False

        try:
            logger.info(f"Authenticating user: {self.username}")
            loop = asyncio.get_event_loop()

            try:
                login_result = await asyncio.wait_for(
                    loop.run_in_executor(None, self._do_login),
                    timeout=150,
                )
            except TimeoutError:
                logger.error("Authentication timed out after 150 seconds")
                self._increment_failed_attempts()
                return False

            if not login_result:
                self._increment_failed_attempts()
                return False

            # Verify login
            user_profile = await loop.run_in_executor(None, rh.load_user_profile)
            if user_profile:
                self.login_time = datetime.now()
                self._is_authenticated = True
                self._failed_login_attempts = 0
                logger.info(f"Authenticated user: {self.username}")
                return True

            logger.error("Login verification failed: could not load user profile")
            self._increment_failed_attempts()
            return False

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
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

            logger.error("Login failed — no access token in response")
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
        info: dict[str, Any] = {
            "is_authenticated": self._is_authenticated,
            "is_valid": self.is_session_valid(),
            "username": self.username,
            "login_time": self.login_time.isoformat() if self.login_time else None,
            "last_successful_call": (
                self.last_successful_call.isoformat()
                if self.last_successful_call
                else None
            ),
            "session_timeout_hours": self.session_timeout_hours,
            "failed_login_attempts": self._failed_login_attempts,
            "max_failed_attempts": self.max_failed_attempts,
        }
        if self.login_time:
            remaining = timedelta(hours=self.session_timeout_hours) - (
                datetime.now() - self.login_time
            )
            info["time_until_expiry"] = (
                str(remaining) if remaining.total_seconds() > 0 else "Expired"
            )
        return info

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
