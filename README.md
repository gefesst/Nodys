# Nodys

Python/PySide6 desktop voice chat. Development proceeds through stacked draft pull requests; `main` stays unchanged until review.

## Local preview

On macOS open `Просмотр Nodys.command`. The first run installs dependencies in `.venv`.
Two clients open: Alice (channel owner) and Bob (member), with an isolated temporary database and configuration. Preview uses loopback ports 15555/15556. Close both clients to stop the servers and remove preview data. Restart the launcher after each change to see current code.

Cross-platform: create a Python virtual environment, install `requirements.txt`, then run `python tools/preview.py`. Use `--clients 1` for one window.

## Checks

`python -m unittest discover -s tests -v`

`python -m compileall -q client server tools tests`

## Architecture direction

Keep Python for the desktop client and services. Extract transport, authentication, channel policy, repositories and migrations into independently tested modules. UI should consume application state through controllers rather than own transport and database rules. Preserve executable entry points throughout migration.

The current branch starts this migration; the comprehensive audit is not yet resolved. In particular, encrypted remote audio, media storage, migration versioning and hardware audio validation still require implementation. Do not expose the development servers to untrusted networks.

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

**Remote voice is intentionally unavailable until encrypted UDP is implemented.** Both the voice client and server reject non-loopback hosts so session tokens cannot be transmitted in plaintext over the network. TLS protects control traffic only; this branch is not a remote voice release.

For a manual TLS preview, open `Просмотр Nodys TLS.command` on macOS or run `python tools/preview.py --tls` (OpenSSL required). It generates a temporary localhost certificate trusted only by the two test clients. Test channels, messages and settings in Alice/Bob windows. Check accept/decline/end call behavior manually; microphone permission and real sound quality require your hardware. Closing both windows removes the temporary accounts and certificate.

For repeatable process checks: `python tools/preview.py --tls --smoke-seconds 10`. This confirms startup and process survival, not microphone quality.
