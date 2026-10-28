"""FriendshipService: explicit dependencies, independent of socket dispatch."""
try:
    from ..storage.database import connect as database_connection
except ImportError:
    from storage.database import connect as database_connection
class FriendshipService:
    def __init__(self, database, accounts, calls):
        self.database, self.accounts, self.calls = database, accounts, calls

    def send_friend_request(self, from_user: str, to_user: str) -> bool:
        if from_user == to_user:
            return False
        if not self.accounts.user_exists(to_user):
            return False

        with database_connection(self.database) as conn:
            cur = conn.cursor()
            # already friends?
            cur.execute(
                "SELECT 1 FROM friends WHERE (user_login=? AND friend_login=?) OR (user_login=? AND friend_login=?)",
                (from_user, to_user, to_user, from_user),
            )
            if cur.fetchone():
                return False

            # pending already?
            cur.execute("SELECT 1 FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
            if cur.fetchone():
                return False

            cur.execute("INSERT INTO friend_requests(from_user, to_user) VALUES(?,?)", (from_user, to_user))
            conn.commit()
            return True

    def get_friend_requests(self, to_user: str) -> list:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute("SELECT from_user FROM friend_requests WHERE to_user=?", (to_user,))
            return [r[0] for r in cur.fetchall()]

    def accept_friend_request(self, from_user: str, to_user: str) -> bool:
        if (not from_user) or (not to_user) or (from_user == to_user):
            return False

        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
            # Принять можно только существующую заявку.
            if cur.rowcount <= 0:
                conn.commit()
                return False

            cur.execute("INSERT OR IGNORE INTO friends(user_login, friend_login) VALUES(?,?)", (from_user, to_user))
            cur.execute("INSERT OR IGNORE INTO friends(user_login, friend_login) VALUES(?,?)", (to_user, from_user))
            conn.commit()
        return True

    def decline_friend_request(self, from_user: str, to_user: str) -> bool:
        if (not from_user) or (not to_user) or (from_user == to_user):
            return False

        with database_connection(self.database) as conn:
            cur = conn.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
            conn.commit()
        return cur.rowcount > 0

    def get_friends(self, login: str) -> list:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute("SELECT friend_login FROM friends WHERE user_login=? AND friend_login<>?", (login, login))
            return [r[0] for r in cur.fetchall()]

    def are_friends(self, user_a: str, user_b: str) -> bool:
        if not user_a or not user_b or user_a == user_b:
            return False
        with database_connection(self.database, timeout=10) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM friends
                WHERE (user_login=? AND friend_login=?)
                   OR (user_login=? AND friend_login=?)
                LIMIT 1
                """,
                (user_a, user_b, user_b, user_a),
            ).fetchone()
            return bool(row)

    def remove_friend(self, current_user: str, friend_login: str) -> bool:
        """Remove friendship in both directions and clear pending requests between users."""
        if (not current_user) or (not friend_login) or (current_user == friend_login):
            return False

        with database_connection(self.database) as conn:
            cur = conn.cursor()

            # remove accepted friendship in both directions
            cur.execute(
                "DELETE FROM friends WHERE (user_login=? AND friend_login=?) OR (user_login=? AND friend_login=?)",
                (current_user, friend_login, friend_login, current_user),
            )
            deleted_friends = cur.rowcount

            # also clear pending requests in both directions (if any)
            cur.execute(
                "DELETE FROM friend_requests WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)",
                (current_user, friend_login, friend_login, current_user),
            )
            deleted_requests = cur.rowcount

            conn.commit()

        self.calls.finish(current_user, friend_login)
        return (deleted_friends > 0) or (deleted_requests > 0)
