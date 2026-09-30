import asyncio
import re
import secrets
import time

import arequest

import parsers
from ocr import solve

BASE = "https://www.brainwareuniversity.ac.in/studentselfservice"
CAPTCHA_URL = "https://www.brainwareuniversity.ac.in/securimage_univ/securimage_show_buis_student.php"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)
LOGIN_OK_MARKER = "window.location='redirect-to-dashboard.php'"
LOGIN_FAIL_MARKER = 'incorrect-login">'
LOGGED_OUT_MARKER = "window.location='index.php?action=logout'"


class PortalError(RuntimeError):
    pass


def _progress(callback, text: str) -> None:
    if callback is None:
        return
    try:
        callback(text)
    except Exception:
        pass


class BwuClient:
    def __init__(self, student_code: str, password: str, retries: int = 5, timeout: int = 240):
        self.student_code = student_code
        self.password = password
        self.retries = retries
        self.timeout = timeout
        self._login_lock = asyncio.Lock()
        self._logged_in = False
        self._session = arequest.Session(
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=float(timeout),
            cookies={"PHPSESSID": secrets.token_hex(16)},
            allow_redirects=True,
        )

    async def _request(self, method: str, url: str, referer: str, **kwargs):
        resp = await self._session.request(method, url, referer=referer, **kwargs)
        resp.raise_for_status()
        return resp

    async def _login_once(self, progress=None) -> bool:
        _progress(progress, "🖼️ Fetching captcha image…")
        img = (await self._request("GET", CAPTCHA_URL, f"{BASE}/", params={"_": int(time.time())})).content
        _progress(progress, "🧩 Solving captcha…")
        code = await asyncio.to_thread(solve, img)
        data = {
            "student_code": self.student_code,
            "password": self.password,
            "captcha_code": code,
            "login": "Login",
        }
        _progress(progress, "🔑 Submitting credentials…")
        body = (await self._request("POST", f"{BASE}/", f"{BASE}/", data=data)).text
        if LOGIN_OK_MARKER in body:
            return True
        if LOGIN_FAIL_MARKER in body:
            m = re.search(r'(?s)<span class="d-block bg-danger.*?>(.*?)</span>', body)
            detail = parsers.clean(m.group(1)) if m else "unknown error"
            raise ValueError(f"rejected: {detail} (code={code!r})")
        raise ValueError(f"unexpected login response (code={code!r})")

    async def _login_locked(self, progress=None) -> None:
        self._logged_in = False
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                _progress(progress, f"🔐 Login attempt {attempt}/{self.retries}")
                await self._login_once(progress)
                self._logged_in = True
                _progress(progress, "✅ Login OK!")
                return
            except ValueError as exc:
                last = exc
                _progress(progress, f"❌ {exc} — retrying…")
                await asyncio.sleep(3)
        raise PortalError(f"login failed after {self.retries} attempts: {last}")

    async def login(self, progress=None) -> None:
        async with self._login_lock:
            await self._login_locked(progress)

    async def _page(self, method: str, path: str, referer: str, data=None) -> str:
        if not self._logged_in:
            async with self._login_lock:
                if not self._logged_in:
                    await self._login_locked()
        url = path if path.startswith("http") else f"{BASE}/{path}"
        body = (await self._request(method, url, referer, data=data)).text
        if LOGGED_OUT_MARKER in body:
            async with self._login_lock:
                await self._login_locked()
            body = (await self._request(method, url, referer, data=data)).text
        return body

    async def logout(self) -> None:
        async with self._login_lock:
            try:
                await self._request("GET", "index.php?action=logout", f"{BASE}/")
            except Exception:
                pass
            self._logged_in = False

    async def close(self) -> None:
        try:
            await self._session.close()
        except Exception:
            pass

    async def welcome_html(self) -> str:
        return await self._page("GET", "redirect-to-dashboard.php", f"{BASE}/")

    async def dashboard_html(self) -> str:
        return await self._page("GET", "student-how-to-use.php", f"{BASE}/redirect-to-dashboard.php")

    async def payments_html(self) -> str:
        return await self._page("GET", "centre-student-payment.php?opt=show&type=n", f"{BASE}/redirect-to-dashboard.php")

    async def marks_html(self, semester_id: str) -> str:
        return await self._page(
            "POST",
            "centre-student-marks.php",
            f"{BASE}/centre-student-marks.php",
            data={"module_semester_id": str(semester_id), "show": "show"},
        )

    async def student_name(self) -> str:
        m = parsers.NAME_H1_RE.search(await self.welcome_html())
        return parsers.clean(m.group(1)) if m else "Student"

    async def dashboard(self) -> dict:
        return parsers.parse_dashboard(await self.dashboard_html())

    async def payments(self) -> dict:
        return parsers.parse_payments(await self.payments_html())

    async def marks(self, semester_id: str) -> dict:
        return parsers.parse_marks(await self.marks_html(semester_id))

    async def _options(self) -> list:
        body = await self._page(
            "POST",
            "centre-student-marks.php",
            f"{BASE}/centre-student-marks.php",
            data={"module_semester_id": "-1"},
        )
        return parsers.parse_marks(body)["options"]

    async def marks_options(self) -> list:
        return await self._options()

    async def snapshot(self, progress=None) -> dict:
        _progress(progress, "👤 Verifying session…")
        _progress(progress, "📊 Loading dashboard…")
        results = await asyncio.gather(
            self.student_name(),
            self.dashboard(),
            self.payments(),
            return_exceptions=True,
        )
        _progress(progress, "💳 Loading fee & payment details…")
        name = results[0] if isinstance(results[0], str) else "Student"
        dash = results[1] if isinstance(results[1], dict) else {
            "attendance_pct": None, "fee_amount": None, "fee_due": None,
            "activities": None, "exam_score": None, "exam_status": None,
            "courses": [], "notices": [],
        }
        pay = results[2] if isinstance(results[2], dict) else {"rows": [], "upcoming_amount": None, "upcoming_due": None}
        _progress(progress, "🏠 Main dashboard")
        return {"dashboard": dash, "payments": pay, "name": name}
