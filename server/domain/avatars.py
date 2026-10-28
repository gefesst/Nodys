"""Validate and canonicalize portable avatar images before persistence."""
import base64
import binascii
from io import BytesIO
from PIL import Image, UnidentifiedImageError

PREFIX = 'data:image/png;base64,'


def normalize_avatar(value):
    if not isinstance(value,str):
        raise ValueError('Некорректный аватар')
    if not value.startswith(PREFIX):
        # Preserve legacy references without opening client-supplied filesystem paths.
        if len(value) > 1024 or value.startswith('data:'):
            raise ValueError('Некорректный аватар')
        return value
    if len(value) > 140_000:
        raise ValueError('Аватар слишком большой')
    try:
        raw = base64.b64decode(value[len(PREFIX):],validate=True)
        with Image.open(BytesIO(raw)) as source:
            if source.format != 'PNG' or max(source.size) > 256:
                raise ValueError('Некорректный размер или формат аватара')
            source.load()
            clean = source.convert('RGBA')
            clean.thumbnail((128,128))
            output = BytesIO()
            clean.save(output,format='PNG')
        return PREFIX+base64.b64encode(output.getvalue()).decode('ascii')
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Повреждённое изображение аватара') from error
