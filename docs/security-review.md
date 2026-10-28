# Security review — development audit completion

This is the implementation agent's code review and reproducible regression evidence, not an independent cryptographic certification. No claim of public-production readiness follows from these checks.

## Trust boundaries and evidence

| Boundary / threat | Defense | Regression evidence |
|---|---|---|
| Claimed login differs from token owner | Identity derived from persisted session; ACL checked under mutation lock | `test_audit_permissions.py` |
| Password reset races login | Password verification + session issuance share users write transaction | Account/router code; password/legacy/revocation tests |
| Logout write fails or server unavailable | Server propagates failure; client retains private durable revocation entry | `test_audit_permissions.py`, `test_session_cleanup.py` |
| Untrusted control request | Framed size/deadline, strict types/enums/fields, auth admission | `test_request_security.py` |
| Untrusted/slow response | Object-only decoding, length bounds and total deadline | `test_response_framing.py` |
| Public listener without encryption / forged TLS peer | TLS required off-loopback, chain and hostname validation | `test_tls.py` |
| UDP replay/tampering/reflection | AEAD header binding, directional keys, 128-packet replay window | `test_voice_crypto.py`, including every-byte corruption and concurrent counters |
| Restart reuses nonce with same key | Persisted one-use grant claim; obtain fresh keys on restart | `test_voice_authorization.py`, `test_voice_network.py` |
| Unauthorized receiver, stale membership, expired grant | Authoritative checks on every sender/recipient; no positive ACL cache | `test_voice_authorization.py` |
| UDP flood consumes DB work | Bounded global/IP budgets before DB; per-authenticated-route budget | Admission regression + existing limiter tests |
| Retried mutations duplicate records | Payload-bound receipts, same-DB atomic commit/rollback, bounded retention | `test_audit_permissions.py` |
| Channel deleted but history cleanup fails | Persistent cross-DB cleanup marker and idempotent retry | `test_audit_permissions.py` |
| Old session/call callbacks affect new state | Controller generation/token checks and captured call ID | `test_call_controller.py`, `test_audit_permissions.py` |
| Memory growth / huge audio backlog | Bounded admission maps, touch/event caches, speaker/frame buffers | Limiter/mixer tests and explicit cache bounds |

SQL uses bound parameters for user data. The fixed migration heartbeat columns now use literal statements rather than generated SQL. DB files/backups and generated private keys receive owner-only POSIX permissions; on Windows the user-profile/checkout account ACL remains the operating-system boundary. Certificate generation is internal to the preview tooling and never installs a trust anchor in the OS store.

Passwords are PBKDF2-SHA256 with random salts and 600,000 iterations for new/updated records. Verification bounds stored work factors and hash lengths. Successfully authenticated older records upgrade with compare-and-swap; malformed records fail closed. Runtime dependencies are pinned separately from development analysis tools.

## Reproducible checks

```
python tools/check.py
python -m compileall -q client server shared tools tests
python -m pip check
python -m ruff check client server shared tools --select F821,F822,F823
python -m bandit -r client server shared -ll
python -m pip_audit -r requirements.txt --no-deps --disable-pip
python tools/preview.py --tls --smoke-seconds 8
```

Install `requirements-checks.txt` for the last three analysis tools. CI runs equivalent checks. Bandit low-severity style heuristics are not used as a security-completeness claim; medium/high findings must pass.

## Release boundaries, not hidden implementation TODOs

The relay can decrypt audio: this is transport encryption, not E2EE. A malicious endpoint or compromised host is outside the protection provided by a bearer session. Application-level rate limits do not absorb a volumetric DDoS attack. TLS certificate provisioning, backups/access controls and network perimeter policy belong to deployment. Keys may exist in database backups. Long-running load, real microphones, external networks and an independent assessment of the custom media protocol remain release acceptance work. No packaging or public deployment was authorized for this stage.
