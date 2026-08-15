# StyleVault Project Context

This file is the long-term context summary for new agent sessions. It should stay concise, current, and authoritative.

## 1. Project Positioning

**StyleVault** is a local-first personal visual memory layer for creative work.
It is not just a素材库 or gallery. Its purpose is to turn collected images, videos, and web cases into a structured, queryable, and reusable memory layer for AI-assisted creation.

Final goal:
- build a durable personal visual memory layer for AI creation
- preserve aesthetic preferences, style patterns, rhythm, lighting, composition, and editing language
- support future AI editing and style-aware generation
- serve as a personal style knowledge base, not a generic asset manager

## 2. Current Version Status

- Frozen release: **v0.4.1**
- Release branch: `release/v0.4`
- Git tag: `v0.4.1`

Milestone completion:
- **M0** complete: base architecture and schemas
- **M1** complete: ingest pipeline
- **M2** complete: image analysis pipeline
- **M2.5** complete: visual quality calibration with Golden Dataset and editing_rules
- **M3.0** complete: architecture-only video analysis scaffold
- **M3.0.5** complete: video analysis test preparation and acceptance script
- **M3.1** not started

## 3. Current Architecture

### ingest
- `stylevault-ingest`
- Handles attachment import, Apple Photos import, and URL/browser capture
- SHA-1 deduplication
- Creates item skeletons only
- Analysis is decoupled and queued as `pending`

### analyze-image
- `stylevault-analyze-image`
- Phase A: local deterministic features via `apple-vision analyze` + Pillow
- Phase B: OpenAI-compatible multimodal vision analysis
- Output includes:
  - `subject`
  - `style`
  - `mood`
  - `color`
  - `composition`
  - `lighting`
  - `camera`
  - `rhythm` (image entries remain `null`)
  - `summary`
  - `preference`
  - `editing_rules`

### analyze-video
- `stylevault-analyze-video`
- Architecture-only scaffold in M3.0
- Uses unified adapter abstraction:
  - `VideoAdapter`
  - `FfmpegAdapter` placeholder
  - `MockAdapter`
- No direct ffmpeg dependency in the top-level flow
- Mock pipeline validates rhythm parameters and Style DNA merge logic

### style_dna
- Concept: `visual (M2.5 editing_rules) ⊕ rhythm (M3 params) -> style_dna.signature`
- Style DNA is the unified style fingerprint for future retrieval and editing logic
- Do not bind this early to a vector database

### Schemas
- Frozen schema: `schemas/item.schema.json`
- Frozen state is preserved and must not be modified casually
- Draft / future schema work goes into `schemas/drafts/`
- Current draft artifacts include:
  - `schemas/drafts/item.schema.v2.draft.json`
  - `schemas/drafts/video.schema.json`
- Rhythm is being upgraded from simple tags to parameterized structure in drafts only

## 4. Core Design Principles

- **Local first**: keep data and logic on-device when possible
- **File + metadata separation**: source files and JSON metadata are separate; JSON is the source of truth
- **Two-stage analysis**: deterministic local features first, semantic analysis second
- **Schema version management**: frozen schema remains stable; evolution goes through drafts and versioned artifacts
- **Adapter abstraction**: video analysis must go through adapters, not direct ffmpeg coupling

## 5. Current Model Strategy

### Agent default model
- `minis-model-use` currently has no callable agent-loop model available in practice
- Existing provider/model configuration exists in the environment, but the agent-loop list is not usable at the moment
- For project automation, use repository scripts and explicit environment variables rather than assuming an active agent-loop model

### Vision analysis model
- Default Phase B image vision model: **gpt-5.6-terra**
- Called through an OpenAI-compatible endpoint
- Configured via environment variables:
  - `STYLEVAULT_MODEL=gpt-5.6-terra`
  - `OPENAI_BASE_URL=<openai-compatible proxy>`
  - `OPENAI_API_KEY=<key>`

### Deep analysis model
- No separate deep-analysis model is currently bound as a dedicated project default
- If a dedicated deep-analysis model is later added, it should use the same environment-driven OpenAI-compatible interface and remain configurable

## 6. Current Paused Items

- `ffmpeg` is **not installed** in the current environment
- M3.1 is **not started**
- No further attempts should be made to install ffmpeg unless explicitly requested

## 7. Next Direction

After M3.0.5, the next product directions are:
- **Style Retrieval**: semantic + style-dna based retrieval of similar cases
- **Preference Feedback**: user preference correction loop and ranking
- **Style DNA**: unify visual rules and rhythm parameters into one reusable style signature
- **Future auto-editing**: use Style DNA to guide AI editing and clip generation

## 8. Current Do-Not-Do List

- Do not break the frozen schema
- Do not bind to a vector database too early
- Do not expand the scope before the retrieval layer is ready
- Do not reintroduce direct ffmpeg coupling into the top-level video analysis flow
- Do not treat low-confidence algorithm output as certain fact

## 9. Repository / Workflow Notes

- GitHub repo: `github.com/syy266313/stylevault`
- Current working branch: `main`
- Frozen release branch: `release/v0.4`
- Current frozen tag: `v0.4.1`
- Skills are versioned in the repository under `skills/stylevault-*` and synchronized to `/var/minis/skills/` for execution

## 10. Short Operational Summary

- Ingest is done
- Image analysis is done
- Visual calibration is done
- Video architecture is scaffolded
- Video runtime implementation is paused until ffmpeg is ready
- The next major product step after ffmpeg readiness is M3.1
