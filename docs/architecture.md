# Architecture migration

## Current boundaries

- `server/domain/authorization.py`: session expiry, channel voice permissions and active private-call policy, independent of sockets and UI.
- `server/storage/database.py`: explicit transaction and connection lifetime.
- `server/server.py`: existing TCP entry point, dispatch and remaining application/storage operations.
- `server/voice_server.py`: UDP packet adapter and in-memory routing. Authorizes every sender and recipient against current persisted state.
- `client/network.py`: asynchronous control requests.
- `client/ui`: existing views and controllers, to be separated incrementally.
- `tools/preview.py`: isolated development lifecycle; owns both server processes and two independent desktop clients.
- `tests`: synthetic fixtures only; authorization regressions and optional Qt UI tests. CI installs desktop requirements so UI tests execute.

## Rules

A bearer session belongs to one login. A remembered UDP endpoint alone never authorizes audio. Missing or malformed session/call/schema data denies access. No permissive legacy fallback is supported. Room identifiers are canonicalized before routing.

Database context managers commit or roll back and always close. Preview data lives outside the checkout and is removed when its process group terminates. Application startup must retain network preferences across authentication changes.

## Remaining stages

1. Replace per-packet connection churn with a measured read model and explicit cross-process revocation invalidation. Preserve denial after revocation and receiver checks.
2. Extract command handlers/services and repositories; introduce versioned migration fixtures and protocol schemas.
3. Separate client session/channel state from Qt widgets. Add request generations and serialized voice transitions.
4. Secure control/audio transport, media storage, acknowledged events and multi-speaker mixing.
5. Lock dependencies and package for target platforms, with hardware audio acceptance.

Do not present this first extraction as completion of the entire architecture migration. TCP and UDP encryption, real audio and network failure matrices remain release gates.

## Channel state and portable avatars (second change set)

`client/application/request_scope.py` assigns response tickets to the current screen, action and identity. Channel switches invalidate tickets; repeated reads accept only the newest response. The shared request adapter also rejects responses from a previous authentication session. Settings revisions prevent a pending refresh/save response from overwriting newer edits.

`server/domain/presence_order.py` persists the highest voice update sequence per session/channel in `voice_presence_versions`. Updates and presence writes share an immediate transaction. A late join cannot undo a leave, and a late leave cannot undo a newer join. The client reserves sequence ranges in its configuration so process restarts and wall-clock rollback do not reuse older command numbers. Independent devices should use distinct authentication sessions. Legacy unsequenced clients work only before sequenced updates for the same session/channel.

Avatars now travel as bounded 128-pixel PNG thumbnails in existing avatar fields. `client/application/avatars.py` prepares them; `server/domain/avatars.py` decodes, validates and re-encodes them with Pillow. No server file reads use the client-provided path. Legacy paths remain readable for compatibility but are not automatically migrated. Inline thumbnails avoid a breaking protocol/schema migration; separate content-addressed media storage and caching remain appropriate for larger deployments.
