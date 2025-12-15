import os, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# -------- SETTINGS --------
TIMEZONE = "America/Denver"
POST_HOUR = 9   # 9 AM local time
POST_MINUTE = 0
# --------------------------

def get_token():
    r = requests.post(
        "https://public-api.wordpress.com/oauth2/token",
        data={
            "client_id": os.environ["WPCOM_CLIENT_ID"],
            "client_secret": os.environ["WPCOM_CLIENT_SECRET"],
            "grant_type": "password",
            "username": os.environ["WPCOM_USERNAME"],
            "password": os.environ["WPCOM_APP_PASSWORD"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def generate_post():
    # TEMP CONTENT — we’ll replace this with AI next
    return {
        "title": "Test post from the robot (ignore me)",
        "content": "<p>If you’re reading this, the robot works.</p>",
        "excerpt": "Testing auto-post setup",
        "tags": ["test"],
        "categories": ["Uncategorized"],
    }

def schedule_post(token, post):
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    publish = now.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
    if publish <= now:
        publish += timedelta(days=1)

    r = requests.post(
        f"https://public-api.wordpress.com/rest/v1.1/sites/{os.environ['WPCOM_SITE_ID']}/posts/new",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": post["title"],
            "content": post["content"],
            "excerpt": post["excerpt"],
            "status": "future",
            "date": publish.isoformat(),
            "tags": post["tags"],
            "categories": post["categories"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    token = get_token()
    post = generate_post()
    created = schedule_post(token, post)
    print("Scheduled:", created.get("URL"))
