import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

# スケジュールをスクレイピング
def fetch_schedule():
    url = "https://aikatsu-academy.com/schedule/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    # 年月（例：['2025.5', '2025.6', '2025.7']）
    month_headers = soup.select(".p-schedule-header .swiper-slide")
    body_slides = soup.select(".p-schedule-body .swiper-slide")

    events = []

    for i, (header, body) in enumerate(zip(month_headers, body_slides)):
        match = re.search(r"(\d{4})\.(\d{1,2})", header.get_text())
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))

        for item in body.select(".p-schedule-body__item"):
            date_text = item.select_one(".data").get_text(strip=True)
            day_match = re.search(r"\d+", date_text)
            if not day_match:
                continue
            day = int(day_match.group(0))

            for post_item in item.select(".post__item"):
                category_elements = post_item.select(".cat")
                categories = [c.get_text(strip=True) for c in category_elements]
                p = post_item.select_one("p")
                full_text = p.get_text(strip=True)
                time_match = re.match(r"(\d{1,2}:\d{2})〜\s*(.+)", full_text)

                if time_match:
                    time_str, title = time_match.groups()
                    dt = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %H:%M")
                    start = dt
                    end = dt + timedelta(hours=1)
                else:
                    title = full_text
                    start = datetime(year, month, day)
                    end = start + timedelta(days=1)  # 終日イベント（次の日の0時）

                # 絵文字 prefix
                prefixes = []
                urls = []

                candidates = [
                    ("みえる", "💌", "https://www.youtube.com/@himeno-mieru"),
                    ("メエ", "🐑", "https://www.youtube.com/@mamimu-meh"),
                    ("パリン", "🐣", "https://www.youtube.com/@wao-parin"),
                    ("たいむ", "🐩", "https://www.youtube.com/@rindou-taimu"),
                    ("アイカツアカデミー！配信部", "🏫", "https://www.youtube.com/@aikatsu-academy"),
                ]

                matches = []
                for word, prefix, url in candidates:
                    pos = title.find(word)
                    if pos != -1:
                        matches.append((pos, prefix, url))

                # title に出現する順にソート
                matches.sort(key=lambda x: x[0])

                prefixes = [m[1] for m in matches]
                urls = [m[2] for m in matches]
                prefix = "".join(prefixes)

                # category 表現変換
                category_texts = []
                for category in categories:
                    if "YouTube" in category:
                        continue
                    elif "メンバーシップ" in category:
                        category_texts.append("🔒")
                    elif "グッズ" in category:
                        category_texts.append("🛍️")
                    elif "カード" in category:
                        category_texts.append("🎴")
                    elif "ミュージック" in category:
                        category_texts.append("🎵")
                    elif "スペシャル" in category:
                        category_texts.append("✨")
                    elif "short" in category.lower():
                        category_texts.append("📎")
                    else:
                        category_texts.append(category)
                category_text = "".join(category_texts)

                # title クレンジング
                title = re.sub(r"\[.*?個人配信\]", "", title)
                title = title.replace("[アイカツアカデミー！配信部]", "")
                title = title.strip()

                summary = f"{f'{category_text}' if category_text else ''}{prefix}{title}"

                events.append({
                    "summary": summary,
                    "start": start,
                    "end": end,
                    "urls": urls,
                })
    return events

def parse_naive_dt(s):
    # Z → +00:00 に変換
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=None)  # タイムゾーンを外す

# 予定を表示
def print_schedule(events):
    for event in events:
        print(json.dumps({
            "summary": event["summary"],
            "start": event["start"].isoformat(),
            "end": event["end"].isoformat(),
            "description": " ".join(event["urls"]),
        }, ensure_ascii=False))

# Googleカレンダーに登録

def diff_events(service, calendar_id, events):
    # 期間決定
    start_date = min(e["start"] for e in events).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    latest_event = max(e["start"] for e in events)
    month_after_next = (latest_event.replace(day=1) + timedelta(days=62)).replace(day=1)
    end_date = month_after_next

    existing_events = []
    page_token = None
    while True:
        response = service.events().list(
            calendarId=calendar_id,
            timeMin=start_date.isoformat() + "Z",
            timeMax=end_date.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token
        ).execute()
        existing_events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    # dict(summary -> events)
    existing_map = {}
    for ex in existing_events:
        title = ex.get("summary", "")
        existing_map.setdefault(title, []).append(ex)

    to_add = []
    to_update = []
    unchanged = []
    to_delete = []

    # 今回のイベントをマッチング
    for ev in events:
        new_start = ev["start"].replace(tzinfo=None)
        new_end = ev["end"].replace(tzinfo=None)
        matches = existing_map.get((ev["summary"], new_start.date()), [])

        matches = existing_map.get(ev["summary"], [])

        if matches:
            matched = False
            for ex in matches:
                try:
                    ex_start = parse_naive_dt(ex["start"]["dateTime"])
                    ex_end = parse_naive_dt(ex["end"]["dateTime"])
                except (KeyError, ValueError):
                    continue

                # 完全一致なら unchanged
                if ex_start == new_start and ex_end == new_end:
                    matched = True
                    unchanged.append(ev)
                    break

                # 24時間以内の差なら update 扱い
                if abs((new_start - ex_start).total_seconds()) <= 6 * 3600:
                    to_update.append(ev)
                    matched = True
                    break

            if not matched:
                # 既存はあるけど時刻が大きく違う → add 扱い
                to_add.append(ev)
        else:
            # summary が全くない → add
            to_add.append(ev)

    # === 削除対象判定 ===
    # 今回の events の (summary, start, end) のセット
    current_keys = set((ev["summary"], ev["start"], ev["end"]) for ev in events)

    for ex in existing_events:
        try:
            ex_start = parse_naive_dt(ex["start"]["dateTime"])
            ex_end = parse_naive_dt(ex["end"]["dateTime"])
        except (KeyError, ValueError):
            continue
        key = (ex.get("summary", ""), ex_start, ex_end)
        if key not in current_keys:
            to_delete.append(ex)

    return to_add, to_update, unchanged, to_delete, existing_events

def add_to_calendar(events, dry=False):
    if not events:
        print("No events to add.")
        return

    credentials = service_account.Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    calendar_id = os.environ.get("CALENDAR_ID")
    service = build("calendar", "v3", credentials=credentials)

    to_add, to_update, unchanged, to_delete, existing_events = diff_events(service, calendar_id, events)

    if dry:
        print("=== Dry Run Result ===")
        for e in to_add:
            print("[ADD]", e["summary"], e["start"].isoformat())
        for e in to_update:
            print("[UPDATE]", e["summary"], e["start"].isoformat())
        for e in unchanged:
            print("[SKIP]", e["summary"], e["start"].isoformat())
        for ex in to_delete:
            print("[DELETE]", ex.get("summary", ""), ex["start"]["dateTime"])
        return

    existing_map = {}
    for ex in existing_events:
        title = ex.get("summary", "")
        existing_map.setdefault(title, []).append(ex)

    # 追加
    for ev in to_add:
        body = {
            "summary": ev["summary"],
            "description": " ".join(ev["urls"]),
            "start": {"dateTime": ev["start"].isoformat(), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": ev["end"].isoformat(), "timeZone": "Asia/Tokyo"},
        }
        service.events().insert(calendarId=calendar_id, body=body).execute()
        print(f"Added: {ev['summary']}")

    # 更新（削除→追加）
    for ev in to_update:
        # 既存削除
        for ex in existing_map.get(ev["summary"], []):
            service.events().delete(calendarId=calendar_id, eventId=ex["id"]).execute()
            print(f"Deleted old: {ev['summary']}")
        # 新規追加
        body = {
            "summary": ev["summary"],
            "description": " ".join(ev["urls"]),
            "start": {"dateTime": ev["start"].isoformat(), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": ev["end"].isoformat(), "timeZone": "Asia/Tokyo"},
        }
        service.events().insert(calendarId=calendar_id, body=body).execute()
        print(f"Updated: {ev['summary']}")

    # 削除
    for ex in to_delete:
        service.events().delete(calendarId=calendar_id, eventId=ex["id"]).execute()
        print(f"Deleted obsolete: {ex.get('summary', '')}")

# Cloud Functions/ローカル両対応のエントリポイント
def main(request=None):
    if request is not None:
        method = request.method
        if method not in ("GET", "POST"):
            return ("Method Not Allowed", 405)

    events = fetch_schedule()
    mode = os.environ.get("MODE", "").lower()

    if mode == "dry":
        add_to_calendar(events, dry=True)
        return "Dry run completed"
    else:
        add_to_calendar(events, dry=False)
        return "Added/Updated schedule"

# ローカル実行用
if __name__ == "__main__":
    result = main()
    print(result)
