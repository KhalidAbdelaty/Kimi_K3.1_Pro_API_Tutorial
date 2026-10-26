"""Probe: is a request rejected if reasoning_content is dropped from the assistant message?"""
import os, json, time
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
load_dotenv(find_dotenv(usecwd=True))
time.sleep(22)
client = OpenAI(api_key=os.environ["MOONSHOT_API_KEY"], base_url="https://api.moonshot.ai/v1", max_retries=0)
tools = [{"type": "function", "function": {"name": "get_swatch", "description": "Return the swatch color.", "parameters": {"type": "object", "properties": {}, "required": []}}}]
messages = [{"role": "user", "content": "Call get_swatch, then tell me the swatch color in one word."}]
r1 = client.chat.completions.create(model="kimi-k3.1-pro", reasoning_effort="high", max_completion_tokens=4096, messages=messages, tools=tools, tool_choice="required")
d = r1.choices[0].message.model_dump(exclude_none=True)
tc = d["tool_calls"][0]
time.sleep(22)
bad = [messages[0], {k: v for k, v in d.items() if k != "reasoning_content"}, {"role": "tool", "tool_call_id": tc["id"], "content": "Swatch is red."}]
try:
    r3 = client.chat.completions.create(model="kimi-k3.1-pro", reasoning_effort="high", max_completion_tokens=4096, messages=bad, tools=tools)
    print("NO-REASONING ACCEPTED ->", r3.choices[0].message.content)
except Exception as e:
    print("NO-REASONING REJECTED ->", type(e).__name__, str(e)[:400])
