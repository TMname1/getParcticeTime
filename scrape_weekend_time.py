import re
from pathlib import Path
from datetime import datetime, date, time, timedelta, timezone
import sys
from urllib import request, error

PRIMARY_URL = "https://czq.rth1.xyz/time"
FALLBACK_URL = "https://r.jina.ai/" + PRIMARY_URL
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DAY_CONFIG = {
    "\u5468\u4e94": ("Friday", 4),
    "\u5468\u516d": ("Saturday", 5),
    "\u5468\u65e5": ("Sunday", 6),
}


def fetch_content():
    """Attempt to fetch the schedule page, falling back via Jina if needed."""
    attempts = [("primary", PRIMARY_URL), ("fallback", FALLBACK_URL)]
    last_exc = None
    for label, url in attempts:
        try:
            req = request.Request(url, headers=HEADERS)
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            return body, label
        except error.HTTPError as exc:
            last_exc = exc
            if exc.code == 403 and url != FALLBACK_URL:
                continue
        except Exception as exc:  # pragma: no cover - network failures
            last_exc = exc
    raise RuntimeError(f"Unable to fetch schedule: {last_exc}")


def extract_time_ranges(text: str):
    """Extract time ranges for Friday, Saturday, Sunday from the given text."""
    time_map = {}
    normalized_lines = [line.strip().replace("\uff1a", ":") for line in text.splitlines()]
    in_week_section = False

    for line in normalized_lines:
        if not in_week_section and "\u672c\u5468\u5b89\u6392" in line:
            in_week_section = True
            continue
        if not in_week_section:
            continue
        if not line or not line.startswith("*"):
            continue
        for day, _ in DAY_CONFIG.items():
            if day in line:
                match = re.search(r"(\d{1,2}:\d{2})\s*[\-~\u2013]\s*(\d{1,2}:\d{2})", line)
                if match:
                    time_map[day] = match.group(1), match.group(2)
        if len(time_map) == len(DAY_CONFIG):
            break
    return time_map


def parse_clock(clock_str: str) -> time:
    hour, minute = map(int, clock_str.split(":"))
    return time(hour=hour, minute=minute)


def next_weekday(start: date, target_weekday: int) -> date:
    days_ahead = (target_weekday - start.weekday()) % 7
    return start + timedelta(days=days_ahead)


def combine_datetime(base_date: date, clock: time, tzinfo) -> datetime:
    return datetime.combine(base_date, clock, tzinfo=tzinfo)


def ensure_timezone():
    try:
        from zoneinfo import ZoneInfo  # type: ignore

        return ZoneInfo("Asia/Shanghai")
    except Exception:  # pragma: no cover - fallback when tzdata unavailable
        return timezone(timedelta(hours=8), name="Asia/Shanghai")


def build_ics(events, calendar_name="CZQ Weekend Training"):
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CodexAgent//CZQ Weekend//EN",
        f"NAME:{calendar_name}",
        f"X-WR-CALNAME:{calendar_name}",
        "CALSCALE:GREGORIAN",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "X-LIC-LOCATION:Asia/Shanghai",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    for event in events:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{now_stamp}",
            f"SUMMARY:{event['summary']}",
            f"DTSTART;TZID=Asia/Shanghai:{event['start']}",
            f"DTEND;TZID=Asia/Shanghai:{event['end']}",
            "RRULE:FREQ=WEEKLY",
            f"DESCRIPTION:Source {PRIMARY_URL}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def main(output_path: str = "weekend_schedule.ics"):
    content, source_label = fetch_content()
    time_map = extract_time_ranges(content)
    if len(time_map) < len(DAY_CONFIG):
        raise SystemExit("Failed to parse all weekend slots. The page layout may have changed.")

    tzinfo = ensure_timezone()
    today = datetime.now(tzinfo).date()
    events = []

    for day_cn, (day_en, weekday_index) in DAY_CONFIG.items():
        start_clock, end_clock = time_map[day_cn]
        start_time = parse_clock(start_clock)
        end_time = parse_clock(end_clock)
        event_date = next_weekday(today, weekday_index)
        start_dt = combine_datetime(event_date, start_time, tzinfo)
        end_dt = combine_datetime(event_date, end_time, tzinfo)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        events.append(
            {
                "uid": f"{day_en.lower()}-{start_dt.strftime('%Y%m%dT%H%M%S')}@czq.rth1.xyz",
                "summary": f"{day_cn} Training",
                "start": start_dt.strftime("%Y%m%dT%H%M%S"),
                "end": end_dt.strftime("%Y%m%dT%H%M%S"),
            }
        )

    ics_text = build_ics(events)
    Path(output_path).write_text(ics_text, encoding="utf-8")
    print(f"Generated {output_path} using {source_label} data")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "weekend_schedule.ics"
    main(target)
