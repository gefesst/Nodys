"""Regression checks for the integrated theme and bounded audio counters."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))


class AudioDiagnosticsTests(unittest.TestCase):
    def test_status_flags_and_callback_counters(self):
        from audio.diagnostics import AudioDiagnostics

        diagnostics = AudioDiagnostics()
        for kind, status in [
            ("capture", SimpleNamespace(input_overflow=True)),
            ("playback", SimpleNamespace(output_underflow=True)),
        ]:
            started = diagnostics.begin(kind, status)
            diagnostics.end(kind, started)
        snapshot = diagnostics.snapshot()
        self.assertEqual(snapshot["input_overflows"], 1)
        self.assertEqual(snapshot["output_underflows"], 1)
        self.assertEqual(snapshot["capture_callbacks"], 1)
        self.assertEqual(snapshot["playback_callbacks"], 1)
        self.assertNotIn("audio", snapshot)
        snapshot["input_overflows"] = 99
        self.assertEqual(diagnostics.snapshot()["input_overflows"], 1)


class DesignGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from application.qt_runtime import prepare_platform_plugins

        prepare_platform_plugins()
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_tooltips_blocked_for_dynamic_widgets_without_losing_accessibility(self):
        from ui.design.motion import TooltipBlocker
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QPushButton
        button=QPushButton();button.setToolTip('Подсказка');button.setAccessibleName('Микрофон')
        blocker=TooltipBlocker()
        self.assertTrue(blocker.eventFilter(button,QEvent(QEvent.ToolTip)))
        self.assertFalse(blocker.eventFilter(button,QEvent(QEvent.Enter)))
        self.assertEqual(button.accessibleName(),'Микрофон')

    def test_composer_expands_and_returns_to_single_line_height(self):
        from ui.design.widgets import Composer
        editor=Composer();editor.resize(400,44);editor.show();self.addCleanup(editor.close)
        self.app.processEvents();self.assertEqual(editor.height(),44)
        editor.setPlainText('Первая строка\nВторая строка\nТретья строка')
        self.app.processEvents();self.assertGreater(editor.height(),44)
        self.assertLessEqual(editor.height(),130)
        editor.clear();self.app.processEvents();self.assertEqual(editor.height(),44)

    def test_dialogs_stay_compact_and_five_fit_at_available_heights(self):
        from ui.design.widgets import DialogDelegate
        from ui.design.models import DialogModel
        from PySide6.QtWidgets import QListView
        view=QListView();self.addCleanup(view.close)
        model=DialogModel(view);view.setModel(model);view.setItemDelegate(DialogDelegate(view))
        view.setResizeMode(QListView.Adjust);view.setUniformItemSizes(True)
        rows=[{'login':f'friend{i}','nickname':f'Friend {i}'} for i in range(6)]
        for height in (340,500,600):
            view.resize(310,height);view.show()
            model.replace(rows[:5]);self.app.processEvents();view.doItemsLayout()
            self.assertEqual(view.verticalScrollBar().maximum(),0)
            self.assertLess(view.visualRect(model.index(4)).bottom(),view.viewport().height())
            model.replace(rows);self.app.processEvents();view.doItemsLayout()
            self.assertLessEqual(view.itemDelegate().sizeHint(None,model.index(0)).height(),76)
            if view.viewport().height()<6*76:
                self.assertGreater(view.verticalScrollBar().maximum(),0)

    def test_voice_dock_controls_follow_channel_and_private_call_state(self):
        from PySide6.QtWidgets import QWidget
        from ui.design.voice_dock import VoiceDock
        main=QWidget();self.addCleanup(main.close)
        main.open_voice_surface=lambda:None;main.end_voice_surface=lambda:None
        main.call_window=None
        main.channels_page=SimpleNamespace(_voice_muted=True,_voice_deafened=False)
        dock=VoiceDock(main);dock.sync_controls()
        self.assertEqual(dock.controls["mic"].icon_name,"mic-off")
        self.assertTrue(dock.controls["mic"].isChecked())
        self.assertFalse(dock.controls["headphones"].property("danger"))
        main.call_window=SimpleNamespace(mic_enabled=True,sound_enabled=False)
        dock.sync_controls()
        self.assertEqual(dock.controls["mic"].icon_name,"mic")
        self.assertEqual(dock.controls["headphones"].icon_name,"headphones-off")
        self.assertTrue(dock.controls["headphones"].property("danger"))

    def test_voice_dock_animation_reverses_and_reserves_bottom_space(self):
        from PySide6.QtWidgets import QWidget
        from ui.design.voice_dock import VoiceDock
        from PySide6.QtCore import QAbstractAnimation
        main=QWidget();main.resize(1120,620)
        main.chats_page=SimpleNamespace(voice_dock_space=QWidget(main))
        main.channels_page=SimpleNamespace(voice_dock_space=QWidget(main))
        main.open_voice_surface=lambda:None
        main.end_voice_surface=lambda:None
        dock=VoiceDock(main);main.show();self.addCleanup(main.close)
        dock.set_present(True)
        dock.animation.setCurrentTime(90)
        self.assertGreater(dock.get_progress(),0)
        self.assertLess(dock.get_progress(),1)
        dock.set_present(False)
        dock.animation.setCurrentTime(180)
        self.assertTrue(dock.isHidden())
        self.assertEqual(main.chats_page.voice_dock_space.height(),0)
        dock.set_present(True);dock.animation.setCurrentTime(180)
        self.assertEqual(dock.y()+dock.height(),main.height()-14)
        self.assertEqual(main.chats_page.voice_dock_space.height(),152)
        self.assertEqual(dock.animation.state(),QAbstractAnimation.Stopped)

    def test_structural_surfaces_keep_one_alpha_layer(self):
        from app_window import AppWindow
        from ui.design.shell import TitleBar
        from PySide6.QtWidgets import QWidget, QFrame
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtGui import QImage, QPainter
        from style_manager import load_styles
        class Surface(QWidget):
            paintEvent = AppWindow.paintEvent
        window = Surface()
        window.resize(600,400)
        window.setAttribute(Qt.WA_TranslucentBackground)
        window.setStyleSheet(load_styles())
        title = TitleBar(window); title.setGeometry(0,0,600,42)
        rail = QWidget(window); rail.setObjectName("Sidebar"); rail.setGeometry(0,42,88,358)
        sidebar = QFrame(window); sidebar.setObjectName("SectionSidebar"); sidebar.setGeometry(88,42,200,358)
        window.show(); self.addCleanup(window.close); self.app.processEvents()
        for enabled, expected in [(True,245),(False,255)]:
            window.setProperty("translucent_background",enabled)
            image=QImage(window.size(),QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent)
            painter=QPainter(image)
            window.render(painter,QPoint(),renderFlags=QWidget.DrawChildren)
            painter.end()
            self.assertEqual(image.pixelColor(599,399).alpha(),0)
            self.assertTrue(any(0<image.pixelColor(x,y).alpha()<expected
                                for x in range(586,600) for y in range(386,400)))
            for x,y in [(500,20),(10,300),(100,300),(500,300)]:
                self.assertEqual(image.pixelColor(x,y).alpha(),expected)

    def test_tabs_have_no_transition_overlay(self):
        from ui.design.motion import TransitionStack,PageOverlay
        from PySide6.QtWidgets import QWidget
        stack=TransitionStack();stack.addWidget(QWidget());stack.addWidget(QWidget())
        stack.show();self.addCleanup(stack.close)
        stack.setCurrentIndex(1);self.app.processEvents()
        self.assertFalse(stack.findChildren(PageOverlay))

    def test_manual_scroll_cancels_delayed_resize_anchor(self):
        from ui.design.widgets import MessageList
        from PySide6.QtWidgets import QAbstractSlider
        view=MessageList();self.addCleanup(view.close)
        view.reflow.start()
        view.verticalScrollBar().triggerAction(QAbstractSlider.SliderSingleStepAdd)
        self.assertFalse(view.reflow.isActive())

    def test_page_transition_fades_without_translating_snapshot(self):
        from ui.design.motion import PageOverlay
        from PySide6.QtWidgets import QWidget
        from PySide6.QtGui import QPixmap
        from unittest.mock import patch
        host=QWidget();host.resize(200,100);self.addCleanup(host.close)
        overlay=PageOverlay(host,QPixmap(200,100));overlay.animation.stop()
        for progress in (0.0,0.5,1.0):
            overlay.set_progress(progress)
            with patch('ui.design.motion.QPainter') as painter:
                overlay.paintEvent(None)
                self.assertEqual(painter.return_value.drawPixmap.call_args.args[:2],(0,0))
                painter.return_value.setOpacity.assert_called_with(1-progress)

    def test_first_friends_load_runs_with_polling_disabled_without_restarting_timer(self):
        from unittest.mock import patch
        from ui.friends_page import FriendsPage
        with patch.object(FriendsPage,"start_request") as request:
            page=FriendsPage();self.addCleanup(page.close)
            page.ctx=SimpleNamespace(login="alice")
            page.set_polling_enabled(False)
            page.ensure_initial_load()
            self.assertEqual([call.args[0]["action"] for call in request.call_args_list],
                             ["get_friends","get_friend_requests"])
            self.assertFalse(page.timer.isActive())
            page.ensure_initial_load()
            self.assertEqual(request.call_count,2)
            request.call_args_list[0].args[1]({"status":"ok","friends":[{"login":"bob","nickname":"Bob"}]})
            self.assertFalse(page._skeleton_visible)
            page.ensure_initial_load()
            self.assertEqual(request.call_count,2)

    def test_friends_render_without_waiting_for_requests(self):
        from unittest.mock import patch
        from ui.friends_page import FriendsPage, FriendItem
        with patch.object(FriendsPage, "start_request"):
            page = FriendsPage()
            self.addCleanup(page.close)
            page.timer.stop()
            page.handle_friends({"status":"ok", "friends":[{"login":"alice","nickname":"Alice"}]})
            self.assertFalse(page._has_loaded_requests_once)
            self.assertFalse(page._skeleton_visible)
            self.assertEqual(len(page.findChildren(FriendItem)), 1)
            page.set_view("requests")
            self.assertTrue(page._skeleton_visible)
            page.set_view("all")
            self.assertFalse(page._skeleton_visible)
            page.set_view("requests")
            page.handle_requests({"status":"ok", "requests":[]})
            self.assertFalse(page._skeleton_visible)

    def test_selector_popup_keyboard_selection_and_cancel(self):
        from ui.design.widgets import ScrollSafeComboBox
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        combo = ScrollSafeComboBox()
        combo.addItems([f"Device {i}" for i in range(20)])
        combo.resize(320,46); combo.show()
        self.addCleanup(combo.close)
        combo.showPopup(); self.app.processEvents()
        self.assertTrue(combo.view().isVisible())
        self.assertTrue(combo.view().window().mask().isEmpty())
        self.assertTrue(combo.view().window().testAttribute(Qt.WA_TranslucentBackground))
        self.assertEqual(combo.view().sizeHintForRow(0),40)
        QTest.keyClick(combo.view(), Qt.Key_Down)
        QTest.keyClick(combo.view(), Qt.Key_Return)
        self.assertEqual(combo.currentIndex(),1)
        combo.showPopup(); self.app.processEvents()
        QTest.keyClick(combo.view(), Qt.Key_Down)
        QTest.keyClick(combo.view(), Qt.Key_Escape)
        self.assertEqual(combo.currentIndex(),1)
        self.assertFalse(combo.view().isVisible())

    def test_image_plugins_load_svg_controls_and_avatar_formats(self):
        from PySide6.QtGui import QImageReader, QImage
        from ui.design.widgets import ASSETS

        formats = {bytes(value).decode() for value in QImageReader.supportedImageFormats()}
        self.assertTrue({"svg", "jpeg", "webp"}.issubset(formats), formats)
        for name in ("radio-checked.svg", "radio-unchecked.svg", "chevron-down.svg"):
            image = QImage(str(ASSETS / name))
            self.assertFalse(image.isNull(), name)
        checked = QImage(str(ASSETS / "radio-checked.svg"))
        self.assertEqual(checked.pixelColor(9, 9).name(), "#91adff")

    def test_long_header_elides_and_restores_full_name_on_resize(self):
        from ui.design.widgets import ElidedLabel
        label=ElidedLabel('Александра Константинопольская-Рождественская')
        self.addCleanup(label.close)
        label.resize(180,30);label.show();self.app.processEvents()
        self.assertTrue(label.text().endswith('…'))
        self.assertEqual(label.toolTip(),label.full_text)
        label.resize(900,30);self.app.processEvents()
        self.assertEqual(label.text(),label.full_text)

    def test_scrollbars_reserve_the_same_content_gutter_in_both_directions(self):
        from PySide6.QtWidgets import QScrollBar,QStyleOptionSlider,QStyle
        from PySide6.QtCore import Qt
        from ui.design import tokens
        style=(Path(__file__).resolve().parents[1]/'client/styles/nodus.qss').read_text()
        for key,value in vars(tokens).items():
            if isinstance(value,str):style=style.replace('@'+key+'@',value)
        for direction in (Qt.Vertical,Qt.Horizontal):
            bar=QScrollBar(direction);bar.setStyleSheet(style)
            bar.setRange(0,100);bar.setPageStep(20);bar.setValue(40)
            bar.resize(18,180) if direction==Qt.Vertical else bar.resize(180,18)
            bar.show();self.app.processEvents()
            option=QStyleOptionSlider();bar.initStyleOption(option)
            rect=bar.style().subControlRect(QStyle.CC_ScrollBar,option,QStyle.SC_ScrollBarSlider,bar)
            self.assertEqual(rect.left() if direction==Qt.Vertical else rect.top(),12)
            self.assertEqual(rect.width() if direction==Qt.Vertical else rect.height(),3)
            bar.close()

    def test_startup_screen_centers_content_and_stops_hidden_animation(self):
        from unittest.mock import Mock
        from PySide6.QtCore import QAbstractAnimation
        from ui.design.startup import StartupPage
        previous=self.app.property('reduce_motion')
        self.addCleanup(lambda:self.app.setProperty('reduce_motion',previous))
        self.app.setProperty('reduce_motion',False)
        cancel=Mock();page=StartupPage(cancel);self.addCleanup(page.close)
        for width,height in ((1120,578),(1280,738),(1440,858)):
            page.resize(width,height);page.show();self.app.processEvents()
            self.assertAlmostEqual(page.progress.geometry().center().x(),width/2,delta=1)
            self.assertLess(page.cancel_button.geometry().bottom(),height)
        self.assertEqual(page.progress.animation.state(),QAbstractAnimation.Running)
        page.hide();self.assertEqual(page.progress.animation.state(),QAbstractAnimation.Stopped)
        self.app.setProperty('reduce_motion',True)
        page.show();self.app.processEvents()
        self.assertEqual(page.progress.animation.state(),QAbstractAnimation.Stopped)
        page.cancel_button.click();cancel.assert_called_once()

    def test_icon_only_buttons_paint_at_their_actual_center(self):
        from unittest.mock import patch
        from PySide6.QtCore import QRectF
        from ui.design.widgets import Button, ASSETS
        for asset in ASSETS.glob('*.svg'):
            for width, height in ((24,54), (28,28), (32,28), (32,40), (38,38), (44,44), (64,44)):
                with self.subTest(symbol=asset.stem, size=(width,height)):
                    button = Button('', asset.stem)
                    button.setFixedSize(width, height)
                    for state in ('normal', 'hover', 'pressed', 'disabled'):
                        button._hover = float(state == 'hover')
                        button.setDown(state == 'pressed')
                        button.setEnabled(state != 'disabled')
                        rects=[]
                        with patch('ui.design.widgets.icon', new=lambda p,n,r,c: rects.append(QRectF(r))):
                            button.grab()
                        rect = rects[-1]
                        self.assertEqual(rect.center().x(), width / 2, state)
                        self.assertEqual(rect.center().y(), height / 2, state)
                    button.close()

    def test_labeled_buttons_center_the_whole_group_or_keep_left_alignment(self):
        from unittest.mock import patch
        from PySide6.QtCore import QRectF
        from ui.design.widgets import Button
        for label, symbol in (('Позвонить','phone'), ('Написать','chat'),
                              ('Копировать диагностику','copy'), ('Голос','wave')):
            for left_aligned in (False,True):
                button = Button(label,symbol)
                button.setFixedSize(320,40)
                button.setProperty('align_left',left_aligned)
                rects=[]
                with patch('ui.design.widgets.icon', new=lambda p,n,r,c: rects.append(QRectF(r))):
                    button.grab()
                rect = rects[-1]
                if left_aligned:
                    self.assertEqual(rect.left(),12)
                else:
                    right = rect.right()+8+button.fontMetrics().horizontalAdvance(label)
                    self.assertAlmostEqual((rect.left()+right)/2,button.width()/2,delta=0.5)
                self.assertEqual(rect.center().y(),20)
                button.close()

    def test_navigation_and_call_icons_have_independent_centered_painting(self):
        from unittest.mock import patch
        from PySide6.QtCore import QRectF
        from ui.design.widgets import RoundCallButton
        from ui.design.shell import NavButton
        for symbol in ('users','chat','hash','profile'):
            button=NavButton('Раздел',symbol)
            for active in (False,True):
                button.setProperty('active',active)
                rects=[]
                with patch('ui.design.shell.icon', new=lambda p,n,r,c: rects.append(QRectF(r))):
                    button.grab()
                rect=rects[-1]
                self.assertEqual(rect.center().x(),button.width()/2)
                self.assertEqual(rect.center().y(),19)
            button.close()
        for symbol in ('mic','headphones','end'):
            button=RoundCallButton('Управление звонком',symbol)
            rects=[]
            with patch('ui.design.widgets.icon', new=lambda p,n,r,c: rects.append(QRectF(r))):
                button.grab()
            rect=rects[-1]
            self.assertEqual(rect.center().x(),button.width()/2)
            self.assertEqual(rect.center().y(),button.height()/2)
            button.close()

    def test_round_call_controls_keep_circle_height_inside_layout(self):
        from PySide6.QtWidgets import QWidget, QHBoxLayout
        from ui.design.widgets import RoundCallButton
        host=QWidget()
        layout=QHBoxLayout(host)
        buttons=[RoundCallButton('Микрофон','mic'),RoundCallButton('Звук','headphones'),
                 RoundCallButton('Завершить','end',danger=True)]
        for button in buttons:
            layout.addWidget(button)
        host.resize(300,80);host.show();self.app.processEvents()
        self.addCleanup(host.close)
        for button in buttons:
            self.assertEqual(button.size().toTuple(),(52,52))
            self.assertEqual(button.sizeHint().toTuple(),(52,52))

    def test_buttons_do_not_acquire_a_second_hover_or_focus_outline(self):
        from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QFocusEvent
        from ui.design.motion import MotionFilter
        from ui.design.widgets import Button, RoundCallButton
        from ui.design.shell import NavButton
        from ui.design.action_menu import MenuButton
        host=QWidget();layout=QVBoxLayout(host)
        controls=[QPushButton('Подключиться'),QPushButton('Создать'),
                  Button('Сохранить'),Button('', 'send', True),
                  RoundCallButton('Микрофон','mic'),NavButton('Друзья','users'),
                  MenuButton('Копировать')]
        for button in controls:layout.addWidget(button)
        controller=MotionFilter(host);controller.watch(host)
        host.show();self.app.processEvents();self.addCleanup(host.close)
        for button in controls:
            for event in (QEvent(QEvent.Enter),QFocusEvent(QEvent.FocusIn,Qt.TabFocusReason),
                          QEvent(QEvent.Leave),QFocusEvent(QEvent.FocusOut)):
                self.app.sendEvent(button,event)
                self.assertFalse(hasattr(button,"_focus_ring"),type(button).__name__)
            self.assertFalse(button.testAttribute(Qt.WA_MacShowFocusRect))

    def test_button_icons_contrast_with_surfaces_through_hover_and_selection(self):
        from unittest.mock import patch
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QWidget
        from ui.design.widgets import Button
        def luminance(color):
            values=[color.redF(),color.greenF(),color.blueF()]
            linear=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in values]
            return sum(v*w for v,w in zip(linear,(0.2126,0.7152,0.0722)))
        host=QWidget();host.setObjectName('ContrastHost');host.resize(100,80)
        host.setStyleSheet('QWidget#ContrastHost {background:#18212A;}')
        self.addCleanup(host.close)
        button=Button('', 'settings',parent=host);button.setFixedSize(64,44);button.move(10,10)
        host.show();self.app.processEvents()
        for flat in (False,True):
            for primary in (False,True):
                for danger in (False,True):
                    for hover in (0,0.25,0.5,1):
                        for pressed in (False,True):
                            with self.subTest(flat=flat,primary=primary,danger=danger,hover=hover,pressed=pressed):
                                button.primary=primary;button.setProperty('flat',flat)
                                button.setProperty('danger',danger);button._hover=hover;button.setDown(pressed)
                                colors=[]
                                with patch('ui.design.widgets.icon',new=lambda p,n,r,c: colors.append(QColor(c))):
                                    image=host.grab().toImage()
                                fg=luminance(colors[-1]);bg=luminance(image.pixelColor(18,32))
                                self.assertGreaterEqual((max(fg,bg)+0.05)/(min(fg,bg)+0.05),3.0)

    def test_dialog_poll_preserves_search_selection_and_accessibility_index(self):
        from PySide6.QtWidgets import QListView
        from PySide6.QtCore import QPersistentModelIndex
        from PySide6.QtTest import QSignalSpy
        from ui.design.models import DialogModel
        model = DialogModel()
        view = QListView(); view.setModel(model)
        self.addCleanup(view.close)
        rows = [{"login": "anna", "nickname": "Анна", "online": True},
                {"login": "alexey", "nickname": "Алексей", "online": True}]
        model.replace(rows); model.filter("anna")
        view.setCurrentIndex(model.index(0))
        index = QPersistentModelIndex(view.currentIndex())
        resets = QSignalSpy(model.modelReset)
        changes = QSignalSpy(model.dataChanged)
        model.replace([dict(rows[0], online=False), rows[1]])
        self.assertEqual(resets.count(), 0)
        self.assertEqual(changes.count(), 1)
        self.assertTrue(index.isValid())
        self.assertEqual(view.currentIndex().row(), 0)
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.rows[0]["login"], "anna")
        model.replace([dict(rows[0], online=False), rows[1]])
        self.assertEqual(changes.count(), 1)

    def test_read_badge_clears_immediately_and_rejects_older_unread_response(self):
        from ui.chats_page import ChatsPage
        page=ChatsPage();self.addCleanup(page.close)
        page.ctx=SimpleNamespace(login="alice",session_token="test")
        calls=[];page.start_request=lambda data,callback:calls.append((data,callback))
        page.unread_counts={"bob":2,"carol":1}
        page.dialog_model.replace([{"login":"bob","unread_count":2},{"login":"carol","unread_count":1}])
        page.conversation.rows=[{"id":4,"from_user":"bob"}]
        totals=[];page.on_unread_total_changed=totals.append
        page.load_unread_counts(force=True)
        old=calls[0][1]
        page.mark_chat_read("bob")
        self.assertEqual(page.unread_counts,{"carol":1})
        self.assertEqual(totals[-1],1)
        self.assertEqual(page.dialog_model.rows[0]["unread_count"],0)
        self.assertEqual(calls[-1][0]["through_id"],4)
        old({"status":"ok","counts":{"bob":2,"carol":1},"total":3})
        self.assertNotIn("bob",page.unread_counts)
        self.assertEqual(calls[-1][0]["action"],"get_unread_counts")

    def test_dialog_order_uses_last_message_not_presence(self):
        from ui.chats_page import ChatsPage
        from ui.design.models import DialogModel
        from unittest.mock import Mock
        page = SimpleNamespace(unread_counts={},
            dialog_summaries={"recent": {"timestamp": "2026-10-29 14:36:00"},
                              "older": {"timestamp": "2026-10-29 14:20:00"}},
            dialog_model=DialogModel(), filter_friends=Mock(), search=SimpleNamespace(text=lambda: ""),
            active_friend=None,conversation=SimpleNamespace(prefetch=Mock()))
        friends=[dict(login="older",nickname="Anna",online=True),
                 dict(login="empty",nickname="Aaron",online=True),
                 dict(login="recent",nickname="Zoe",online=False)]
        ChatsPage.handle_friends(page,dict(status="ok",friends=friends))
        self.assertEqual([row['login'] for row in page.dialog_model.rows], ['recent','older','empty'])
        for row in friends:
            row['online']=not row['online']
        ChatsPage.handle_friends(page,dict(status="ok",friends=friends))
        self.assertEqual([row['login'] for row in page.dialog_model.rows], ['recent','older','empty'])

    def test_closed_selector_ignores_wheel_but_keeps_keyboard_selection(self):
        from PySide6.QtCore import Qt, QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtTest import QTest
        from ui.design.widgets import ScrollSafeComboBox
        combo = ScrollSafeComboBox()
        combo.addItems(['Default', 'Device A', 'Device B'])
        combo.show()
        self.addCleanup(combo.close)
        event = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(), QPoint(0,-120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        self.app.sendEvent(combo, event)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertFalse(event.isAccepted())
        QTest.keyClick(combo, Qt.Key_Down)
        self.assertEqual(combo.currentIndex(), 1)

    def test_member_menu_keyboard_selects_role_without_removal(self):
        from PySide6.QtWidgets import QWidget, QPushButton
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from ui.channels_page import ChannelMemberItem
        from unittest.mock import Mock
        host = QWidget(); host.resize(1120, 620)
        self.addCleanup(host.close)
        role_changed, removed = Mock(), Mock()
        item = ChannelMemberItem({"login": "bob", "role": "member"}, "alice",
            {"assign_roles": True, "manage_members": True, "my_role": "owner"},
            role_changed, removed)
        item.setParent(host); item.setGeometry(450, 450, 650, 90)
        host.show(); self.app.processEvents()
        button = item.findChild(QPushButton, "ChannelTinyActionButton")
        button.click(); self.app.processEvents()
        menu = item._actions_menu
        self.assertLessEqual(menu.geometry().bottom(), host.height()-12)
        QTest.keyClick(menu.buttons[0], Qt.Key_Down)
        self.assertFalse(menu.buttons[0].property("keyboardFocus"))
        self.assertTrue(menu.buttons[1].property("keyboardFocus"))
        QTest.keyClick(menu.buttons[1], Qt.Key_Return)
        role_changed.assert_called_once_with("bob", "admin")
        removed.assert_not_called()

    def test_inline_menu_stays_inside_window_and_escape_does_not_activate(self):
        from PySide6.QtWidgets import QWidget, QPushButton
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from ui.design.action_menu import ActionMenu
        host=QWidget();host.resize(1120,620);host.show()
        self.addCleanup(host.close)
        fired=[]
        menu=ActionMenu(host);menu.addAction('Action',lambda:fired.append(True))
        menu.popup(host.mapToGlobal(QPoint(1100,610)))
        self.assertLessEqual(menu.geometry().right(),host.width()-12)
        self.assertLessEqual(menu.geometry().bottom(),host.height()-12)
        QTest.keyClick(menu.buttons[0], Qt.Key_Down)
        self.assertTrue(menu.buttons[0].property('keyboardFocus'))
        self.assertEqual(menu.buttons[0].grab().toImage().pixelColor(5,20).name(), '#3a4d67')
        QTest.keyClick(menu.buttons[0],Qt.Key_Escape)
        self.assertFalse(fired)
        self.assertFalse(menu.isVisible())
        other=ActionMenu(host);other.addAction('Action',lambda:fired.append(True))
        other.popup(host.mapToGlobal(QPoint(500,200)))
        QTest.keyClick(other.buttons[0],Qt.Key_Return)
        self.assertEqual(fired,[True])

    def test_quick_switch_arrow_keys_and_empty_result(self):
        from PySide6.QtWidgets import QWidget
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from ui.design.quick_switch import QuickSwitch
        host=QWidget();host.resize(1440,900)
        host.friends_page=SimpleNamespace(_friends_data=[{'login':'alice'},{'login':'bob'}])
        host.channels_page=SimpleNamespace(channels=[])
        host.chats_page=SimpleNamespace(_friends_received_at=2, dialog_model=SimpleNamespace(
            all_rows=[{'login':'alice','online':False},{'login':'bob','online':False}]))
        panel=QuickSwitch(host)
        host.show();panel.show();self.app.processEvents()
        self.assertFalse(panel.targets[0][1]['online'])
        self.assertFalse(panel.list.horizontalScrollBar().isVisible())
        self.assertLessEqual(panel.list.visualRect(panel.model.index(0,0)).right(),
                             panel.list.viewport().rect().right())
        QTest.keyClick(panel.query,Qt.Key_Down)
        self.assertEqual(panel.list.currentIndex().row(),1)
        QTest.keyClick(panel.query,Qt.Key_Up)
        self.assertEqual(panel.list.currentIndex().row(),0)
        panel.query.setText('missing')
        self.assertIs(panel.results.currentWidget(),panel.empty)
        panel.close();host.close()

    def test_windows_opaque_preference_removes_previous_backdrop(self):
        from ui.design import backdrop
        from unittest.mock import patch, Mock
        import ctypes
        setter=Mock(return_value=0)
        window=SimpleNamespace(property=lambda name:False,winId=lambda:123)
        with patch.object(backdrop.sys,'platform','win32'), \
             patch.object(backdrop.sys,'getwindowsversion',return_value=SimpleNamespace(build=22621),create=True), \
             patch.object(ctypes,'windll',SimpleNamespace(dwmapi=SimpleNamespace(DwmSetWindowAttribute=setter)),create=True), \
             patch('PySide6.QtWidgets.QApplication.platformName',return_value='windows'):
            backdrop.install(window)
        self.assertEqual(setter.call_args.args[1],38)
        self.assertEqual(setter.call_args.args[2]._obj.value,1)
        self.assertEqual(window.backdrop_description,'Непрозрачный фон')

    def test_empty_state_shrinks_top_space_without_clipping_retry(self):
        from ui.design.state_surfaces import EmptyState
        from PySide6.QtWidgets import QPushButton
        panel=EmptyState('Не удалось загрузить сообщения','Проверьте соединение и попробуйте ещё раз.','Повторить')
        self.addCleanup(panel.close)
        panel.set_top_offset(158)
        panel.resize(600,340);panel.show();self.app.processEvents()
        retry=panel.findChild(QPushButton)
        self.assertLessEqual(retry.geometry().bottom(),panel.height())
        self.assertLess(panel.layout().contentsMargins().top(),158)
        panel.resize(900,600);self.app.processEvents()
        self.assertEqual(panel.layout().contentsMargins().top(),158)

    def test_microphone_silence_recovers_and_permission_error_survives_completion(self):
        from ui.design.microphone_check import MicrophoneCheck
        from unittest.mock import patch
        panel=MicrophoneCheck()
        self.addCleanup(panel.close)
        with patch('ui.design.microphone_check.time.monotonic',return_value=10):
            panel.listening()
        with patch('ui.design.microphone_check.time.monotonic',return_value=14):
            panel.update_meter()
            self.assertEqual(panel.title.text(),'Пока не слышим микрофон')
            panel.level=40
            panel.update_meter()
            self.assertEqual(panel.title.text(),'Проверка микрофона')
        panel.failed('Permission denied')
        panel.completed()
        self.assertEqual(panel.title.text(),'Нет доступа к микрофону')
        self.assertEqual(panel.status.text(),'Разрешите доступ к микрофону в настройках системы.')

    def test_inline_microphone_check_releases_stream_on_close(self):
        import threading
        import numpy as np
        from unittest.mock import patch
        from PySide6.QtWidgets import QWidget
        from ui.design.microphone_check import MicrophoneCheck
        entered, released = threading.Event(), threading.Event()
        class Stream:
            def __init__(self, **kw): self.callback=kw['callback']
            def __enter__(self):
                self.callback(np.array([[0.2]],dtype=float),1,None,None)
                entered.set()
                return self
            def __exit__(self,*args): released.set()
        host=QWidget()
        panel=MicrophoneCheck(host)
        self.assertFalse(panel.isWindow())
        with patch.dict(sys.modules,{'sounddevice':SimpleNamespace(InputStream=Stream)}), patch('config.load_config',return_value={}):
            try:
                panel.start()
                self.assertTrue(entered.wait(2))
                self.assertEqual(panel.level,50)
                panel.close()
                self.assertTrue(released.wait(2))
            finally:
                panel.stop_event.set()
                if panel.worker: panel.worker.join(2)
        host.close()

    def test_resize_targets_follow_all_edges_without_covering_content(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QWidget
        from ui.design.shell import create_resize_handles, position_resize_handles

        window = QWidget()
        window.resize_handles = create_resize_handles(window)
        for width, height in ((1120, 620), (1280, 780), (1440, 900)):
            window.resize(width, height)
            position_resize_handles(window)
            for point in (QPoint(0, 0), QPoint(width - 1, height - 1),
                          QPoint(0, height // 2), QPoint(width // 2, 0),
                          QPoint(width - 1, height // 2), QPoint(width // 2, height - 1)):
                self.assertTrue(any(h.geometry().contains(point) for h in window.resize_handles))
            self.assertFalse(any(h.geometry().contains(window.rect().center())
                                 for h in window.resize_handles))
        window.close()

    def test_rounded_corners_still_have_reachable_resize_handles(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QWidget
        from ui.design.shell import create_resize_handles, position_resize_handles
        from ui.design.window_shape import window_region

        window = QWidget()
        window.resize(1120, 620)
        window.resize_handles = create_resize_handles(window)
        position_resize_handles(window)
        region = window_region(1120, 620)
        for handle in window.resize_handles[4:]:
            center = handle.geometry().center()
            self.assertTrue(region.contains(QPoint(center)))
        window.close()

    def test_drag_over_window_control_never_activates_it(self):
        from ui.design.shell import WindowDot, WindowControl
        from PySide6.QtCore import Qt, QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QWidget, QApplication
        host=QWidget();self.addCleanup(host.close)
        for button in (WindowDot('#E8BC64',host),WindowControl('—',parent=host)):
            clicks=[];button.clicked.connect(lambda:clicks.append(True))
            def event(kind,x,buttons):
                return QMouseEvent(kind,QPointF(x,5),QPointF(x,5),Qt.LeftButton if kind!=QEvent.MouseMove else Qt.NoButton,buttons,Qt.NoModifier)
            QApplication.sendEvent(button,event(QEvent.MouseButtonPress,5,Qt.LeftButton))
            QApplication.sendEvent(button,event(QEvent.MouseMove,50,Qt.LeftButton))
            QApplication.sendEvent(button,event(QEvent.MouseMove,5,Qt.LeftButton))
            QApplication.sendEvent(button,event(QEvent.MouseButtonRelease,5,Qt.NoButton))
            self.assertFalse(clicks)
            QApplication.sendEvent(button,event(QEvent.MouseButtonPress,5,Qt.LeftButton))
            QApplication.sendEvent(button,event(QEvent.MouseButtonRelease,5,Qt.NoButton))
            self.assertEqual(clicks,[True])

    def test_resize_fallback_preserves_minimum_and_opposite_corner(self):
        from PySide6.QtCore import Qt, QPoint, QPointF
        from PySide6.QtWidgets import QWidget
        from ui.design.shell import ResizeHandle

        window = QWidget()
        window.setMinimumSize(400, 300)
        window.setGeometry(100, 100, 600, 500)
        handle = ResizeHandle(window, Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor)
        handle.drag_origin = QPoint(100, 100)
        handle.drag_geometry = window.geometry()
        event = SimpleNamespace(globalPosition=lambda: QPointF(900, 900), accept=lambda: None)
        handle.mouseMoveEvent(event)
        self.assertEqual(window.size().width(), 400)
        self.assertEqual(window.size().height(), 300)
        self.assertEqual(window.geometry().bottomRight(), handle.drag_geometry.bottomRight())
        handle.mouseReleaseEvent(event)
        self.assertIsNone(handle.drag_origin)
        window.close()

    def test_channel_forms_keep_reference_geometry_under_theme_and_resize(self):
        from PySide6.QtCore import QPoint
        from ui.channels_page import ChannelsPage
        from ui.design import tokens
        previous = self.app.styleSheet()
        style = (Path(__file__).resolve().parents[1] / 'client/styles/nodus.qss').read_text()
        for key, value in vars(tokens).items():
            if isinstance(value, str):
                style = style.replace('@' + key + '@', value)
        self.app.setStyleSheet(style)
        page = ChannelsPage()
        page.show()
        try:
            for width, height in ((1032, 578), (1192, 738), (1352, 858)):
                page.resize(width, height)
                for form, field, button in (
                    (page.create_page, page.create_name_input, page.create_confirm_btn),
                    (page.join_page, page.join_code_input, page.join_confirm_btn),
                ):
                    page.main_stack.setCurrentWidget(form)
                    self.app.processEvents()
                    self.assertEqual(field.height(), 46)
                    self.assertEqual(button.size().toTuple(), (200, 40))
                    self.assertEqual(button.mapTo(page, QPoint()).y(), 429)
                    self.assertLessEqual(field.mapTo(page, QPoint()).x() + field.width(), width)
        finally:
            page.close()
            self.app.setStyleSheet(previous)

    def test_voice_tiles_reflow_and_clear_all_participants(self):
        from ui.channels_page import ChannelsPage
        page=ChannelsPage()
        page._voice_participants=[{'login':str(i),'nickname':'Участник '+str(i)} for i in range(5)]
        page.main_stack.setCurrentWidget(page.channel_page)
        page.channel_inner_stack.setCurrentIndex(1)
        page.show()
        for width in (1032,1192,1352):
            page.resize(width,740)
            self.app.processEvents()
            page._render_voice_participants()
            self.assertEqual(page.voice_members_layout.count(),5)
            self.assertLessEqual(page._voice_columns,3)
            for i in range(5):
                self.assertEqual(page.voice_members_layout.itemAt(i).widget().height(),225)
        page._voice_participants=[]
        page._render_voice_participants()
        self.assertEqual(page.voice_members_layout.count(),1)
        page.close()

    def test_outer_window_region_cuts_four_corners_and_restores_maximized(self):
        from PySide6.QtCore import QPoint
        from ui.design.window_shape import window_region
        for width,height in ((1120,620),(1280,780),(1440,900)):
            region=window_region(width,height)
            for x,y in ((0,0),(width-1,0),(0,height-1),(width-1,height-1)):
                self.assertFalse(region.contains(QPoint(x,y)))
                self.assertTrue(window_region(width,height,True).contains(QPoint(x,y)))
            self.assertTrue(region.contains(QPoint(width//2,0)))
            self.assertTrue(region.contains(QPoint(width//2,height//2)))

    def test_theme_does_not_clip_navigation_or_icon_buttons(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        from ui.design.shell import NavButton
        from ui.design.widgets import Button
        from style_manager import load_styles

        window = QWidget()
        layout = QVBoxLayout(window)
        nav = NavButton("Друзья", "users")
        send = Button("", "send", True)
        layout.addWidget(nav)
        layout.addWidget(send)
        layout.addStretch()
        window.setStyleSheet(load_styles("main"))
        window.resize(150, 250)
        window.show()
        self.app.processEvents()
        self.assertGreaterEqual(nav.height(), 64)
        self.assertGreaterEqual(send.height(), 40)
        window.close()

    def test_call_controls_toggle_real_callbacks_without_repolishing(self):
        from ui.call_window import ActiveCallWindow
        mic, sound = [], []
        from PySide6.QtWidgets import QWidget
        host = QWidget(); host.resize(1440,900)
        window = ActiveCallWindow('alice','bob',on_mic_toggle=mic.append,on_sound_toggle=sound.append,parent=host)
        window._mic_clicked()
        window._sound_clicked()
        self.assertEqual(mic,[False])
        self.assertEqual(sound,[False])
        self.assertTrue(window.btn_mic.property("danger"))
        self.assertEqual(window.btn_mic.icon_name,"mic-off")
        self.assertEqual(window.btn_sound.icon_name,"headphones-off")
        window._mic_clicked()
        self.assertEqual(mic,[False,True])
        self.assertFalse(window.btn_mic.property("danger"))
        self.assertEqual(window.btn_mic.icon_name,"mic")
        window.close()

    def test_profile_sections_do_not_submit_hidden_password_or_profile_drafts(self):
        from ui.profile_page import ProfilePage
        page = ProfilePage('alice','Alice')
        page.ctx = SimpleNamespace(avatar='saved-avatar')
        sent = []
        page.start_request = lambda payload, callback: sent.append((payload,callback))
        page.show_section("password")
        page.save_changes()
        self.assertEqual(sent, [])
        page.nickname_edit.setText('Unsubmitted name')
        page.avatar_path = 'unsubmitted-avatar'
        page.password_edit.setText('new-password')
        page.current_password_edit.setText('current-password')
        page.show_section('password')
        page.save_changes()
        self.assertEqual(sent[-1][0]['nickname'],'Alice')
        self.assertEqual(sent[-1][0]['avatar'],'saved-avatar')
        self.assertEqual(sent[-1][0]['password'],'new-password')
        sent[-1][1]({'status':'error','message':'test rejection'})
        page.show_section('edit')
        page.save_changes()
        self.assertEqual(sent[-1][0]['password'],'')
        self.assertEqual(sent[-1][0]['current_password'],'')
        self.assertEqual(sent[-1][0]['nickname'],'Unsubmitted name')
        page.close()

    def test_late_preferred_channel_does_not_override_manual_selection(self):
        from ui.channels_page import ChannelsPage
        from unittest.mock import Mock
        callbacks=[]
        selected=[2]
        page=SimpleNamespace(_alive=True,_loading_channels=False,ctx=SimpleNamespace(login='alice'),
            _channels_loaded_once=True,_channel_navigation_revision=1,
            start_request=lambda payload,callback:callbacks.append(callback),
            _active_channel_id=lambda:selected[0],_apply_channel_header=Mock(),
            render_channels=Mock(),_apply_channel_permissions_ui=Mock(),_set_channel_list_state=Mock(),
            main_stack=SimpleNamespace(currentWidget=lambda:'settings'),
            placeholder_page='placeholder',open_channel=Mock(),show_toast=Mock())
        ChannelsPage.load_channels(page,force_refresh=True,preferred_channel_id=2)
        selected[0]=1
        page._channel_navigation_revision+=1
        callbacks[0]({'status':'ok','channels':[{'id':1,'name':'Owner'},{'id':2,'name':'Member'}]})
        self.assertEqual(page.active_channel['id'],1)
        page.open_channel.assert_not_called()

    def test_only_latest_channel_list_reply_applies(self):
        from ui.channels_page import ChannelsPage
        from unittest.mock import Mock
        callbacks=[]
        page=SimpleNamespace(_alive=True,_loading_channels=False,ctx=SimpleNamespace(login='alice'),
            _channels_loaded_once=True,
            start_request=lambda payload,callback:callbacks.append(callback),
            _active_channel_id=lambda:1,_apply_channel_header=Mock(),
            render_channels=Mock(),_apply_channel_permissions_ui=Mock(),_set_channel_list_state=Mock(),
            main_stack=SimpleNamespace(currentWidget=lambda:'settings'),
            placeholder_page='placeholder',open_channel=Mock(),show_toast=Mock())
        ChannelsPage.load_channels(page,force_refresh=True)
        ChannelsPage.load_channels(page,force_refresh=True)
        callbacks[1]({'status':'ok','channels':[{'id':1,'name':'Current'}]})
        callbacks[0]({'status':'ok','channels':[{'id':1,'name':'Outdated'}]})
        self.assertEqual(page.active_channel['name'],'Current')

    def test_overlay_stays_inside_host_and_releases_shade_on_escape(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit
        from ui.design.overlay import OverlayDialog
        host = QWidget(); host.resize(1120,620);host.show()
        dialog = OverlayDialog(host,520,420)
        layout = QVBoxLayout(dialog);field = QLineEdit();layout.addWidget(field)
        dialog.open();self.app.processEvents()
        self.assertFalse(dialog.isWindow())
        self.assertTrue(dialog.shade.isVisible())
        for width,height in ((1120,620),(1440,900)):
            host.resize(width,height);self.app.processEvents()
            self.assertTrue(host.rect().contains(dialog.geometry()))
            self.assertEqual(dialog.shade.geometry(),host.rect())
        for _ in range(5):
            QTest.keyClick(field,Qt.Key_Tab);self.app.processEvents()
            self.assertTrue(dialog.isAncestorOf(self.app.focusWidget()))
        QTest.keyClick(field,Qt.Key_Escape);self.app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.assertFalse(dialog.shade.isVisible())
        dialog.open();self.app.processEvents();dialog.accept()
        self.assertFalse(dialog.shade.isVisible())
        host.close()

    def test_confirmation_cancel_is_safe_and_accept_runs_once(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget, QPushButton
        from ui.design.dialogs import confirm
        host = QWidget(); host.resize(1120,620); host.show()
        calls = []
        dialog = confirm(host, "Удалить канал?", "Проверка", "Удалить", lambda: calls.append(1), danger=True)
        self.app.processEvents()
        self.assertTrue(host.rect().contains(dialog.geometry()))
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertEqual(calls, [])
        dialog = confirm(host, "Удалить канал?", "Проверка", "Удалить", lambda: calls.append(1), danger=True)
        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Удалить")
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(calls, [1])
        self.assertFalse(dialog.shade.isVisible())
        host.close()

    def test_quick_switch_repeated_filtering_and_target_selection(self):
        from PySide6.QtWidgets import QWidget
        from unittest.mock import Mock
        from ui.design.quick_switch import QuickSwitch
        main=QWidget()
        main.friends_page=SimpleNamespace(_friends_data=[{'login':'alice','nickname':'Alice'}])
        main.channels_page=SimpleNamespace(channels=[{'id':1,'name':'Team'}],open_channel=Mock())
        main.chats_page=SimpleNamespace(open_chat=Mock())
        main.show_channels=Mock()
        main.show_chats=Mock()
        dialog=QuickSwitch(main)
        for _ in range(100):
            dialog.query.setText('no match')
            self.assertEqual(dialog.model.rowCount(),0)
            dialog.query.setText('Team')
            self.assertEqual(dialog.model.rowCount(),1)
            self.app.processEvents()
        dialog.open_selected()
        main.channels_page.open_channel.assert_called_once_with({'id':1,'name':'Team'})
        dialog.close()
        main.close()

    def test_all_svg_assets_render_after_repeated_collection(self):
        import gc
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from ui.design.widgets import ASSETS, icon, ICONS
        # Exercise initial parsing, cache hits, and QObject lifetime together.
        image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
        for repeat in range(3):
            for path in ASSETS.glob('*.svg'):
                image.fill(Qt.transparent)
                painter = QPainter(image)
                try:
                    icon(painter, path.stem, QRectF(0, 0, 32, 32), '#ACB9CC')
                finally:
                    painter.end()
                self.assertTrue(ICONS[(path.stem, '#ACB9CC')].isValid())
                self.assertTrue(any(image.pixelColor(x,y).alpha() for y in range(32) for x in range(32)))
            gc.collect()

    def test_motion_tracks_late_fields_without_application_global_filter(self):
        from PySide6.QtWidgets import QWidget, QLineEdit, QVBoxLayout
        from PySide6.QtCore import QEvent, QChildEvent, Qt
        from PySide6.QtGui import QFocusEvent
        from ui.design.motion import MotionFilter
        window = QWidget()
        layout = QVBoxLayout(window)
        controller = MotionFilter(window)
        controller.watch(window)
        field = QLineEdit(window)
        field.setStyleSheet("min-height:22px;max-height:22px;padding:11px 14px;")
        field.setFixedHeight(46)
        layout.addWidget(field)
        window.show(); self.app.processEvents()
        self.app.sendEvent(window, QChildEvent(QEvent.ChildPolished, field))
        self.app.sendEvent(field, QFocusEvent(QEvent.FocusIn))
        self.assertTrue(field._nodus_motion_watched)
        self.assertFalse(field.testAttribute(Qt.WA_MacShowFocusRect))
        self.assertFalse(hasattr(field, "_focus_ring"))
        self.app.sendEvent(field, QFocusEvent(QEvent.FocusOut))
        self.assertFalse(hasattr(field, "_focus_ring"))
        window.close()

    def test_search_focus_has_only_one_border_and_composer_uses_its_outer_frame(self):
        from PySide6.QtWidgets import QWidget,QLineEdit,QFrame,QPlainTextEdit
        from PySide6.QtCore import Qt,QEvent
        from PySide6.QtGui import QFocusEvent
        from ui.design.motion import MotionFilter
        host=QWidget();host.resize(320,170);self.addCleanup(host.close)
        field=QLineEdit(host);field.setGeometry(20,20,240,46)
        field.setStyleSheet('QLineEdit {background:#18212A;border:1px solid #354152;border-radius:10px;padding:0;min-height:0;} QLineEdit:focus {border-color:#91ADFF;}')
        frame=QFrame(host);frame.setObjectName('ComposerFrame');frame.setGeometry(20,90,260,60)
        editor=QPlainTextEdit(frame);editor.setObjectName('MessageComposer')
        controller=MotionFilter(host);controller.watch(host)
        host.show();host.activateWindow();field.setFocus(Qt.TabFocusReason);self.app.processEvents()
        self.assertTrue(field.hasFocus())
        image=host.grab().toImage()
        self.assertEqual(image.pixelColor(140,20).name(),'#91adff')
        for y in (22,23,24):
            self.assertEqual(image.pixelColor(140,y).name(),'#18212a')
        self.app.sendEvent(editor,QFocusEvent(QEvent.FocusIn,Qt.TabFocusReason))
        self.assertTrue(frame.property('editorFocused'))
        self.assertFalse(hasattr(editor,'_focus_ring'))
        self.app.sendEvent(editor,QFocusEvent(QEvent.FocusOut))
        self.assertFalse(frame.property('editorFocused'))
