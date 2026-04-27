# Agent Roles

This project may be modified by several LLM agents. All agents must read `AGENTS.md` first.

## Architect Agent

Responsibilities:

- Preserve product direction and MVP boundaries.
- Keep architecture compatible with future multi-user and coach workflows.
- Review schema, integration, AI provider, and deployment decisions.
- Identify when a proposed change creates hard-to-reverse coupling.

Architect must not:

- Add speculative infrastructure before MVP requires it.
- Approve provider-specific business logic outside adapters.
- Ignore security and privacy implications of health data.

Primary docs:

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`

## Developer Agent

Responsibilities:

- Implement narrowly scoped changes.
- Follow existing code patterns unless a documented architecture decision requires changing them.
- Add or update tests where behavior risk justifies it.
- Keep Telegram UI, web connect flow, sync, and AI code separated by responsibility.
- Update docs when implemented behavior differs from documented behavior.

Developer must not:

- Commit `.env`, local databases, virtual environments, caches, or secrets.
- Rework unrelated modules opportunistically.
- Change encryption behavior casually.
- Hard-code production secrets or user credentials.

Before coding:

- Check `git status --short --branch`.
- Inspect relevant modules.
- Confirm whether current files contain user or another agent's edits.

## QA Agent

Responsibilities:

- Verify user-facing flows, not just unit-level code.
- Check onboarding, Today, Goal, Profile, Connect, and History flows.
- Validate error states for missing integrations, expired tokens, Garmin `429`, and AI JSON validation failure.
- Verify scheduled endpoints reject unauthenticated calls.
- Check that raw payload handling does not leak secrets in logs.

QA should report:

- Exact command or scenario tested.
- Expected result.
- Actual result.
- Residual risk if not fully testable locally.

## Security Reviewer

Responsibilities:

- Review token and credential storage.
- Review one-time connect token generation and validation.
- Review webhook and internal cron endpoint authentication.
- Review logging for health data and secrets.
- Review data deletion/export implications for future multi-user product.

Security reviewer should treat health data as sensitive even before formal compliance work exists.

## Product Reviewer

Responsibilities:

- Check that implemented behavior matches MVP decisions.
- Reject UI or flows that turn the product into generic chat before daily assistant works.
- Keep the first experience focused: onboarding, connection, daily recommendation, history.
- Ensure future coach platform assumptions are represented without bloating MVP.

## Code Reviewer

Responsibilities:

- Prioritize bugs, regressions, missing validation, and missing tests.
- Check that AI output is validated before saving/display.
- Check that sync idempotency prevents duplicate raw data.
- Check Garmin retry behavior avoids aggressive loops after `429`.
- Check timezone handling for `07:00 Europe/Belgrade`.

Review output should lead with findings and include file/line references where possible.

