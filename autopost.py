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
def friday_rotation_type(publish_dt):
    """
    Rotates Fuck It Friday types:
    Week 1 = A (Low-Effort Dinner Wins)
    Week 2 = B (Parenting Permission Slips)
    Week 3 = C (Hot Takes)
    """
    week_number = publish_dt.isocalendar()[1]
    return ["A", "B", "C"][(week_number - 1) % 3]

def build_prompt(theme, publish_dt):
    weekday = publish_dt.weekday()
    cta_style = rotating_cta_style(publish_dt)
    stan_link = STAN_URL if STAN_URL else "[STAN STORE LINK]"

    base_voice = """
VOICE RULES:
- Profanity is normal and on-brand (fuck, shit, ass allowed)
- Do NOT swear every sentence
- Conversational, honest, slightly unhinged
- No corporate tone
- No therapy-speak
- No alcohol references
- No inspirational poster bullshit
- No repeating frameworks unless explicitly told
"""

    if weekday == 0:
        prompt = f"""
Write a Mom Chaos Monday blog post in the PottyMouthPanda voice.

{base_voice}

POST RULES:
- Focus on ONE specific, real parenting moment
- Mental load, burnout, schedules, chaos
- NO recipes
- NO meal plans
- Include ONE practical takeaway or mindset shift at the end

STRUCTURE:
1. Short real-life story
2. Why it was frustrating or overwhelming
3. One realistic tip or reframe
4. Gentle close

CTA:
- Optional
- One sentence max
- Soft mention only

LENGTH:
700–1000 words

GOAL:
Make the reader feel less alone.
"""

    elif weekday == 2:
        prompt = f"""
Write a WTF’s for Dinner Wednesday blog post in the PottyMouthPanda voice.

{base_voice}

POST RULES:
- Feature ONE new family- and budget-friendly recipe
- Weeknight realistic
- FULL ingredients and instructions required
- Include optional swaps for picky eaters or budget needs

STRUCTURE:
1. Why this recipe exists
2. Ingredients list
3. Step-by-step instructions
4. Optional swaps or shortcuts
5. Why this recipe works

HARD RULES:
- NO frameworks
- NO weekly plans
- NO long storytelling

CTA:
Soft CTA only (one sentence)

LENGTH:
600–900 words

GOAL:
Reader thinks “I could actually make this.”
"""

    elif weekday == 4:
        fit_type = friday_rotation_type(publish_dt)

        prompt = f"""
Write a Fuck It Friday blog post in the PottyMouthPanda voice.

{base_voice}

THIS WEEK’S TYPE: {fit_type}

TYPE RULES:
A = Low-Effort Dinner Wins
B = Parenting Permission Slips
C = Hot Takes

STRUCTURE:
1. Strong opening opinion
2. Normalize the shortcut or belief
3. Reframe guilt or expectations
4. Calm, relieving close

CTA:
Optional, never salesy

LENGTH:
700–1000 words

GOAL:
Make readers exhale.
"""

    elif weekday == 6:
        prompt = f"""
Write a Feed the Chaos Sunday Drop blog post in the PottyMouthPanda voice.

{base_voice}

POST RULES:
- Weekly meal plan OVERVIEW ONLY
- NO recipes
- NO teaching
- NO storytelling

REQUIRED CONTENT:
- 3 breakfast options
- 2–3 lunch options
- 1–2 rotating snack options
- 6 dinners

STRUCTURE:
1. Short relief-focused opening
2. Breakfast list
3. Lunch list
4. Snack list
5. Dinner list
6. Value explanation
7. Direct CTA

CTA:
“This is the overview. The full plan lives inside Feed the Chaos.”
Link: {stan_link}

LENGTH:
600–800 words

GOAL:
Make the paid plan feel obvious.
"""

    else:
        raise ValueError("No prompt defined for this weekday")

    return prompt


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
