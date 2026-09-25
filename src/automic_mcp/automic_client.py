"""Thin async HTTP client for the Automic AE REST API.

Stage 2 scope: read-only calls only (ping, search, get a single object).
No calls that create/modify/delete/execute anything.
"""

import base64
import warnings
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

from automic_mcp.config import AutomicSettings, get_settings


def _basic_auth_header(username: str, password: str) -> str:
    """Build the Authorization header the way the AE REST API expects.

    httpx's built-in BasicAuth encodes credentials as UTF-8. The AE REST API
    docs explicitly require ISO-8859-1, so we build the header ourselves to
    match - for ASCII-only credentials the two are identical, but they
    diverge for accented/non-ASCII characters.
    """
    token = base64.b64encode(f"{username}:{password}".encode("iso-8859-1")).decode("ascii")
    return f"Basic {token}"


class AutomicClient:
    """Use as an async context manager: `async with AutomicClient() as c: ...`

    A fresh HTTP connection is opened per call site rather than kept alive
    for the whole server process - simpler to reason about and to test, and
    fine for the call volume an MCP tool sees.
    """

    def __init__(self, settings: AutomicSettings | None = None) -> None:
        self._settings = settings or get_settings()

        if not self._settings.verify_ssl:
            warnings.warn(
                "AUTOMIC_VERIFY_SSL is false - TLS certificate verification is "
                "disabled for the Automic connection. Only use this for a known "
                "internal server with a self-signed certificate.",
                stacklevel=2,
            )

        self._http = httpx.AsyncClient(
            base_url=self._settings.base_url,
            headers={
                "Authorization": _basic_auth_header(
                    self._settings.basic_auth_username,
                    self._settings.password.get_secret_value(),
                ),
                "Accept": "application/json",
            },
            verify=self._settings.verify_ssl,
            timeout=30.0,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def ping(self) -> None:
        response = await self._http.get("/ping")
        response.raise_for_status()

    async def search_objects(
        self,
        object_name: str | None = None,
        object_types: list[str] | None = None,
        folder_path: str | None = None,
        max_results: int = 20,
    ) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        if object_name:
            filters.append({"filter_identifier": "object_name", "object_name": object_name})
        if object_types:
            filters.append({"filter_identifier": "object_type", "values": object_types})
        if folder_path:
            filters.append(
                {
                    "filter_identifier": "location",
                    "location": folder_path,
                    "include_subfolders": True,
                }
            )
        if not filters:
            raise ValueError(
                "search_objects requires at least one of: object_name, object_types, folder_path"
            )

        response = await self._http.post(
            f"/{self._settings.client_id}/search",
            json={"filters": filters, "max_results": max_results},
        )
        response.raise_for_status()
        return response.json()

    async def get_object(self, object_name: str) -> dict[str, Any]:
        # Per the API docs, special characters (e.g. '/') in path segments
        # must be percent-encoded - quote(..., safe="") encodes everything,
        # including '/', matching that requirement.
        encoded_name = quote(object_name, safe="")
        response = await self._http.get(f"/{self._settings.client_id}/objects/{encoded_name}")
        response.raise_for_status()
        return response.json()
