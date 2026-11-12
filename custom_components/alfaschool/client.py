"""Asynchronous Alfa School client with an isolated cookie session per account."""

import asyncio
from datetime import date

import aiohttp
from yarl import URL

from .const import BASE_URL
from .exceptions import AuthenticationError, ScheduleError
from .parser import AccountNameParser, ScheduleParser, parse_schedule


class AlfaSchoolClient:
    """Read the student's schedule; never modify lessons."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str):
        self.session = session
        self.username = username
        self.password = password
        self.student_name: str | None = None
        self._lock = asyncio.Lock()

    async def _request(self, path: str, data: dict | None = None) -> str:
        async with self.session.request(
            "POST" if data is not None else "GET",
            BASE_URL + path,
            data=data,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
            if response.url.origin() != URL(BASE_URL).origin():
                raise ScheduleError("Unexpected response host")
            return await response.text()

    async def _login(self) -> None:
        self.session.cookie_jar.clear()
        parser = ScheduleParser()
        parser.feed(await self._request("/profile"))
        if not parser.login:
            raise ScheduleError("Login form not found")
        data = {
            "userlogin": self.username,
            "userpass": self.password,
            "b_auth": "Войти",
        }
        if parser.timestamp:
            data["timestamp"] = parser.timestamp
        html = await self._request("/profile", data)
        parser = ScheduleParser()
        parser.feed(html)
        if parser.login:
            raise AuthenticationError("Credentials rejected")
        account = AccountNameParser()
        account.feed(html)
        self.student_name = account.name

    async def async_fetch_months(self, months: set[date]) -> list[dict]:
        """Log in once and fetch a complete snapshot, deduplicated by lesson ID."""
        async with self._lock:
            await self._login()
            events = {}
            for month in sorted(months):
                html = await self._request(f"/schedule/m/{month.isoformat()}//")
                for event in parse_schedule(html):
                    events[event["id"]] = event
            return sorted(events.values(), key=lambda event: event["start"])
