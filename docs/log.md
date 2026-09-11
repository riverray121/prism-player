# Dev Log

Development context for resuming work. One line per entry. Not a changelog.

## Completed
- Step 1: show store with atomic replace, Companion API, bearer middleware, audio route with ranges.
- Step 2: SQLite requests with external-id dedupe, `on_request` hook.
- Step 3: `ddp.py` byte-identical to Prism's ddp.ts (shared fixture `tests/fixtures/ddp_packets.json`), `hubs.py` (mDNS + config by MAC, WLED JSON), `engine.py` frame scheduler on an injectable clock with restore-on-stop, `none` audio backend, `/v1/play`, `/v1/stop`, `/v1/status`.
- Step 5: queue (`queue: [ids]` or `all` with shuffle), `/v1/next`, `on_play` and `on_stop` hooks.
- Step 4: `audio/ha.py` (`play_media` with the audio URL, wait for `playing`, position from `media_position` + elapsed since `media_position_updated_at`, 1 s state cache, `media_stop`), `main.py` builds it for `audio.backend: ha`; `calibrate.py` click show (1 kHz burst and a 3-frame white flash every second) installed as `calibrate-click`, keys nudge the offset live through `Engine.set_offset`.
- Step 6: Dockerfile (python:3.12-slim, pip install, `/healthz` HEALTHCHECK on `PLAYER_PORT`), `.dockerignore`.

## Todo
- Step 3 bench run on the real hub (user go).
- Step 4 bench run through the living room speaker, then `calibrate` (user go).
- Docker build was not run on the Mac (Docker was not running); build on the Pi 5 or start Docker first. Then tag v0.1.0.

## Notes
- Position correction compares the audio position with light time plus `offset_s`, and a re-base keeps the offset. Without that, any offset over one frame re-based every two polls and vanished.
- `HaBackend` shares the app's aiohttp session rather than owning one; the serve context closes it.
- A backward clock re-base (audio behind the lights) never resends frames; later frames land later. A forward re-base skips to the frame due now, like any late frame.
- `play` and `next` return once the next show is current, so a status read right after them reports it.
- `Hubs._on_change` runs on the zeroconf thread pool callback into the loop via `asyncio.create_task`; the browser is created on the event loop, so the callback fires there.
