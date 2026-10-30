# Architecture and invariants

## Boundaries

- `server/server.py`: TCP lifecycle, service composition and thin compatibility entry points. Account, relationship, message and request-dispatch behavior no longer resides here.
- `server/protocol/router.py`: request-to-service adapter with explicit typed dependencies.
- `server/services/accounts.py`, `friends.py`, `events.py`: account/session lifecycle, relationships and event delivery.
- `server/storage/messages.py`: direct-message persistence.
- `server/domain/passwords.py`: bounded password verification and upgrades to 600,000-round PBKDF2.
- `server/protocol/requests.py`: bounded request vocabulary, strict types and role/decision values.
- `server/server_transport`: verified TLS configuration, absolute framing deadline and bounded admission counters.
- `server/domain`: authoritative session/channel/private-call authorization, ordered presence and avatar validation.
- `server/services/channels.py`: channel creation, membership, roles, settings and presence. Explicit database/clock dependencies; no sockets or Qt.
- `server/services/calls.py`: transactional call transitions and durable notifications. SQLite is the sole active-call authority.
- `server/services/mutations.py`: nested units of work, authorization under the write lock and bounded idempotency receipts.
- `server/services/channel_cleanup.py`: persistent retry for channel history deletion across the separate account/message databases.
- `server/storage`: connection lifetime, migrations, events and scoped voice grants.
- `server/voice_server.py`: single-owner encrypted UDP relay, one reused SQLite connection, current authorization checked for every sender and recipient; no positive ACL cache.
- `shared/voice_protocol.py`: versioned authenticated datagrams.
- `client/transport`: verified control connections and encrypted voice connection establishment.
- `client/application`: asynchronous session/voice lifecycle, request generations, portable avatars, durable logout retry and platform setup.
- `client/audio/mixer.py`: bounded per-speaker reorder buffers, short loss concealment and saturating mixing.
- `client/application/call_controller.py`: session-scoped signaling, request cancellation, event cursor and call identity. Emits state/notice signals; owns no widgets or audio devices.
- `client/application/polling.py`: service/page polling policy with explicit timer and lifecycle bindings.
- `client/transport/framing.py`: bounded response parser with an absolute deadline.
- `client/ui`: rendering, navigation and view interaction. MainWindow delegates signaling/polling and uses one shared nonblocking cleanup path for logout and close.

## Identity and transactions

A bearer session owns a single login; request `login` fields cannot impersonate another user. Password changes require the current password and revoke other sessions and voice grants. Delayed close requests identify the call they intend to finish. Durable logout replay revokes its original token and cannot clear a new device's call while another session is valid.

Supported mutations obtain the users write lock before any chat write lock. Authorization is checked again under the lock. Nested helpers share the connection; only the outer scope commits. A successful mutation and its replay receipt commit in the same target database. Failed operations roll back. Receipts expire after 24 hours and are bounded to 1,000 per token. Same request ID with different content is rejected. The client reuses an ID within one network request; independent user actions receive different IDs.

Account and message databases are separate. There is no claim of an atomic transaction spanning both. Channel deletion persists a cleanup marker with membership deletion; message cleanup is idempotent and retried after deletion, at startup and every 30 seconds. Revoked membership stops message/voice access before physical history cleanup completes.

Migrations are ordered and versioned in `server/storage/migrations.py` (currently users v6, chat v8). Existing databases receive consistent SQLite backup snapshots (including WAL) before upgrade. Failed upgrades roll back; future/inconsistent versions stop startup. Backups contain sensitive data and are not automatically removed.

## Network and media

TCP requests have bounded size, field values and an absolute receive deadline. Admission counters are bounded and process-local; they reset on restart and are not distributed abuse protection. Remote control transport requires verified TLS. Plaintext is allowed only on loopback.

UDP v2 (`NV2`) uses independent directional AES-GCM keys, authenticated transport ID and 64-bit packet sequence, plus a 128-packet replay window. A persisted one-use grant claim prevents nonce reuse after relay restart. Audio carries a separate media sequence; forwarded audio also carries its originating transport ID. Heartbeats do not create gaps in the media sequence. Clients reject retired streams after key rotation. Update clients and server together: v1 audio is deliberately incompatible.

Voice is 16 kHz mono PCM, 20 ms / 640 bytes per frame. Playback starts with a two-frame prebuffer, keeps at most eight frames per speaker and 32 speakers, reorders arrivals, rejects duplicates/late frames and fades the previous frame for at most two missing frames. This is fixed jitter buffering and simple concealment, not an adaptive codec. Server-readable audio is encrypted in transit; this is not E2EE or an independently audited DTLS/SRTP implementation.

Network and audio lifecycle work runs outside Qt. Network requests remain retained until the worker exits and their queued completion has been processed; public callbacks are emitted from a GUI-thread slot and recheck cancellation before delivery. Request generations prevent old sessions/screens from applying stale results. Logout records a private local retry entry before sending; retries preserve the original endpoint/TLS configuration. Entries expire with the maximum session lifetime. Disk failure or forced termination before the queue write can still prevent durable delivery.

## Development and validation

Platform launchers (`Просмотр noda.cmd` on Windows, `Просмотр noda.command` on macOS) start the same persistent local noda preview (one window, sample conversations); `--smoke-seconds` uses disposable data for CI. Certificates are generated with the installed cryptography library; no external OpenSSL executable is required. Preview resources never belong in production packaging. Runtime dependencies are pinned. CI checks Windows, macOS and Linux, refuses skipped tests, runs the actual Windows launcher, TLS two-client process smoke, undefined-name analysis, Bandit medium/high severity checks and dependency auditing. See [audit-closeout.md](audit-closeout.md) for measured evidence and remaining external acceptance. Packaging is deferred.

## Security follow-through

Login password verification and token issuance share a write transaction, so a concurrent password reset cannot be followed by a token issued using the old password. Revocation storage failures propagate instead of returning success; the logout retry queue retains failed deliveries. Expired sessions also prune associated voice credentials and presence versions. Session-touch and compatibility-event caches are bounded.

Call accept/decline/end carry the call ID captured by the controller. Late callbacks are fenced by session and controller generation; a successful action invalidates in-flight older polls. Removing a friendship terminates its call as well as revoking media access.

UDP admission has bounded per-IP (4,000/s) and relay-wide (10,000/s) budgets before DB work, in addition to authenticated per-route limits. Shared NAT clients share the IP budget. These limits and cryptographic regression tests are not claims of DDoS immunity or third-party certification. See [security-review.md](security-review.md).
