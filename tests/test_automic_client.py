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


def _fake_execution(run_id: int) -> dict:
    return {"run_id": run_id, "name": "DAILY_BACKUP", "status_text": "ENDED_OK - ok."}


async def test_list_executions_builds_expected_query_params(settings: AutomicSettings) -> None:
    with respx.mock(base_url=settings.base_url) as mock:
        route = mock.get(f"/{settings.client_id}/executions").mock(
            return_value=httpx.Response(200, json={"data": [], "total": 0, "hasmore": False})
        )
        async with AutomicClient(settings) as client:
            await client.list_executions(
                object_name="DAILY*",
                object_types=["JOBS", "JOBP"],
                time_frame_from="2026-09-01T00:00:00Z",
                time_frame_to="2026-09-02T00:00:00Z",
                max_results=10,
                start_at_run_id=42,
            )

    sent = route.calls.last.request.url.params
    assert sent["name"] == "DAILY*"
    assert sent["type"] == "JOBS,JOBP"  # comma-joined, not repeated params
    assert sent["time_frame_from"] == "2026-09-01T00:00:00Z"
    assert sent["time_frame_to"] == "2026-09-02T00:00:00Z"
    assert sent["time_frame_option"] == "activation"
    assert sent["max_results"] == "10"
    assert sent["start_at_run_id"] == "42"


async def test_iter_executions_pages_through_multiple_pages(settings: AutomicSettings) -> None:
    page_1 = [_fake_execution(run_id) for run_id in range(110, 100, -1)]  # 110..101, 10 items
    page_2 = [_fake_execution(run_id) for run_id in range(100, 94, -1)]  # 100..95, 6 items

    def handler(request: httpx.Request) -> httpx.Response:
        start_at = request.url.params.get("start_at_run_id")
        if start_at is None:
            return httpx.Response(200, json={"data": page_1, "total": 16, "hasmore": True})
        return httpx.Response(200, json={"data": page_2, "total": 16, "hasmore": False})

    with respx.mock(base_url=settings.base_url) as mock:
        mock.get(f"/{settings.client_id}/executions").mock(side_effect=handler)
        async with AutomicClient(settings) as client:
            run_ids = [e["run_id"] async for e in client.iter_executions(max_total=100)]

    assert run_ids == list(range(110, 94, -1))  # all 16, in order, no duplicates


async def test_iter_executions_stops_at_max_total_without_fetching_extra_pages(
    settings: AutomicSettings,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        data = [_fake_execution(run_id) for run_id in range(100, 90, -1)]  # 10 items
        return httpx.Response(200, json={"data": data, "total": 100, "hasmore": True})

    with respx.mock(base_url=settings.base_url) as mock:
        mock.get(f"/{settings.client_id}/executions").mock(side_effect=handler)
        async with AutomicClient(settings) as client:
            run_ids = [e["run_id"] async for e in client.iter_executions(max_total=5)]

    assert len(run_ids) == 5
    assert calls == 1  # first page already had enough - no second request made


async def test_iter_executions_stops_if_pagination_makes_no_progress(
    settings: AutomicSettings,
) -> None:
    # Simulates the case where start_at_run_id doesn't behave as expected
    # and the "next" page repeats the same items - must not loop forever.
    same_page = [_fake_execution(run_id) for run_id in range(100, 95, -1)]  # 5 items

    with respx.mock(base_url=settings.base_url) as mock:
        mock.get(f"/{settings.client_id}/executions").mock(
            return_value=httpx.Response(200, json={"data": same_page, "total": 999, "hasmore": True})
        )
        async with AutomicClient(settings) as client:
            run_ids = [e["run_id"] async for e in client.iter_executions(max_total=100)]

    assert run_ids == list(range(100, 95, -1))  # only the first page's items, not looped forever
