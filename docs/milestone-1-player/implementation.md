# Player — Implementation

Thin vertical slices in build order. Each is independently testable end-to-end.

## Slice 1 — Store and Companion API
- Goal: Prism can connect, publish a show, list shows, download a bundle, delete a show.
- Touches: `main.py serve`, `config.py`, `api.py` (`/healthz`, `/v1/info`, `/v1/shows*`), `store.py`, bearer auth middleware, `example-config.yaml`, `pyproject.toml`.
- Acceptance: `PUT` of a valid bundle from the Prism repo's test fixture unpacks and lists with the manifest's fields; a bundle with a missing frame file or a wrong frame size is refused with 400 and leaves any existing show untouched; `GET .../bundle` returns a zip equal in content to the upload; a wrong token gets 401; `/healthz` needs no token.
- Out of scope: requests, hubs, playback.

## Slice 2 — Requests
- Goal: the queue exists and Prism can move requests through their states.
- Touches: `requests.py`, `api.py` (`/v1/requests*`), `on_request` hook.
- Acceptance: `POST` creates a request and fires the hook once; a second `POST` with the same `external.spotify_uri` returns the same request and fires nothing; `PATCH` changes status and stores `show_id`; `GET` lists newest first.
- Out of scope: any playlist source.

## Slice 3 — Lights only
- Goal: a show plays on real hubs with no audio.
- Touches: `hubs.py`, `ddp.py`, `engine.py` (clock, scheduler, restore-on-stop), `audio/none.py`, `api.py` (`/v1/play` with one show, `/v1/stop`, `/v1/status`).
- Acceptance: DDP bytes for a 300-pixel and a 1444-pixel frame equal Prism's `ddp.ts` output for the same input (fixture shared as hex); with a fake clock the scheduler sends frame `i` at `i / 40` s and skips, never queues, late frames; a hub that was off is off after stop and one that was on received no power write; on the bench hub the show visibly plays and the hub returns to its prior look after stop (user run).
- Out of scope: audio, queues.

## Slice 4 — Audio through Home Assistant
- Goal: audio and lights play in sync from one clock.
- Touches: `audio/base.py`, `audio/ha.py`, `api.py` (`/v1/shows/{id}/audio`), engine start sequence and position correction, `calibrate.py`, `main.py calibrate`.
- Acceptance: against a fake HA, the clock starts when the entity reports `playing` and re-bases only after two consecutive disagreements over one frame; the audio route streams the file with range support; `calibrate` prints an offset after the user nudges; on the bench, a show plays through the living room speaker with flashes on beats after calibration (user run).
- Out of scope: local audio output.

## Slice 5 — Queue, next, hooks
- Goal: playlists of shows play through, and a home system can follow along.
- Touches: `engine.py` queue, `api.py` (`queue` forms of `/v1/play`, `/v1/next`, status queue), `on_play` and `on_stop` hooks.
- Acceptance: a queue of two shows plays both with a restore between them; `next` ends the first at once; `queue: "all"` with shuffle plays every stored show once; hooks fire at each start and end with the show summary and a failing hook URL changes nothing.
- Out of scope: repeat modes.

## Slice 6 — Container and release
- Goal: a tagged image runs on the Pi 5 from a compose file.
- Touches: `Dockerfile`, `/healthz` in the image, README run section, version tag.
- Acceptance: `docker build` produces an image that serves `/healthz` with host networking and a mounted config; `uv run pytest`, ruff, and mypy pass; tag `v0.1.0`.
- Out of scope: the deployment's compose entry (lives in the deployment repo).
