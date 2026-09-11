# prism-player

Plays light shows made in Prism: stores show bundles, plays each show's audio through a Home Assistant media player, and streams the light frames to WLED hubs over DDP in sync. Implements Prism's Companion API so Prism can push shows and pull them back.

Design and process live in `docs/`. Read them before starting work.

## Session start
Read `docs/index.md`, then the ACTIVE milestone's `log.md` → `implementation.md`,
then `design.md` / `architecture.md` as the task needs. Only the ACTIVE milestone
is current — ignore shipped ones unless asked.

## Stack
- Python 3.12, uv, aiohttp (HTTP API and client), zeroconf (WLED mDNS), PyYAML, SQLite (stdlib).
- Docker image, one container, host networking.

## Commands
- Test: `uv run pytest`
- Lint: `uvx ruff check src/ tests/`
- Typecheck: `uvx mypy src/`
- Run: `uv run prism-player serve --config example-config.yaml`

## Git
- Remote: github.com/riverray121/prism-player (public)
- Push: after the user has tested a slice on the bench hub and confirmed.

## Standing rules
- The Companion API and the show bundle format are defined in the Prism repo (`docs/companion-api.md`). This project implements them; it does not redefine them. A change to the contract is made there first.
- Personal deployment config (hubs, tokens, HA entity names) never enters this repo. `example-config.yaml` shows the shape with placeholder values.
- The user runs hardware tests. Do not send DDP frames to a real hub or call a real Home Assistant unless the user says go for that run.
