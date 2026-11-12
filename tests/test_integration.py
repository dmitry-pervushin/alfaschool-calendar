"""Integration behavior tested against actual Home Assistant classes."""

from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import aiohttp
import probatio
import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.alfaschool.calendar import AlfaSchoolCalendar
from custom_components.alfaschool.client import AlfaSchoolClient
from custom_components.alfaschool.config_flow import interval_schema
from custom_components.alfaschool.coordinator import AlfaSchoolCoordinator
from custom_components.alfaschool.exceptions import AuthenticationError, ScheduleError
from custom_components.alfaschool.parser import parse_schedule

LOGIN = '<form><input name="userpass"><input name="timestamp" value="123"></form>'
EMPTY = '<table class="schedule"></table>'


def markup(lesson_id="123", when="07.10.2025 19:00:00", details="Проведено"):
    return f'''<table class="schedule"><tr><td>
    <div class="busy"><span title="888;07.10.2025 14:00:00;07.10.2025 15:00:00">Занятый период</span></div>
    <div class="lessonform" title="{details}"><span title="{lesson_id};{when};60;DONE;NOR"></span>
    <b>Итальянский</b><div>Преподаватель</div><span class="info">Стоимость: <b>100</b></span>
    </div></td></tr></table>'''


def make_entry(hours=24):
    return ConfigEntry(
        domain="alfaschool",
        title="Alfa School",
        version=1,
        minor_version=1,
        source="user",
        unique_id="student@example.com",
        data={"username": "student@example.com", "password": "secret"},
        options={"interval_hours": hours},
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )


@pytest.fixture
async def school_server():
    state = {"reject": False, "posted": None}

    async def profile(request):
        if request.method == "POST":
            state["posted"] = dict(await request.post())
            response = web.Response(
                text=LOGIN if state["reject"] else "<h1>Profile</h1>"
            )
            response.set_cookie("school_session", "student")
            return response
        return web.Response(text=LOGIN)

    async def schedule(request):
        assert request.cookies.get("school_session") == "student"
        return web.Response(text=markup())

    app = web.Application()
    app.router.add_route("*", "/profile", profile)
    app.router.add_get("/schedule/m/{month}//", schedule)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    with patch(
        "custom_components.alfaschool.client.BASE_URL", f"http://127.0.0.1:{port}"
    ):
        yield state
    await runner.cleanup()


async def test_async_client_posts_form_and_deduplicates(school_server):
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True)
    ) as session:
        client = AlfaSchoolClient(session, "student@example.com", "secret")
        events = await client.async_fetch_months({date(2025, 9, 1), date(2025, 10, 1)})
        assert len(events) == 1
        assert events[0]["start"].astimezone(timezone.utc).hour == 16
        assert events[0]["summary"] == "Alfa School — Итальянский"
        assert school_server["posted"] == {
            "userlogin": "student@example.com",
            "userpass": "secret",
            "b_auth": "Войти",
            "timestamp": "123",
        }


async def test_authentication_and_page_errors(school_server):
    school_server["reject"] = True
    async with aiohttp.ClientSession() as session:
        client = AlfaSchoolClient(session, "student@example.com", "secret")
        with pytest.raises(AuthenticationError):
            await client.async_fetch_months({date(2025, 10, 1)})
    assert parse_schedule(EMPTY) == []
    with pytest.raises(ScheduleError):
        parse_schedule("<h1>Maintenance</h1>")
    with pytest.raises(ScheduleError):
        parse_schedule(markup(when="bad date"))


@pytest.mark.parametrize("hours", [4, 8, 24, 168])
async def test_calendar_overlap_current_next_cancellation_and_cached_reads(hass, hours):
    entry = make_entry(hours)
    lessons = parse_schedule(
        markup() + markup("124", "08.10.2025 19:00:00", "Отменено")
    )
    client = AsyncMock()
    client.async_fetch_months.return_value = lessons
    coordinator = AlfaSchoolCoordinator(hass, entry, client)
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(hours=min(hours, 24))
    entity = AlfaSchoolCalendar(coordinator, entry)
    now = datetime(2025, 10, 7, 16, 30, tzinfo=timezone.utc)
    with patch("custom_components.alfaschool.calendar.dt_util.now", return_value=now):
        assert entity.event.uid == "lesson-123@my.alfaschool.ru"
    with patch(
        "custom_components.alfaschool.calendar.dt_util.now",
        return_value=now + timedelta(days=1),
    ):
        assert entity.event is None
    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    events = await entity.async_get_events(hass, start, end)
    assert len(events) == 1
    count = client.async_fetch_months.call_count
    assert await entity.async_get_events(hass, start, end) == events
    assert client.async_fetch_months.call_count == count
    assert await entity.async_get_events(hass, lessons[0]["end"], end) == []
    assert await entity.async_get_events(hass, start, lessons[0]["start"]) == []


def test_update_interval_maximum_and_legacy_settings():
    schema = interval_schema()
    for hours in (1, 4, 8, 24):
        assert schema({"interval_hours": hours})["interval_hours"] == hours
    for hours in (0, 25, 168):
        with pytest.raises(probatio.Invalid):
            schema({"interval_hours": hours})
    assert interval_schema(168)({})["interval_hours"] == 24


async def test_failure_preserves_snapshot_and_unavailable(hass):
    entry = make_entry()
    client = AsyncMock()
    client.async_fetch_months.return_value = parse_schedule(markup())
    coordinator = AlfaSchoolCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    original = coordinator.data
    entity = AlfaSchoolCalendar(coordinator, entry)
    assert entity.available
    client.async_fetch_months.side_effect = ScheduleError("format changed")
    await coordinator.async_refresh()
    assert coordinator.data is original
    assert not entity.available
    with pytest.raises(HomeAssistantError):
        await coordinator.async_get_events(
            datetime(2025, 10, 1, tzinfo=timezone.utc),
            datetime(2025, 11, 1, tzinfo=timezone.utc),
        )
    client.async_fetch_months.side_effect = AuthenticationError("rejected")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_config_flow_calendar_setup_options_reload_and_unload(hass):
    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        return_value=parse_schedule(markup()),
    ):
        result = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        assert result["type"] == "form"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": "student@example.com",
                "password": "secret",
                "interval_hours": 8,
            },
        )
        await hass.async_block_till_done()
        assert result["type"] == "create_entry"
        entry = result["result"]
        assert entry.state is ConfigEntryState.LOADED
        assert hass.states.get("calendar.alfa_school_student_example_com") is not None
        assert entry.runtime_data.update_interval == timedelta(hours=8)
        session = entry.runtime_data.client.session
        options = await hass.config_entries.options.async_init(entry.entry_id)
        assert options["type"] == "form"
        await hass.config_entries.options.async_configure(
            options["flow_id"], {"interval_hours": 4}
        )
        await hass.async_block_till_done()
        assert entry.runtime_data.update_interval == timedelta(hours=4)
        assert session.closed
        current_session = entry.runtime_data.client.session
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert current_session.closed


async def test_config_flow_rejects_credentials(hass):
    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        side_effect=AuthenticationError("rejected"),
    ):
        result = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": "student@example.com",
                "password": "bad",
                "interval_hours": 24,
            },
        )
        assert result["errors"] == {"base": "invalid_auth"}
        assert not hass.config_entries.async_entries("alfaschool")


async def test_duplicate_account_and_reauthentication_keep_calendar_identity(hass):
    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        return_value=[],
    ):
        flow = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "username": "student@example.com",
                "password": "old",
                "interval_hours": 24,
            },
        )
        await hass.async_block_till_done()
        entry = result["result"]
        original_entity = hass.states.get("calendar.alfa_school_student_example_com")
        assert original_entity.state == "off"
        duplicate = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            duplicate["flow_id"],
            {"username": "STUDENT@example.com", "password": "old", "interval_hours": 4},
        )
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"
        reauth = await hass.config_entries.flow.async_init(
            "alfaschool",
            context={
                "source": "reauth",
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
            },
            data=dict(entry.data),
        )
        assert reauth["step_id"] == "reauth_confirm"
        with patch(
            "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
            side_effect=AuthenticationError("rejected"),
        ):
            failed = await hass.config_entries.flow.async_configure(
                reauth["flow_id"], {"password": "bad"}
            )
            assert failed["errors"] == {"base": "invalid_auth"}
            assert entry.data["password"] == "old"
        result = await hass.config_entries.flow.async_configure(
            reauth["flow_id"], {"password": "new"}
        )
        await hass.async_block_till_done()
        assert result["reason"] == "reauth_successful"
        assert entry.data["password"] == "new"
        assert len(hass.config_entries.async_entries("alfaschool")) == 1
        assert hass.states.get("calendar.alfa_school_student_example_com") is not None


async def test_calendar_get_events_service(hass):
    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        return_value=parse_schedule(markup()),
    ):
        flow = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "username": "student@example.com",
                "password": "secret",
                "interval_hours": 24,
            },
        )
        await hass.async_block_till_done()
        result = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": "calendar.alfa_school_student_example_com",
                "start_date_time": "2025-10-01T00:00:00+00:00",
                "end_date_time": "2025-11-01T00:00:00+00:00",
            },
            blocking=True,
            return_response=True,
        )
        events = result["calendar.alfa_school_student_example_com"]["events"]
        assert len(events) == 1
        assert events[0]["summary"] == "Alfa School — Итальянский"
        assert events[0]["start"] == "2025-10-07T19:00:00+03:00"


@pytest.mark.parametrize(
    "names, ids",
    [
        (
            ("Dmitry", "Anna"),
            ("calendar.alfa_school_dmitry", "calendar.alfa_school_anna"),
        ),
        (
            ("Alex", "Alex"),
            ("calendar.alfa_school_alex", "calendar.alfa_school_alex_2"),
        ),
    ],
)
async def test_two_accounts_have_separate_calendars_and_events(hass, names, ids):
    async def fetch(client, months):
        lesson_id = "101" if client.username == "first@example.com" else "202"
        when = "07.10.2025 19:00:00" if lesson_id == "101" else "08.10.2025 19:00:00"
        return parse_schedule(markup(lesson_id=lesson_id, when=when))

    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        new=fetch,
    ):
        entries = []
        for username, name in zip(("first@example.com", "second@example.com"), names):
            flow = await hass.config_entries.flow.async_init(
                "alfaschool", context={"source": "user"}
            )
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {
                    "username": username,
                    "password": "secret",
                    "name": name,
                    "interval_hours": 8,
                },
            )
            await hass.async_block_till_done()
            entries.append(result["result"])
        registry = er.async_get(hass)
        for index, entity_id in enumerate(ids):
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.attributes["friendly_name"] == f"Alfa School — {names[index]}"
            assert registry.async_get(entity_id).unique_id == entries[index].entry_id
        assert entries[0].entry_id != entries[1].entry_id
        assert (
            entries[0].runtime_data.client.session
            is not entries[1].runtime_data.client.session
        )
        response = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": list(ids),
                "start_date_time": "2025-10-01T00:00:00+00:00",
                "end_date_time": "2025-11-01T00:00:00+00:00",
            },
            blocking=True,
            return_response=True,
        )
        assert response[ids[0]]["events"][0]["start"] == "2025-10-07T19:00:00+03:00"
        assert response[ids[1]]["events"][0]["start"] == "2025-10-08T19:00:00+03:00"


async def test_renaming_preserves_entity_id_unique_id_and_user_customization(hass):
    with patch(
        "custom_components.alfaschool.client.AlfaSchoolClient.async_fetch_months",
        return_value=[],
    ):
        flow = await hass.config_entries.flow.async_init(
            "alfaschool", context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "username": "student@example.com",
                "password": "secret",
                "name": "  Dmitry  ",
                "interval_hours": 8,
            },
        )
        await hass.async_block_till_done()
        entry = result["result"]
        entity_id = "calendar.alfa_school_dmitry"
        registry = er.async_get(hass)
        unique_id = registry.async_get(entity_id).unique_id
        for new_name, expected_name in (
            ("Дмитрий Первушин", "Дмитрий Первушин"),
            ("  ", "student@example.com"),
        ):
            options = await hass.config_entries.options.async_init(entry.entry_id)
            await hass.config_entries.options.async_configure(
                options["flow_id"], {"name": new_name, "interval_hours": 4}
            )
            await hass.async_block_till_done()
            assert (
                hass.states.get(entity_id).attributes["friendly_name"]
                == f"Alfa School — {expected_name}"
            )
            assert registry.async_get(entity_id).unique_id == unique_id
            assert registry.async_get(entity_id).config_entry_id == entry.entry_id
            assert len(hass.states.async_entity_ids("calendar")) == 1
        registry.async_update_entity(
            entity_id, name="Мой календарь", new_entity_id="calendar.my_lessons"
        )
        await hass.async_block_till_done()
        options = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            options["flow_id"], {"name": "Dmitry", "interval_hours": 8}
        )
        await hass.async_block_till_done()
        assert (
            hass.states.get("calendar.my_lessons").attributes["friendly_name"]
            == "Мой календарь"
        )
        assert registry.async_get("calendar.my_lessons").unique_id == unique_id
