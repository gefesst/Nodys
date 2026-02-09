class UserContext:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UserContext, cls).__new__(cls)
            cls._instance.login = ""
            cls._instance.nickname = ""
            cls._instance.avatar = ""
        return cls._instance

    def set_user(self, login: str, nickname: str, avatar: str = ""):
        self.login = login or ""
        self.nickname = nickname or ""
        self.avatar = avatar or ""

    def clear(self):
        self.login = ""
        self.nickname = ""
        self.avatar = ""
