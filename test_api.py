"""
test_api.py - a quick script to test the JoyQuest backend.

It sends two sample requests to a running server and prints the results:
  1. task "quests"     -> should return intro + 3 quests + closing
  2. task "rough_day"  -> should return a message + suggestion

How to use:
  1. Start the server in one terminal:  python app.py
  2. In another terminal, run:          python test_api.py

If the AI isn't connected yet, you'll see the friendly "not connected"
message instead of quests - that's expected until you add your .env values.
"""

import json

import requests

SERVER_URL = "http://127.0.0.1:5000/api/chat"


def call(task, mood, minutes, budget, interests, memories):
    """Send one request and print the pretty JSON response."""
    payload = {
        "task": task,
        "mood": mood,
        "minutes": minutes,
        "budget": budget,
        "interests": interests,
        "memories": memories,
    }
    print(f"\n----- Sending '{task}' request -----")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(SERVER_URL, json=payload, timeout=60)
    except requests.exceptions.RequestException as error:
        print("Could not reach the server. Is it running? Error:", error)
        return

    print(f"\nStatus code: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print("Response was not JSON:\n", response.text)


if __name__ == "__main__":
    # Sample 1: normal quest generation.
    call(
        task="quests",
        mood="bored",
        minutes=30,
        budget="free",
        interests="music and being outside",
        memories=["Ate mango ice cream with friends", "Watched a funny movie"],
    )

    # Sample 2: rough day message.
    call(
        task="rough_day",
        mood="low",
        minutes=10,
        budget="free",
        interests="",
        memories=["Ate mango ice cream with friends", "Watched a funny movie"],
    )
