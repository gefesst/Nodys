import sys
import json
from PySide6.QtWidgets import QApplication
from auth_window import AuthWindow
from ui.main_window import MainWindow

CONFIG_FILE = "config.json"

def load_config():
    try:
        with open(CONFIG_FILE,"r") as f:
            return json.load(f)
    except:
        return {}

def save_config(data):
    with open(CONFIG_FILE,"w") as f:
        json.dump(data,f)

def main():
    app = QApplication(sys.argv)
    config = load_config()

    if config.get("login"):
        window = MainWindow(config["login"], config.get("nickname",""))
        window.show()
    else:
        auth = AuthWindow()
        auth.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
