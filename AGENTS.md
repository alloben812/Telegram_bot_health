# AGENTS.md

This repository is developed with multiple LLM agents. This file is the shared entry point for all agents, regardless of role.

Always communicate with the user in Russian unless the user explicitly asks otherwise.

## Source of Truth

Read these files before making product or architecture decisions:

- `docs/PRODUCT.md` - product vision, MVP scope, user flows.
- `docs/ARCHITECTURE.md` - target architecture, data model direction, deployment.
- `docs/AGENT_ROLES.md` - responsibilities for architect, developer, QA, and reviewer agents.
- `CLAUDE.md` - current repository mechanics and legacy implementation notes.

If documents conflict with code, inspect the code and report the mismatch before changing behavior. Do not silently rewrite product decisions.

## Current Product Direction

The project starts as a personal Telegram health and training assistant for one athlete. The target product is a multi-user platform for athletes and coaches.

MVP priority:

1. Daily assistant.
2. Goal planner.
3. AI chat with quick actions.

The first MVP must focus on daily recommendations and today's planned workout, based on connected device data and saved user profile settings.

## Working Rules

- Prefer small, explicit changes over broad rewrites.
- Keep future multi-user support in mind, but do not overbuild before MVP behavior works.
- Do not hard-code new single-user assumptions unless explicitly marked as MVP-only.
- Preserve encrypted credential/token handling.
- Do not change `SECRET_KEY` semantics. Changing it makes encrypted fields unreadable.
- Store raw device payloads fully and encrypted where appropriate.
- Normalize device data separately for calculations and UI.
- AI output must be structured JSON validated by backend schemas before being saved or shown.
- Backend calculates facts; AI interprets facts and proposes recommendations.
- Keep provider-specific AI SDK code behind an `AIProvider` abstraction.

## Important Current Gaps

The existing code and README still describe a Claude/Anthropic, polling, SQLite-first bot. The target MVP now uses:

- OpenAI as the first AI provider behind a provider abstraction.
- Telegram webhook instead of polling for production.
- Web Connect UI for device connections.
- Neon Postgres in production.
- Render Free Web Service for MVP hosting.
- GitHub Actions cron for scheduled sync/recommendation endpoints.

Agents should treat the current implementation as a starting point, not as final architecture.

## Git and Safety

- Do not revert user changes.
- Do not remove local files such as databases, caches, or `.env` files unless explicitly asked.
- `.garth_cache/`, local SQLite databases, virtual environments, and secrets should not be committed.
- Before substantial code changes, check `git status --short --branch`.
- When making code changes, update docs if product or architecture behavior changes.

