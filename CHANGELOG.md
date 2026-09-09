# Changelog

All notable changes to QuantProof are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-09-09

### Added

- m1: `quantproof rank --gguf a.gguf b.gguf --tasks ./tasks` runs every
  local GGUF variant against a user task pack through a `llama-server`
  child process and prints the ranked pass-rate / tok/s table with the
  per-variant collapse delta versus the best variant, plus a per-task
  pass matrix.
- Task-pack schema (`tasks.json`): C-coding tasks graded by their own
  shell test command over the extracted code block, and general-QA tasks
  graded by an exact substring check.
- `quantproof init` scaffolds `./tasks` with the bundled 10-task example
  pack (5 C-coding, 5 general-QA); example packs ship separately under
  `examples/c-coding/` and `examples/general-qa/`.
- `quantproof doctor` verifies `llama-server` on PATH and reports GPU
  visibility, with install hints when the binary is missing.
- pytest suite covering task-pack loading, both graders, scoring and
  collapse-delta math, table rendering, and llama-server orchestration
  against a stubbed OpenAI-compatible server.
