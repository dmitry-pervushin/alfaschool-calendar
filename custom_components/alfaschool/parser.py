"""Parse lesson cards from the Alfa School schedule."""

from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from .exceptions import AuthenticationError, ScheduleError

MOSCOW = ZoneInfo("Europe/Moscow")


class AccountNameParser(HTMLParser):
    """Read the signed-in student's name from the account menu."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._capture = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and dict(attrs).get("href") == "#nav-user" and not self._parts:
            self._capture = True
        if self._capture and tag == "br":
            self._parts.append(" ")

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._capture = False

    @property
    def name(self) -> str | None:
        return " ".join("".join(self._parts).split()) or None


class ScheduleParser(HTMLParser):
    """Read actual lesson cards; busy blocks and modal duplicates are excluded."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.depth = 0
        self.card = None
        self.capture = None
        self.info = False
        self.schedule_found = False
        self.login = False
        self.timestamp = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "input":
            if attrs.get("name") == "timestamp":
                self.timestamp = attrs.get("value")
            if attrs.get("name") == "userpass":
                self.login = True
        if tag == "table" and "schedule" in classes:
            self.schedule_found = True
        if tag == "div":
            if self.card is not None:
                self.depth += 1
                if self.depth == 2 and not self.info:
                    self.capture = "teacher"
            elif "lessonform" in classes:
                self.depth = 1
                self.card = {
                    "details": attrs.get("title", ""),
                    "subject": "",
                    "teacher": "",
                    "fields": None,
                }
                self.info = False
        if self.card is not None:
            if "info" in classes:
                self.info = True
            if tag == "span" and self.card["fields"] is None:
                fields = attrs.get("title", "").split(";")
                if len(fields) >= 5:
                    self.card["fields"] = fields
            if tag == "b" and not self.info:
                self.capture = "subject"

    def handle_data(self, data):
        if self.card is not None and self.capture and not self.info:
            self.card[self.capture] += data

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag in ("b", "div"):
            self.capture = None
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.events.append(self.card)
                self.card = None


def parse_schedule(html):
    parser = ScheduleParser()
    parser.feed(html)
    if parser.login:
        raise AuthenticationError("Authentication required")
    if not parser.schedule_found:
        raise ScheduleError(
            "Не найдена таблица расписания; формат сайта мог измениться"
        )
    events = []
    for card in parser.events:
        fields = card["fields"]
        if not fields or not fields[0].isdigit():
            raise ScheduleError("Не удалось прочитать данные занятия")
        try:
            start = datetime.strptime(fields[1], "%d.%m.%Y %H:%M:%S").replace(
                tzinfo=MOSCOW
            )
            minutes = int(fields[2])
        except (ValueError, IndexError) as err:
            raise ScheduleError("Invalid lesson date or duration") from err
        if minutes <= 0:
            raise ScheduleError("Некорректная длительность занятия")
        events.append(
            {
                "id": fields[0],
                "start": start,
                "end": start + timedelta(minutes=minutes),
                "summary": "Alfa School — " + (card["subject"].strip() or "Занятие"),
                "description": "Преподаватель: "
                + card["teacher"].strip()
                + "\n"
                + card["details"],
                "cancelled": "отмен" in card["details"].lower(),
            }
        )
    return events
