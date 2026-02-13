class UserContext:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UserContext, cls).__new__(cls)
            cls._instance.login = ""
            cls._instance.nickname = ""
            cls._instance.avatar = ""
            cls._instance.session_token = ""
            cls._instance.token_expires_at = ""  # ISO string
        return cls._instance

    def set_user(self, login: str, nickname: str, avatar: str = "", session_token: str = "", token_expires_at: str = ""):
        self.login = login or ""
        self.nickname = nickname or ""
        self.avatar = avatar or ""
        self.session_token = session_token or ""
        self.token_expires_at = token_expires_at or ""

    def clear(self):
        self.login = ""
        self.nickname = ""
        self.avatar = ""
        self.session_token = ""
        self.token_expires_at = ""
