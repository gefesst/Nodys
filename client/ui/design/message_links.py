"""One URL parser for painting and hit-testing; only web links may open."""
import re
from PySide6.QtCore import QUrl

_PATTERN = re.compile(r'(?:https?://|www\.)[^\s<>"\x00-\x1f]+', re.IGNORECASE)


def link_spans(text):
    for match in _PATTERN.finditer(text):
        value = match.group().rstrip('.,!?;:\'')
        for closing, opening in ((')', '('), (']', '['), ('}', '{')):
            while value.endswith(closing) and value.count(closing) > value.count(opening):
                value = value[:-1]
        url = QUrl(('https://' if value.lower().startswith('www.') else '') + value, QUrl.StrictMode)
        if url.scheme().lower() not in ('http', 'https') or not url.isValid() or not url.host():
            continue
        # QTextLayout indexes UTF-16, unlike Python's Unicode code-point indexes.
        start = len(text[:match.start()].encode('utf-16-le')) // 2
        length = len(value.encode('utf-16-le')) // 2
        yield start, length, url
