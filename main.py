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
                category_element = post_item.select_one(".cat")
                if not category_element:
                    continue
                category = category_element.get_text(strip=True)
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
                if "みえる" in title:
                    prefixes.append("💌")
                    urls.append("https://www.youtube.com/@himeno-mieru")
                if "メエ" in title:
                    prefixes.append("🐑")
                    urls.append("https://www.youtube.com/@mamimu-meh")
                if "パリン" in title:
                    prefixes.append("🐣")
                    urls.append("https://www.youtube.com/@wao-parin")
                if "たいむ" in title:
                    prefixes.append("🐩")
                    urls.append("https://www.youtube.com/@rindou-taimu")
                if "アイカツアカデミー！配信部" in title:
                    prefixes.append("🏫")
                    urls.append("https://www.youtube.com/@aikatsu-academy")
                prefix = "".join(prefixes)

                # category 表現変換
                if "YouTube" in category:
                    category_text = ""
                elif "メンバーシップ" in category:
                    category_text = "🔒"
                elif "グッズ" in category:
                    category_text = "🛍️"
                elif "カード" in category:
                    category_text = "🎴"
                elif "ミュージック" in category:
                    category_text = "🎵"
                elif "スペシャル" in category:
                    category_text = "✨"
                elif "short" in category.lower():
                    category_text = "📎"
                else:
                    category_text = category

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

# Googleカレンダーに登録（今月の既存イベントは削除）
def add_to_calendar(events):
    if not events:
        print("No events to add.")
        return

    credentials = service_account.Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    calendar_id = os.environ.get("CALENDAR_ID")
    service = build("calendar", "v3", credentials=credentials)

    # 3ヶ月分の期間をカバー
    start_date = min(e["start"] for e in events).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    latest_event = max(e["start"] for e in events)
    month_after_next = (latest_event.replace(day=1) + timedelta(days=62)).replace(day=1)
    end_date = month_after_next

    print(f"Fetching existing events from {start_date} to {end_date}...")
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

    # 重複しないイベントだけを抽出
    def is_duplicate(new_event):
        for existing in existing_events:
            try:
                existing_start = parse_naive_dt(existing["start"]["dateTime"])
                existing_end = parse_naive_dt(existing["end"]["dateTime"])
            except (KeyError, ValueError):
                continue

            new_start = new_event["start"].replace(tzinfo=None)
            new_end = new_event["end"].replace(tzinfo=None)

            trim_existing_title = existing.get("summary")
            trim_existing_title.replace('\u200b', ' ')
            trim_existing_title.replace('\u3000', ' ')

            if (
                    trim_existing_title == new_event["summary"] and
                    existing_start == new_start and
                    existing_end == new_end
            ):
                return True
        return False

    # 新しいイベントだけ追加
    new_events = [e for e in events if not is_duplicate(e)]
    print(f"{len(new_events)} new events to insert...")

    for event in new_events:
        body = {
            "summary": event["summary"],
            "description": " ".join(event["urls"]),
            "start": {"dateTime": event["start"].isoformat(), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": event["end"].isoformat(), "timeZone": "Asia/Tokyo"},
        }
        service.events().insert(calendarId=calendar_id, body=body).execute()
        print(f"Added: {event['summary']}")

# Cloud Functions/ローカル両対応のエントリポイント
def main(request=None):
    if request is not None:
        method = request.method
        if method not in ("GET", "POST"):
            return ("Method Not Allowed", 405)

    events = fetch_schedule()
    mode = os.environ.get("MODE", "").lower()

    if mode == "dry":
        print_schedule(events)
        return "Printed schedule (dry run)"
    else:
        add_to_calendar(events)
        return "Added schedule to calendar"

# ローカル実行用
if __name__ == "__main__":
    result = main()
    print(result)
