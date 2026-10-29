"""Disposable room workflow and responsive screenshots over a real local server."""
import os,sys,time,json,argparse
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'client'),str(ROOT/'tools')]
from review_support.sandbox import Sandbox

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    lab=Sandbox(ROOT)
    from config import save_config
    save_config(dict(lab.config,login=lab.me,token=lab.tokens[lab.me]))
    from application.qt_runtime import prepare_platform_plugins
    prepare_platform_plugins()
    from PySide6.QtWidgets import QApplication,QLineEdit
    from ui.design.widgets import Button
    from review_support import audio  # synthetic devices; real encrypted transport
    from app_window import AppWindow
    app=QApplication([])
    from application.qt_runtime import prepare_application_fonts
    from style_manager import apply_app_styles
    prepare_application_fonts(app);apply_app_styles(app)
    w=AppWindow();w.show();checks=[]
    def wait(predicate=lambda:True,seconds=.15):
        start=time.monotonic()
        while time.monotonic()-start<10:
            app.processEvents();time.sleep(.005)
            if time.monotonic()-start>=seconds and predicate():return
        raise AssertionError('UI timeout')
    def shot(name):
        for width,height in [(1120,620),(1280,704),(1440,900)]:
            w.resize(width,height);wait(seconds=.25)
            assert w.width()==width,(name,w.width(),width)
            w.grab().save(str(output/f'{name}-{width}.png'))
    try:
        wait(lambda:bool(getattr(w,'main_page',None)) and w.main_page.friends_page._has_loaded_friends_once)
        m=w.main_page;p=m.channels_page;m.show_channels()
        wait(lambda:bool(p.channels));p.open_channel(p.channels[0]);wait(lambda:p._rooms_manage)
        cid=p._active_channel_id()
        for kind,name in [('text','объявления'),('text','вопросы'),('voice','Команда'),('voice','Встреча')]:
            p.edit_room_dialog(kind=kind);wait()
            dialog=p._room_editor;dialog.findChild(QLineEdit).setText(name)
            next(b for b in dialog.findChildren(Button) if b.text()=='Создать').click()
            wait(lambda name=name:any(r['name']==name for r in p._rooms))
        checks.append('create text and voice rooms through UI')
        room=next(r for r in p._rooms if r['name']=='объявления')
        p.select_room(room);wait(lambda:not p.conversation.loading)
        p.conversation.editor.setPlainText('Сообщение только в объявлениях');p.conversation.send()
        wait(lambda:any('только в объявлениях' in r.get('text','') for r in p.conversation.rows))
        shot('text-room')
        p.edit_room_dialog(room=room);wait();dialog=p._room_editor;dialog.findChild(QLineEdit).setText('новости команды')
        next(b for b in dialog.findChildren(Button) if b.text()=='Сохранить').click()
        wait(lambda:any(r['name']=='новости команды' for r in p._rooms));checks.append('rename selected room without losing history')
        p.conversation.editor.setPlainText('Черновик новостей')
        p.select_room(next(r for r in p._rooms if r['name']=='вопросы'));wait(lambda:not p.conversation.loading)
        assert not p.conversation.rows
        p.select_room(next(r for r in p._rooms if r['name']=='новости команды'))
        assert p.conversation.editor.toPlainText()=='Черновик новостей'
        assert any('только в объявлениях' in r['text'] for r in p.conversation.rows)
        checks.append('room histories and drafts isolated, cached switch restores immediately')
        voice=next(r for r in p._rooms if r['name']=='Команда')
        result=lab.request('alexey','set_channel_voice_presence',channel_id=cid,room_id=voice['id'],joined=True)
        assert result['status']=='ok',result
        p.select_room(voice);p.load_rooms(force=True)
        wait(lambda:bool(p._voice_participants));shot('voice-room')
        p.toggle_voice_join();wait(lambda:p._voice_joined)
        wait(lambda:any(person['login']==lab.me for person in p._voice_participants))
        shot('voice-connected')
        p.toggle_voice_join();wait(lambda:not p._voice_joined)
        for target in (next(r for r in p._rooms if r['name']=='Встреча'),voice):
            p.select_room(target);p.load_rooms(force=True);wait(seconds=.4)
            assert not p._voice_joined and p._voice_client is None
            assert not any(login==lab.me for _,login in p._room_avatars)
        checks.append('join, leave and switch rooms without phantom self or automatic rejoin (synthetic audio)')
        p.edit_room_dialog(kind='text');wait();shot('create-room-dialog');p._room_editor.reject()
        for i in range(12):
            result=lab.request(lab.me,'create_channel_room',channel_id=cid,kind='text',name=f'тема-{i+1}')
            assert result['status']=='ok',result
        p.load_rooms(force=True);wait(lambda:len(p._rooms)==18)
        shot('many-rooms');checks.append('room list scrolls at all three sizes')
        result=lab.request(lab.me,'get_channel_rooms',channel_id=cid)
        assert any(r['name']=='новости команды' for r in result['rooms'])
        checks.append('room names persisted on server')
        (output/'report.json').write_text(json.dumps(dict(checks=checks,error=None),ensure_ascii=False,indent=2))
    finally:
        w.close();app.processEvents();lab.close()
    print(json.dumps(checks,ensure_ascii=False))

if __name__=='__main__':main()
