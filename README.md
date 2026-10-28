# Nodys

Python/PySide6 desktop voice chat. Development branch: `refactor/nodys-foundation`.

## Local preview

On macOS open `Просмотр Nodys.command`. The first run installs dependencies in `.venv`.
Two clients open: Alice (channel owner) and Bob (member), with an isolated temporary database and configuration. Preview uses loopback ports 15555/15556. Close both clients to stop the servers and remove preview data. Restart the launcher after each change to see current code.

Cross-platform: create a Python virtual environment, install `requirements.txt`, then run `python tools/preview.py`. Use `--clients 1` for one window.

## Checks

`python -m unittest discover -s tests -v`

`python -m compileall -q client server tools tests`

## Architecture direction

Keep Python for the desktop client and services. Extract transport, authentication, channel policy, repositories and migrations into independently tested modules. UI should consume application state through controllers rather than own transport and database rules. Preserve executable entry points throughout migration.

The current branch starts this migration; the comprehensive audit is not yet resolved. In particular, secure transport, media storage, group audio mixing and migration versioning still require implementation. Do not expose the development servers to untrusted networks.

## Current changes

Voice packets revalidate the session and channel/private-call policy for both sender and recipients. Kick, logout, expiration, channel deletion and call termination therefore stop forwarding on the next authorization check. TCP and UDP share session and voice policy rules in `server/domain/authorization.py`.

`server/storage/database.py` owns transaction completion and connection closure. The existing TCP dispatcher remains in place while responsibilities are extracted incrementally. Per-packet authorization currently reads SQLite; large-room throughput still needs measurement and an invalidation-aware optimization before a public release.

The settings page has a whole-page scroll container. Channel list polling preserves create/join screens and no longer overwrites settings drafts. Session configuration preserves endpoints on login/logout and retains tokens on temporary resume failure.

Run `python tools/preview.py --smoke-seconds 8` for a bounded two-client process smoke. Actual microphone/speaker quality requires manual testing. The preview launcher uses temporary accounts and storage on loopback only.

## Second change set: channel state

Channel responses are scoped to the selected channel/session, empty chats render a hint, settings drafts survive delayed responses, and voice presence updates are ordered on the server. New channel/profile avatars are portable PNG thumbnails instead of local file paths. Existing path-based avatars must be selected and saved again to migrate them.

Manual preview: open the test channel in both windows; use Alice to edit the channel avatar/name, then check Bob. Switch channels while requests are pending and leave/rejoin voice to inspect the participant list. Audio hardware permissions and quality require a separate manual test.
