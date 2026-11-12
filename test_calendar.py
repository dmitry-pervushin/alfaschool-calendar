from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alfaschool_calendar import Client, calendar, fold, parse_schedule, write_atomic


def page(lesson_id="123", when="07.10.2025 19:00:00", title="60 мин, Проведено"):
    return f'''<table class="schedule as-calendar"><tr><td>
    <div class="busy"><span title="888;07.10.2025 14:00:00;07.10.2025 15:00:00">Занятый период</span></div>
    <div class="lesson lessonform past" title="{title}">
    <span title="{lesson_id};{when};60;DONE;NOR;;;ONE;0"></span>
    <span>19:00</span><a href="/chat"> </a><b>Итальянский</b>
    <div>Преподаватель</div><span class="info">ID: <b>{lesson_id}</b><br>
    Стоимость: <b>100</b></span></div>
    <div class="modal"><b>Итальянский</b></div></td></tr></table>'''


class CalendarTests(unittest.TestCase):
    def test_real_markup_shape_timezone_duration_and_no_busy_or_duplicates(self):
        events = parse_schedule(page())
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["summary"], "Alfa School — Итальянский")
        self.assertIn("Преподаватель: Преподаватель", event["description"])
        self.assertEqual(event["end"] - event["start"], timedelta(hours=1))
        result = calendar(events)
        self.assertIn("DTSTART:20251007T160000Z\r\n", result)
        self.assertIn("DTEND:20251007T170000Z\r\n", result)
        self.assertNotIn("Стоимость", result)
        self.assertEqual(result.count("BEGIN:VEVENT"), 1)
        self.assertIn("UID:lesson-123@my.alfaschool.ru", result)

    def test_login_and_changed_markup_fail_instead_of_empty_calendar(self):
        for html in ['<input name="userpass">', '<h1>Ошибка сервера</h1>']:
            with self.assertRaises(RuntimeError):
                parse_schedule(html)
        self.assertEqual(parse_schedule('<table class="schedule"></table>'), [])

    def test_month_boundary_deduplication_and_requested_window(self):
        client = Client()
        html = page("123", "30.09.2025 19:00:00")
        with patch.object(client, "request", return_value=html) as request:
            events = client.events(date(2025, 9, 1), date(2025, 10, 31))
            self.assertEqual(request.call_count, 2)
            self.assertEqual(len(events), 1)
        with patch.object(client, "request", return_value=html):
            self.assertEqual(client.events(date(2025, 10, 1), date(2025, 10, 31)), [])

    def test_cancelled_and_utf8_folding(self):
        self.assertIn("STATUS:CANCELLED", calendar(parse_schedule(page(title="Отменено"))))
        line = "DESCRIPTION:" + "Длинная строка; " * 40
        folded = fold(line)
        self.assertTrue(all(len(part.encode()) <= 75 for part in folded.split("\r\n")))
        self.assertEqual(folded.replace("\r\n ", ""), line)

    def test_atomic_failure_preserves_previous_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calendar.ics"
            write_atomic(path, "old")
            with patch("alfaschool_calendar.os.replace", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    write_atomic(path, "new")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(list(Path(folder).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
