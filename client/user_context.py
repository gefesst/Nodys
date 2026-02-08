class UserContext:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.login = ""
            cls._instance.nickname = ""
            cls._instance.avatar_path = ""
            cls._instance.online = False
        return cls._instance

    def set_user(self, login, nickname, avatar_path=""):
        self.login = login
        self.nickname = nickname
        self.avatar_path = avatar_path
        self.online = True

    def clear(self):
        self.login = ""
        self.nickname = ""
        self.avatar_path = ""
        self.online = False
