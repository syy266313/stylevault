# M3.3.1 Real-Video Generalization Benchmark

> Status: contract only. No real user videos are collected by this document.

## Purpose

M3.3.1 measures how the M3 runtime behaves on real user videos after the synthetic M3.3 detector acceptance. It is an independent benchmark, not a milestone gate and not a replacement for `configs/video-m3.3-color-fixtures.json`.

The benchmark produces a report about generalization, failure modes, and coverage. It must never change synthetic ground truth or make `M3.3` acceptance pass automatically.

## Dataset boundary

- Real videos are referenced by local `item_id` and metadata only; source media stays outside Git.
- No video, frame, audio, thumbnail, log, path containing personal information, or credential may be committed.
- The benchmark manifest contains no default samples. Samples are added only after local consent and privacy review.
- A source SHA-1 is the deduplication key. The same SHA-1, item, or known derivative may not appear in more than one split.
- Recommended splits are `development`, `validation`, and `holdout`.
- `holdout` is evaluated only for final reporting and cannot be used for threshold selection, detector redesign, or fixture changes.

## Manifest contract

Each entry records:

| Field | Meaning |
|---|---|
| `sample_id` | Stable benchmark identifier, not a user filename |
| `item_id` | Existing StyleVault item reference |
| `source_sha1` | SHA-1 of the original source media |
| `source_kind` | `user_video` |
| `source_origin` | Existing ingest channel: `photos`, `attachment`, or `import` |
| `duration_ms` | Probe result; positive integer |
| `width`, `height` | Probe result; positive integers |
| `fps` | Probe result; finite positive number |
| `codec` | Probe result; non-empty codec name when available |
| `capture_time` | Capture time when available, otherwise `null`; do not infer it |
| `split` | `development`, `validation`, or `holdout` |
| `annotation_status` | `not_started`, `in_progress`, `complete`, or `needs_review` |
| `privacy_status` | `pending`, `approved_local_only`, or `excluded` |
| `notes` | Non-sensitive annotation or exclusion note |

## Annotation contract

Annotations are human observations and may contain `unknown`; they are not detector output.

- `shot_boundaries`: ordered boundary times in milliseconds, with annotator confidence and notes.
- `transition_types`: event type and time/window. Allowed labels are `hard_cut`, `dissolve`, `fade`, and `unknown`.
- `camera_moves`: event/window label from `static`, `pan`, `zoom`, and `unknown`.
- `color_continuity`: sequence-level label from `stable`, `gradual_drift`, `abrupt_shift`, `alternating`, `fade_like`, and `unknown`, plus optional evidence notes.
- Every annotation records `annotator_id` as a non-personally-identifying local code, `annotated_at`, and `confidence` in `[0,1]`.
- Ambiguous boundaries and events are recorded with a tolerance window rather than false precision.

## Evaluation boundary

A future evaluator may compare detector observations to annotations using event tolerance windows and report metrics grouped by duration, resolution, FPS, codec, and capture context. It must output a standalone benchmark report with sample coverage, excluded samples, annotation agreement, and failure examples.

The evaluator must not:

- be called by `evaluate_video.py` milestone acceptance;
- modify `configs/video-m3.3-color-fixtures.json`;
- modify `schemas/item.schema.json`;
- write detector results back into source `item.json` files;
- use `holdout` samples for tuning.

## Acceptance and privacy review checklist

Before adding a sample: confirm local consent, source SHA-1, no cross-split duplicate, metadata completeness, and `privacy_status=approved_local_only`. Exclude faces, speech, location, or other sensitive material unless the user explicitly accepts local-only processing. Remove or redact identifying notes from the manifest.

## Implemented report scaffold boundary

`validate_m331_benchmark.py` validates the manifest contract and emits a report-only scaffold. It accepts an empty manifest honestly, reports zero eligible samples, and marks real benchmark metrics unavailable. It does not collect media, invoke detector evaluation, connect to `evaluate_video.py`, or write to item/index files. A future evaluator remains separate from this validator and from synthetic M3.3 acceptance.
