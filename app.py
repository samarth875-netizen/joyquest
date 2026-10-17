"""
JoyQuest backend (simple Flask app).

Calls Google's free Generative AI API (Generative Language API) instead of
DigitalOcean Gradient AI. The backend:
  1. Serves the frontend (static/index.html) and a small API.
  2. Accepts the user's mood/time/budget/interests/Joy Jar memories.
  3. Asks Google's AI model for 3 joy quests or a rough-day message.
  4. Returns clean JSON to the frontend.

No database and no login. Secrets are read from environment variables and are
never sent to the browser.

Beginner notes:
  - Lines that start with # are comments; Python ignores them.
  - A "function" is a reusable block of code defined with "def".
  - Secrets (the Google API key) come from environment variables, never from
    this file, and never reach the browser.
"""

import json
import os
import re
import time
from collections import defaultdict, deque

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

# ----------------------------------------------------------------------
# 1. SETUP: read secrets from .env (local) or env vars (App Platform)
# ----------------------------------------------------------------------

load_dotenv()  # loads the .env file into environment variables

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Google Generative AI API credentials. Get these from Google AI Studio.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.environ.get("GOOGLE_MODEL", "gemini-pro")

# How long we wait for the AI before giving up (seconds).
REQUEST_TIMEOUT = 45

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# Instructions sent to the AI on every request. This makes the expected JSON
# shape explicit and keeps the answers warm and safe.
SYSTEM_PROMPT = (
    "You are JoyQuest, a warm, playful guide who helps people find small moments "
    "of joy. Use the knowledge base for ideas and for why they work. When asked "
    "for quests, return exactly 3 specific, safe, doable quests that match the "
    "user's mood, time, budget, and interests, as JSON only with no extra text. "
    "When asked for a rough-day message, be gentle and mention the user's own "
    "saved memories if any, and suggest one tiny action, as JSON only. Be kind, "
    "never preachy. You are not a therapist: if someone shares serious distress, "
    "respond gently and encourage them to reach out to a trusted person or a "
    "local helpline. Never invent research facts."
)

# ----------------------------------------------------------------------
# 2. ALLOWED VALUES (used to validate what the frontend sends)
# ----------------------------------------------------------------------

MOODS = {"great", "okay", "low", "stressed", "bored"}
MINUTES = {10, 30, 60}
BUDGETS = {"free", "under200", "flexible"}

MAX_INTERESTS_CHARS = 300
MAX_MEMORIES = 10
MAX_MEMORY_CHARS = 200

# ----------------------------------------------------------------------
# 3. SAFETY: words that suggest serious distress
#    We check these BEFORE calling the AI. If we find one, we skip the AI
#    and return a warm message that points to real help.
# ----------------------------------------------------------------------

DISTRESS_PHRASES = [
    "kill myself", "killing myself", "kill my self",
    "end my life", "ending my life", "end it all",
    "want to die", "wanna die", "want to be dead",
    "wish i was dead", "wish i were dead", "wish i wasnt here",
    "better off dead", "better off without me",
    "suicide", "suicidal", "self harm", "self-harm", "selfharm",
    "hurt myself", "harm myself", "cut myself", "cutting myself",
    "no reason to live", "nothing to live for", "cant go on", "can't go on",
    "dont want to live", "don't want to live", "do not want to live",
    "stop existing", "not want to be here anymore",
]

SAFETY_MESSAGE = (
    "It sounds like you're carrying something really heavy right now, and I'm "
    "glad you told me. JoyQuest is a small mood-lifting tool, not a therapist, "
    "so please don't face this alone. Try to talk to someone you trust - a "
    "friend, family member, teacher, or doctor. If you're in India, you can "
    "call Tele-MANAS at 14416 (free, 24x7) or use a local crisis helpline. "
    "You matter, and real people can help."
)


def contains_distress(text):
    """Return True if the text looks like it mentions serious distress."""
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in DISTRESS_PHRASES)


# ----------------------------------------------------------------------
# 4. INPUT VALIDATION
# ----------------------------------------------------------------------

def validate_payload(payload):
    """
    Check and tidy up what the frontend sent.
    Returns (clean_data, error_message). If error_message is set, we stop.
    """
    if not isinstance(payload, dict):
        return None, "Sorry, the request looked wrong. Please try again."

    task = payload.get("task")
    if task not in ("quests", "rough_day"):
        return None, "Unknown task. Please try again."

    mood = payload.get("mood")
    if mood not in MOODS:
        return None, "Please pick how you're feeling first."

    try:
        minutes = int(payload.get("minutes"))
    except (TypeError, ValueError):
        return None, "Please choose how much time you have."

    if minutes not in MINUTES:
        return None, "Please choose a valid amount of time."

    budget = payload.get("budget")
    if budget not in BUDGETS:
        return None, "Please choose a budget."

    interests = payload.get("interests") or ""
    if not isinstance(interests, str):
        interests = str(interests)
    interests = interests.strip()[:MAX_INTERESTS_CHARS]

    memories = payload.get("memories") or []
    if not isinstance(memories, list):
        memories = []

    clean_memories = []
    for item in memories[:MAX_MEMORIES]:
        if not isinstance(item, str):
            item = str(item)
        item = item.strip()[:MAX_MEMORY_CHARS]
        if item:
            clean_memories.append(item)

    return {
        "task": task,
        "mood": mood,
        "minutes": minutes,
        "budget": budget,
        "interests": interests,
        "memories": clean_memories,
    }, None


# ----------------------------------------------------------------------
# 5. BUILD THE PROMPT FOR GOOGLE AI
# ----------------------------------------------------------------------

def build_messages(data):
    """Turn the user's choices into a prompt for Google's AI model."""
    memories_text = "; ".join(data["memories"]) if data["memories"] else "none saved yet"

    if data["task"] == "quests":
        user_text = (
            "Create exactly 3 joy quests for today.\n"
            f"Mood: {data['mood']}\n"
            f"Minutes available: {data['minutes']}\n"
            f"Budget: {data['budget']}\n"
            f"Interests: {data['interests'] or 'nothing specific'}\n"
            f"Their saved happy memories: {memories_text}\n\n"
            "Reply with ONLY valid JSON in exactly this shape, no extra text:\n"
            '{"intro": "one short friendly line", '
            '"quests": [{"title": "short title", "description": "one or two '
            'sentences", "minutes": 15, "cost": "free"}], "closing": "one short '
            'encouraging line"}\n'
            "There must be exactly 3 quests. Each quest needs title, description, "
            "minutes (a number), and cost (free / low / flexible)."
        )
    else:  # rough_day
        user_text = (
            "Write a gentle rough-day message.\n"
            f"Mood: {data['mood']}\n"
            f"Their saved happy memories: {memories_text}\n\n"
            "If they have saved memories, warmly mention at least one of them.\n"
            "Reply with ONLY valid JSON in exactly this shape, no extra text:\n"
            '{"message": "a gentle 2 to 4 sentence message", '
            '"suggestion": "one small, low-effort action"}'
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def build_google_prompt(messages):
    """Join the messages into a single text block for Google's API."""
    parts = []
    for m in messages:
        role = m["role"].title()
        parts.append(f"{role}: {m['content']}")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# 6. TALK TO GOOGLE'S GENERATIVE AI API
# ----------------------------------------------------------------------

def call_google_ai(prompt_text):
    """
    Send the prompt to Google's Generative Language API.
    Returns (reply_text, error_message).
    """
    if not GOOGLE_API_KEY:
        return None, (
            "JoyQuest isn't connected to Google AI yet. "
            "(The server is missing GOOGLE_API_KEY.)"
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GOOGLE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    )
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.7},
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "The AI took too long to reply. Please try again."
    except requests.exceptions.RequestException:
        # We do NOT include the exception text, so the key can never leak.
        return None, "Couldn't reach Google AI. Please try again in a moment."

    if response.status_code != 200:
        return None, "Google AI returned an error. Please try again."

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"], None
    except (ValueError, KeyError, IndexError, TypeError):
        return None, "The AI replied in an unexpected way. Please try again."


# ----------------------------------------------------------------------
# 7. PARSE + CHECK THE AI'S JSON
# ----------------------------------------------------------------------

def strip_code_fences(text):
    """Remove ```json ... ``` fences if the AI wrapped its JSON in them."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)  # remove opening fence
    text = re.sub(r"\s*```$", "", text)           # remove closing fence
    return text.strip()


def parse_json(text):
    """Return a dict from the AI text, or None if it isn't valid JSON."""
    if not text:
        return None
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except ValueError:
                return None
    return None


def valid_quests(data):
    """Check the 'quests' shape. Return the cleaned dict or None."""
    if not isinstance(data, dict):
        return None
    intro = data.get("intro")
    closing = data.get("closing")
    quests = data.get("quests")
    if not isinstance(quests, list) or len(quests) != 3:
        return None

    clean = []
    for q in quests:
        if not isinstance(q, dict):
            return None
        title = str(q.get("title", "")).strip()
        description = str(q.get("description", "")).strip()
        if not title or not description:
            return None
        try:
            minutes = int(q.get("minutes"))
        except (TypeError, ValueError):
            minutes = 15  # safe default
        cost = str(q.get("cost", "free")).strip() or "free"
        clean.append(
            {"title": title, "description": description, "minutes": minutes, "cost": cost}
        )

    return {
        "intro": str(intro or "Here are three small joys for today.").strip(),
        "quests": clean,
        "closing": str(closing or "You've got this. One small thing counts.").strip(),
    }


def valid_rough_day(data):
    """Check the 'rough_day' shape. Return the cleaned dict or None."""
    if not isinstance(data, dict):
        return None
    message = str(data.get("message", "")).strip()
    suggestion = str(data.get("suggestion", "")).strip()
    if not message or not suggestion:
        return None
    return {"message": message, "suggestion": suggestion}


# ----------------------------------------------------------------------
# 8. DEMO MODE (sample data, no AI call)
# ----------------------------------------------------------------------

def demo_response(data):
    """Return sample quests or a rough-day message for a demo/presentation."""
    if data["task"] == "rough_day":
        if data["memories"]:
            memory = data["memories"][-1]
            message = (
                "It's okay that today feels heavy - you don't have to fix everything "
                f"right now. Remember this moment you saved: \"{memory}\". That was real, "
                "and so are the small good things still around you."
            )
        else:
            message = (
                "It's okay that today feels heavy - you don't have to fix everything "
                "right now. Just getting through today counts, and you don't have to do it alone."
            )
        return {
            "message": message,
            "suggestion": "Make a warm drink and sit by a window for five minutes.",
        }

    sample = {
        10: [
            {"title": "Chai by the window", "description": "Make a cup of chai and drink it slowly without your phone, watching whatever's outside.", "minutes": 10, "cost": "free"},
            {"title": "Three good things", "description": "Write down three small things that went okay today, however tiny.", "minutes": 10, "cost": "free"},
            {"title": "Ten slow breaths", "description": "Step outside and take ten slow breaths of fresh air.", "minutes": 10, "cost": "free"},
        ],
        30: [
            {"title": "Walk and notice five new things", "description": "Take a short walk nearby and spot five things you've never noticed before.", "minutes": 30, "cost": "free"},
            {"title": "Voice note to a friend", "description": "Send a friend a voice note telling them one thing you like about them.", "minutes": 30, "cost": "free"},
            {"title": "Half an hour of your hobby", "description": "Spend 30 minutes on something you enjoy - drawing, music, cooking, anything.", "minutes": 30, "cost": "low"},
        ],
        60: [
            {"title": "Long walk with music", "description": "Go for an hour-long walk with your favourite music and no destination.", "minutes": 60, "cost": "free"},
            {"title": "Cook something new", "description": "Make a dish you've never cooked before and share it with someone.", "minutes": 60, "cost": "low"},
            {"title": "Explore a new corner", "description": "Visit a part of your town you've never been to and wander.", "minutes": 60, "cost": "low"},
        ],
    }
    quests = [dict(q) for q in sample.get(data["minutes"], sample[30])]

    if data["interests"]:
        quests[0] = {
            "title": f"A little {data['interests']} break",
            "description": f"Do something small just for you that involves {data['interests']}, for about {data['minutes']} minutes.",
            "minutes": data["minutes"],
            "cost": "free",
        }

    return {
        "intro": f"Here are three small joys for a {data['mood']} day with {data['minutes']} minutes.",
        "quests": quests,
        "closing": "One small thing counts. You've got this. (Demo mode - connect your Google AI key for real quests.)",
    }


# ----------------------------------------------------------------------
# 9. SIMPLE RATE LIMIT (protects your credits): 20 requests / minute / IP
# ----------------------------------------------------------------------

RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 60
_hits = defaultdict(deque)  # ip -> timestamps of recent requests


def client_ip():
    """Get the visitor's IP address (works behind App Platform too)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_rate_limited(ip):
    """Return True if this IP has made too many requests recently."""
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


# ----------------------------------------------------------------------
# 10. ROUTES
# ----------------------------------------------------------------------

@app.get("/")
def index():
    """Serve the frontend page."""
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/health")
def health():
    """A tiny check that the server is alive."""
    return jsonify({"ok": True})


@app.post("/api/chat")
def chat():
    """Main endpoint: generate quests or a rough-day message."""
    ip = client_ip()
    if is_rate_limited(ip):
        return jsonify({"error": "You're going a bit fast! Please wait a minute."}), 429

    payload = request.get_json(silent=True)
    data, error = validate_payload(payload)
    if error:
        return jsonify({"error": error}), 400

    # Safety check BEFORE using the AI.
    combined = " ".join([data["interests"], " ".join(data["memories"])])
    if contains_distress(combined):
        return jsonify({"safety": True, "message": SAFETY_MESSAGE})

    # Demo mode: return sample data without calling Google AI.
    DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")
    if DEMO_MODE:
        return jsonify(demo_response(data))

    messages = build_messages(data)
    prompt_text = build_google_prompt(messages)

    # Try once, and if the JSON doesn't parse/validate, retry once more.
    for attempt in range(2):
        reply_text, agent_error = call_google_ai(prompt_text)
        if agent_error:
            return jsonify({"error": agent_error}), 500

        ai_data = parse_json(reply_text)

        if data["task"] == "quests":
            result = valid_quests(ai_data)
            if result:
                return jsonify(result)
        else:
            result = valid_rough_day(ai_data)
            if result:
                return jsonify(result)

        # Nothing valid - nudge the AI to fix its JSON and try again.
        messages = messages + [
            {"role": "assistant", "content": reply_text or ""},
            {
                "role": "user",
                "content": "That wasn't valid JSON in the exact shape I asked for. "
                "Please reply with ONLY the JSON, nothing else.",
            },
        ]
        prompt_text = build_google_prompt(messages)

    return jsonify({"error": "The AI had trouble replying. Please try again."}), 500


# ----------------------------------------------------------------------
# 11. OPTIONAL CORS (only needed if you test the frontend from a
#     different origin). Enable by setting ENABLE_CORS=true.
# ----------------------------------------------------------------------

if os.environ.get("ENABLE_CORS", "").lower() == "true":

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        return response


if __name__ == "__main__":
    # Local development only. In production we use "gunicorn app:app".
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
