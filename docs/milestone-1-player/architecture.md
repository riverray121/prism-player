# Player — Architecture

## Stack

- Python 3.12 with uv. The Pi 5 already runs Python services (framed, printd); no new toolchain.
- aiohttp for the HTTP server, the WLED JSON calls, and the Home Assistant REST calls. One event loop runs the API and the frame scheduler.
- zeroconf for `_wled._tcp` browsing.
- SQLite (stdlib) for requests; shows are folders on disk with the manifest as the index.
- pytest, ruff, mypy.

## Key decisions

- One process, one event loop, one show at a time. The frame scheduler is an asyncio task that sleeps until the next frame deadline computed from the monotonic clock, sends every hub's packets for that frame, and repeats. A late frame is skipped, never queued, so lights cannot drift behind audio.
- DDP packets match Prism's sender: header per the DDP spec, frames over 480 pixels split across packets with the push flag on the last, one UDP socket. Same bytes on the wire as the live streamer, so a published show looks like the live one.
- The audio backend is an interface with two methods: `start(url) -> None` and `position() -> float | None`, plus `stop()`. `ha` implements it with `media_player.play_media` and the entity's `media_position` and `media_position_updated_at`. `none` starts nothing and reports no position. A `local` backend (ALSA) fits the same interface if it is ever needed.
- Position correction is conservative: the clock re-bases only after two consecutive polls disagree by more than one frame, and a re-base is applied as a jump, not a rate change. Audio through a network media player has a stable offset with occasional jumps; smoothing would hide the jumps and drift instead.
- Hub state restore reads `/json/state` `on` before the first frame and writes power back only for hubs that were off. Hubs that were on rely on WLED's realtime timeout to return to their own look; the player never writes a preset or segment state.
- The store is the filesystem: `data/shows/{id}/` holds the unpacked bundle; the manifest is the summary source. A `PUT` unpacks to a temporary folder, validates, and renames over the old folder, so a replace is atomic and a bad upload changes nothing.
- The token is read from an environment variable named in the config, never from the config value itself, so a config file can be committed.

## Structure

```
src/prism_player/
  main.py        CLI: serve, calibrate
  config.py      YAML config model and validation
  api.py         aiohttp routes: Companion API, play/stop/next/status, audio, healthz
  store.py       show folders, bundle validation and unpack, summaries
  requests.py    SQLite requests table, dedupe on external id
  hubs.py        mDNS browse, config merge, WLED JSON (info, cfg, state, power)
  ddp.py         packet builder and UDP sender
  engine.py      clock, frame scheduler, queue, restore-on-stop, hooks
  audio/
    base.py      backend interface
    ha.py        Home Assistant media player backend
    none.py      lights-only backend
  calibrate.py   click show generation and the interactive offset loop
tests/           pytest; DDP bytes, bundle validation, engine scheduling with a fake clock and fake hubs, ha backend against a fake HA
Dockerfile
example-config.yaml
```

## Breakouts

- Companion API and bundle format: the Prism repo, `docs/companion-api.md`.

## Risks / unknowns

- `media_position` accuracy from Music Assistant through Sendspin is unmeasured. If the reported position jitters by more than a frame between polls, the correction threshold must widen, and if the true offset varies between sessions the `local` backend becomes necessary.
- WiFi to the hubs at 40 frames per second with 1444 pixels is 8 DDP packets per frame. Prism holds this from the Mac; the Pi 5 on Ethernet has more headroom, but a congested 2.4 GHz band can still drop packets. Dropped frames are visible as a stutter, not a desync.
- Home Assistant's `play_media` with a URL through Music Assistant must accept an unauthenticated plain HTTP URL. If it refuses, the audio route falls back to HA's own media source proxy.
