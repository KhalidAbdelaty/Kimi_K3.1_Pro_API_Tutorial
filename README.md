# Kimi K3.1 Pro CAD Agent

Companion code for the DataCamp tutorial *Kimi K3.1 Pro API Tutorial: Build a Self-Checking 3D CAD Agent*.

The agent shows Kimi K3.1 Pro four renders of an L-shaped bracket, asks for an editable CadQuery program, runs that program in a Docker sandbox, lets Kimi inspect and re-render its own result through tool calls, and then asks for one design change: widen the slot from 6 mm to 9 mm. A separate evaluator scores the saved STEP files against a hidden reference after the run ends. Kimi never sees the reference, the dimension manifest, or any score.

## What you need

| Script | Needs |
| --- | --- |
| `check_connection.py` | `openai`, `python-dotenv`, a Kimi API key |
| `build_reference.py`, `evaluator.py`, `report.py` | Everything in `requirements.txt` (CadQuery included) |
| `agent.py` | Everything above, plus Docker for the sandbox |

Kimi K3.1 Pro needs a top-up of at least $1 on the Kimi platform. At that tier the account allows 3 requests per minute, so `agent.py` spaces request starts 21 seconds apart.

Tested on Linux x86_64 with Python 3.12.3 and Docker 29.9.2. CadQuery 2.8.0 needs Python 3.11 or newer.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # then put your MOONSHOT_API_KEY in .env

python check_connection.py         # one request to confirm the key and model
docker build -t cad-sandbox:2.8.0 sandbox/
python build_reference.py          # hidden answer key plus the four input views
python agent.py                    # baseline, repair loop, slot edit; saves runs/<timestamp>/
python report.py runs/<timestamp>  # hidden scores, cost per phase, figures
```

`agent.py` uses `kimi-k3.1-pro` with `reasoning_effort="high"` on every request and keeps the full assistant message, including `reasoning_content` and `tool_calls`, in the history.

## Without Docker

You can still reproduce the scores and figures of the recorded runs, because they only read saved STEP files:

```bash
python report.py runs/20261026-214530
python evaluator.py score runs/20261026-214530/candidates/c0/candidate.step
```

Setting `CAD_SANDBOX=subprocess` makes the runner execute candidates as a local Python process instead of a container. That is for debugging only: it gives model-written code the same access as your user account.

## Project layout

```text
agent.py              the three-phase agent (Chat Completions, four app-defined tools)
build_reference.py    the ground-truth bracket and the four reference views
evaluator.py          hidden evaluator: 13 feature checks, absolute voxel IoU, edit checks
report.py             scores a saved run, totals cost per phase, draws the figures
check_connection.py   one-request API check
estimate_tokens.py    input-token estimate for the first request
cadkit/runner.py      runs a candidate in the Docker sandbox
cadkit/render.py      fixed-camera orthographic renderer (NumPy, no GPU)
sandbox/              the sandbox image: no network, read-only, non-root
inputs/               the four images sent to Kimi
hidden/               answer key; agent.py never reads it
runs/                 the three recorded runs from October 26, 2026
probes/               small API and sandbox checks, with their saved output
docs/                 architecture diagram
```

`hidden/frozen_hashes.txt` holds SHA-256 hashes of the evaluation rules, the manifest, and the four input images, taken before the first Kimi request. Every `runs/*/run.json` records the same hashes.

## Recorded results

| | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| Single-shot checks passed | 13/13 | 13/13 | 13/13 |
| Single-shot IoU (absolute) | 1.0 | 1.0 | 0.9987 |
| Repairs used | 0 of 3 | 0 of 3 | 0 of 3 |
| Edit checks passed | 8/8 | 8/8 | 8/8 |
| Total cost (USD) | 0.0629 | 0.0730 | 0.0715 |

Run 3 drew 6.0 mm holes against a true 6.5 mm, which sits exactly on the ±0.5 mm hole tolerance. These are three runs on one fixture, not a success rate, and they are not a BenchCAD score.
