# Player — Design

## Summary

prism-player is an always-on service that stores the shows Prism publishes, keeps the queue of songs Prism should analyze, and plays a show: audio through a Home Assistant media player, lights over DDP to WLED hubs, both from one clock. It implements Prism's Companion API so Prism connects to it like to any companion.

## How it works

Store: a show arrives as a bundle over `PUT /v1/shows/{id}` and is unpacked into its own folder. The manifest is validated against the bundle format before anything is written; a bad bundle is refused and the previous show stays. Shows are listed with their manifest summaries and can be downloaded again as a bundle or deleted.

Requests: `POST /v1/requests` adds a song to the queue with a title, an artist, and external ids. Prism reads the queue and moves a request through `analyzing`, `published`, `rejected`. A request whose external id already exists is answered with the existing request, so a sync source can post the same track repeatedly. The `on_request` hook fires once per new request.

Hubs: WLED hubs are found by mDNS (`_wled._tcp`) and merged with the configured list by MAC address. For every light in a show, the player resolves the hub by MAC, reads the output's start pixel and pixel count from the hub's LED config, and builds the DDP frame layout. A light whose hub is unreachable is skipped and reported in status; the show plays on the rest.

Play: `POST /v1/play` takes one show or a queue. For each show the player reads every target hub's power state, powers hubs on, starts the audio, starts the clock, and streams frames at the bundle's frame rate until the last frame. Then it stops sending, restores each hub (a hub that was off is blacked out and powered off; a hub that was on is left to its realtime timeout), and moves to the next queued show. `stop` does the same restore at once. `next` ends the current show and starts the next.

Clock: the player's monotonic clock is the show's time base. The audio backend reports when playback started and the current position; the clock is offset by a configured constant and re-based when the reported position disagrees with it by more than one frame for two consecutive polls. Frames are sent on a fixed-rate schedule from the clock, never from audio callbacks.

Calibration: `prism-player calibrate` plays a generated click show (a flash on every hub at a fixed interval with a click in the audio) and lets the user nudge the offset from the terminal until flash and click coincide. The result is printed for the config.

Hooks: `on_play` and `on_stop` POST the show summary to configured URLs at the start and end of a show, so a home system can flag show mode. Hooks are fire-and-forget; a failed hook never affects playback.

## Usage

- Prism connects with the URL and token, publishes shows, reads requests.
- A sync source (any script) posts requests.
- A home system calls `play`, `stop`, `next`, polls `status`, and receives hooks.
- `prism-player serve` runs the service; `prism-player calibrate` measures the audio offset.

## Scope

- In: Companion API; show store; requests with hooks; hub discovery and DDP streaming; restore-on-stop; `ha` audio backend with offset and position correction; `none` audio backend (lights only); play queue, stop, next, status; calibrate; container image.
- Out: any playlist or Spotify awareness (a sync source does that); a local audio output backend; multiple simultaneous shows; editing shows; authentication beyond one bearer token; TLS.

## Open questions

None.
