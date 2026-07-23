# marketing-generator — Project Context
# 安裝位置: C:\Projects\marketing-generator\CLAUDE.md

## Stack
Python stdlib only (zero 3rd-party for core) + http.server backend
Data store: GitHub Contents API
AI providers: Anthropic adapter + Gemini adapter (interchangeable)
Shared modules: local-kit-source repo (config_loader, safe_git, json_collection, logger, migration_tracker)

## Completed Phases
Phase 1–8.1 complete

## Blocked (do not touch without explicit unblock)
- Phase 6 (DA Trainer integration) — BLOCKED
- Phase 8.2 (start_all.py) — BLOCKED

## Credential Rules
- .env.example must NEVER contain real keys — lesson from 3 prior leak incidents
- Anthropic key: already invalid (rotated)
- GitHub PAT: rotated after leak — current PAT in .env.local only

## Shared Module Protocol
Before modifying any shared module, check local-kit-source first.
Changes to shared modules affect ALL dependent projects.

## Current SDD
Read: docs/SDD.md before starting any Phase
