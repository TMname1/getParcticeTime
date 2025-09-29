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

TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[\-~\u2013]\s*(\d{1,2}:\d{2})")

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

def extract_time_ranges(text: str, current_week: int | None = None):
    """Extract time ranges for weekend training sessions."""
    time_map = {}
    normalized_lines = [line.strip().replace("\uff1a", ":") for line in text.splitlines()]
    in_week_section = False
    pending_day = None
    pending_rows = []

    def parse_week_spec(spec: str):
        weeks = set()
        tokens = re.split(r"[,\uFF0C\u3001]", spec)
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            token = token.replace("\u5468", "")
            range_match = re.match(r"(\d{1,2})\s*[-~\u2013]\s*(\d{1,2})", token)
            if range_match:
                start_week, end_week = map(int, range_match.groups())
                if start_week <= end_week:
                    weeks.update(range(start_week, end_week + 1))
                else:
                    weeks.update(range(end_week, start_week + 1))
                continue
            for number in re.findall(r"\d+", token):
                weeks.add(int(number))
        return weeks

    def choose_table_time(rows):
        if current_week is not None:
            for spec, start, end in rows:
                weeks = parse_week_spec(spec)
                if weeks and current_week in weeks:
                    return start, end
        for _, start, end in rows:
            if start and end:
                return start, end
        return None

    def finalize_table():
        nonlocal pending_day, pending_rows
        if pending_day and pending_rows:
            chosen = choose_table_time(pending_rows)
            if chosen:
                time_map[pending_day] = chosen
        pending_day = None
        pending_rows = []

    for line in normalized_lines:
        if not in_week_section and "\u672c\u5468\u5b89\u6392" in line:
            in_week_section = True
            continue
        if not in_week_section:
            continue

        if pending_day and pending_rows and line and not line.startswith("|"):
            finalize_table()

        if pending_day and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 2 and not all(cell.strip("- ") == "" for cell in cells[:2]):
                time_match = TIME_RANGE_RE.search(cells[1])
                if time_match:
                    pending_rows.append((cells[0], time_match.group(1), time_match.group(2)))
            continue

        if pending_day and not line:
            continue

        if not line or not line.startswith("*"):
            continue

        matched_day = None
        for day in DAY_CONFIG:
            if day in line:
                matched_day = day
                break
        if matched_day is None:
            continue

        time_match = TIME_RANGE_RE.search(line)
        if time_match:
            time_map[matched_day] = (time_match.group(1), time_match.group(2))
            pending_day = None
            pending_rows = []
        else:
            pending_day = matched_day
            pending_rows = []

        if len(time_map) == len(DAY_CONFIG):
            break

    if pending_day and pending_rows:
        finalize_table()

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
    tzinfo = ensure_timezone()
    now = datetime.now(tzinfo)
    current_week = now.isocalendar()[1]
    time_map = extract_time_ranges(content, current_week=current_week)
    if len(time_map) < len(DAY_CONFIG):
        raise SystemExit("Failed to parse all weekend slots. The page layout may have changed.")

    today = now.date()
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
