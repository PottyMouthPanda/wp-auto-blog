import os
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI

# =========================
# CONFIG
# =========================

TZ_NAME = os.getenv("BLOG_TIMEZONE", "America/Denver")
TZ = ZoneInfo(TZ_NAME)

WPCOM_CLIENT_ID = os.getenv("WPCOM_CLIENT_ID", "").strip()
WPCOM_CLIENT_SECRET = os.getenv("WPCOM_CLIENT_SECRET", "").strip()
WPCOM_USERNAME = os.getenv("WPCOM_USERNAME", "").strip()
WPCOM_APP_PASSWORD = os.getenv("WPCOM_APP_PASSWORD", "").strip()
WPCOM_SITE_ID = os.getenv("WPCOM_SITE_ID", "").strip()

STAN_URL = os.getenv("STAN_STORE_URL", "").strip()  # ex: https://stan.store/ThePottyMouthPanda
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")  # safe default

# If your workflow runs at/near 9am local, publishing immediately is simplest.
# If you want WP to schedule it a few minutes ahead, set:
#   POST_MODE=future and FUTURE_MINUTES=5
POST_MODE = os.getenv("POST_MODE", "publish").strip().lower()  # publish or future
FUTURE_MINUTES = int(os.getenv("FUTURE_MINUTES", "5"))

# Category mapping (your WP categories)
CATEGORY_MOM_CHAOS = os.getenv("CAT_MOM_CHAOS", "Parenting in the Wild")
CATEGORY_WTFS = os.getenv("CAT_WTFS", "WTFs for Dinner")
CATEGORY_FIF = os.getenv("CAT_FIF", "Fuck-It Fridays")
CATEGORY_SUNDAY = os.getenv("CAT_SUNDAY", "Hot Mess Hacks")  # you can change this if you create "Feed the Chaos"

# =========================
# DATA STRUCTURES
# =========================

@dataclass
class GeneratedPost:
    title: str
    excerpt: str
    html: str
    category: str


# =========================
# WORDPRESS.COM AUTH + POST
# =========================

def wpcom_get_token() -> str:
    """
    WordPress.com OAuth2 token via password grant.
    Uses WPCOM_USERNAME + WPCOM_APP_PASSWORD.
    """
    if not all([WPCOM_CLIENT_ID, WPCOM_CLIENT_SECRET, WPCOM_USERNAME, WPCOM_APP_PASSWORD]):
        raise RuntimeError("Missing one or more WordPress.com env vars (client id/secret/username/app password).")

    url = "https://public-api.wordpress.com/oauth2/token"
    data = {
        "client_id": WPCOM_CLIENT_ID,
        "client_secret": WPCOM_CLIENT_SECRET,
        "grant_type": "password",
        "username": WPCOM_USERNAME,
        "password": WPCOM_APP_PASSWORD,
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    payload = r.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to obtain access_token. Response: {payload}")
    return token


def wpcom_create_post(token: str, post: GeneratedPost, publish_dt_local: datetime) -> dict:
    """
    Create post on WP.com site.
    """
    if not WPCOM_SITE_ID:
        raise RuntimeError("Missing WPCOM_SITE_ID env var.")

    url = f"https://public-api.wordpress.com/rest/v1.1/sites/{WPCOM_SITE_ID}/posts/new"
    headers = {"Authorization": f"Bearer {token}"}

    # Decide post status + date
    status = "publish"
    iso_date = None

    if POST_MODE == "future":
        status = "future"
        # schedule a few minutes in the future
        future_local = datetime.now(TZ) + timedelta(minutes=FUTURE_MINUTES)
        iso_date = future_local.isoformat()
    else:
        # publish now (at workflow time)
        status = "publish"
        iso_date = None

    payload = {
        "title": post.title,
        "content": post.html,
        "excerpt": post.excerpt,
        "status": status,
        "categories": post.category,
    }
    if iso_date:
        payload["date"] = iso_date

    r = requests.post(url, headers=headers, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()


# =========================
# CONTENT LOGIC
# =========================

def friday_rotation_type(publish_dt_local: datetime) -> str:
    """
    Rotates Fuck It Friday types:
    Week 1 = A (Low-Effort Dinner Wins)
    Week 2 = B (Parenting Permission Slips)
    Week 3 = C (Hot Takes)
    """
    week_number = publish_dt_local.isocalendar()[1]
    return ["A", "B", "C"][(week_number - 1) % 3]


def pick_theme_for_today(now_local: datetime) -> dict | None:
    """
    Returns a dict describing what to generate today (Mon/Wed/Fri/Sun),
    or None if today is not a post day.
    """
    weekday = now_local.weekday()  # Mon=0 ... Sun=6

    if weekday == 0:
        return {"key": "mom_chaos_monday", "label": "Mom Chaos Monday", "category": CATEGORY_MOM_CHAOS}
    if weekday == 2:
        return {"key": "wtfs_wednesday", "label": "WTF’s for Dinner Wednesday", "category": CATEGORY_WTFS}
    if weekday == 4:
        return {"key": "fuck_it_friday", "label": "Fuck It Friday", "category": CATEGORY_FIF}
    if weekday == 6:
        return {"key": "feed_the_chaos_sunday", "label": "Feed the Chaos Sunday Drop", "category": CATEGORY_SUNDAY}

    return None


def build_prompt(theme: dict, publish_dt_local: datetime) -> str:
    stan_link = STAN_URL if STAN_URL else "[STAN STORE LINK]"

    base_voice = """
You are writing as PottyMouthPanda.

VOICE RULES:
- Profanity is normal and on-brand (fuck, shit, ass allowed).
- Do NOT swear every sentence.
- Conversational, honest, slightly unhinged, and funny when it fits.
- No corporate tone. No therapy-speak. No inspirational poster bullshit.
- No alcohol/wine references.
- Never mention being an AI or model.

STYLE RULES:
- Short paragraphs, skimmable, readable.
- Use H2 headers where useful.
- Avoid repeating the same framework phrases post-to-post.
"""

    key = theme["key"]

    if key == "mom_chaos_monday":
        return f"""
{base_voice}

Write a Mom Chaos Monday blog post.

REQUIREMENTS:
- Center on ONE specific, relatable parenting moment/story (real-life chaos, mental load, burnout, schedules, kids).
- NO recipes.
- NO meal plan.
- Include ONE practical tip, trick, or mindset shift at the end.

STRUCTURE:
1) Hook + story (real, specific)
2) Why it hit so hard / what made it chaotic
3) The “here’s what actually helped” tip
4) Gentle close (no hard sell)

CTA:
- Optional
- One sentence max
- Soft mention only, like: “This is why I simplify meals so hard.”

LENGTH:
700–1000 words

OUTPUT FORMAT (STRICT):
Return VALID JSON ONLY with keys: title, excerpt (<=160 chars), html
"""

    if key == "wtfs_wednesday":
        return f"""
{base_voice}

Write a WTF’s for Dinner Wednesday blog post.

REQUIREMENTS:
- Feature ONE new family- and budget-friendly recipe.
- Weeknight realistic.
- Include FULL ingredients and step-by-step instructions.
- Include optional swaps for picky eaters and budget constraints.

HARD RULES:
- NO weekly plan.
- NO long storytelling.
- NO “framework” post.

STRUCTURE:
1) Hook + why this recipe exists
2) Ingredients
3) Instructions
4) Swaps/shortcuts
5) Why it works + quick close

CTA:
- Soft (one sentence) and optional:
  “This is the kind of recipe I build my weekly plans around.”

LENGTH:
600–900 words

OUTPUT FORMAT (STRICT):
Return VALID JSON ONLY with keys: title, excerpt (<=160 chars), html
"""

    if key == "fuck_it_friday":
        fit_type = friday_rotation_type(publish_dt_local)
        return f"""
{base_voice}

Write a Fuck It Friday blog post.

THIS WEEK’S TYPE: {fit_type}

TYPE RULES:
A = Low-Effort Dinner Wins
- Frozen food, snack plates, breakfast for dinner, shortcuts that count.
- Normalize “bare minimum” as smart.

B = Parenting Permission Slips
- Dismantle guilt. Validate tired parents.
- No fixing. Just permission and relief.

C = Hot Takes (safe)
- Call out harmful expectations or narratives.
- Focus on systems/culture, not attacking individuals.
- Grounded, not mean.

STRUCTURE:
1) Strong opening opinion
2) Normalize the shortcut/belief
3) Reframe guilt/expectations
4) Calm, relieving close

CTA:
- Optional
- Never salesy

LENGTH:
700–1000 words

OUTPUT FORMAT (STRICT):
Return VALID JSON ONLY with keys: title, excerpt (<=160 chars), html
"""

    if key == "feed_the_chaos_sunday":
        return f"""
{base_voice}

Write a Feed the Chaos Sunday Drop blog post.

PURPOSE:
- Weekly meal plan OVERVIEW only.
- Do NOT include full recipes.
- Do NOT teach a framework.
- Keep it skimmable and confident.

REQUIRED CONTENT:
- 3 breakfast options
- 2–3 lunch options
- 1–2 rotating snack options
- 6 dinners

STRUCTURE:
1) Short relief-focused opening
2) Breakfast list
3) Lunch list
4) Snack list
5) Dinner list
6) 3–5 bullet “why this plan works”
7) Direct CTA

CTA (DIRECT):
“This is the overview. The full plan lives inside Feed the Chaos.”
Include the link: {stan_link}

LENGTH:
600–800 words

OUTPUT FORMAT (STRICT):
Return VALID JSON ONLY with keys: title, excerpt (<=160 chars), html
"""

    raise ValueError("Unknown theme key")


# =========================
# OPENAI GENERATION
# =========================

def extract_json_from_response(text: str) -> dict:
    """
    Attempts to extract a JSON object from model output.
    """
    text = text.strip()

    # If it's already pure JSON
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    # Try to find first JSON object in text
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")
    return json.loads(m.group(0))


def ai_generate_post(theme: dict, publish_dt_local: datetime) -> GeneratedPost:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY env var.")

    prompt = build_prompt(theme, publish_dt_local)

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Retry a couple times if the model returns invalid JSON
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = client.responses.create(
                model=OPENAI_MODEL,
                input=prompt,
            )
            # Responses API returns text in output_text
            text = resp.output_text
            data = extract_json_from_response(text)

            title = (data.get("title") or "").strip()
            excerpt = (data.get("excerpt") or "").strip()
            html = (data.get("html") or "").strip()

            if not title or not html:
                raise ValueError("JSON missing required fields (title/html).")

            # Add a very light CTA link safety if Stan URL exists and Sunday post forgets it
            # (We don't force links on other days.)
            if theme["key"] == "feed_the_chaos_sunday" and STAN_URL and STAN_URL not in html:
                html += f'<p><a href="{STAN_URL}">Grab this week’s full Feed the Chaos plan here.</a></p>'

            return GeneratedPost(
                title=title,
                excerpt=excerpt[:160],
                html=html,
                category=theme["category"],
            )

        except Exception as e:
            last_err = e
            print(f"AI generation attempt {attempt} failed: {e}")
            time.sleep(1.5)

    raise RuntimeError(f"AI generation failed after retries: {last_err}")


# =========================
# MAIN
# =========================

def main():
    now_local = datetime.now(TZ)
    theme = pick_theme_for_today(now_local)

    # ✅ Clean exit on non-post days (no more red X)
    if theme is None:
        print(f"Not a scheduled post day in {TZ_NAME}. Exiting cleanly.")
        return 0

    publish_dt_local = now_local  # publish at run time; set POST_MODE=future to schedule ahead

    print(f"Generating: {theme['label']} | Category: {theme['category']} | Local time: {now_local.isoformat()}")
    post = ai_generate_post(theme, publish_dt_local)

    token = wpcom_get_token()
    created = wpcom_create_post(token, post, publish_dt_local)

    print("✅ Post created.")
    print("Title:", created.get("title"))
    print("URL:", created.get("URL") or created.get("url"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
