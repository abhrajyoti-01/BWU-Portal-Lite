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
    BufferedInputFile,
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
import parsers
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
att_pending = {}
gc_pending = {}
dp = Dispatcher()

STAGES = {
    "dash": "↪️ Redirecting to the dashboard…",
    "fees": "💳 Loading fee & payment details…",
    "att": "📊 Loading attendance…",
    "attsw": "📅 Loading semester-wise attendance…",
    "notices": "📢 Loading notices…",
    "marks": "📝 Loading marks…",
    "marks:cur": "📝 Loading semester list…",
    "fb": "📝 Loading feedback…",
    "logout": "🚪 Logout",
}
MARKS_STAGE = "⏳ Loading marks… (this page takes ~1 min)"
DATA_ROUTES = ("dash", "fees", "att", "notices", "marks", "fb")


def _reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📊 Dashboard"), KeyboardButton(text="💳 Fees & Payments")],
        [KeyboardButton(text="📝 Marks"), KeyboardButton(text="🎓 Attendance")],
        [KeyboardButton(text="📢 Notices"), KeyboardButton(text="🧾 Feedback")],
        [KeyboardButton(text="🚪 Logout")],
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


async def _stage(bot: Bot, chat_id: int, message_id: int, text: str):
    t, e = emoji.plain(text)
    for attempt in (
        lambda: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t, entities=_ents(e)),
        lambda: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    return None


async def _say(bot: Bot, chat_id: int, text: str):
    t, e = emoji.plain(text)
    for attempt in (
        lambda: bot.send_message(chat_id, t, entities=_ents(e)),
        lambda: bot.send_message(chat_id, text),
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


async def send_rich(bot: Bot, chat_id: int, html: str, kb: dict = None, effect: bool = False,
                    reply_to: int = None, rkb: ReplyKeyboardMarkup = None):
    try:
        return await bot(SendRichMessage(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=emoji.wrap_rich(html)),
            **({"reply_markup": rkb} if rkb else {}),
            **({"message_effect_id": config.TELEGRAM_EFFECT_ID} if effect and config.TELEGRAM_EFFECT_ID else {}),
            **({"reply_parameters": ReplyParameters(message_id=reply_to)} if reply_to else {}),
        ))
    except Exception:
        pass
    plain_text = messages.rich_to_plain(html)
    t, e = emoji.plain(plain_text)
    rp = ReplyParameters(message_id=reply_to) if reply_to else None
    for attempt in (
        lambda: bot.send_message(chat_id, t, entities=_ents(e), reply_markup=rkb or _kb(kb), reply_parameters=rp),
        lambda: bot.send_message(chat_id, plain_text, reply_markup=rkb or _kb(kb), reply_parameters=rp),
        lambda: bot.send_message(chat_id, plain_text, reply_markup=rkb or _kb(kb)),
    ):
        try:
            return await attempt()
        except Exception:
            continue
    return None


async def edit_rich(bot: Bot, chat_id: int, message_id: int, html: str, kb: dict = None):
    try:
        return await bot(EditMessageText(
            chat_id=chat_id,
            message_id=message_id,
            rich_message=InputRichMessage(html=emoji.wrap_rich(html)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
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


async def _flow(route: str, bot: Bot, chat_id: int, message_id: int, user_id: int,
                first_name: str = "", set_stage: bool = True):
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

        stage = MARKS_STAGE if route.startswith("m:") else STAGES.get(route)
        if set_stage and stage:
            await _stage(bot, chat_id, message_id, stage)

        if route == "dash":
            snap = await client.snapshot()
            dash = snap["dashboard"]
            dash["pay_rows"] = snap["payments"]["rows"]
            return await edit_rich(bot, chat_id, message_id, messages.dashboard_rich(dash, snap["name"], config.ATTENDANCE_THRESHOLD), messages.buttons_kb(messages.NAV))
        if route == "fees":
            pay = await client.payments()
            return await edit_rich(bot, chat_id, message_id, messages.payments_rich(pay, config.FEE_WARN_DAYS), messages.buttons_kb(messages.NAV))
        if route == "att":
            kb = messages.buttons_kb([
                [("📊 Current attendance", "att:cur")],
                [("📅 Semester-wise", "att:sw")],
                [("🏠 Menu", "menu")],
            ])
            return await edit_rich(bot, chat_id, message_id, messages.attendance_pick_rich(), kb)
        if route == "notices":
            dash = await client.dashboard()
            return await edit_rich(bot, chat_id, message_id, messages.notices_rich(dash["notices"], BASE_URL), messages.buttons_kb(messages.NAV))
        if route == "fb":
            return await _fb_courses(bot, chat_id, message_id, client, user_id)
        if route == "marks":
            kb = messages.buttons_kb([
                [("📊 Current marks", "marks:cur")],
                [("🎓 Semester grade card", "gc")],
                [("🏠 Menu", "menu")],
            ])
            return await edit_rich(bot, chat_id, message_id, messages.marks_pick_rich(), kb)
        if route == "marks:cur":
            options = await client.marks_options()
            kb = messages.buttons_kb(messages.semester_rows(options))
            return await edit_rich(bot, chat_id, message_id, messages.semester_menu_rich() + messages.buttons_html(messages.semester_rows(options)), kb)
        if route.startswith("m:"):
            sem = route.split(":", 1)[1]
            options = await client.marks_options()
            label = next((o["label"] for o in options if o["value"] == sem), f"Semester {sem}")
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


async def _fb_courses(bot: Bot, chat_id: int, message_id: int, client, user_id: int, note: str = ""):
    if message_id:
        await _stage(bot, chat_id, message_id, "📝 Loading feedback…")
    courses = await client.feedback_courses()
    kb = messages.buttons_kb(messages.feedback_course_rows(courses))
    return await edit_rich(bot, chat_id, message_id, messages.feedback_courses_rich(courses, note), kb)


async def _on_receipt(query: CallbackQuery, bot: Bot, chat_id: int, message_id, user_id: int, ref: str):
    client = manager.get(user_id)
    if not client:
        if message_id:
            await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())
        return
    if message_id:
        await _stage(bot, chat_id, message_id, "🧾 Downloading receipt…")
    buf = bytearray()
    sent = False
    try:
        buf, fname = await client.receipt_file(ref)
        doc = await bot.send_document(chat_id, BufferedInputFile(bytes(buf), filename=fname))
        manager.track(user_id, chat_id, doc.message_id)
        sent = True
    except Exception:
        sent = False
    finally:
        if buf:
            buf[:] = b"\x00" * len(buf)
            buf.clear()
    if message_id:
        base = "✅ Receipt sent. It is never stored on the server." if sent else "⚠️ Could not send receipt."
        rows = [[("🏠 Menu", "menu")]]
        await edit_rich(bot, chat_id, message_id, base + "\n" + messages.buttons_html(rows),
                        messages.buttons_kb(rows))


async def _on_feedback(query: CallbackQuery, bot: Bot, chat_id: int, message_id, user_id: int, data: str):
    client = manager.get(user_id)
    if not client:
        if message_id:
            await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())
        return
    try:
        if data == "fb":
            return await _fb_courses(bot, chat_id, message_id, client, user_id)

        if data.startswith("fba:"):
            _, idx_s, value = data.split(":", 2)
            state = manager.get_fb(user_id)
            if not state:
                return await _fb_courses(bot, chat_id, message_id, client, user_id, "<p>⏳ Please choose the course again.</p>")
            state["answers"][str(state["questions"][int(idx_s)]["n"])] = value
            manager.set_fb(user_id, state)
            nxt = int(idx_s) + 1
            if nxt < len(state["questions"]):
                return await edit_rich(bot, chat_id, message_id, messages.feedback_question_rich(state, nxt))
            return await edit_rich(bot, chat_id, message_id, messages.feedback_summary_rich(state))

        if data.startswith("fbs:"):
            state = manager.get_fb(user_id)
            if not state:
                return await _fb_courses(bot, chat_id, message_id, client, user_id, "<p>⏳ Please choose the course again.</p>")
            if message_id:
                await _stage(bot, chat_id, message_id, "📝 Submitting feedback…")
            fields = {}
            for q in state["questions"]:
                n = q["n"]
                fields[f"question_bank_id_{n}"] = q["question_bank_id"]
                fields[f"theory_lab_{n}"] = q["theory_lab"]
                fields[f"faculty_id_{n}"] = q["faculty_id"]
                fields[f"answer_no[{n}][]"] = state["answers"].get(str(n), "")
            fields.update(state["hidden"])
            fields["submit"] = "Submit"
            html = await client.feedback_submit(fields)
            manager.clear_fb(user_id)
            if "submitted successfully" in html:
                return await _fb_courses(bot, chat_id, message_id, client, user_id,
                                         "<b>✅ Your Feedback information submitted successfully!</b> You can switch course below:")
            return await _fb_courses(bot, chat_id, message_id, client, user_id,
                                     "<mark>⚠️ Submission failed.</mark> Choose the course to try again:")

        if data == "fbx":
            manager.clear_fb(user_id)
            return await _fb_courses(bot, chat_id, message_id, client, user_id)

        if data.startswith("fb:"):
            topic = data.split(":", 1)[1]
            if message_id:
                await _stage(bot, chat_id, message_id, "📝 Loading feedback form…")
            html = await client.feedback_proceed(topic)
            if parsers.feedback_status(html) == "taken":
                return await _fb_courses(bot, chat_id, message_id, client, user_id,
                                         "<mark>⚠️ Your feedback has been taken for this topic.</mark> Choose another:")
            parsed = parsers.parse_feedback_questions(html)
            if not parsed["questions"]:
                return await _fb_courses(bot, chat_id, message_id, client, user_id,
                                         "<p>⚠️ No questions found — choose another course.</p>")
            state = {
                "title": parsed["title"],
                "hidden": parsed["hidden"],
                "questions": parsed["questions"],
                "answers": {},
                "topic": topic,
            }
            manager.set_fb(user_id, state)
            return await edit_rich(bot, chat_id, message_id, messages.feedback_question_rich(state, 0))
    except Exception as exc:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⚠️ {escape(str(exc))}")
        except Exception:
            pass


async def _att_wise(bot: Bot, chat_id: int, message_id: int, user_id: int, sem: str,
                    from_date: str, to_date: str, label: str):
    client = manager.get(user_id)
    if not client:
        return await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())
    try:
        html = await client.attendance_wise(sem, from_date, to_date)
        parsed = parsers.parse_attendance_wise(html)
        data = {
            "attendance_pct": None,
            "courses": parsed["courses"],
            "total": parsed["total"],
            "subtitle": parsed["subtitle"],
        }
        await edit_rich(bot, chat_id, message_id,
                        messages.attendance_rich(
                            data,
                            config.ATTENDANCE_THRESHOLD,
                            f"Semester-wise · {label} · {from_date} → {to_date}",
                        ),
                        messages.buttons_kb(messages.NAV))
    except Exception as exc:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⚠️ {escape(str(exc))}")
        except Exception:
            pass


async def _on_attendance(query: CallbackQuery, bot: Bot, chat_id: int, message_id, user_id: int, data: str):
    client = manager.get(user_id)
    if not client:
        if message_id:
            await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())
        return
    try:
        if data == "att:cur":
            if message_id:
                await _stage(bot, chat_id, message_id, "📊 Loading attendance…")
            dash = await client.dashboard()
            await edit_rich(bot, chat_id, message_id,
                            messages.attendance_rich(dash, config.ATTENDANCE_THRESHOLD, "Current semester"),
                            messages.buttons_kb(messages.NAV))
            manager.track(user_id, chat_id, message_id)
            return

        if data == "att:sw":
            if message_id:
                await _stage(bot, chat_id, message_id, "📅 Loading semester-wise attendance…")
            form = await client.attendance_wise_form()
            att_pending[user_id] = {"from": form["from_date"], "to": form["to_date"], "options": form["options"]}
            rows = [[(o["label"], f"atsw:{o['value']}")] for o in form["options"]]
            rows.append([("🏠 Menu", "menu")])
            kb = messages.buttons_kb(rows)
            body = ("<h2>📅 Semester-wise attendance</h2>"
                    f"<p>Default window: <b>{form['from_date'] or '?'} → {form['to_date'] or '?'}</b></p>"
                    "<p>Choose semester:</p>" + messages.buttons_html(rows))
            return await edit_rich(bot, chat_id, message_id, body, kb)

        if data.startswith("atsw:"):
            sem = data.split(":", 1)[1]
            info = att_pending.setdefault(user_id, {})
            options = info.get("options") or []
            if not options:
                form = await client.attendance_wise_form()
                options = form["options"]
                info["from"], info["to"] = form["from_date"], form["to_date"]
            label = next((o["label"] for o in options if o["value"] == sem), f"Semester {sem}")
            info.update({"sem": sem, "label": label, "awaiting_date": True})
            from_d = info.get("from") or "?"
            to_d = info.get("to") or "?"
            kb = messages.buttons_kb([[("⏩ Use default window", f"atswd:{sem}")], [("🏠 Menu", "menu")]])
            body = (f"<h2>📅 {escape(label)}</h2>"
                    f"<p>Window: <b>{escape(from_d)}</b> → <b>{escape(to_d)}</b></p>"
                    "<p>Send a <b>From Date</b> as <code>YYYY-MM-DD</code> —<br/>"
                    "or tap ⏩ to use the default window:</p>" + messages.buttons_html([[("⏩ Use default window", f"atswd:{sem}")], [("🏠 Menu", "menu")]]))
            return await edit_rich(bot, chat_id, message_id, body, kb)

        if data.startswith("atswd:"):
            sem = data.split(":", 1)[1]
            info = att_pending.get(user_id, {})
            options = info.get("options") or []
            label = next((o["label"] for o in options if o["value"] == sem), f"Semester {sem}")
            from_d = info.get("from") or (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            to_d = info.get("to") or datetime.now().strftime("%Y-%m-%d")
            att_pending.pop(user_id, None)
            if message_id:
                await _stage(bot, chat_id, message_id, "📅 Loading semester-wise attendance…")
            await _att_wise(bot, chat_id, message_id, user_id, sem, from_d, to_d, label)
            manager.track(user_id, chat_id, message_id)
            return
    except Exception as exc:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⚠️ {escape(str(exc))}")
        except Exception:
            pass


async def _on_grade_card(query: CallbackQuery, bot: Bot, chat_id: int, message_id, user_id: int, data: str):
    client = manager.get(user_id)
    if not client:
        if message_id:
            await edit_rich(bot, chat_id, message_id, messages.login_prompt_rich())
        return
    state = gc_pending.setdefault(user_id, {})
    try:
        if data == "gc":
            if message_id:
                await _stage(bot, chat_id, message_id, "🎓 Loading grade card form…")
            form = await client.grade_card_form()
            state.clear()
            years = form["years"]
            default_year = form.get("year_default") or (years[0]["value"] if years else None)
            state.update({
                "course_id": form["course_id"],
                "years": years,
                "student_type": form.get("student_type") or "R",
                "year": default_year,
                "year_label": next((y["label"] for y in years if y["value"] == default_year), default_year),
            })
            note = "Year is preselected — tap to change. Choose a session to continue."
            return await edit_rich(bot, chat_id, message_id, messages.gc_session_rich(state, note),
                                   messages.buttons_kb(messages.gc_session_rows(state)))

        if data.startswith("gce:") or data.startswith("gcy:"):
            if data.startswith("gce:"):
                state["even_odd"] = data.split(":", 1)[1]
            else:
                year = data.split(":", 1)[1]
                state["year"] = year
                state["year_label"] = next((y["label"] for y in state.get("years", []) if y["value"] == year), year)
            if state.get("even_odd") and state.get("year"):
                parity = state["even_odd"]
                kb = messages.buttons_kb(messages.gc_sem_rows(parity))
                return await edit_rich(bot, chat_id, message_id, messages.gc_sem_rich(parity), kb)
            note = "Now choose the examination year." if state.get("even_odd") else "Now choose the exam session."
            return await edit_rich(bot, chat_id, message_id, messages.gc_session_rich(state, note),
                                   messages.buttons_kb(messages.gc_session_rows(state)))

        if data.startswith("gcs:"):
            sem = data.split(":", 1)[1]
            state["sem"] = sem
            state["sem_label"] = messages.SEM_LABELS.get(sem, sem)
            if message_id:
                await _stage(bot, chat_id, message_id, "🎓 Fetching grade card…")
            html = await client.grade_card_show(
                state.get("course_id"), state.get("even_odd", "O"), sem,
                state.get("year") or "", state.get("student_type") or "R",
            )
            rows = parsers.parse_grade_card_result(html)
            if rows:
                state["link"] = rows[0]["link"]
                manager.track(user_id, chat_id, message_id)
            kb = messages.buttons_kb(
                [[("🎓 Download Grade Card", "gcd:1")], [("🏠 Menu", "menu")]]
                if rows else
                [[("🔀 Change session / year", "gc")], [("🏠 Menu", "menu")]]
            )
            return await edit_rich(bot, chat_id, message_id, messages.gc_result_rich(rows, state), kb)

        if data.startswith("gcd:"):
            link = state.get("link")
            if not link:
                return await edit_rich(bot, chat_id, message_id, messages.gc_session_rich(state),
                                       messages.buttons_kb(messages.gc_session_rows(state)))
            if message_id:
                await _stage(bot, chat_id, message_id, "🎓 Downloading grade card…")
            buf = bytearray()
            sent = False
            try:
                name = f"grade-card-{state.get('sem_label', '')}-{state.get('year_label', '')}".replace(" ", "-")
                buf, fname = await client.grade_card_file(link, name)
                doc = await bot.send_document(chat_id, BufferedInputFile(bytes(buf), filename=fname))
                manager.track(user_id, chat_id, doc.message_id)
                sent = True
            except Exception:
                sent = False
            finally:
                if buf:
                    buf[:] = b"\x00" * len(buf)
                    buf.clear()
            gc_pending.pop(user_id, None)
            if message_id:
                base = "✅ Grade card sent. It is never stored on the server." if sent else "⚠️ Could not send grade card."
                rows = [[("🏠 Menu", "menu")]]
                await edit_rich(bot, chat_id, message_id, base + "\n" + messages.buttons_html(rows),
                                messages.buttons_kb(rows))
                if sent:
                    manager.track(user_id, chat_id, message_id)
            return
    except Exception as exc:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"⚠️ {escape(str(exc))}")
        except Exception:
            pass


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    name = user.first_name if user and user.first_name else "there"
    is_admin = user.id == config.ADMIN_USER_ID
    if manager.is_logged_in(user.id):
        text = messages.menu_rich(name)
    else:
        text = messages.welcome_rich(name, is_admin)
    await send_rich(message.bot, message.chat.id, text, effect=True, reply_to=message.message_id,
                    rkb=_reply_kb(is_admin))


@dp.message(Command("login"))
async def cmd_login(message: Message, command: CommandObject):
    parsed = _parse_login_args(command.args or "")
    if not parsed:
        await _reply(message, "Usage:\n/login STUDENT_CODE:PASSWORD\nor /login STUDENT_CODE PASSWORD")
        return
    code, password = parsed
    try:
        await message.delete()
    except Exception:
        pass
    msg = await _say(message.bot, message.chat.id, "🧩 Bypassing captcha…")
    if msg is None:
        return
    try:
        await manager.login(message.from_user.id, code, password)
    except PortalError as exc:
        await _edit(msg, f"⚠️ Login failed: {escape(str(exc))}")
        return
    except Exception as exc:
        await _edit(msg, f"⚠️ Login error: {escape(str(exc))}")
        return
    await _edit(msg, "↪️ Redirecting to the dashboard…")
    client = manager.get(message.from_user.id)
    manager.track(message.from_user.id, msg.chat.id, msg.message_id)
    try:
        snap = await client.snapshot()
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


@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    msg = await _reply(message, STAGES["logout"])
    if msg is not None:
        await _flow("logout", message.bot, msg.chat.id, msg.message_id, message.from_user.id, set_stage=False)


@dp.message(F.text)
async def on_text(message: Message):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    if message.from_user.id in att_date_wait:
        info = att_date_wait[message.from_user.id]
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            await _reply(message, "⚠️ Send the From Date as YYYY-MM-DD (e.g. 2026-09-01)")
            return
        att_date_wait.pop(message.from_user.id, None)
        msg = await _reply(message, STAGES["attsw"])
        if msg is None:
            return
        await _att_wise(message.bot, msg.chat.id, msg.message_id, message.from_user.id,
                        info["sem"], text, info["to"], info["label"])
        manager.track(message.from_user.id, msg.chat.id, msg.message_id)
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

    route = {
        "📊 Dashboard": "dash",
        "💳 Fees & Payments": "fees",
        "📝 Marks": "marks",
        "🎓 Attendance": "att",
        "📢 Notices": "notices",
        "🧾 Feedback": "fb",
        "🚪 Logout": "logout",
        "⚙️ Admin": "admin",
    }.get(text)
    if not route:
        return
    msg = await _reply(message, STAGES.get(route, "⏳ Loading…"))
    if msg is None:
        return
    await _flow(route, message.bot, msg.chat.id, msg.message_id, message.from_user.id,
                message.from_user.first_name or "", set_stage=False)
    if route in DATA_ROUTES or route.startswith("m:"):
        manager.track(message.from_user.id, msg.chat.id, msg.message_id)


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
            await send_rich(bot, chat_id, text)
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
            if message_id:
                await _qedit(query, "⛔ Admin only.")
            return
        n = await manager.clear()
        await _qedit(query, f"🧹 Cleared {n} stored session(s).")
        return

    if data.startswith("rcpt:"):
        await _on_receipt(query, bot, chat_id, message_id, user.id, data.split(":", 1)[1])
        return

    if data.startswith("att:") or data.startswith("atsw:") or data.startswith("atswd:"):
        await _on_attendance(query, bot, chat_id, message_id, user.id, data)
        return

    if data == "gc" or data.startswith(("gce:", "gcs:", "gcy:", "gcd:")):
        await _on_grade_card(query, bot, chat_id, message_id, user.id, data)
        return

    if data.startswith("fb"):
        await _on_feedback(query, bot, chat_id, message_id, user.id, data)
        return

    route = "menu" if data == "menu" else data
    if message_id is None:
        await send_rich(bot, chat_id, messages.menu_rich(user.first_name or ""), messages.buttons_kb(messages.NAV))
        return
    await _flow(route, bot, chat_id, message_id, user.id, user.first_name or "")
    if route in DATA_ROUTES or route.startswith("m:"):
        manager.track(user.id, chat_id, message_id)


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

    async def _delete_tracked(user_id: int, msgs) -> None:
        for chat_id, message_id in msgs:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception:
                pass

    manager.on_cleanup = _delete_tracked
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
