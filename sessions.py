import asyncio
import time

from portal import BwuClient, PortalError


class SessionManager:
    def __init__(self, ttl_minutes: int = 5, retries: int = 5, timeout: int = 240):
        self.ttl = ttl_minutes * 60
        self.retries = retries
        self.timeout = timeout
        self._sessions = {}
        self.total_logins = 0

    def _expired(self, entry: dict) -> bool:
        return (time.time() - entry["ts"]) > self.ttl

    def _close_async(self, client) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _run():
            try:
                await client.close()
            except Exception:
                pass

        loop.create_task(_run())

    async def login(self, user_id: int, code: str, password: str, progress=None) -> None:
        client = BwuClient(code, password, retries=self.retries, timeout=self.timeout)
        await client.login(progress)
        old = self._sessions.pop(user_id, None)
        if old:
            self._close_async(old["client"])
        self._sessions[user_id] = {
            "client": client,
            "code": code,
            "password": password,
            "ts": time.time(),
        }
        self.total_logins += 1

    def get(self, user_id: int):
        entry = self._sessions.get(user_id)
        if not entry:
            return None
        if self._expired(entry):
            self._sessions.pop(user_id, None)
            self._close_async(entry["client"])
            return None
        entry["ts"] = time.time()
        return entry["client"]

    def is_logged_in(self, user_id: int) -> bool:
        entry = self._sessions.get(user_id)
        if not entry:
            return False
        if self._expired(entry):
            self._sessions.pop(user_id, None)
            self._close_async(entry["client"])
            return False
        return True

    async def logout(self, user_id: int) -> bool:
        entry = self._sessions.pop(user_id, None)
        if not entry:
            return False
        try:
            await entry["client"].logout()
        except Exception:
            pass
        try:
            await entry["client"].close()
        except Exception:
            pass
        return True

    async def clear(self) -> int:
        users = list(self._sessions.keys())
        for user_id in users:
            await self.logout(user_id)
        return len(users)

    async def sweep(self) -> int:
        now = time.time()
        expired = [uid for uid, e in self._sessions.items() if now - e["ts"] > self.ttl]
        for user_id in expired:
            entry = self._sessions.pop(user_id, None)
            if entry:
                try:
                    await entry["client"].close()
                except Exception:
                    pass
        return len(expired)

    def user_ids(self) -> list:
        return list(self._sessions.keys())

    def hold_active(self, user_id: int) -> bool:
        entry = self._sessions.get(user_id)
        return bool(entry) and not self._expired(entry)

    def stats(self) -> dict:
        now = time.time()
        active = sum(1 for e in self._sessions.values() if now - e["ts"] <= self.ttl)
        return {
            "users": len(self._sessions),
            "active_within_ttl": active,
            "total_logins": self.total_logins,
            "ttl_minutes": self.ttl // 60,
        }


__all__ = ["SessionManager", "PortalError"]
