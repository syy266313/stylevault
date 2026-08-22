# StyleVault Agent Contract

This file is the execution contract for coding agents. Read it before planning or editing.

## Startup

1. Read `docs/PROJECT_CONTEXT.md`, then this file.
2. Read the relevant `SKILL.md`, schema, config, and nearby implementation before editing.
3. Check `git status --short`; preserve unrelated user changes.
4. State the target, affected files, invariant(s), and verification command before a substantial implementation.

## Architecture Boundaries

- `schemas/item.schema.json` is frozen. Schema evolution belongs in `schemas/drafts/`.
- `item.json` is canonical. `indexes/` is derived and rebuildable.
- Ingest creates skeletons only. Image and video analysis consume queued work.
- Video orchestration depends on `VideoAdapter`, never on ffmpeg calls outside `FfmpegAdapter`.
- Algorithmic transition and camera observations retain confidence, source, and detection method. Low confidence is a candidate, not a fact.
- Do not add a vector database, cloud persistence, or an unrelated UI framework without an approved architecture decision.

## Ownership

- `skills/stylevault-ingest/`: import, SHA-1 deduplication, queue skeletons.
- `skills/stylevault-analyze-image/`: deterministic and semantic image analysis.
- `skills/stylevault-analyze-video/`: M3 rhythm, adapters, Style DNA merge, acceptance.
- `schemas/drafts/`: forward-compatible contracts; do not mutate frozen v1.
- `configs/`: versioned policy, ontology, and golden data; edits require compatible tests.

## Change Rules

- Keep changes scoped. Prefer existing JSON and CLI patterns over new abstractions.
- No dependency installation or external API execution unless the task explicitly requires it.
- Never print, commit, or hard-code secrets. Consume environment variables by name only.
- Repository `skills/stylevault-*` is authoritative; synchronize it to `/var/minis/skills/` after changing a skill.
