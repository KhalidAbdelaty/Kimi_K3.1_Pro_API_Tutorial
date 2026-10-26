"""Estimate the input tokens of the first request (system prompt, four images, prompt)."""
import json
import os
import urllib.request
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from agent import BASELINE_PROMPT, MODEL, SYSTEM_PROMPT, image_part

load_dotenv(find_dotenv(usecwd=True))
images = [image_part(p) for p in sorted(Path("inputs").glob("view*.png"))]
payload = {"model": MODEL, "messages": [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": images + [{"type": "text", "text": BASELINE_PROMPT}]}]}
request = urllib.request.Request(
    "https://api.moonshot.ai/v1/tokenizers/estimate-token-count",
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {os.environ['MOONSHOT_API_KEY']}",
             "Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=60) as resp:
    print(json.loads(resp.read()))
