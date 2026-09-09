**English** | [简体中文](./README.zh-CN.md)

<div align="center">

<img src="https://readme-typing-svg.demolab.com/?font=Fira+Code&weight=600&size=22&pause=1600&color=E65662&center=true&vCenter=true&random=false&width=720&lines=quantproof+rank+--gguf+Q4_K_M.gguf+IQ2_XXS.gguf+--tasks+.%2Ftasks%3Branked%3A+variant+%7C+pass+rate+%7C+tok%2Fs+%7C+%CE%94+vs+best%3Bfind+the+collapse+before+the+download" alt="quantproof rank --gguf Q4_K_M.gguf IQ2_XXS.gguf --tasks ./tasks; ranked: variant | pass rate | tok/s | Δ vs best; find the collapse before the download">

# QuantProof

**Benchmark tool for local LLM developers to rank quant variants on their own tasks.**

Published quant tables rank variants on someone else's tasks. QuantProof runs every quant variant of one model against *your* task pack and shows exactly where quality collapses on your workload — before you spend a weekend and 40 GB of downloads finding out by hand.

[![CI](https://github.com/SuperMarioYL/quantproof/actions/workflows/ci.yml/badge.svg)](https://github.com/SuperMarioYL/quantproof/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-e65662)](https://github.com/SuperMarioYL/quantproof/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776ab)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-e65662)](./LICENSE)
![Local](https://img.shields.io/badge/local_only-no_telemetry-e65662)

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/hero-dark.svg">
  <img src="assets/presentation/hero-light.svg" width="960" alt="QuantProof — pass-rate bars for quant variants with the collapse delta (illustrative)">
</picture>

</div>

---

## <img src="assets/icons/rocket.svg" width="22" alt=""> Quickstart

Prerequisites: Python 3.12+, and [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` on PATH for real runs (the stub demo below works without it). Install from source:

```bash
git clone https://github.com/SuperMarioYL/quantproof.git
cd quantproof
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e .
```

Scaffold the bundled example pack — 10 tasks, zero authoring:

```bash
quantproof init
```

Try the full pipeline without a model (uses the deterministic stub server from `tests/`):

```bash
printf '(stub)' > Q4_K_M.demo.gguf && printf '(stub)' > IQ2_XXS.demo.gguf && \
  quantproof rank --gguf Q4_K_M.demo.gguf IQ2_XXS.demo.gguf --tasks ./tasks \
  --server-bin "python3 tests/stub_llama_server.py"
```

Run it for real, on GGUFs you already have:

```bash
quantproof rank --gguf model.Q4_K_M.gguf model.IQ2_XXS.gguf --tasks ./tasks
```

That is the whole loop: one command per run, one `llama-server` child per variant, and a ranked table at the end. Before a real run, `quantproof doctor` checks that `llama-server` is on PATH and reports GPU visibility with install hints.

## <img src="assets/icons/video.svg" width="22" alt=""> Recorded demo

The commands and outputs below are copied verbatim from a real `0.1.0` run — full record in [docs/demo-results.json](docs/demo-results.json), narrative companion in [docs/demo-report.md](docs/demo-report.md). `llama-server` was not installed on the recording machine, so the rank step substitutes the deterministic stub server via `--server-bin`: server spawn, `/health` wait, sampling, both graders and the collapse-delta table are the real code paths, but the pass rates demonstrate the pipeline, not quant quality.

```text
QuantProof — 10 tasks x k=3 per variant, base model: Qwen/Qwen3.8-27B
        Quant calibration — ranked on your tasks
┏━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┓
┃ Variant ┃ Pass rate ┃ Δ vs best ┃  tok/s ┃ Size (GB) ┃
┡━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━┩
│ Q4_K_M  │    100.0% │  baseline │ 9673.7 │      0.00 │
│ IQ2_XXS │     60.0% │  -40.0 pp │ 8702.7 │      0.00 │
└─────────┴───────────┴───────────┴────────┴───────────┘
collapse: IQ2_XXS (-40.0 pp) versus Q4_K_M on your tasks
```

The per-task matrix from the same run shows *where* the degradation lands — the stub's collapse mode fails c-01, c-02, c-03 and qa-01 while the rest hold:

```text
Per-task pass rate (passed samples / k)
┏━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Task  ┃ Grader    ┃ Q4_K_M ┃ IQ2_XXS ┃
┡━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ c-01  │ codeblock │  3/3   │   0/3   │
│ c-02  │ codeblock │  3/3   │   0/3   │
│ c-03  │ codeblock │  3/3   │   0/3   │
│ c-04  │ codeblock │  3/3   │   3/3   │
│ c-05  │ codeblock │  3/3   │   3/3   │
│ qa-01 │ contains  │  3/3   │   0/3   │
│ qa-02 │ contains  │  3/3   │   3/3   │
│ qa-03 │ contains  │  3/3   │   3/3   │
│ qa-04 │ contains  │  3/3   │   3/3   │
│ qa-05 │ contains  │  3/3   │   3/3   │
└───────┴───────────┴────────┴─────────┘
```

The stub answers in about a millisecond, so its `tok/s` figures are meaningless; on a real run they are decode speed as reported by the server's token usage. Reproduce the recording from a fresh clone with the quickstart commands above.

## <img src="assets/icons/bulb.svg" width="22" alt=""> Why QuantProof exists

A hot open-weight release immediately spawns 20+ community quantization variants — each one click to download, one day of GPU time to judge. On a 16 GB card the big quants do not even fit, which pushes you into the 1–4-bit regime where collapse varies most. The community's answers to "which quant should I use" are someone else's measurements:

- **Published benchmark tables** say 4-bit broadly holds and 1-bit collapses — but they score the author's tasks, not yours, and are regenerated by hand once per release.
- **llama-bench** measures what is cheap and transfers: decode speed and perplexity per file. Perplexity on generic text does not predict whether a 1-bit variant still writes valid C for *this* workload.
- **lm-evaluation-harness** runs fixed public suites whose whole value is comparability — the opposite of per-workload calibration.

The people who need the real answer keep paying for it by hand: one r/LocalLLaMA user benchmarked 21 variants of a single release on their own C code on an RTX 5080; another spent 11 days and roughly 167 GPU-hours comparing 8 community variants. QuantProof is that loop, automated and owned by you:

- The primitive is the **collapse delta**: a per-variant quality score measured on a portable, user-owned task pack, expressed relative to the best variant that ran. `IQ2_XXS: -40.0 pp on your tasks` is a row no blog table can print.
- Grading is **deterministic**: your own shell test commands for code, exact substrings for QA. Same pack, same verdict, every rerun — no LLM-as-judge drift.
- The core is **model-agnostic from day one**: any GGUF file, any quantizer, because the pack and the graders never assume a model.

## <img src="assets/icons/schema.svg" width="22" alt=""> How it works

One CLI process, files on disk, no daemon, no database, no telemetry. At most two processes are alive at any moment: the CLI and one `llama-server` child.

```
tasks.json ──┐
 *.gguf ─────┼─▶ resolve ─▶ runner ──▶ llama-server -m <gguf> :8111
             │                │              │  /health, then k samples per task
             │                ▼              ▼
             │            grader ◀── /v1/chat/completions
             │                │  code block -> temp dir -> test_cmd (exit 0 = pass)
             │                │  or exact substring for QA
             │                ▼
             └──────────── report: score, tok/s, per-task rates
                           -> ranked table + collapse deltas vs the best variant
```

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/architecture-dark.svg">
  <img src="assets/presentation/architecture-light.svg" width="960" alt="Architecture blueprint: resolve, runner, grader and report around one llama-server child">
</picture>

The calibration loop that drives an unattended overnight run:

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/process-dark.svg">
  <img src="assets/presentation/process-light.svg" width="960" alt="The calibration loop: load pack, run each variant through llama-server, grade, rank with collapse deltas">
</picture>

## <img src="assets/icons/file-text.svg" width="22" alt=""> Task packs

A task pack is a directory with a `tasks.json` file — plain data you own, version, and share. `quantproof init` scaffolds one from the bundled 10-task example pack; the two example packs also ship separately:

| Pack | Tasks | Grader |
| --- | --- | --- |
| [examples/c-coding](examples/c-coding/tasks.json) | 5 C programs (primes, fizzbuzz, sums, string reverse, Fibonacci) | `codeblock` — compile with `cc`, run, `diff` against expected output |
| [examples/general-qa](examples/general-qa/tasks.json) | 5 short factual questions | `contains` — exact substring in the reply |
| bundled (`quantproof init`) | both of the above, 10 tasks | mixed |

The schema:

```json
{
  "base_model": "Qwen/Qwen3.8-27B",
  "k_samples": 3,
  "tasks": [
    {
      "id": "c-01",
      "prompt": "Write a complete C program ... Reply with the program in one fenced code block.",
      "grader": {
        "type": "codeblock",
        "test_cmd": "cc -o prog main.c && ./prog > out.txt && printf '2\\n3\\n5\\n...' | diff - out.txt",
        "filename": "main.c",
        "timeout_s": 60
      }
    },
    {
      "id": "qa-01",
      "prompt": "What is the capital of France? Reply with just the city name.",
      "grader": { "type": "contains", "expected": "Paris" }
    }
  ]
}
```

`codeblock` writes the **first fenced code block** of the reply to `filename` inside an isolated temp directory and runs `test_cmd` there; exit code 0 is a pass. `contains` passes when `expected` appears as an exact substring. Task packs run shell commands you wrote — the same trust level as your CI scripts. `base_model` is informational (it names the model the variants belong to), `k_samples` is how many samples each variant draws per task.

## <img src="assets/icons/terminal-2.svg" width="22" alt=""> Command line

| Command | What it does |
| --- | --- |
| `quantproof doctor` | Verify `llama-server` is on PATH and report GPU visibility; prints install hints when missing |
| `quantproof init` | Scaffold `./tasks` with the bundled 10-task example pack |
| `quantproof rank` | Run every `--gguf` variant against the pack and print the ranked table |

`rank` options:

| Option | Default | Description |
| --- | --- | --- |
| `--gguf` | required | Local GGUF file; repeat per variant, or pass several space-separated after one flag |
| `--tasks` | required | Task pack directory (or its `tasks.json`) |
| `--k` | pack value | Override samples per task |
| `--port` | `8111` | Port for the `llama-server` child |
| `--startup-timeout` | `600` | Seconds to wait for `/health` (big models load slowly) |
| `--server-bin` | `llama-server` | Advanced: a llama-server-compatible command (wrapper, container shim, or the test stub) |

Variant labels are parsed from filenames (`Model-27B.Q4_K_M.gguf` → `Q4_K_M`); files without a recognizable quant tag fall back to the file stem. A sample that errors is recorded as failed and the run continues — an overnight sweep does not die on one flaky request.

## <img src="assets/icons/chart-bar.svg" width="22" alt=""> Capabilities and integrations

<picture>
  <source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 640px)" srcset="assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/presentation/integrations-dark.svg">
  <img src="assets/presentation/integrations-light.svg" width="960" alt="What plugs in today: local GGUF files, llama-server, shell test commands, task packs">
</picture>

| Component | Current support |
| --- | --- |
| Variants | Local `.gguf` files, any model and quantizer; labels parsed from filenames |
| Backend | llama.cpp `llama-server` only, via its OpenAI-compatible `/v1/chat/completions` |
| Code grading | Your own shell test commands (`cc`, `diff`, `grep`, pytest, ...) in an isolated temp dir |
| QA grading | Exact substring checks |
| Output | rich-ranked terminal table with collapse deltas and a per-task matrix |
| Example packs | C-coding and general-QA under `examples/`, bundled 10-task pack via `init` |

## <img src="assets/icons/settings.svg" width="22" alt=""> Configuration and limits

- **v0.1 works with GGUF files already on disk.** Downloading variants from a GGUF repo (`--gguf-repo` / `--quants`) is m2 and not implemented; `HF_ENDPOINT` mirror support lands with it. Until then QuantProof itself makes zero network calls.
- **llama.cpp only.** No Ollama, vLLM or transformers backends in v0.1; task packs and reports are backend-independent, so other backends are a matter of roadmap.
- **Deterministic graders only.** No LLM-as-judge; a rerun of the same pack reproduces the same verdicts (up to model sampling itself — k samples exist precisely to measure that variance).
- **Terminal report only.** The gistable `report.md` / `results.json` artifacts and crash-resumable `results.jsonl` runs are m2.
- **Collapse flag threshold**: variants more than 10 percentage points below the best are called out in the table footer.

## <img src="assets/icons/route.svg" width="22" alt=""> Roadmap

- [x] **v0.1 (current, m1)** — task-pack schema, both graders, llama-server orchestration, ranked table with collapse deltas and per-task matrix, `init` + `doctor`
- [ ] **m2** — resolve quant names against a GGUF repo and auto-download variants (honoring `HF_ENDPOINT`); crash-resumable runs; gistable `results.json` + `report.md`
- [ ] **m3** — a sub-one-hour three-variant quick mode as the documented default first run, plus a real-GPU demo recording

Not planned for v0.1: web UI or hosted leaderboard, backends beyond llama.cpp, LLM-as-judge grading, creating or tuning quants (this tool ranks, never generates), multi-GPU or multi-host runs, accounts or telemetry of any kind.

## <img src="assets/icons/license.svg" width="22" alt=""> Development and license

```bash
python -m pip install -e ".[test]"
python -m pytest
```

The suite covers task-pack loading and validation, both graders, scoring and collapse-delta math, table rendering, and llama-server orchestration against the stub server in [tests/stub_llama_server.py](tests/stub_llama_server.py) — no GPU or model required. Presentation artwork is regenerated with `python3 docs/render_presentation.py --repo .`.

[MIT](./LICENSE) © 2026 SuperMarioYL

---

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
