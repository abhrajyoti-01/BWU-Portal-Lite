import asyncio
import logging
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.methods import EditMessageText, SendRichMessage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardMarkup,
    InputRichMessage,
    KeyboardButton,
    Message,
    MessageEntity,
    ReplyKeyboardMarkup,
    ReplyParameters,
)

import config
import emoji
import messages
from portal import PortalError
from sessions import SessionManager

logging.disable(logging.CRITICAL)

BASE_URL = "https://www.brainwareuniversity.ac.in/studentselfservice"

manager = SessionManager(
    ttl_minutes=config.SESSION_TTL_MIN,
    retries=config.LOGIN_RETRIES,
    timeout=config.HTTP_TIMEOUT,
)
pending_broadcast = set()
dp = Dispatcher()

ROUTES = {
    "📊 Dashboard": "dash",
    "💳 Fees & Payments": "fees",
    "📝 Marks": "marks",
    "🎓 Attendance": "att",
    "📢 Notices": "notices",
    "🚪 Logout": "logout",
    "⚙️ Admin": "admin",
}


def _reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📊 Dashboard"), KeyboardButton(text="💳 Fees & Payments")],
        [KeyboardButton(text="📝 Marks"), KeyboardButton(text="🎓 Attendance")],
        [KeyboardButton(text="📢 Notices"), KeyboardButton(text="🚪 Logout")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _kb(kb: dict = None):
    return InlineKeyboardMarkup.model_validate(kb) if kb else None


def _ents(ents: list):
    return [MessageEntity.model_validate(e) for e in ents]


def _parse_login_args(text: str):
    s = (text or "").strip()
    if not s:
        return None
    if ":" in s:
        code, _, password = s.partition(":")
    else:
        parts = s.split(None, 1)
        if len(parts) != 2:
            return None
        code, password = parts
    code, password = code.strip().upper(), password.strip()
    if not code or not password:
        return None
    return code, password


class _ProgressEditor:
    def __init__(self, bot: Bot, chat_id: int, message_id: int):
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._loop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()
        self._last = ""

    def __call__(self, text: str) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._set(text), self._loop)
        except Exception:
            pass

    async def _set(self, text: str) -> None:
        async with self._lock:
            if text == self._last:
                return
            self._last = text
            t, e = emoji.plain(text)
            for attempt in (
                lambda: self._bot.edit_message_text(chat_id=self._chat_id, message_id=self._message_id, text=t, entities=_ents(e)),
                lambda: self._bot.edit_message_text(chat_id=self._chat_id, message_id=self._message_id, text=text),
            ):
                try:
                    await attempt()
                    return
                except Exception:
                    continue


async def _edit(message: Message, text: str):
    t, e = emoji.plain(text)
    for attempt in (
        lambda: message.edit_text(t, entities=_ents(e)),
        lambda: message.edit_text(text),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    return None


async def _reply(message: Message, text: str):
    t, e = emoji.plain(text)
    params = ReplyParameters(message_id=message.message_id)
    for attempt in (
        lambda: message.answer(t, entities=_ents(e), reply_parameters=params),
        lambda: message.answer(text, reply_parameters=params),
        lambda: message.answer(text),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    return None


async def _qedit(query: CallbackQuery, text: str):
    if not query.message:
        return None
    return await _edit(query.message, text)


async def send_rich(bot: Bot, chat_id: int, html: str, kb: dict = None, effect: bool = False, reply_to: int = None):
    try:
        return await bot(SendRichMessage(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=emoji.wrap_rich(html)),
            **({"message_effect_id": config.TELEGRAM_EFFECT_ID} if effect and config.TELEGRAM_EFFECT_ID else {}),
            **({"reply_parameters": ReplyParameters(message_id=reply_to)} if reply_to else {}),
        ))
    except Exception:
        pass
    plain_text = messages.rich_to_plain(html)
    t, e = emoji.plain(plain_text)
    rp = ReplyParameters(message_id=reply_to) if reply_to else None
    for attempt in (
        lambda: bot.send_message(chat_id, t, entities=_ents(e), reply_markup=_kb(kb), reply_parameters=rp),
        lambda: bot.send_message(chat_id, plain_text, reply_markup=_kb(kb), reply_parameters=rp),
        lambda: bot.send_message(chat_id, plain_text, reply_markup=_kb(kb)),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    return None


async def edit_rich(bot: Bot, chat_id: int, message_id: int, html: str, kb: dict = None):
    params = {"chat_id": chat_id, "message_id": message_id, "rich_message": {"html": emoji.wrap_rich(html)}}
    if kb:
        params["reply_markup"] = kb
    try:
        return await bot(EditMessageText(
            chat_id=chat_id,
            message_id=message_id,
            rich_message=InputRichMessage(html=emoji.wrap_rich(html)),
        ))
    except Exception:
        pass
    plain_text = messages.rich_to_plain(html)
    t, e = emoji.plain(plain_text)
    for attempt in (
        lambda: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t, entities=_ents(e), reply_markup=_kb(kb)),
        lambda: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=plain_text, reply_markup=_kb(kb)),
        lambda: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=plain_text),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    try:
        return await bot.send_message(chat_id, plain_text, reply_markup=_kb(kb))
    except Exception:
        return None


async def _flow(route: str, bot: Bot, chat_id: int, message_id: int, user_id: int, first_name: str = ""):
    try:
        if route == "logout":
            kb = messages.buttons_kb([[("✅ Yes, logout", "logout:yes"), ("❌ Cancel", "menu")]])
            return await edit_rich(bot, chat_id, message_id, messages.logout_confirm_rich(), kb)

        if route == "admin":
            if user_id != config.ADMIN_USER_ID:
                return await edit_rich(bot, chat_id, message_id, "⛔ Admin only.")
            return await edit_rich(bot, chat_id, message_id, messages.admin_rich(manager.stats()))

        client = manager.get(user_id)
        if not client:
            return await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())

        if route == "menu":
            return await edit_rich(bot, chat_id, message_id, messages.menu_rich(first_name), messages.buttons_kb(messages.NAV))
        if route == "dash":
            editor = _ProgressEditor(bot, chat_id, message_id)
            snap = await client.snapshot(editor)
            dash = snap["dashboard"]
            dash["pay_rows"] = snap["payments"]["rows"]
            return await edit_rich(bot, chat_id, message_id, messages.dashboard_rich(dash, snap["name"], config.ATTENDANCE_THRESHOLD), messages.buttons_kb(messages.NAV))
        if route == "fees":
            editor = _ProgressEditor(bot, chat_id, message_id)
            editor("💳 Loading fee & payment details…")
            pay = await client.payments()
            return await edit_rich(bot, chat_id, message_id, messages.payments_rich(pay, config.FEE_WARN_DAYS), messages.buttons_kb(messages.NAV))
        if route == "att":
            editor = _ProgressEditor(bot, chat_id, message_id)
            editor("📊 Loading attendance…")
            dash = await client.dashboard()
            return await edit_rich(bot, chat_id, message_id, messages.attendance_rich(dash, config.ATTENDANCE_THRESHOLD), messages.buttons_kb(messages.NAV))
        if route == "notices":
            editor = _ProgressEditor(bot, chat_id, message_id)
            editor("📢 Loading notices…")
            dash = await client.dashboard()
            return await edit_rich(bot, chat_id, message_id, messages.notices_rich(dash["notices"], BASE_URL), messages.buttons_kb(messages.NAV))
        if route == "marks":
            options = await client.marks_options()
            kb = messages.buttons_kb(messages.semester_rows(options))
            return await edit_rich(bot, chat_id, message_id, messages.semester_menu_rich() + messages.buttons_html(messages.semester_rows(options)), kb)
        if route.startswith("m:"):
            sem = route.split(":", 1)[1]
            editor = _ProgressEditor(bot, chat_id, message_id)
            editor("⏳ Loading marks… (this page takes ~1 min)")
            options = await client.marks_options()
            label = next((o["label"] for o in options if o["value"] == sem), f"Semester {sem}")
            editor(f"📝 Fetching {label} marks record…")
            marks = await client.marks(sem)
            kb = messages.buttons_kb(messages.semester_rows(options))
            return await edit_rich(bot, chat_id, message_id, messages.marks_rich(marks, label, options), kb)
    except Exception as exc:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⚠️ {escape(str(exc))}")
        except Exception:
            try:
                await bot.send_message(chat_id, f"⚠️ {escape(str(exc))}")
            except Exception:
                pass
    return None


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    name = user.first_name if user and user.first_name else "there"
    is_admin = user.id == config.ADMIN_USER_ID
    if manager.is_logged_in(user.id):
        text = messages.menu_rich(name)
    else:
        text = messages.welcome_rich(name, is_admin)
    await send_rich(message.bot, message.chat.id, text, effect=True, reply_to=message.message_id)
    await message.answer("Menu:", reply_markup=_reply_kb(is_admin))


@dp.message(Command("login"))
async def cmd_login(message: Message, command: CommandObject):
    parsed = _parse_login_args(command.args or "")
    if not parsed:
        await _reply(message, "Usage:\n/login STUDENT_CODE:PASSWORD\nor /login STUDENT_CODE PASSWORD")
        return
    code, password = parsed
    msg = await _reply(message, "🚀 Start login…")
    if msg is None:
        return
    editor = _ProgressEditor(message.bot, msg.chat.id, msg.message_id)
    try:
        await manager.login(message.from_user.id, code, password, editor)
    except PortalError as exc:
        await _edit(msg, f"⚠️ Login failed: {escape(str(exc))}")
        return
    except Exception as exc:
        await _edit(msg, f"⚠️ Login error: {escape(str(exc))}")
        return
    client = manager.get(message.from_user.id)
    try:
        snap = await client.snapshot(editor)
        dash = snap["dashboard"]
        dash["pay_rows"] = snap["payments"]["rows"]
        await edit_rich(
            message.bot,
            msg.chat.id,
            msg.message_id,
            messages.dashboard_rich(dash, snap["name"], config.ATTENDANCE_THRESHOLD),
            messages.buttons_kb(messages.NAV),
        )
    except Exception:
        await edit_rich(
            message.bot, msg.chat.id, msg.message_id, messages.login_ok_rich(code), messages.buttons_kb(messages.NAV)
        )
    await message.answer("Menu:", reply_markup=_reply_kb(message.from_user.id == config.ADMIN_USER_ID))


@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    msg = await _reply(message, "🚪 Logout")
    if msg is not None:
        await _flow("logout", message.bot, msg.chat.id, msg.message_id, message.from_user.id)


@dp.message(F.text)
async def on_text(message: Message):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    if message.from_user.id in pending_broadcast and message.from_user.id == config.ADMIN_USER_ID:
        pending_broadcast.discard(message.from_user.id)
        if not text:
            return
        sent = 0
        for user_id in manager.user_ids():
            try:
                await send_rich(message.bot, user_id, f"<h2>📣 Admin broadcast</h2><p>{escape(text)}</p>")
                sent += 1
            except Exception:
                pass
        await _reply(message, f"📣 Broadcast sent to {sent} user(s).")
        return

    route = ROUTES.get(text)
    if not route:
        return
    status = {"dash": "📊 Loading dashboard…", "fees": "💳 Loading fee & payment details…",
              "att": "📊 Loading attendance…", "notices": "📢 Loading notices…",
              "marks": "📝 Loading semester list…", "logout": "🚪 Logout"}.get(route, "⏳ Loading…")
    msg = await _reply(message, status)
    if msg is None:
        return
    await _flow(route, message.bot, msg.chat.id, msg.message_id, message.from_user.id, message.from_user.first_name or "")


@dp.callback_query(F.data)
async def on_callback(query: CallbackQuery):
    user = query.from_user
    await query.answer()
    data = query.data or ""
    bot = query.bot
    chat_id = query.message.chat.id if query.message else user.id
    message_id = query.message.message_id if query.message else None

    if data == "logout:yes":
        removed = await manager.logout(user.id)
        text = messages.logged_out_rich() if removed else messages.login_prompt_rich()
        if message_id:
            await edit_rich(bot, chat_id, message_id, text)
        else:
            await send_rich(bot, chat_id, text, reply_to=None)
        return

    if data == "admin:broadcast":
        if user.id != config.ADMIN_USER_ID:
            if message_id:
                await _qedit(query, "⛔ Admin only.")
            return
        pending_broadcast.add(user.id)
        await _qedit(query, "📣 Send the broadcast text now (plain text message).")
        return

    if data == "admin:clear":
        if user.id != config.ADMIN_USER_ID:
            await _qedit(query, "⛔ Admin only.")
            return
        n = await manager.clear()
        await _qedit(query, f"🧹 Cleared {n} stored session(s).")
        return

    route = "menu" if data == "menu" else data
    if message_id is None:
        await send_rich(bot, chat_id, messages.menu_rich(user.first_name or ""), messages.buttons_kb(messages.NAV))
        return
    await _flow(route, bot, chat_id, message_id, user.id, user.first_name or "")


async def _run_digest(bot: Bot) -> None:
    for user_id in manager.user_ids():
        client = manager.get(user_id)
        if not client:
            continue
        try:
            snap = await client.snapshot()
        except PortalError:
            continue
        data = snap["dashboard"]
        data["pay_rows"] = snap["payments"]["rows"]
        try:
            await send_rich(bot, user_id, messages.dashboard_rich(data, snap["name"], config.ATTENDANCE_THRESHOLD), effect=True)
        except Exception:
            pass


async def _digest_loop(bot: Bot) -> None:
    if not config.DIGEST_AT:
        return
    hh, _, mm = config.DIGEST_AT.partition(":")
    tz = ZoneInfo(config.TZ)
    while True:
        now = datetime.now(tz)
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await _run_digest(bot)


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await manager.sweep()
        except Exception:
            pass


async def _on_startup(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="login", description="Log in: /login CODE:PASSWORD"),
        BotCommand(command="logout", description="Log out of the portal"),
    ])
    asyncio.create_task(_digest_loop(bot))
    asyncio.create_task(_sweep_loop())


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is required (see .env.example)")
    bot = Bot(config.BOT_TOKEN)
    dp.startup.register(_on_startup)
    dp.run_polling(bot)


if __name__ == "__main__":
    main()
