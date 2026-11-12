#!/usr/bin/env python3
"""Export the authenticated Alfa School schedule to iCalendar. Python 3.9+."""

import argparse
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import http.cookiejar
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = "https://my.alfaschool.ru"
MOSCOW = ZoneInfo("Europe/Moscow")


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
                self.card = {"details": attrs.get("title", ""),
                             "subject": "", "teacher": "", "fields": None}
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
        raise RuntimeError("Сайт запросил вход: сессия истекла или неверный логин/пароль")
    if not parser.schedule_found:
        raise RuntimeError("Не найдена таблица расписания; формат сайта мог измениться")
    events = []
    for card in parser.events:
        fields = card["fields"]
        if not fields or not fields[0].isdigit():
            raise RuntimeError("Не удалось прочитать данные занятия")
        start = datetime.strptime(fields[1], "%d.%m.%Y %H:%M:%S").replace(tzinfo=MOSCOW)
        minutes = int(fields[2])
        if minutes <= 0:
            raise RuntimeError("Некорректная длительность занятия")
        events.append({"id": fields[0], "start": start,
                       "end": start + timedelta(minutes=minutes),
                       "summary": "Alfa School — " + (card["subject"].strip() or "Занятие"),
                       "description": "Преподаватель: " + card["teacher"].strip()
                       + "\n" + card["details"],
                       "cancelled": "отмен" in card["details"].lower()})
    return events


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data else None
        request = urllib.request.Request(BASE + path, data=body,
                                         headers={"User-Agent": "AlfaschoolCalendar/1.0"})
        with self.opener.open(request, timeout=30) as response:
            if urllib.parse.urlsplit(response.url).hostname != "my.alfaschool.ru":
                raise RuntimeError("Неожиданный адрес ответа сайта")
            return response.read().decode("utf-8")

    def login(self, username, password):
        parser = ScheduleParser()
        parser.feed(self.request("/profile"))
        data = {"userlogin": username, "userpass": password, "b_auth": "Войти"}
        if parser.timestamp:
            data["timestamp"] = parser.timestamp
        parser = ScheduleParser()
        parser.feed(self.request("/profile", data))
        if parser.login:
            raise RuntimeError("Вход отклонён: проверьте ALFASCHOOL_USERNAME и ALFASCHOOL_PASSWORD")

    def events(self, start, end):
        month = start.replace(day=1)
        result = {}
        while month <= end:
            html = self.request("/schedule/m/" + month.isoformat() + "//")
            for event in parse_schedule(html):
                if start <= event["start"].date() <= end:
                    result[event["id"]] = event
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        return sorted(result.values(), key=lambda event: event["start"])


def escape(value):
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace(
        "\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line):
    # RFC 5545: physical lines are at most 75 octets, including continuation space.
    result, part = [], ""
    for char in line:
        if len((part + char).encode("utf-8")) > 75:
            result.append(part)
            part = " "
        part += char
    return "\r\n".join(result + [part])


def calendar(events):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Alfaschool Calendar//RU",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:Alfa School"]
    for event in events:
        lines += ["BEGIN:VEVENT", "UID:lesson-" + event["id"] + "@my.alfaschool.ru",
                  "DTSTAMP:" + stamp,
                  "DTSTART:" + event["start"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                  "DTEND:" + event["end"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                  "SUMMARY:" + escape(event["summary"]),
                  "DESCRIPTION:" + escape(event["description"]),
                  "URL:" + BASE + "/schedule/w/" + event["start"].date().isoformat()
                  + "//?open=" + event["id"],
                  "STATUS:" + ("CANCELLED" if event["cancelled"] else "CONFIRMED"),
                  "END:VEVENT"]
    return "\r\n".join(fold(line) for line in lines + ["END:VCALENDAR", ""])


def write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            name = file.name
            file.write(content.encode("utf-8"))
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/alfaschool.ics")
    parser.add_argument("--start", type=date.fromisoformat, help="YYYY-MM-DD, по умолчанию 30 дней назад")
    parser.add_argument("--end", type=date.fromisoformat, help="YYYY-MM-DD, по умолчанию через 90 дней")
    parser.add_argument("--interval-hours", type=float, help="Повторять опрос каждые N часов; без параметра — один раз")
    args = parser.parse_args()
    if args.interval_hours is not None and (not 0 < args.interval_hours < float("inf")):
        parser.error("--interval-hours должен быть конечным положительным числом")
    username = os.environ.get("ALFASCHOOL_USERNAME")
    password = os.environ.get("ALFASCHOOL_PASSWORD")
    if not username or not password:
        parser.error("Задайте ALFASCHOOL_USERNAME и ALFASCHOOL_PASSWORD в окружении")
    while True:
        try:
            today = datetime.now(MOSCOW).date()
            start, end = args.start or today - timedelta(days=30), args.end or today + timedelta(days=90)
            if start > end:
                raise ValueError("Дата начала должна быть не позже даты конца")
            client = Client()
            client.login(username, password)
            events = client.events(start, end)
            write_atomic(args.output, calendar(events))
            print(f"{datetime.now().isoformat(timespec='seconds')}: {len(events)} занятий, "
                  f"{start} — {end}, {args.output}", flush=True)
        except Exception as error:
            print(f"Ошибка обновления: {error}", file=sys.stderr, flush=True)
            if args.interval_hours is None:
                return 1
        if args.interval_hours is None:
            return 0
        time.sleep(args.interval_hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
