"""Headless resize comparison of the prior prototype and bounded production view."""

import argparse
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from application.qt_runtime import prepare_platform_plugins

prepare_platform_plugins()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ui.design import widgets, models


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    results = []
    old_widgets = load("prior_widgets", args.prototype / "widgets.py")
    old_models = load("prior_models", args.prototype / "models.py")
    for name, component, data, count in [
        ("prior_full_history", old_widgets, old_models, 10000),
        ("bounded_production", widgets, models, 240),
    ]:
        view = component.MessageList()
        model = data.MessageModel(view)
        view.setModel(model)
        view.setItemDelegate(component.MessageDelegate(view, "alice"))
        rows = [
            data.Message(
                i,
                "bob",
                "Bob",
                ("Сообщение " + str(i) + " — одинаковый текст для сравнения. ")
                * (1 + i % 8),
            )
            for i in range(10000 - count, 10000)
        ]
        model.replace(rows)
        view.resize(900, 700)
        view.show()
        app.processEvents()
        view.doItemsLayout()
        gaps = []
        previous = [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            gaps.append((now - previous[0]) * 1000)
            previous[0] = now

        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(tick)
        heartbeat.start()
        sizes = iter([600, 1000, 780] * 3)
        resize = QTimer()
        resize.setInterval(900)

        def step():
            width = next(sizes, None)
            if width is None:
                resize.stop()
                heartbeat.stop()
                app.quit()
            else:
                view.resize(width, 700)

        resize.timeout.connect(step)
        resize.start()
        app.exec()
        ordered = sorted(gaps)
        results.append(
            dict(
                case=name,
                database_rows=10000,
                loaded_rows=count,
                timer_interval_ms=10,
                timer_gap_p95_ms=ordered[int(0.95 * (len(ordered) - 1))],
                timer_gap_max_ms=max(gaps),
                samples=len(gaps),
            )
        )
        view.close()
    args.output.write_text(
        json.dumps(
            dict(platform=platform.platform(), rendering="offscreen", results=results),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
