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

## Set up

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # then put your MOONSHOT_API_KEY in .env (path B only)
```

## Reproduce the article's numbers

There are two paths. Path A checks the recorded results without spending anything. Path B runs the experiment again and gives you new results.

### Path A: re-score the recorded runs (no API key, no Docker)

`runs/` holds the three runs from the article, with every program Kimi wrote, every STEP file it produced, and the usage record of every API request. `report.py` reads those files only. It sends no request to Kimi and runs no model code:

```bash
python report.py runs/20261026-214530
python report.py runs/20261026-214846
python report.py runs/20261026-215224
```

For each run it prints the 13 feature checks and the IoU of every candidate, the 8 edit checks, and tokens and cost per phase. It also rewrites that run's `results.json` and `figures/` with the same values. Two smaller checks:

```bash
python evaluator.py score runs/20261026-215224/candidates/c0/candidate.step   # one candidate (the 6.0 mm holes)
python -m probes.evaluator_controls                                            # IoU on a plain L and a part scaled 1.2x
```

### Path B: run the full experiment again (API key, credit, Docker)

You need a Kimi API key with at least $1 of top-up and a working Docker install.

```bash
python check_connection.py         # one request to confirm the key and model
docker build -t cad-sandbox:2.8.0 sandbox/
python build_reference.py          # optional: rebuilds hidden/ and inputs/ from source
python agent.py                    # baseline, repair loop, slot edit; saves runs/<timestamp>/
python report.py runs/<timestamp>  # hidden scores, cost per phase, figures
```

A run makes at least six requests and took about three minutes and 6.3 to 7.3 cents in the recorded trials. Kimi's output varies, so a new run gives its own numbers. `build_reference.py` is optional because the fixture is already committed. If you rerun it, compare the new files with `hidden/frozen_hashes.txt` (`sha256sum hidden/eval_rules.json hidden/manifest.json inputs/*.png`) to confirm you are scoring against the same fixture.

`agent.py` uses `kimi-k3.1-pro` with `reasoning_effort="high"` on every request and keeps the full assistant message, including `reasoning_content` and `tool_calls`, in the history.

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
