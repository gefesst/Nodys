import socket
import threading
import json
import sqlite3
import os

DB_FILE = "users.db"
CHAT_DB_FILE = "voice_chat.db"
online_users = set()

# ---------------- INIT DB ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            login TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            nickname TEXT NOT NULL,
            avatar TEXT
        )
    """)
    # Таблица друзей (односторонние)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            user_login TEXT,
            friend_login TEXT,
            PRIMARY KEY(user_login, friend_login)
        )
    """)
    # Таблица запросов дружбы
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friend_requests (
            from_user TEXT,
            to_user TEXT,
            PRIMARY KEY(from_user, to_user)
        )
    """)
    conn.commit()
    conn.close()

# ---------------- INIT Chat DB ----------------
def init_chat_db():
    conn = sqlite3.connect(CHAT_DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user TEXT NOT NULL,
            to_user TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# ----------------- Users -----------------
def add_user(login, password, nickname, avatar=""):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (login, password, nickname, avatar) VALUES (?, ?, ?, ?)",
            (login, password, nickname, avatar)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user(login):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT login, password, nickname, avatar FROM users WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"login": row[0], "password": row[1], "nickname": row[2], "avatar": row[3]}
    return None

def update_user(login, nickname, password=None, avatar=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if password:
        cursor.execute(
            "UPDATE users SET nickname=?, password=?, avatar=? WHERE login=?",
            (nickname, password, avatar, login)
        )
    else:
        cursor.execute(
            "UPDATE users SET nickname=?, avatar=? WHERE login=?",
            (nickname, avatar, login)
        )
    conn.commit()
    conn.close()

# ----------------- Server -----------------
def handle_client(conn, addr):
    try:
        data = conn.recv(4096)
        if not data:
            return
        data = json.loads(data.decode())
        action = data.get("action")

        # ------------------- AUTH -------------------
        if action == "register":
            login = data.get("login")
            password = data.get("password")
            nickname = data.get("nickname")
            avatar = data.get("avatar","")
            if add_user(login, password, nickname, avatar):
                resp = {"status":"ok"}
            else:
                resp = {"status":"error","message":"Логин уже занят"}

        elif action == "login":
            login = data.get("login")
            password = data.get("password")
            user = get_user(login)
            if not user:
                resp = {"status":"error","message":"Пользователь не найден"}
            elif user["password"] != password:
                resp = {"status":"error","message":"Неверный пароль"}
            else:
                online_users.add(login)  # добавляем в online_users
                resp = {
                    "status": "ok",
                    "login": login,
                    "nickname": user["nickname"],
                    "avatar": user.get("avatar", "") or "",
                    "online": True
                }

        elif action == "logout":
            login = data.get("login")
            online_users.discard(login)  # убираем из online_users
            resp = {"status":"ok"}

        elif action == "update_profile":
            login = data.get("login")
            nickname = data.get("nickname")
            password = data.get("password") or None
            avatar = data.get("avatar") or None
            update_user(login, nickname, password, avatar)
            resp = {"status":"ok"}

        elif action == "status":
            login = data.get("login")
            resp = {"status":"ok", "online": login in online_users}

        elif action == "find_user":
            login_to_find = data.get("login")
            user = get_user(login_to_find)
            if user:
                resp = {"status":"ok","login":user["login"],"nickname":user["nickname"],"avatar":user["avatar"]}
            else:
                resp = {"status":"error","message":"Пользователь не найден"}

        # ----------------- FRIEND REQUESTS -----------------
        elif action == "send_friend_request":
            from_user = data.get("from_user")
            to_user = data.get("to_user")
            conn_db = sqlite3.connect(DB_FILE)
            cursor = conn_db.cursor()
            try:
                cursor.execute(
                    "INSERT INTO friend_requests (from_user,to_user) VALUES (?,?)",
                    (from_user,to_user)
                )
                conn_db.commit()
                resp = {"status":"ok"}
            except sqlite3.IntegrityError:
                resp = {"status":"error","message":"Запрос уже отправлен"}
            finally:
                conn_db.close()

        elif action == "get_friend_requests":
            user = data.get("login")
            conn_db = sqlite3.connect(DB_FILE)
            cursor = conn_db.cursor()
            cursor.execute("SELECT from_user FROM friend_requests WHERE to_user=?", (user,))
            rows = cursor.fetchall()
            requests = [r[0] for r in rows]
            conn_db.close()
            resp = {"status":"ok","requests":requests}

        elif action == "accept_friend_request":
            user = data.get("login")
            from_user = data.get("from_user")
            conn_db = sqlite3.connect(DB_FILE)
            cursor = conn_db.cursor()
            cursor.execute("INSERT OR IGNORE INTO friends (user_login, friend_login) VALUES (?,?)", (user, from_user))
            cursor.execute("INSERT OR IGNORE INTO friends (user_login, friend_login) VALUES (?,?)", (from_user, user))
            cursor.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, user))
            conn_db.commit()
            conn_db.close()
            resp = {"status":"ok"}

        elif action == "decline_friend_request":
            user = data.get("login")
            from_user = data.get("from_user")
            conn_db = sqlite3.connect(DB_FILE)
            cursor = conn_db.cursor()
            cursor.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, user))
            conn_db.commit()
            conn_db.close()
            resp = {"status":"ok"}

        # ----------------- FRIENDS -----------------
        elif action == "get_friends":
            user_login = data.get("login")
            conn_db = sqlite3.connect(DB_FILE)
            cursor = conn_db.cursor()
            cursor.execute("""
                SELECT u.login, u.nickname, u.avatar
                FROM friends f1
                JOIN friends f2 ON f1.friend_login = f2.user_login
                JOIN users u ON f1.friend_login = u.login
                WHERE f1.user_login = ? AND f2.friend_login = ?
            """, (user_login, user_login))
            rows = cursor.fetchall()
            friends = []
            for r in rows:
                login_f = r[0]
                friends.append({
                    "login": login_f,
                    "nickname": r[1],
                    "avatar": r[2],
                    "online": login_f in online_users  # статус онлайн реально
                })
            conn_db.close()
            resp = {"status":"ok","friends":friends}

        # ----------------- CHAT MESSAGES -----------------
        elif action == "send_message":
            from_user = data.get("from_user")
            to_user = data.get("to_user")
            text = data.get("message")
            try:
                conn_db = sqlite3.connect(CHAT_DB_FILE)
                cursor = conn_db.cursor()
                cursor.execute(
                    "INSERT INTO messages (from_user, to_user, text) VALUES (?, ?, ?)",
                    (from_user, to_user, text)
                )
                conn_db.commit()
                resp = {"status":"ok"}
            except Exception as e:
                resp = {"status":"error","message": str(e)}
            finally:
                conn_db.close()

        elif action == "get_messages":
            from_user = data.get("from_user")
            to_user = data.get("to_user")
            try:
                conn_db = sqlite3.connect(CHAT_DB_FILE)
                cursor = conn_db.cursor()
                cursor.execute("""
                    SELECT from_user, to_user, text FROM messages
                    WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                    ORDER BY id ASC
                """, (from_user, to_user, to_user, from_user))
                rows = cursor.fetchall()
                messages = [{"from_user": r[0], "to_user": r[1], "text": r[2]} for r in rows]
                resp = {"status":"ok", "messages": messages}
            except Exception as e:
                resp = {"status":"error","message": str(e)}
            finally:
                conn_db.close()

        else:
            resp = {"status":"error","message":"Неизвестная команда"}

        conn.sendall(json.dumps(resp).encode())

    except Exception as e:
        print("Ошибка:", e)
    finally:
        conn.close()

# ----------------- Start Server -----------------
def start():
    init_db()
    init_chat_db()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1",5555))
    server.listen()
    print("[SERVER STARTED]")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn,addr), daemon=True).start()

if __name__ == "__main__":
    start()
