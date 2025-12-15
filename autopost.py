import os
import requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# =========================
# SETTINGS
# =========================
TIMEZONE = "America/Denver"
POST_HOUR = 9
POST_MINUTE = 0

# Categories (must match WordPress EXACTLY)
CATEGORY_PARENTING = "Parenting in the Wild"
CATEGORY_WTFS = "WTFs for Dinner"
CATEGORY_FUCKIT = "Fuck-It Fridays"
CATEGORY_RECIPES = "Real-AF Recipes"

STAN_URL = os.environ.get("STAN_STORE_URL", "").strip()

# Weekly theme map
THEMES = {
    0: {  # Monday
        "label": "Mom Chaos Monday",
        "category": CATEGORY_PARENTING,
        "tags": ["Mom Chaos Monday", "parenting", "real life"],
    },
    2: {  # Wednesday
        "label": "WTF’s for Dinner Wednesday",
        "category": CATEGORY_WTFS,
        "tags": ["WTFs for Dinner", "meal planning", "dinner ideas"],
    },
    4: {  # Friday
        "label": "Fuck It Friday",
        "category": CATEGORY_FUCKIT,
        "tags": ["Fuck It Friday", "easy dinners", "hot mess"],
    },
    6: {  # Sunday
        "label": "Feed the Chaos Sunday Drop",
        "category": CATEGORY_RECIPES,
        "tags": ["Feed the Chaos", "meal plans", "weekly drop"],
    },
}

# =========================
# AUTH
# =========================
def get_token() -> str:
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

# =========================
# DATE LOGIC
# =========================
def next_post_datetime(now_local: datetime) -> datetime:
    for add_days in range(0, 8):
        d = now_local + timedelta(days=add_days)
        candidate = d.replace(
            hour=POST_HOUR,
            minute=POST_MINUTE,
            second=0,
            microsecond=0,
        )
        if d.weekday() in THEMES and candidate > now_local:
            return candidate
    raise RuntimeError("Could not determine next post date")

def already_scheduled(token: str, target_day: date) -> bool:
    site = os.environ["WPCOM_SITE_ID"]
    r = requests.get(
        f"https://public-api.wordpress.com/rest/v1.1/sites/{site}/posts/",
        headers={"Authorization": f"Bearer {token}"},
        params={"status": "future", "number": 50},
        timeout=30,
    )
    r.raise_for_status()
    for post in r.json().get("posts", []):
        if (post.get("date") or "").startswith(target_day.isoformat()):
            return True
    return False

# =========================
# POST GENERATION (TEMP)
# =========================
def generate_post(theme: dict, publish_dt: datetime) -> dict:
    title = f"{theme['label']} – {publish_dt.strftime('%B %d')}"
    cta = (
        f"<p><strong>CTA:</strong> Grab my latest meal plans here 👉 "
        f"<a href='{STAN_URL}'>{STAN_URL}</a></p>"
        if STAN_URL
        else ""
    )

    content = (
        f"<p><strong>{theme['label']}</strong></p>"
        "<p>This is a placeholder post to confirm scheduling, categories, "
        "and weekly cadence are working correctly.</p>"
        "<p>Next step: replace this with AI-generated content in your real voice.</p>"
        f"{cta}"
    )

    return {
        "title": title,
        "content": content,
        "excerpt": f"{theme['label']} post",
        "categories": [theme["category"]],
        "tags": theme["tags"],
    }

# =========================
# SCHEDULE POST
# =========================
def schedule_post(token: str, post: dict, publish_dt: datetime):
    site = os.environ["WPCOM_SITE_ID"]
    r = requests.post(
        f"https://public-api.wordpress.com/rest/v1.1/sites/{site}/posts/new",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": post["title"],
            "content": post["content"],
            "excerpt": post["excerpt"],
            "status": "future",
            "date": publish_dt.isoformat(),
            "categories": post["categories"],
            "tags": post["tags"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    token = get_token()
    publish_dt = next_post_datetime(now)
    theme = THEMES[publish_dt.weekday()]

    if already_scheduled(token, publish_dt.date()):
        print("Post already scheduled for", publish_dt.date())
        exit(0)

    post = generate_post(theme, publish_dt)
    created = schedule_post(token, post, publish_dt)
    print("Scheduled:", created.get("URL"))
