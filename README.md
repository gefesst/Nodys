# noda

Python/PySide6 desktop voice chat. The noda interface is implemented in `feat/nodus-approved-design` for review. The ordinary entry point remains `client/main.py`; application packaging remains deferred.

## Local preview

On Windows install Python 3.13 (with the Python launcher) and open `Просмотр noda.cmd`. On macOS open `Просмотр noda.command`. Both enable TLS automatically and install pinned dependencies in `.venv`. Temporary certificates are generated without an external OpenSSL installation.
One client opens with six sample conversations. This manual preview keeps its own local database and preferences between restarts, including profile avatars. Data lives in `noda/preview` under the OS local application-data directory and stays separate from production and disposable automated tests. TLS uses a local certificate and dynamically allocated loopback ports.

Cross-platform: create a Python virtual environment, install `requirements.txt`, then run `python tools/live_preview.py`. For a disposable two-client test use `python tools/preview.py --tls`.

## Checks

`python tools/check.py` (fails on skipped tests as well as failures)

`python -m compileall -q client server shared tools tests`

## Audit and architecture

The code remediation and measured checks are recorded in [the audit report](docs/audit-closeout.md). See [architecture](docs/architecture.md) for module boundaries, transactions and security invariants. Hardware, external-network and long-running acceptance remain explicit release gates; packaging is deferred.

Runtime dependencies are pinned in `requirements.txt`. Run `python -m pip check` after installation. Windows is the primary desktop target; CI validates Windows, macOS and Linux, including the Windows launcher and two-client TLS process startup. This design implementation remains on its separate review branch; it is not automatically merged into `main`.

The current voice protocol is NV2: update clients and server together. Voice is encrypted in transit and is not end-to-end encrypted. Remote control connections require verified TLS. Preview uses isolated temporary credentials and certificates; never package preview helpers as the application entry point.

For a bounded process smoke: `python tools/preview.py --tls --smoke-seconds 8`.
For a synthetic relay capacity probe: `python tools/benchmark_voice.py --peers 8`.

The “Компактно” display mode has been removed. Normal window resizing remains supported.

## Integrated design review

See [implementation and verification](docs/design-implementation.md). The production UI uses `client/ui/design/` and `client/styles/nodus.qss`. Test fixtures are confined to `tools/review_support/`.

Run `python tools/ui_review.py --synthetic-voice --output work/ui-review` for an isolated real-server review. This command **always uses offscreen Qt**, does not open desktop windows, and never opens a microphone. Screens and a short GIF are written to the chosen directory.

For normal manual use, run `python client/main.py` with your existing configuration, or use the preview launcher above when you intentionally want two test windows. After updating, install `requirements.txt` again; macOS includes the Cocoa bridge for the optional native backdrop.
