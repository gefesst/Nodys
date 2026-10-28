# Nodys

Python/PySide6 desktop voice chat. Current audited development changes are published to `main`. Further checked fixes are pushed to GitHub as development continues; application packaging remains deferred.

## Local preview

On macOS open `Просмотр Nodys.command`. It enables TLS automatically. The first run installs dependencies in `.venv`; OpenSSL is required for the temporary test certificate.
Two clients open: Alice (channel owner) and Bob (member), with an isolated temporary database and configuration. Preview uses loopback ports 15555/15556. Close both clients to stop the servers and remove preview data. Restart the launcher after each change to see current code.

Cross-platform: create a Python virtual environment, install `requirements.txt`, then run `python tools/preview.py --tls`. Use `--clients 1` for one window.

## Checks

`python -m unittest discover -s tests -v`

`python -m compileall -q client server shared tools tests`

## Audit and architecture

The code remediation and measured checks are recorded in [the audit report](docs/audit-closeout.md). See [architecture](docs/architecture.md) for module boundaries, transactions and security invariants. Hardware, external-network and long-running acceptance remain explicit release gates; packaging is deferred.

Runtime dependencies are pinned in `requirements.txt`. Run `python -m pip check` after installation. CI validates Windows, Linux and macOS. Development changes are published directly to `main` after local checks, as requested.

The current voice protocol is NV2: update clients and server together. Voice is encrypted in transit and is not end-to-end encrypted. Remote control connections require verified TLS. Preview uses isolated temporary credentials and certificates; never package preview helpers as the application entry point.

For a bounded process smoke: `python tools/preview.py --tls --smoke-seconds 8`.
For a synthetic relay capacity probe: `python tools/benchmark_voice.py --peers 8`.

The “Компактно” display mode has been removed. Normal window resizing remains supported.
