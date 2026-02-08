from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea
from PySide6.QtCore import Qt

class ChannelsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("background-color:#36393f; color:white;")
        root = QVBoxLayout(self)
        root.setContentsMargins(20,20,20,20)
        root.setSpacing(12)

        # Заголовок
        title = QLabel("Каналы")
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        root.addWidget(title, alignment=Qt.AlignLeft)

        # Кнопки действия
        btn_create = QPushButton("Создать сервер")
        btn_create.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                border-radius:6px;
                padding:6px 12px;
            }
            QPushButton:hover {
                background-color:#4752c4;
            }
        """)
        root.addWidget(btn_create, alignment=Qt.AlignLeft)

        btn_connect = QPushButton("Подключиться к серверу")
        btn_connect.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                border-radius:6px;
                padding:6px 12px;
            }
            QPushButton:hover {
                background-color:#4752c4;
            }
        """)
        root.addWidget(btn_connect, alignment=Qt.AlignLeft)

        # Секция списка серверов (пока пустая)
        servers_label = QLabel("Список серверов:")
        servers_label.setStyleSheet("font-weight:bold; margin-top:20px;")
        root.addWidget(servers_label, alignment=Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.addStretch()  # пока пусто
        scroll.setWidget(scroll_content)
        root.addWidget(scroll)
