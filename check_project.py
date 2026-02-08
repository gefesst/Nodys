import os
import re
import importlib
import traceback

ROOT = os.path.abspath(".")
CLIENT_DIR = os.path.join(ROOT, "client")
UI_DIR = os.path.join(CLIENT_DIR, "ui")

TARGET_FILES = [
    os.path.join(CLIENT_DIR, "main.py"),
    os.path.join(UI_DIR, "main_window.py"),
    os.path.join(UI_DIR, "friends_page.py"),
    os.path.join(UI_DIR, "chats_page.py"),
]

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def count_defs(text, func_name):
    # Ищет объявления вида "def load_friends("
    pattern = rf"^\s*def\s+{re.escape(func_name)}\s*\("
    return len(re.findall(pattern, text, flags=re.MULTILINE))

def has_token(text, token):
    return token in text

def print_header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def check_file_exists():
    print_header("1) Проверка наличия файлов")
    missing = []
    for p in TARGET_FILES:
        ok = os.path.exists(p)
        print(f"[{'OK' if ok else 'MISS'}] {p}")
        if not ok:
            missing.append(p)
    return missing

def check_friends_page(path):
    print_header("2) Анализ friends_page.py")
    text = read_text(path)
    if not text:
        print("Не удалось прочитать файл.")
        return

    load_count = count_defs(text, "load_friends")
    print(f"def load_friends найдено: {load_count}")
    if load_count != 1:
        print("⚠ Должно быть ровно 1 объявление load_friends.")

    refresh_in_init = False
    # Грубая эвристика: есть ли self.refresh() рядом с __init__
    init_pos = text.find("def __init__(")
    if init_pos != -1:
        init_chunk = text[init_pos:init_pos + 2500]
        refresh_in_init = "self.refresh()" in init_chunk

    print(f"self.refresh() внутри __init__: {'ДА' if refresh_in_init else 'НЕТ'}")
    if refresh_in_init:
        print("⚠ Убери self.refresh() из __init__, иначе возможны дубли на старте.")

def check_chats_page(path):
    print_header("3) Анализ chats_page.py")
    text = read_text(path)
    if not text:
        print("Не удалось прочитать файл.")
        return

    checks = [
        ("AutoMessageThread", has_token(text, "class AutoMessageThread")),
        ("time.sleep", has_token(text, "time.sleep(")),
        ("QThread import", bool(re.search(r"from\s+PySide6\.QtCore\s+import.*\bQThread\b", text))),
        ("Signal import", bool(re.search(r"from\s+PySide6\.QtCore\s+import.*\bSignal\b", text))),
        ("msg_timer", has_token(text, "self.msg_timer")),
        ("friends_timer", has_token(text, "self.friends_timer")),
        ("start_auto_update()", has_token(text, "def start_auto_update")),
        ("stop_auto_update()", has_token(text, "def stop_auto_update")),
        ("start_request()", has_token(text, "def start_request")),
    ]

    for name, present in checks:
        print(f"{name:20}: {'YES' if present else 'NO'}")

    if has_token(text, "class AutoMessageThread"):
        print("⚠ Нужно удалить AutoMessageThread полностью.")
    if has_token(text, "time.sleep("):
        print("⚠ time.sleep в UI/потоках для чата убрать.")
    if not has_token(text, "def start_request"):
        print("⚠ Нужен единый start_request с хранением потоков в списке.")
    if not has_token(text, "self._threads"):
        print("⚠ Нужен self._threads = [] для удержания живых QThread.")

def check_runtime_import_paths():
    print_header("4) Проверка реальных путей импортов (какие файлы реально грузятся)")
    # Чтобы импортировать client.main и ui.* из корня
    import sys
    if CLIENT_DIR not in sys.path:
        sys.path.insert(0, CLIENT_DIR)

    modules = [
        "main",
        "ui.main_window",
        "ui.friends_page",
        "ui.chats_page",
    ]

    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
            print(f"[OK] {mod_name:16} -> {getattr(mod, '__file__', 'NO __file__')}")
        except Exception as e:
            print(f"[ERR] {mod_name:16} -> {e}")
            traceback.print_exc(limit=1)

def check_main_window(path):
    print_header("5) Анализ main_window.py")
    text = read_text(path)
    if not text:
        print("Не удалось прочитать файл.")
        return

    needed = [
        ("show_chats", "def show_chats"),
        ("show_friends", "def show_friends"),
        ("show_profile", "def show_profile"),
        ("show_channels", "def show_channels"),
        ("calls chats start", "self.chats_page.start_auto_update"),
        ("calls chats stop", "self.chats_page.stop_auto_update"),
    ]
    for label, token in needed:
        print(f"{label:22}: {'YES' if token in text else 'NO'}")

def main():
    print_header("VOICE CHAT PROJECT CHECKER")
    print(f"ROOT:   {ROOT}")
    print(f"CLIENT: {CLIENT_DIR}")
    print(f"UI:     {UI_DIR}")

    missing = check_file_exists()
    if missing:
        print("\nЕсть отсутствующие файлы — сначала исправь структуру.")
        return

    check_friends_page(os.path.join(UI_DIR, "friends_page.py"))
    check_chats_page(os.path.join(UI_DIR, "chats_page.py"))
    check_main_window(os.path.join(UI_DIR, "main_window.py"))
    check_runtime_import_paths()

    print_header("Готово")
    print("Если видишь AutoMessageThread=YES или load_friends > 1 — это почти точно причина вылетов.")

if __name__ == "__main__":
    main()
