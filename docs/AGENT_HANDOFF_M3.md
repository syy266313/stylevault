# StyleVault Agent Handoff: M3.1.1 / M3.2 Fixture Rebuild

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
- Fixture foundation is ready for checkpoint commit; unrelated untracked `AGENTS.md` is preserved

## M3.1 implementation
- `FfmpegAdapter.probe()` calls ffprobe for duration, dimensions, fps, codec, format
- `FfmpegAdapter.segment()` calls ffmpeg `scdet` and builds shot intervals
- ffmpeg calls are inside `FfmpegAdapter`
- missing-tool and command errors return structured JSON from CLI commands
- public `scene_threshold` remains normalized 0-1; adapter maps it to ffmpeg `scdet` 0-100
- M3.2 transition and camera detection remain `unknown` placeholders; no heuristic implementation is retained

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
- `schemas/item.schema.json`: unchanged

## M3.2 fixture foundation completed
- Added independent `configs/video-m3.2-fixtures.json`; M3.1 `configs/video-test-suite.json` was not changed
- Six fixtures are defined: `static_hard_cut`, `static_dissolve`, `static_fade` (`fade_out_in` pattern), `pan_horizontal`, `zoom_in`, `no_motion`
- Added `scripts/m3_2_fixtures.py`: specification validation, deterministic Pillow frame generation, and adapter-owned ffmpeg encoding
- Added `scripts/evaluate_m32_fixtures.py`: independent probe contract evaluator; it does not evaluate transition/camera predictions
- Added `tests/test_m3_2_fixtures.py`: configuration, generation, probe, reproducibility, provenance and cleanup checks
- Ground truth is `synthetic_spec`; no algorithm output is used to create it
- No video binaries, frames, temporary logs or credentials were added to Git
- No complete `transition_types` / `camera_moves` detection was implemented

## Next task
- Implement frame/window-based transition detection and explainable motion estimation inside `FfmpegAdapter`
- Keep M3.2 acceptance on this fixture suite only; do not use the M3.1 mock suite
- Do not enter M3.3, M3.4 or M4

## Next task: M3.1.1 only
Do not enter M3.2. Fix the six review items above. Add focused tests or executable checks. Do not install ffmpeg unless explicitly approved. Update `PROJECT.md`, `CHANGELOG.md`, and `SKILL.md`. Run py_compile, mock, validate, missing-ffmpeg error checks, and all relevant tests. Report what remains unverified.

## Model workflow
- 5.6 sol: architecture review only, identify P0/P1 and exact files.
- 5.4 mini: implement a small approved patch and run tests.
- Use Trea from M3.2 onward only if it can access this same workspace and run shell/tests.
- Compress context after each milestone or after 2-3 repair rounds. Start a new session using this file, not the old conversation.
