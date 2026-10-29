"""Attachment wire limits shared by desktop and server."""
MAX_FILE_SIZE = 10 * 1024 * 1024
CHUNK_SIZE = 48 * 1024
USER_QUOTA = 100 * 1024 * 1024


def size_label(size):
    return f'{size / 1024 / 1024:.1f} МБ' if size >= 1024 * 1024 else f'{max(1, (size + 1023) // 1024)} КБ'
