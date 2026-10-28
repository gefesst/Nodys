# Nodys

Python/PySide6 desktop voice chat. Development proceeds through stacked draft pull requests; `main` stays unchanged until review.

## Local preview

On macOS open `Просмотр Nodys.command`. The first run installs dependencies in `.venv`.
Two clients open: Alice (channel owner) and Bob (member), with an isolated temporary database and configuration. Preview uses loopback ports 15555/15556. Close both clients to stop the servers and remove preview data. Restart the launcher after each change to see current code.

Cross-platform: create a Python virtual environment, install `requirements.txt`, then run `python tools/preview.py`. Use `--clients 1` for one window.

## Checks

`python -m unittest discover -s tests -v`

`python -m compileall -q client server shared tools tests`

## Architecture direction

Keep Python for the desktop client and services. Extract transport, authentication, channel policy, repositories and migrations into independently tested modules. UI should consume application state through controllers rather than own transport and database rules. Preserve executable entry points throughout migration.

The current branch starts this migration; the comprehensive audit is not yet resolved. In particular, media storage, migration versioning, public-server hardening and hardware audio validation still require implementation. Do not expose the development servers to untrusted networks.

## Current changes

Voice packets revalidate the session and channel/private-call policy for both sender and recipients. Kick, logout, expiration, channel deletion and call termination therefore stop forwarding on the next authorization check. TCP and UDP share session and voice policy rules in `server/domain/authorization.py`.

`server/storage/database.py` owns transaction completion and connection closure. The existing TCP dispatcher remains in place while responsibilities are extracted incrementally. Per-packet authorization currently reads SQLite; large-room throughput still needs measurement and an invalidation-aware optimization before a public release.

The settings page has a whole-page scroll container. Channel list polling preserves create/join screens and no longer overwrites settings drafts. Session configuration preserves endpoints on login/logout and retains tokens on temporary resume failure.

Run `python tools/preview.py --smoke-seconds 8` for a bounded two-client process smoke. Actual microphone/speaker quality requires manual testing. The preview launcher uses temporary accounts and storage on loopback only.

## Second change set: channel state

Channel responses are scoped to the selected channel/session, empty chats render a hint, settings drafts survive delayed responses, and voice presence updates are ordered on the server. New channel/profile avatars are portable PNG thumbnails instead of local file paths. Existing path-based avatars must be selected and saved again to migrate them.

Manual preview: open the test channel in both windows; use Alice to edit the channel avatar/name, then check Bob. Switch channels while requests are pending and leave/rejoin voice to inspect the participant list. Audio hardware permissions and quality require a separate manual test.

## Third change set: calls, audio and TLS

Call events now have durable IDs and can be reread after a dropped response. Each poll also returns the current call state, so missed call-end notifications cannot leave a stale call window indefinitely. Repeated snapshots do not restart audio.

Audio playback mixes bounded queues for individual speakers with saturation instead of playing speakers sequentially. This is a basic PCM mixer, not a complete jitter/packet-loss solution.

Control connections use verified TLS for remote hosts (certificate chain and hostname, TLS 1.2 minimum). Set `NODYS_HOST`, `NODYS_PORT`, `NODYS_TLS_CERT` and `NODYS_TLS_KEY` on the TCP server. Client configuration accepts `api_tls` and optional `api_ca_file`; normal public certificates use system trust. Plaintext control is permitted only on loopback. The server defaults to `127.0.0.1` and limits concurrent client handlers to 64.

The third change set initially blocked remote voice. The fourth change set below replaces that restriction with authenticated encrypted UDP; old plaintext voice clients are no longer compatible.

For a manual TLS preview, open `Просмотр Nodys TLS.command` on macOS or run `python tools/preview.py --tls` (OpenSSL required). It generates a temporary localhost certificate trusted only by the two test clients. Test channels, messages and settings in Alice/Bob windows. Check accept/decline/end call behavior manually; microphone permission and real sound quality require your hardware. Closing both windows removes the temporary accounts and certificate.

For repeatable process checks: `python tools/preview.py --tls --smoke-seconds 10`. This confirms startup and process survival, not microphone quality.

## Fourth change set: encrypted voice

Voice now uses AES-256-GCM authenticated datagrams. Login tokens travel only through the control connection, never in UDP. Each connection gets independent keys for each direction, scoped to one channel or active private call. Duplicate, modified and plaintext packets are rejected. A newer authenticated packet can update the client's NAT address.

Keys expire after one hour; the client renews them before expiry and reconnects after eight seconds without a server acknowledgement. Renewing credentials revokes the old transport. A relay restart requires fresh keys, so encryption counters cannot repeat after restart. Leaving/logging out, membership changes and call termination retain server-side permission checks.

For deployment on a private test network, configure the existing TLS control endpoint and set `NODYS_VOICE_HOST` / `NODYS_VOICE_PORT` for the UDP relay. Configure matching `voice_host` / `voice_port` in each client. Both servers must use the same `NODYS_DB_FILE`. Default listeners remain loopback. No firewall rules or public exposure are changed by the launcher.

This is client-to-server transport encryption, **not end-to-end encryption**: the trusted relay decrypts and re-encrypts audio. Protect the server database and its backups, which hold short-lived transport keys. Internet deployment still needs operational hardening and capacity testing; there is no STUN/TURN or UDP-over-TCP fallback.

### Manual check after this update

1. Start `Просмотр Nodys TLS.command`; Alice and Bob open with isolated test accounts.
2. Join the test channel's voice section in both windows. Allow microphone access yourself if prompted. Check mute, deafen, leave and rejoin. Use headphones to prevent feedback.
3. Leave channel voice, call Bob from Alice, accept, then end the call; both windows should clear the call state.
4. Close both clients when done. Restart the launcher after further code changes.

Automated tests exercise actual TLS credential requests and encrypted UDP with synthetic PCM, packet tampering/replay, key renewal, UDP relay restart, revocation and audio-device startup failure. They do not validate real microphone/speaker quality or communication between two physical machines.
