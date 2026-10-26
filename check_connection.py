"""One request to confirm the key, the endpoint, and the model before the experiment."""
import os
import time

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

load_dotenv(find_dotenv(usecwd=True))  # finds .env in this folder or a parent
client = OpenAI(api_key=os.environ["MOONSHOT_API_KEY"], base_url="https://api.moonshot.ai/v1")

start = time.perf_counter()
response = client.chat.completions.create(
    model="kimi-k3.1-pro",
    reasoning_effort="high",            # the API default is "max"
    max_completion_tokens=2048,         # reasoning and answer share this cap
    messages=[{"role": "user", "content": "In one sentence, what does a STEP file store?"}],
)
message = response.choices[0].message
print(message.content)
print("finish_reason:", response.choices[0].finish_reason)
print("reasoning_content present:", bool(getattr(message, "reasoning_content", None)))
print("usage:", response.usage.model_dump(exclude_none=True))
print(f"seconds: {time.perf_counter() - start:.1f}")
