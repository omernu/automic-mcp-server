"""Stage 2 tests: AutomicClient against a mocked Automic AE REST API (via
respx) - no real network call, since the real server isn't reachable from
here. Response fixtures are grounded in reference/automic-ae-rest-api.json
(the real OpenAPI spec) so they reflect the real response shape.
"""

import json

import httpx
import pytest
import respx

from automic_mcp.automic_client import AutomicClient
from automic_mcp.config import AutomicSettings


@pytest.fixture
def settings() -> AutomicSettings:
    # _env_file=None: without this, AutomicSettings still reads the real
    # local .env (env_file=".env" in its model_config) for any field we
    # don't pass explicitly here - which silently pulled in the developer's
    # real AUTOMIC_VERIFY_SSL value and made this fixture non-reproducible.
    return AutomicSettings(
        _env_file=None,
        base_url="https://automic.example.com:8088/ae/api/v1",
        client_id="100",
        username="testuser",
        password="testpass",
        department="TEST",
    )


def test_verify_ssl_false_warns(settings: AutomicSettings) -> None:
    insecure = settings.model_copy(update={"verify_ssl": False})
    with pytest.warns(UserWarning, match="TLS certificate verification is disabled"):
        AutomicClient(insecure)


def test_verify_ssl_true_by_default_does_not_warn(settings: AutomicSettings, recwarn) -> None:
    AutomicClient(settings)
    assert not any("TLS certificate verification" in str(w.message) for w in recwarn.list)


async def test_ping_success(settings: AutomicSettings) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        mock.get("/ping").mock(return_value=httpx.Response(200))
        async with AutomicClient(settings) as client:
            await client.ping()  # no exception raised = success


async def test_ping_failure_raises(settings: AutomicSettings) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        mock.get("/ping").mock(return_value=httpx.Response(500))
        async with AutomicClient(settings) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.ping()


async def test_basic_auth_header_matches_ae_username_department_password_format(
    settings: AutomicSettings,
) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        route = mock.get("/ping").mock(return_value=httpx.Response(200))
        async with AutomicClient(settings) as client:
            await client.ping()

    request = route.calls.last.request
    # base64("testuser/TEST:testpass") in ISO-8859-1
    assert request.headers["Authorization"] == "Basic dGVzdHVzZXIvVEVTVDp0ZXN0cGFzcw=="


async def test_search_objects_builds_filters_and_returns_response(
    settings: AutomicSettings,
) -> None:
    fixture = {
        "data": [{"name": "DAILY_BACKUP", "type": "JOBS", "folder_path": "\\PROJECT\\JOBS"}],
        "total": 1,
        "hasmore": False,
    }
    with respx.mock(base_url=settings.base_url) as mock:
        route = mock.post(f"/{settings.client_id}/search").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with AutomicClient(settings) as client:
            result = await client.search_objects(object_name="DAILY*", object_types=["JOBS"])

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["filters"] == [
        {"filter_identifier": "object_name", "object_name": "DAILY*"},
        {"filter_identifier": "object_type", "values": ["JOBS"]},
    ]
    assert result == fixture


async def test_search_objects_requires_at_least_one_filter(settings: AutomicSettings) -> None:
    async with AutomicClient(settings) as client:
        with pytest.raises(ValueError):
            await client.search_objects()


async def test_get_object_returns_real_shaped_jobs_definition(settings: AutomicSettings) -> None:
    # Shape taken from the real "JOBS" example in reference/automic-ae-rest-api.json
    fixture = {
        "data": {
            "jobs": {
                "metadata": {"version": "23.0.0"},
                "general_attributes": {
                    "type": "JOBS",
                    "name": "PATCH.JOBS.SETUP",
                    "platform": "WINDOWS",
                },
            }
        }
    }
    with respx.mock(base_url=settings.base_url) as mock:
        mock.get(f"/{settings.client_id}/objects/PATCH.JOBS.SETUP").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with AutomicClient(settings) as client:
            result = await client.get_object("PATCH.JOBS.SETUP")

    assert result["data"]["jobs"]["general_attributes"]["name"] == "PATCH.JOBS.SETUP"


async def test_get_object_percent_encodes_special_characters_in_name(
    settings: AutomicSettings,
) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        route = mock.get(f"/{settings.client_id}/objects/FOLDER%2FJOB").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        async with AutomicClient(settings) as client:
            await client.get_object("FOLDER/JOB")

    assert route.called


async def test_get_object_not_found_raises(settings: AutomicSettings) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        mock.get(f"/{settings.client_id}/objects/NO.SUCH.OBJECT").mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )
        async with AutomicClient(settings) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_object("NO.SUCH.OBJECT")
