# prism-player

Plays light shows made in [Prism](https://github.com/riverray121/prism). Prism analyzes a song and maps it onto addressable lights; prism-player is the always-on side. It stores the shows Prism publishes, plays a show's audio through a Home Assistant media player, and streams the light frames to WLED hubs in sync. It also keeps a queue of songs that should get a show, which Prism reads.

## How it works

```
Prism (Mac)  --PUT bundle-->  store  --play-->  clock  --DDP-->  WLED hubs
                                                  |
                                                  +--play_media(url)-->  Home Assistant  -->  speaker
```

- A show bundle is a zip: the audio file, one frame file per light (RGB bytes at 40 frames per second), and the Prism project files so the show can be edited again. The format is Prism's `docs/companion-api.md`.
- One clock drives a show. The audio starts through Home Assistant's `media_player.play_media` with a URL the player serves; the light clock starts when the media player reports playing, shifted by a measured offset, and re-bases itself against the reported position. Frames go to each hub over DDP.
- Hubs are found by mDNS or listed in config. Before the first frame the player reads each hub's power state and restores it when the show ends, so whatever the hub was showing before comes back.
- Requests are the queue: anything can POST a song to `/v1/requests`; Prism lists them, and marks them analyzing, published, or rejected.

## API

The Companion API (`/v1/info`, `/v1/requests`, `/v1/shows`) as defined by Prism, plus:

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/play` | `{query}` (fuzzy title or artist match, 404 when nothing matches), `{show}`, `{queue: [show, ...]}`, or `{queue: "all", shuffle: bool}` |
| POST | `/v1/stop` | Stop, restore hubs |
| POST | `/v1/next` | Skip to the next queued show |
| GET | `/v1/status` | `{state, show, position_s, queue}` |
| GET | `/v1/shows/{id}/audio` | The show's audio file, for the media player |
| GET | `/healthz` | Liveness |

Every `/v1` call needs `Authorization: Bearer <token>`. `/healthz` and `/v1/shows/{id}/audio` do not (the media player fetches audio without headers; the path is unguessable only by show id, so keep the port off the public internet).

## Config

```yaml
listen: 0.0.0.0:8760
token_env: PLAYER_TOKEN
data_dir: /data
hubs:                          # optional; mDNS finds hubs that are not listed
  - mac: 1cc3abbbc85c
    address: 192.168.8.40
audio:
  backend: ha                  # ha | none
  ha_url: http://127.0.0.1:8123
  ha_token_env: HA_TOKEN
  media_player: media_player.living_room_speaker
  audio_url_base: http://192.168.8.2:8760   # what the media player fetches from
  offset_ms: 0                 # from `prism-player calibrate`
hooks:                         # optional webhooks, POSTed with a JSON body
  on_request: http://127.0.0.1:8123/api/webhook/prism_request
  on_publish: http://127.0.0.1:8123/api/webhook/prism_published   # one POST per batch: {count, shows, pending}
  on_play: http://127.0.0.1:8123/api/webhook/prism_play
  on_stop: http://127.0.0.1:8123/api/webhook/prism_stop
```

## Run

```sh
uv sync
PLAYER_TOKEN=... HA_TOKEN=... uv run prism-player serve --config config.yaml
uv run prism-player calibrate --config config.yaml   # measure audio.offset_ms
```

Docker: `docker build -t prism-player .`, then run with `--network host`, the config mounted at `/config/config.yaml`, a volume at `/data`, and `PLAYER_TOKEN` and `HA_TOKEN` in the environment. The image's healthcheck polls `/healthz` on `PLAYER_PORT` (default 8760); set it to match `listen` when that differs.

`calibrate` needs a terminal: it finds the hubs, installs a 30 s click show, plays it through the configured backend, and reads keys (`+`/`-` nudge the offset by 10 ms, `]`/`[` by 1 ms, `r` restarts, `q` quits and prints the `audio.offset_ms` line for the config).

## License

MIT
