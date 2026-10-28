import base64
from io import BytesIO
import unittest
from PIL import Image
from test_foundation import load
from domain.avatars import normalize_avatar, PREFIX

class AvatarTests(unittest.TestCase):
    def image(self, size=(128,128)):
        output=BytesIO(); Image.new('RGBA',size,(80,120,200,255)).save(output,format='PNG')
        return PREFIX+base64.b64encode(output.getvalue()).decode()

    def test_canonical_image_roundtrip(self):
        image = normalize_avatar(self.image())
        self.assertEqual(normalize_avatar(image),image)

    def test_bad_payloads_rejected(self):
        for value in (123, PREFIX+'broken', PREFIX+'A'*150000, self.image((512,512))):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError): normalize_avatar(value)

class AvatarIntegrationTests(unittest.TestCase):
    def test_member_receives_saved_portable_avatar(self):
        import tempfile
        from pathlib import Path
        server = load('avatar_server', 'server/server.py')
        with tempfile.TemporaryDirectory() as folder:
            server.DB_FILE = str(Path(folder)/'users.db')
            server.init_db()
            for login in ('owner','member'):
                server.add_user(login,'synthetic',login,'')
            owner_token = server.create_session('owner')[0]
            member_token = server.create_session('member')[0]
            channel = server.create_channel('owner','Shared')
            server.join_channel_by_code('member',channel['code'])
            payload = AvatarTests().image()
            result = server.handle_request({'action':'update_channel_settings','token':owner_token,
                'channel_id':channel['id'],'name':'Shared','avatar':payload})
            self.assertEqual(result['status'],'ok')
            result = server.handle_request({'action':'get_channel_details','token':member_token,
                'channel_id':channel['id']})
            self.assertEqual(result['channel']['avatar'],normalize_avatar(payload))
