import os
import json
import requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from openai import OpenAI

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

THEMES = {
    0: {  # Monday
        "label": "Mom Chaos Monday",
        "category": CATEGORY_PARENTING,
        "tags": ["Mom Chaos Monday", "parenting", "real life"],
        "angle": "parenting chaos + how meal planning keeps the house from burning down",
    },
    2: {  # Wednesday
        "label": "WTF’s for Dinner Wednesday",
        "category": CATEGORY_WTFS,
        "tags": ["WTFs for Dinner", "meal planning", "dinner ideas"],
        "angle": "solve the 5pm panic with a practical dinner framework and a few go-to options",
    },
    4: {  # Friday
        "label": "Fuck It Friday",
        "category": CATEGORY_FUCKIT,
        "tags": ["Fuck It Friday", "easy dinners", "hot mess"],
        "angle": "lowest-effort food + permission slips + realistic shortcuts",
    },
    6: {  # Sunday
        "label": "Feed the Chaos Sunday Drop",
        "category": CATEGORY_RECIPES,
        "tags": ["Feed the Chaos", "meal plans", "weekly drop"],
        "angle": "new meal plan drop announcement: what’s inside, who it’s for, why it saves sanity",
    },
}

# =========================
# WORDPRESS.COM AUTH
# =========================
def get_wp_token() -> str:
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
            hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0
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
# AI POST GENERATION
# =========================
def rotating_cta_style(publish_dt: datetime) -> str:
    # 0 soft, 1 direct, 2 soft... deterministic rotation without saving state
    return ["soft", "direct", "soft", "direct"][publish_dt.weekday() % 4]

def build_prompt(theme: dict, publish_dt: datetime) -> str:
    cta_style = rotating_cta_style(publish_dt)
    stan_line = STAN_URL if STAN_URL else "[YOUR STAN STORE LINK]"

    return f"""
You are writing a WordPress blog post in the creator voice: PottyMouthPanda.
Voice rules:
- On-brand profanity, but NOT every sentence (sprinkle, don’t drown).
- Funny, blunt, chaotic mom energy. Practical and real. No corporate tone.
- Skimmable structure: short paragraphs, clear headings, bullets where helpful.
- Must include: Hook -> relatable chaos -> practical steps -> CTA.
- NO alcohol/wine references.
- Avoid “as an AI”, avoid generic inspirational fluff.
Length:
- 900–1200 words.

Post series: {theme["label"]}
Angle: {theme["angle"]}
Publish date (local): {publish_dt.strftime("%A, %B %d, %Y")}

CTA focus: meal plans + Stan Store (email list later, but not primary right now).
CTA style: {cta_style}

Include:
- 1 punchy hook paragraph (scroll-stopper)
- 3–5 section headings (H2)
- At least 5 actionable tips/steps total (bullets allowed)
- A short “If you’re drowning, start here” quick list
- End with a CTA that matches style:
  - soft = warm invite + “if you want the done-for-you version”
  - direct = blunt “here’s the shortcut: grab the plan”
Stan Store link to include at least once: {stan_line}

Output MUST be valid JSON ONLY with exactly these keys:
- title (string)
- excerpt (string, <= 160 chars)
- html (string, valid HTML for WordPress)
"""

def ai_generate_post(theme: dict, publish_dt: datetime) -> dict:
    client = OpenAI()

    prompt = build_prompt(theme, publish_dt)

    # Responses API (recommended) :contentReference[oaicite:2]{index=2}
    resp = client.responses.create(
        model="gpt-5.2",
        input=prompt,
        text={"verbosity": "low"},
    )

    raw = resp.output_text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # fallback: try to extract JSON if the model accidentally wrapped it
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise RuntimeError(f"Model did not return JSON. Output was:\n{raw[:800]}")
        data = json.loads(raw[start : end + 1])

    for k in ["title", "excerpt", "html"]:
        if k not in data or not isinstance(data[k], str) or not data[k].strip():
            raise RuntimeError(f"Missing/invalid '{k}' in model JSON.")

    # Build the final post payload
    return {
        "title": data["title"].strip(),
        "content": data["html"].strip(),
        "excerpt": data["excerpt"].strip(),
        "categories": [theme["category"]],
        "tags": theme["tags"],
    }

# =========================
# SCHEDULE WORDPRESS POST
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

    wp_token = get_wp_token()
    publish_dt = next_post_datetime(now)
    theme = THEMES[publish_dt.weekday()]

    if already_scheduled(wp_token, publish_dt.date()):
        print("Post already scheduled for", publish_dt.date())
        raise SystemExit(0)

    post = ai_generate_post(theme, publish_dt)
    created = schedule_post(wp_token, post, publish_dt)
    print("Scheduled:", created.get("URL"))
