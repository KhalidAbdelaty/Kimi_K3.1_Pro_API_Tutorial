"""Probe: can a role=tool message carry image parts? (Also shows model_dump keeps reasoning_content.)"""
import os, json, base64, io, time
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
from PIL import Image
load_dotenv(find_dotenv(usecwd=True))
client = OpenAI(api_key=os.environ["MOONSHOT_API_KEY"], base_url="https://api.moonshot.ai/v1", max_retries=0)
img = Image.new("RGB", (128, 128), (220, 30, 30)); buf = io.BytesIO(); img.save(buf, "PNG")
uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
tools = [{"type": "function", "function": {"name": "get_swatch", "description": "Render the color swatch and return it as an image.", "parameters": {"type": "object", "properties": {}, "required": []}}}]
messages = [{"role": "user", "content": "Call get_swatch, then tell me the swatch color in one word."}]
r1 = client.chat.completions.create(model="kimi-k3.1-pro", reasoning_effort="high", max_completion_tokens=4096, messages=messages, tools=tools, tool_choice="required")
m = r1.choices[0].message
d = m.model_dump(exclude_none=True)
print("dump keys:", sorted(d.keys()), "| reasoning_content kept:", "reasoning_content" in d)
messages.append(d)
tc = m.tool_calls[0]
messages.append({"role": "tool", "tool_call_id": tc.id, "content": [{"type": "text", "text": "Swatch rendered."}, {"type": "image_url", "image_url": {"url": uri}}]})
try:
    r2 = client.chat.completions.create(model="kimi-k3.1-pro", reasoning_effort="high", max_completion_tokens=4096, messages=messages, tools=tools)
    print("TOOL-IMAGE ACCEPTED ->", r2.choices[0].message.content, "| usage:", r2.usage.model_dump(exclude_none=True))
except Exception as e:
    print("TOOL-IMAGE REJECTED ->", type(e).__name__, str(e)[:400])
# negative test: drop reasoning_content from the assistant message
bad = [messages[0], {k: v for k, v in d.items() if k != "reasoning_content"}, {"role": "tool", "tool_call_id": tc.id, "content": "Swatch is red."}]
try:
    r3 = client.chat.completions.create(model="kimi-k3.1-pro", reasoning_effort="high", max_completion_tokens=4096, messages=bad, tools=tools)
    print("NO-REASONING ACCEPTED ->", r3.choices[0].message.content)
except Exception as e:
    print("NO-REASONING REJECTED ->", type(e).__name__, str(e)[:400])
