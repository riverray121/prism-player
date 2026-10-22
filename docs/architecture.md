# Architecture

prism-player stores the shows Prism publishes, keeps the queue of songs Prism should analyze, and plays a show: audio through a Home Assistant media player, lights over DDP to WLED hubs, both from one clock. The Companion API and the show bundle format are defined in the Prism repo (`docs/companion-api.md`); this project implements them.

## Model

- Store: `PUT /v1/shows/{id}` unpacks a bundle into `data/shows/{id}/`. The upload lands in a temporary folder, is validated against the bundle format (manifest fields, every frame file present, `frame_count * pixel_count * 3` bytes each), then renamed over the old folder. A bad bundle changes nothing. The manifest is the summary source; there is no separate index.
- Requests: a SQLite table. `POST /v1/requests` dedupes on `external.spotify_uri` (or any external id) and fires the `on_request` hook once per new row. Prism moves a request through `analyzing`, `published`, `rejected` with `PATCH`.
- Hubs: `_wled._tcp` mDNS merged with the configured list by MAC. For each light in a show the player resolves the hub by MAC and reads the output's start pixel and count from the hub's `/json/cfg`. An unreachable hub's lights are skipped and reported in status; the show plays on the rest.
- Play: read each target hub's `on` state, power hubs on, start audio, start the clock, send frames at the bundle rate until the last frame, then restore: stop sending, black out and power off hubs that were off, leave hubs that were on to WLED's realtime timeout. `stop` restores at once, and with nothing running it still tells the audio backend to stop (a show cut off by a process restart leaves the speaker streaming); on startup the player fires `on_stop` so a listener's show flag resets; `next` ends the current show and starts the next queued one. A queue is a list of show ids or `all` with optional shuffle. `query` plays the show whose title or artist best matches a spoken phrase (`match.py`: difflib ratio over the title and over artist plus title, plus a per-word pass; threshold 0.6) and answers 404 when nothing reaches it, so a caller never gets a silent no-op.
- Clock: the process monotonic clock is the time base. The audio backend reports when playback started and its current position. The clock is offset by `audio.offset_ms` and re-based only when the reported position disagrees by more than one frame for two consecutive polls (every 2 s), applied as a jump. Frames are scheduled from the clock, never from audio callbacks; a late frame is skipped, never queued.
- Audio backends behind one interface (`start(url)`, `position() -> float | None`, `stop()`): `ha` calls `media_player.play_media` with the URL of `/v1/shows/{id}/audio` and reads `media_position` and `media_position_updated_at`; `none` plays lights only. A `local` ALSA backend fits the same interface if a wired output is ever needed.
- Calibrate: `prism-player calibrate` finds the hubs, installs a generated click show under the id `calibrate-click` (a 1 kHz burst in the audio and a 3-frame white flash on every hub output once a second), plays it through the configured backend, and lets the user nudge the offset from the terminal until flash and click coincide; the show is deleted on exit and the value printed for the config.
- Hooks: `on_request`, `on_publish` (a show was stored or replaced), `on_play`, `on_stop` POST a JSON summary to configured URLs. Fire and forget; a failed hook never affects playback.

## Structure

```
src/prism_player/
  main.py        CLI: serve, calibrate
  config.py      YAML config model; the token comes from the env var the config names
  api.py         aiohttp routes: Companion API, play/stop/next/status, audio, healthz; bearer middleware
  store.py       show folders, bundle validation and atomic unpack, summaries
  requests.py    SQLite requests, dedupe on external id
  hubs.py        mDNS browse, config merge, WLED JSON (info, cfg, state, power)
  ddp.py         packet builder and UDP sender, byte-identical to Prism's ddp.ts
  engine.py      clock, frame scheduler, queue, restore-on-stop, hooks
  audio/         base.py interface, ha.py, none.py
  calibrate.py
tests/           pytest: DDP bytes against a fixture shared with Prism, bundle validation,
                 engine scheduling with a fake clock and fake hubs, ha backend against a fake HA
Dockerfile, example-config.yaml
```

Stack: Python 3.12 with uv, aiohttp (server, WLED and HA clients), zeroconf, PyYAML, SQLite. One process, one event loop, one show at a time.

## Build order

1. Store and Companion API (`/healthz`, `/v1/info`, `/v1/shows*`, auth). Testable with the bundle fixture from the Prism repo.
2. Requests and the `on_request` hook.
3. Lights only: hubs, DDP, engine with `none` audio, `/v1/play`, `/v1/stop`, `/v1/status`. First bench run on the real hub.
4. Audio through HA: `ha` backend, audio route with range support, position correction, `calibrate`. Second bench run: flashes on beats through the living room speaker.
5. Queue, `next`, `on_play` and `on_stop` hooks.
6. Dockerfile, tag `v0.1.0`. The deployment's compose entry lives in the home-brain repo.

Bench runs need the user's go; nothing sends to a real hub or a real HA otherwise.

## Risks

- `media_position` accuracy through Music Assistant and Sendspin is unmeasured. Jitter over a frame means widening the correction threshold; an offset that varies between sessions means building the `local` backend.
- 1444 pixels at 40 Hz is 8 DDP packets per frame. The Pi 5 is on Ethernet; drops on the hubs' 2.4 GHz side show as stutter, not desync.
- `play_media` through Music Assistant must accept a plain HTTP URL without headers. If not, route the audio through HA's media source proxy instead.
