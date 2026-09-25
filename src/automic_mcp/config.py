"""Configuration for connecting to the Automic AE REST API.

Values are loaded from environment variables (or a local .env file, never
committed to git) using pydantic-settings, which validates types and gives
clear error messages if something required is missing.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AutomicSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOMIC_", env_file=".env", extra="ignore")

    base_url: str
    """Base URL up to and including the API version, e.g. https://host:8088/ae/api/v1"""

    client_id: str
    """AE client (tenant) number, used as the {client_id} path segment on every request."""

    username: str
    password: SecretStr
    department: str | None = None
    """Optional AE department. When set, sent as USERNAME/DEPARTMENT in Basic Auth."""

    verify_ssl: bool = True
    """Set to false only for a known internal server with a self-signed cert
    (equivalent to `curl -k`) - this disables TLS certificate verification,
    so the connection is no longer protected against MITM. Never disable
    this for a server reachable over the public internet."""

    @property
    def basic_auth_username(self) -> str:
        """The Basic Auth "username" field, per the AE REST API's expected format."""
        if self.department:
            return f"{self.username}/{self.department}"
        return self.username


@lru_cache
def get_settings() -> AutomicSettings:
    """Cached settings instance - loaded once per process."""
    return AutomicSettings()
