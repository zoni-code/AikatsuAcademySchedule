import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 初期化
def get_calendar_service():
    credentials = service_account.Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=credentials)

# 削除処理
def delete_events_for_3months():
    calendar_id = os.environ.get("CALENDAR_ID")
    service = get_calendar_service()

    now = datetime.now()
    start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_time = (start_time + timedelta(days=93)).replace(hour=0, minute=0, second=0, microsecond=0)  # 約3ヶ月後

    print(f"Fetching events from {start_time.date()} to {end_time.date()}...")

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_time.isoformat() + "Z",
        timeMax=end_time.isoformat() + "Z",
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = events_result.get("items", [])
    print(f"Found {len(events)} events in 3 months.")

    if not events:
        print("No events to delete.")
        return

    # 確認プロンプト
    confirm = input("⚠️ Are you sure you want to delete all these events? Type 'yes' to continue: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    for event in events:
        summary = event.get("summary", "No title")
        print(f"Deleting: {summary}")
        service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()

    print("✅ Finished deleting events.")

if __name__ == "__main__":
    delete_events_for_3months()
