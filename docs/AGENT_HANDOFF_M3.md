# StyleVault Agent Handoff: M3.2.1 Integration Hardening / M3.3 Gated

## Read first
- `AGENTS.md`
- `docs/PROJECT_CONTEXT.md`
- `PROJECT.md`
- `skills/stylevault-analyze-video/SKILL.md`

## Current state
- Repository: `github.com/syy266313/stylevault`
- Branch: `main`
- M3.1.1 baseline: `77b6909`
- Threshold correction commit: `b4b8f6d` (`fix: correct ffmpeg scene threshold mapping`), pushed to `origin/main`
- ffmpeg/ffprobe are available; ffmpeg version `1229403`
- Frozen file: `schemas/item.schema.json`; unchanged
- Fixture foundation checkpoint: `8500e8c` (`feat: add deterministic M3.2 video fixtures`), pushed to `origin/main`
- M3.2 detector/evaluator commit: `19c6f53` (`feat: implement M3.2 frame-based detection`), pushed to `origin/main`
- M3.2.1 integration hardening commit: `eb3ca6c` (`fix: harden M3.2 integration contract`), pushed to `origin/main`
- Agent contract is present on `main` in the subsequent docs commit `5b288fb`, pushed to `origin/main`
- Working tree otherwise contains only unrelated untracked `AGENTS.md`

## M3.1 implementation
- `FfmpegAdapter.probe()` calls ffprobe for duration, dimensions, fps, codec, format
- `FfmpegAdapter.segment()` calls ffmpeg `scdet` and builds shot intervals
- ffmpeg calls are inside `FfmpegAdapter`
- missing-tool and command errors return structured JSON from CLI commands
- public `scene_threshold` remains normalized 0-1; adapter maps it to ffmpeg `scdet` 0-100
- M3.2 transition and camera detection are frame-based and implemented in `FfmpegAdapter`; no shot-statistics-only heuristic is used

## Verification completed
- `ffmpeg -h filter=scdet`: native threshold range confirmed as 0-100
- Public normalized 0-1 threshold maps correctly: `0.30 -> 30.0`
- `python3 -m py_compile ...`: passed
- M3.1.1 tests: `37/37` passed
- Real probe: passed on repository `.mov` sample
- Real segment: passed on repository `.mov` sample
- M3.1 acceptance: `3/3` passed
- Fixture foundation tests: `4/4` passed; full video test suite: `41/41` passed
- Fixture evaluator: `6/6` probe contracts passed
- M3.2.1 integration targets: formal `analyze-m32` CLI, unified `rhythm.params`, segment-aware context, event position windows, strict observation validation
- `schemas/item.schema.json`: unchanged

## M3.2 fixture foundation completed
- Added independent `configs/video-m3.2-fixtures.json`; M3.1 `configs/video-test-suite.json` was not changed
- Six fixtures are defined: `static_hard_cut`, `static_dissolve`, `static_fade` (`fade_out_in` pattern), `pan_horizontal`, `zoom_in`, `no_motion`
- Added `scripts/m3_2_fixtures.py`: specification validation, deterministic Pillow frame generation, and adapter-owned ffmpeg encoding
- Added `scripts/evaluate_m32_fixtures.py`: independent probe contract evaluator; it does not evaluate transition/camera predictions
- Added `tests/test_m3_2_fixtures.py`: configuration, generation, probe, reproducibility, provenance and cleanup checks
- Ground truth is `synthetic_spec`; no algorithm output is used to create it
- No video binaries, frames, temporary logs or credentials were added to Git
- Frame/window detection implementation is present in the working tree and has now passed the redesigned acceptance
- All ffmpeg/ffprobe calls remain inside `FfmpegAdapter`

## M3.2 redesigned acceptance result
- Diagnostic report generated at `/tmp/m32_diagnostic_report.json` before algorithm changes; it recorded frame count/times, RGB diff distribution, brightness, active groups, dissolve/fade windows, zoom scale errors, pan translation trend and no-motion risk.
- Diagnostics confirmed real signal: dissolve sustained RGB diff around 0.02-0.03, fade brightness valley around 0.392, zoom foreground extent growth around 1.85x, pan dx trend stable, and no-motion max diff below 0.003.
- Redesign round 1: `static_hard_cut`, `static_dissolve`, `pan_horizontal`, `no_motion` passed; fade and zoom remained unresolved.
- Redesign round 2: global brightness valley + monotonicity classified `fade_out_in`; expanded scale search plus salient extent trend classified `zoom`.
- Final M3.2 synthetic acceptance: `6/6` passed.
- M3.2.1 integration now requires a formal `analyze-m32` CLI and emits detections under `rhythm.params.transition_types` / `rhythm.params.camera_moves`.
- Detection events carry `segment_index`, `time_s` or `window_ms`; evaluator checks event position against fixture `allowed_window_ms`.
- Observation validation is strict for status, candidate type, non-empty provenance strings, and finite confidence in [0,1].
- M3.2.1 verification: full suite `53/53`, M3.2.1 integration tests `12/12`, fixture acceptance `6/6`, real `analyze-m32` CLI passed, `py_compile` passed, and `git diff --check` passed.
- Real user video generalization remains unverified.

## M3.3 gate
- Do not enter M3.3 until independent `color_continuity` ground truth is ready.
- Do not enter M3.4 or M4.

## Checkpoint decision
- M3.2.1 integration hardening is complete in the working tree pending final verification and commit.
- M3.2 detector commit is `19c6f53`; this is the single authoritative detector commit.
- M3.3 fixture foundation is complete: five independent color sequence specs, runtime generation, and reference metrics validation are ready.
- M3.3 fixture foundation tests: `5/5` passed; independent color input evaluator: `5/5` passed.
- M3.3 detector is not implemented; the existing `ready: false` gate was verified with exit code `2`.
- Full video test suite after fixture additions: `58/58` passed; `py_compile` and `git diff --check` passed.
- Real user video generalization remains unverified.
- Do not enter M3.4 or M4.

## Model workflow
- 5.6 sol: architecture review only, identify P0/P1 and exact files.
- 5.4 mini: implement a small approved patch and run tests.
- Use Trea from M3.2 onward only if it can access this same workspace and run shell/tests.
- Compress context after each milestone or after 2-3 repair rounds. Start a new session using this file, not the old conversation.
