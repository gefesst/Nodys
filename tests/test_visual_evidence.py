"""A comparison must never silently select screenshots from an older run."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.ui_catalog_review import find_capture


class VisualEvidenceTests(unittest.TestCase):
    def test_stale_file_and_failed_run_do_not_override_verified_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            stale,failed,current=[root/name for name in ('stale','failed','current')]
            for path,report in [(stale,dict(screens=['other'],error=None)),
                                (failed,dict(screens=['screen'],error='failed')),
                                (current,dict(screens=['screen'],error=None))]:
                (path/'sizes').mkdir(parents=True)
                (path/'sizes/screen-1440.png').touch()
                (path/'review.json').write_text(json.dumps(report))
            self.assertEqual(find_capture('screen',[stale,failed,current]),current/'sizes/screen-1440.png')
            self.assertIsNone(find_capture('screen',[stale,failed]))
