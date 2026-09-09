# Recorded demo — QuantProof 0.1.0

This is the companion report for [`demo-results.json`](./demo-results.json), recorded
2026-09-09 on macOS arm64 (Apple Silicon) with the package installed via
`pip install -e .` on Python 3.12.13. Outputs were captured non-interactively, so
rich progress bars appear as plain status lines; in an interactive terminal the
same run shows a live per-variant progress bar.

## What actually ran

| Step | Command | Result |
| --- | --- | --- |
| 1 | `quantproof init` | Scaffolds `./tasks` with the bundled 10-task example pack (5 C-coding tasks with test commands, 5 general-QA tasks with contains checks), k=3 |
| 2 | `quantproof doctor` | llama-server was **not installed** on the recording machine, so doctor printed the install hint and exited 1; the Apple Silicon GPU (Metal) was detected |
| 3 | `quantproof rank --gguf Q4_K_M.demo.gguf IQ2_XXS.demo.gguf --tasks ./tasks --server-bin "python3 tests/stub_llama_server.py"` | Full pipeline run over both variants |

## The honest caveat about step 3

Because llama-server was absent, the recorded rank run substitutes the
deterministic stub server shipped at `tests/stub_llama_server.py` through the
`--server-bin` option. The stub stands in for the model: it returns canned
answers for the bundled example pack, and deliberately degraded answers when
the `-m` model path contains a low-bits-per-weight marker (`IQ2_XXS` here).
Everything around the stub is the real code path — server spawn, `/health`
wait, k=3 samples per task over `/v1/chat/completions`, both graders (cc
compile + diff for code tasks, exact substring checks for QA) and the
collapse-delta math. The two `.demo.gguf` files are 8-byte placeholders the
stub never reads.

So read the table below as a **pipeline demonstration, not a quant
measurement**:

```text
        Quant calibration — ranked on your tasks
┏━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┓
┃ Variant ┃ Pass rate ┃ Δ vs best ┃  tok/s ┃ Size (GB) ┃
┡━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━┩
│ Q4_K_M  │    100.0% │  baseline │ 9673.7 │      0.00 │
│ IQ2_XXS │     60.0% │  -40.0 pp │ 8702.7 │      0.00 │
└─────────┴───────────┴───────────┴────────┴───────────┘
collapse: IQ2_XXS (-40.0 pp) versus Q4_K_M on your tasks
```

tok/s comes from response latency and token counts, so it varies per machine;
the stub answers in ~1 ms, which is why the numbers are in the thousands. The
per-task matrix from the same run shows where the stub's degradation bites
(c-01, c-02, c-03, qa-01 drop to 0/3 while the rest hold at 3/3) — the same
table shape a real collapse produces.

## Reproducing

From a fresh clone with the package installed:

```bash
quantproof init
quantproof doctor
printf '(stub)' > Q4_K_M.demo.gguf && printf '(stub)' > IQ2_XXS.demo.gguf && \
  quantproof rank --gguf Q4_K_M.demo.gguf IQ2_XXS.demo.gguf --tasks ./tasks \
  --server-bin "python3 tests/stub_llama_server.py"
```

With llama.cpp installed and real GGUF files on disk, drop `--server-bin` and
point `--gguf` at the files you already have — that run is the real
calibration and is exactly what QuantProof is for.

## Scope at 0.1.0 (m1)

- Implemented: local-GGUF variant resolution, task-pack schema, both graders,
  llama-server orchestration, the ranked terminal table with collapse deltas
  and the per-task matrix, `init` and `doctor`.
- Not implemented (m2/m3): downloading variants from a GGUF repo
  (`--gguf-repo` / `--quants`), resumable `results.jsonl` runs, the gistable
  `report.md` / `results.json` artifacts, and a sub-one-hour quick mode.
- llama.cpp-only: no Ollama / vLLM / transformers backends in v0.1.
