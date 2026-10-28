"""Deterministic UI checks; optional when desktop dependencies are unavailable."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'client'))

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Install desktop requirements for UI tests')
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, NODYS_CONFIG_DIR=self.folder.name)
        self.env.start(); self.addCleanup(self.env.stop)
        self.network = patch('network.NetworkThread.start')
        self.network.start(); self.addCleanup(self.network.stop)
        from user_context import UserContext
        UserContext().set_user(login='alice', nickname='Alice', avatar='',session_token='synthetic')
        from ui.channels_page import ChannelsPage
        self.page = ChannelsPage()
        self.addCleanup(self.page.close)

    def test_forms_survive_empty_poll(self):
        p = self.page
        p.start_request = lambda data, callback, **kw: callback({'status':'ok','channels':[]})
        for form, open_form in ((p.create_page,p.open_create_page),(p.join_page,p.open_join_page)):
            open_form(); p.load_channels(force_refresh=True)
            self.assertIs(p.main_stack.currentWidget(),form)

    def test_settings_are_scrollable(self):
        from PySide6.QtWidgets import QScrollArea
        node = self.page.settings_name_input
        while node is not None and not isinstance(node,QScrollArea):
            node = node.parentWidget()
        self.assertIsNotNone(node)

    def test_registration_error_inline(self):
        from register_window import RegisterWindow
        window = RegisterWindow()
        self.addCleanup(window.close)
        with patch('register_window.QMessageBox.warning') as modal:
            window.handle_register_response({'status':'error','message':'Логин уже существует'})
            modal.assert_not_called()
        self.assertEqual(window.status_label.text(),'Логин уже существует')
