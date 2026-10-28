#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -q -r requirements.txt || exit 1
# Qt ignores plugin files marked hidden on macOS.
chflags -R nohidden .venv/lib/python*/site-packages/PySide6/Qt/plugins || exit 1
.venv/bin/python tools/preview.py --tls "$@"
