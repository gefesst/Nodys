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

Do not present this first extraction as completion of the entire architecture migration. Real audio, external network failure matrices and public-server hardening remain release gates.

## Channel state and portable avatars (second change set)

`client/application/request_scope.py` assigns response tickets to the current screen, action and identity. Channel switches invalidate tickets; repeated reads accept only the newest response. The shared request adapter also rejects responses from a previous authentication session. Settings revisions prevent a pending refresh/save response from overwriting newer edits.

`server/domain/presence_order.py` persists the highest voice update sequence per session/channel in `voice_presence_versions`. Updates and presence writes share an immediate transaction. A late join cannot undo a leave, and a late leave cannot undo a newer join. The client reserves sequence ranges in its configuration so process restarts and wall-clock rollback do not reuse older command numbers. Independent devices should use distinct authentication sessions. Legacy unsequenced clients work only before sequenced updates for the same session/channel.

Avatars now travel as bounded 128-pixel PNG thumbnails in existing avatar fields. `client/application/avatars.py` prepares them; `server/domain/avatars.py` decodes, validates and re-encodes them with Pillow. No server file reads use the client-provided path. Legacy paths remain readable for compatibility but are not automatically migrated. Inline thumbnails avoid a breaking protocol/schema migration; separate content-addressed media storage and caching remain appropriate for larger deployments.

## Call delivery, audio and control transport (third change set)

- `server/storage/events.py`: non-destructive event reads by cursor; retention is 180 seconds and 200 events per user. Legacy clients still use the old destructive queue. A current call snapshot repairs state even when events have expired. Events and call changes are not yet a transactional outbox.
- `client/ui/main_window.py`: reconciles snapshots by session, call ID, peer and status; rejects responses from a previous session. Extracting this controller from the widget remains follow-up work.
- `client/audio/mixer.py`: bounded PCM queues per speaker, summed in int32 and clipped to int16. Network sequencing, adaptive jitter control and codec work remain open.
- `client/transport/control.py`: shared verified TLS connection factory for asynchronous requests and shutdown/resume requests.
- `server/server_transport/tls.py`: server certificate configuration and loopback-only plaintext policy. TLS handshake timeout and a bounded worker count constrain resource use.
- `client/application/qt_runtime.py`: macOS platform-plugin visibility preparation before Qt startup; resolves hidden plugin flags observed in the local development environment.

The third-stage remote-voice block is superseded by the authenticated datagram transport below.

## Encrypted voice (fourth change set)

- `shared/voice_protocol.py` owns the versioned binary envelope and AES-GCM primitive via PyCA cryptography. Header: `NV1`, 16-byte transport ID, 64-bit sequence. Header is authenticated; nonce is four zero bytes plus sequence. Directional 256-bit keys are independently random. Replay window is 128 packets and advances only after authentication. Maximum datagram is 1200 bytes; PCM is exactly 640 bytes (16 kHz, mono, 20 ms, signed 16-bit little endian).
- `server/storage/voice_tickets.py` issues channel/call-scoped one-hour grants after session and ACL checks. One grant per login session. A persistent one-use claim prevents reuse of server send keys after relay restart or in-memory eviction. Fresh credentials are mandatory, even when the old grant has not expired. Login tokens are never part of the UDP envelope.
- `server/voice_server.py` is now a single-loop encrypted relay instead of a global mutable legacy protocol dispatcher. It accepts only authenticated join, heartbeat, leave and audio messages. Source address changes require a newer authenticated sequence. It bounds live routes to 1024, evicts inactive routes, limits each route to 100 messages/second and checks authoritative sender/receiver permissions for every forwarded audio packet.
- `client/transport/voice.py` requests scoped keys through verified control transport, validates the encrypted join acknowledgement and owns the UDP socket. `client/voice_client.py` owns audio devices and the reconnect worker. Audio callbacks queue bounded outgoing frames; encryption and socket I/O happen in the network worker. Failure to start an audio device closes partial streams and the transport.

Cryptographic API reference: https://cryptography.io/en/stable/hazmat/primitives/aead/ . Never reconstruct a cipher with previously used send keys; the persistent claim and client credential renewal are required invariants. This is a Nodys-specific encrypted transport using a standard AEAD primitive, not DTLS, SRTP or an independently audited protocol. It is not E2EE.

Known limits: SQLite reads per sender/recipient remain a scalability cost; packet sequencing prevents replay but the playback buffer does not yet reorder audio or implement loss concealment. Client reconnection is automatic, but initial connection still runs in the existing UI voice-start path and can wait for the network timeout. Transport keys are stored in the protected server DB and may survive in backups. Public admission throttling, migration versioning, load tests and hardware/network acceptance remain follow-up work.
