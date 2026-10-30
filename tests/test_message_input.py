import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from PySide6.QtCore import Qt, QMimeData, QUrl, QPoint, QPointF
from PySide6.QtGui import QImage, QColor, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from ui.design.conversation import Conversation
from ui.design.message_links import link_spans


class MessageInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from application.qt_runtime import prepare_platform_plugins
        prepare_platform_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.owner.ctx = SimpleNamespace(login='alice', nickname='Alice', session_token='')
        self.requests = []
        self.owner.start_request = lambda data, callback: self.requests.append((data, callback))
        self.chat = Conversation(self.owner)
        self.owner.resize(1120, 620)
        self.chat.resize(850, 600)
        self.owner.show()
        self.chat.show()
        self.chat.select('bob', 'Bob')
        self.requests[-1][1](dict(status='ok', messages=[], has_older=False, has_newer=False))
        self.app.processEvents()
        self.addCleanup(self.owner.close)
        self.addCleanup(self.chat.reset)

    def image_mime(self):
        mime = QMimeData()
        image = QImage(100, 60, QImage.Format_RGB32)
        image.fill(QColor('#89AAFF'))
        mime.setImageData(image)
        return mime

    def test_native_paste_shortcut_selects_image_without_sending(self):
        self.chat.editor.setPlainText('подпись')
        self.app.clipboard().setMimeData(self.image_mime())
        self.chat.editor.setFocus()
        count = len(self.requests)
        shortcut = QKeySequence.keyBindings(QKeySequence.Paste)[0][0]
        QTest.keyClick(self.chat.editor, shortcut.key(), shortcut.keyboardModifiers())
        self.app.processEvents()
        draft = self.chat.attachment_drafts['bob']
        path = Path(draft['path'])
        self.assertTrue(path.is_file())
        self.assertEqual(self.chat.editor.toPlainText(), 'подпись')
        self.assertEqual(len(self.requests), count)
        self.chat.remove_attachment()
        self.assertFalse(path.exists())
        self.app.clipboard().clear()

    def test_plain_text_and_web_url_still_paste_as_text(self):
        mime = QMimeData()
        mime.setText('https://example.com/ hello')
        self.chat.editor.insertFromMimeData(mime)
        self.assertEqual(self.chat.editor.toPlainText(), mime.text())
        self.assertFalse(self.chat.attachment_drafts)

    def test_file_drop_on_history_and_editor_selects_file_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'file.txt'
            file.write_text('test')
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(file))])
            for target in (self.chat.view.viewport(), self.chat.editor.viewport()):
                before = len(self.requests)
                enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(target, enter)
                self.assertTrue(enter.isAccepted())
                drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(target, drop)
                self.assertTrue(drop.isAccepted())
                self.assertEqual(self.chat.attachment_drafts['bob']['path'], str(file))
                self.assertEqual(len(self.requests), before)
                self.chat.remove_attachment()
                self.assertTrue(file.exists())

    def test_multiple_files_and_permission_do_not_replace_current_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder)/'a', Path(folder)/'b'
            a.write_bytes(b'a'); b.write_bytes(b'b')
            self.chat.attach_file(str(a))
            mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(a)), QUrl.fromLocalFile(str(b))])
            self.chat.accept_attachment_input(mime)
            self.assertEqual(self.chat.attachment_drafts['bob']['path'], str(a))
            self.chat.can_send = False
            self.chat.accept_attachment_input(self.image_mime())
            self.assertEqual(self.chat.attachment_drafts['bob']['path'], str(a))

    def test_web_links_hit_test_wrapped_unicode_and_do_not_trigger_attachment(self):
        text = '😀 Привет https://example.com/path?q=test.\nwww.example.org/test'
        spans = list(link_spans(text))
        self.assertEqual([url.toString() for _, _, url in spans], ['https://example.com/path?q=test', 'https://www.example.org/test'])
        self.assertFalse(list(link_spans('file:///tmp/a javascript:alert(1) mailto:a@b')))
        self.chat.rows = [dict(id=1, from_user='bob', text=text, created_at='2026-10-30 12:00:00')]
        self.chat.apply(list(self.chat.rows), "latest", {})
        self.app.processEvents()
        index = self.chat.model.index(0)
        message = index.data(Qt.UserRole)
        rect = self.chat.view.visualRect(index)
        hit = None
        for y in range(rect.height()):
            for x in range(74, min(700, rect.width()), 3):
                url = self.chat.delegate.link_at(message, self.chat.view.viewport().width(), QPointF(x, y))
                if url is not None:
                    hit = QPoint(x, y) + rect.topLeft()
                    break
            if hit is not None:
                break
        self.assertIsNotNone(hit)
        with patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=True) as opened, patch.object(self.chat, 'download_metadata') as download:
            QTest.mouseClick(self.chat.view.viewport(), Qt.LeftButton, Qt.NoModifier, hit)
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(opened.call_args[0][0].scheme(), 'https')
            download.assert_not_called()
