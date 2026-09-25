"""Thin async HTTP client for the Automic AE REST API.

Mostly read-only (ping, search, get a single object, list executions), plus
one call that changes state: execute_object. execute_object performs no
guardrail checks itself (allowlist, confirmation token, cooldown) - those
live in guardrails.py and server.py, in front of this call. This class
trusts its caller.
"""

import base64
import warnings
from collections.abc import AsyncIterator
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

    async def list_executions(
        self,
        object_name: str | None = None,
        object_types: list[str] | None = None,
        time_frame_from: str | None = None,
        time_frame_to: str | None = None,
        max_results: int = 50,
        start_at_run_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"max_results": max_results}
        if object_name:
            params["name"] = object_name
        if object_types:
            # The API expects a single comma-separated value here, not a
            # repeated query param - httpx would repeat the param if we
            # passed a list directly, which doesn't match what the docs
            # describe for this field.
            params["type"] = ",".join(object_types)
        if time_frame_from:
            params["time_frame_from"] = time_frame_from
        if time_frame_to:
            params["time_frame_to"] = time_frame_to
        if time_frame_from or time_frame_to:
            params["time_frame_option"] = "activation"
        if start_at_run_id is not None:
            params["start_at_run_id"] = start_at_run_id

        response = await self._http.get(
            f"/{self._settings.client_id}/executions", params=params
        )
        response.raise_for_status()
        return response.json()

    async def iter_executions(
        self,
        object_name: str | None = None,
        object_types: list[str] | None = None,
        time_frame_from: str | None = None,
        time_frame_to: str | None = None,
        page_size: int = 50,
        max_total: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield up to max_total executions, paging through the API.

        The API docs describe start_at_run_id as "RunID > this value" while
        also saying results are sorted descending - an apparent
        contradiction we haven't been able to verify against a real,
        multi-page result set yet. To stay safe regardless of which way it
        actually behaves, we track the run_ids seen so far and stop (rather
        than loop forever or double-count) the moment a "next" page fails to
        introduce any new run_id.
        """
        seen_run_ids: set[int] = set()
        start_at_run_id: int | None = None
        fetched = 0

        while fetched < max_total:
            page = await self.list_executions(
                object_name=object_name,
                object_types=object_types,
                time_frame_from=time_frame_from,
                time_frame_to=time_frame_to,
                max_results=min(page_size, max_total - fetched),
                start_at_run_id=start_at_run_id,
            )
            items = page.get("data", [])
            if not items:
                return

            new_items = [item for item in items if item.get("run_id") not in seen_run_ids]
            if not new_items:
                return  # pagination made no progress - stop rather than loop

            for item in new_items:
                seen_run_ids.add(item["run_id"])
                yield item
                fetched += 1
                if fetched >= max_total:
                    return

            if not page.get("hasmore"):
                return
            start_at_run_id = items[-1]["run_id"]

    async def execute_object(
        self, object_name: str, inputs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run object_name immediately (execution_option="execute" - no
        scheduling for a later time, no recurring execution). Returns
        {"run_id": int}.

        No guardrail checks here by design - see the module docstring.
        """
        body: dict[str, Any] = {"object_name": object_name, "execution_option": "execute"}
        if inputs:
            body["inputs"] = inputs

        response = await self._http.post(f"/{self._settings.client_id}/executions", json=body)
        response.raise_for_status()
        return response.json()
