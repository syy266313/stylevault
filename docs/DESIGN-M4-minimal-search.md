# M4.0 Minimal Deterministic Search

## Scope

M4.0 validates whether the existing image knowledge base is useful with a local, explainable search path. It does not implement M3.4 Style DNA, embeddings, vector storage, a PWA, cloud services, or video benchmark evaluation.

## Source of truth and index

`items/*/item.json` is authoritative. Search reads item metadata directly and uses `indexes/tags.json` only as an optional tag candidate accelerator. If the index is absent, malformed, stale, or missing a requested tag, search falls back to scanning item metadata. Search never writes either source items or indexes.

Eligible records have `analysis.status` equal to `done` or `needs_review`. Malformed JSON and records without a valid id or analysis object are skipped with no process failure.

## Query contract

- Exact tag filters: `--tag`, `--tags`, with `--mode and|or`.
- Metadata filters: `--type`, `--collection`, `--preference-min`.
- Text query: `--text`, matching deterministic case-insensitive whitespace-separated tokens against `analysis.summary` and `analysis.editing_rules[].rule`.
- Empty query means all eligible items, sorted deterministically.
- Duplicate tags and duplicate item ids are collapsed.

`--preference-min` accepts normalized `[0,1]` or the existing raw `[1,5]` preference scale. It is a filter, never a replacement for tag relevance.

## Explainable ranking

```text
score = 5.0 * matched_tag_ratio
      + 1.5 * matched_rule_ratio
      + 1.0 * matched_summary_ratio
      + 0.2 * normalized_preference
```

Tag matches dominate. Text fields add smaller evidence. Preference is only a small tie-break contribution. Sort is descending score then ascending `item_id`, so repeated calls are stable. Results expose score, matched tags, matched summary tokens, matched rule tokens, source path, status, type, and preference.

## Verification boundary

Tests cover AND/OR, metadata filters, preference thresholds, summary/rule search, no results, missing fields, corrupt JSON, duplicate suppression, stable ordering, missing-index fallback, source immutability, and frozen schema preservation.
