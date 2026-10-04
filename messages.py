import re
from datetime import datetime, timedelta
from html import escape

BANNER_2 = "https://www.brainwareuniversity.ac.in/studentselfservice/images/login.jpg"

NAV = [
    [("📊 Dashboard", "dash"), ("💳 Fees & Payments", "fees")],
    [("📝 Marks", "marks"), ("🎓 Attendance", "att")],
    [("📢 Notices", "notices"), ("🧾 Feedback", "fb")],
    [("🚪 Logout", "logout"), ("🏠 Menu", "menu")],
]


def money(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return f"{int(digits):,}" if digits else (value or "-")


def buttons_html(rows: list) -> str:
    out = []
    for row in rows:
        cells = "".join(
            f'<tg-button type="callback_data" data="{escape(data, quote=True)}">{escape(label)}</tg-button>'
            for label, data in row
        )
        out.append(f"<tg-button-row>{cells}</tg-button-row>")
    return "\n".join(out)


def buttons_kb(rows: list) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in rows
        ]
    }


def _due_totals(rows: list) -> list:
    buckets = {}
    for r in rows:
        if r["status"].lower() == "fully paid":
            continue
        amount = "".join(ch for ch in r["fee_amount"] if ch.isdigit())
        key = r["due_on"] or "?"
        buckets.setdefault(key, {"amount": 0, "items": []})
        buckets[key]["amount"] += int(amount or 0)
        buckets[key]["items"].append(r["particulars"])
    return sorted(buckets.items(), key=lambda kv: kv[0])


def welcome_rich(name: str, is_admin: bool) -> str:
    admin_note = "<p>⚙️ You are the <b>admin</b>.</p>" if is_admin else ""
    return "\n".join([
        "<h2>🤖 Brainware Portal Bot</h2>",
        "<tg-slideshow>",
        f'<img src="{BANNER_2}"/>',
        "<figcaption>Brainware Student Self-Service<cite>Brainware University</cite></figcaption>",
        "</tg-slideshow>",
        f"<p>Hi <b>{escape(name)}</b>! I log into the Brainware University "
        "Student Self-Service portal and report in rich style.</p>",
        admin_note,
        "<p><b>Login:</b> <code>/login STUDENT_CODE:PASSWORD</code><br/>"
        "or <code>/login STUDENT_CODE PASSWORD</code></p>",
        "<p><b>Logout:</b> <code>/logout</code> or the 🚪 button</p>",
        buttons_html(NAV),
    ])


def dashboard_rich(data: dict, name: str, threshold: int) -> str:
    d = data
    att = d.get("attendance_pct") or "N/A"
    exam = d.get("exam_status") or "N/A"
    score = d.get("exam_score") or ""
    alerts = []
    if (d.get("attendance_pct") or "").isdigit() and int(d["attendance_pct"]) < threshold:
        alerts.append(f"<mark>⚠️ Attendance {escape(att)}% is below {threshold}%!</mark>")
    for due_on, info in _due_totals(d.get("pay_rows", [])):
        try:
            due_date = datetime.strptime(due_on, "%d-%b-%Y")
        except ValueError:
            continue
        if datetime.now() <= due_date <= datetime.now() + timedelta(days=7):
            alerts.append(f"<mark>⚠️ ₹{money(str(info['amount']))} fee due on {escape(due_on)}</mark>")
    if d.get("fee_state") == "NO DUE":
        fee_row = "<tr><td>💳 Payment</td><td><b>NO DUE</b> ✅</td></tr>"
    elif d.get("fee_amount"):
        fee_row = f"<tr><td>💳 Upcoming fee</td><td><b>₹{money(d['fee_amount'])}</b> due <b>{escape(d['fee_due'] or '-')}</b></td></tr>"
    else:
        fee_row = "<tr><td>💳 Payment</td><td><i>N/A</i></td></tr>"
    rows = [
        f"<tr><td>🎓 Attendance (current sem)</td><td><b>{escape(att)}%</b> <i>(alert under {threshold}%)</i></td></tr>",
        fee_row,
        f"<tr><td>🏅 Activities</td><td><b>{escape(d.get('activities') or '0')}</b></td></tr>",
        f"<tr><td>📝 Exam</td><td><b>{escape(exam)}</b>{' (' + escape(score) + ')' if score and score != '-' else ''}</td></tr>",
    ]
    courses = d.get("courses", [])
    head = "\n".join([
        f"<h2>📊 Dashboard</h2><p><b>{escape(name)}</b> · <i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i></p>",
        *alerts,
        '<table striped compact>' + "".join(rows) + "</table>",
    ])
    if courses:
        body = "".join(
            "<tr>"
            f"<td>{escape(c['code'])}</td><td>{escape(c['name'])}</td>"
            f'<td align="center">{escape(c["attended"])}</td><td align="center">{escape(c["percent"])}%</td>'
            "</tr>"
            for c in courses
        )
        head += (
            f"<details><summary>📚 Course-wise attendance ({len(courses)} papers)</summary>"
            '<table bordered striped compact><tr><th>Course Code</th><th>Course Name</th>'
            "<th>Attended</th><th>%</th></tr>" + body + "</table></details>"
        )
    return head + "\n" + buttons_html(NAV)


def payments_rich(pay: dict, warn_days: int) -> str:
    rows = pay.get("rows", [])
    due = _due_totals(rows)
    paid = [r for r in rows if r["status"].lower() == "fully paid"]
    total_paid = sum(int("".join(ch for ch in r["fee_amount"] if ch.isdigit()) or 0) for r in paid)
    totals = [f"<tr><td>✅ Paid</td><td><b>₹{money(str(total_paid))}</b> <i>({len(paid)} heads)</i></td></tr>"]
    for due_on, info in due:
        totals.append(
            f'<tr><td>❌ Due {escape(due_on)}</td><td><b>₹{money(str(info["amount"]))}</b> '
            f'<i>({len(info["items"])} heads)</i></td></tr>'
        )
    body = []
    for r in rows:
        ok = r["status"].lower() == "fully paid"
        status = "✅ Fully Paid" if ok else f"❌ {escape(r['status'] or 'Due')}"
        detail = (
            f"₹{money(r['received'])} on {escape(r['received_on'] or '-')}"
            if ok
            else f"due {escape(r['due_on'] or '-')}"
        )
        body.append(
            "<tr>"
            f'<td>{escape(r["particulars"])}</td><td align="right">₹{money(r["fee_amount"])}</td>'
            f"<td>{escape(r['due_on'] or '-')}</td><td>{detail}</td>"
            f"<td><code>{escape(r['receipt'] or '-')}</code></td><td>{status}</td>"
            "</tr>"
        )
    return "\n".join([
        "<h2>💳 Fees &amp; Payments</h2>",
        '<table striped compact>' + "".join(totals) + "</table>",
        f"<details><summary>🧾 All fee heads ({len(rows)})</summary>",
        '<table bordered striped compact><tr><th>Particulars</th><th>Fee</th><th>Due on</th>'
        "<th>Payment</th><th>Receipt</th><th>Status</th></tr>" + "".join(body) + "</table></details>",
        buttons_html(receipt_buttons_rows(rows) + NAV),
    ])


def receipt_buttons_rows(rows: list) -> list:
    btns = []
    for r in rows:
        ref = r.get("receipt_ref")
        if ref:
            digits = re.sub(r"\D", "", ref)
            if digits:
                btns.append((f"🧾 {r['receipt'] or digits}", f"rcpt:{digits}"))
    return [btns[i:i + 2] for i in range(0, len(btns), 2)]


def feedback_course_rows(courses: list) -> list:
    btns = [(c["label"][:48], f"fb:{c['value']}") for c in courses]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([("🏠 Menu", "menu")])
    return rows


def feedback_courses_rich(courses: list, note: str = "") -> str:
    head = "<h2>🧾 Student Feedback</h2>"
    if note:
        head += f"<p>{note}</p>"
    head += "<p>Choose a course / topic:</p>"
    return head + "\n" + buttons_html(feedback_course_rows(courses))


def feedback_question_rich(state: dict, idx: int) -> str:
    q = state["questions"][idx]
    rows = [[(opt["label"][:48], f"fba:{idx}:{opt['value']}")] for opt in q["options"]]
    rows.append([("🏠 Menu", "menu")])
    return "\n".join([
        f"<h2>🧾 Feedback</h2><p><b>{escape(state['title'])}</b></p>",
        f"<p>Question <b>{idx + 1}/{len(state['questions'])}</b></p>",
        f"<p>{escape(q['text'])}</p>",
        f"<p><i>Teacher: {escape(q['teacher'])}</i></p>",
        buttons_html(rows),
    ])


def feedback_summary_rich(state: dict) -> str:
    lines = [f"<h2>🧾 Feedback</h2><p><b>{escape(state['title'])}</b></p>", "<p>Review your answers:</p>"]
    for q in state["questions"]:
        ans = state["answers"].get(str(q["n"]))
        label = next((o["label"] for o in q["options"] if o["value"] == ans), "—")
        lines.append(f"<p><b>{q['n']}.</b> {escape(q['text'][:70])}<br/><i>{escape(label)}</i></p>")
    lines.append(buttons_html([[("✅ Submit", "fbs:go"), ("🔙 Redo", "fbx")], [("🏠 Menu", "menu")]]))
    return "\n".join(lines)


def semester_rows(options: list, extra=None) -> list:
    rows = []
    for i in range(0, len(options), 3):
        rows.append([(o["label"], f"m:{o['value']}") for o in options[i:i + 3]])
    rows.append(extra or [("🏠 Menu", "menu")])
    return rows


def marks_rich(marks: dict, semester_label: str, options: list) -> str:
    out = [
        f"<h2>📝 Marks Record</h2><p><b>{escape(semester_label)}</b>",
        f"<br/><i>{escape(marks.get('name') or '')} · {escape(marks.get('programme') or '')}</i></p>",
    ]
    for block in marks.get("blocks", []):
        rows = block["rows"]
        if not rows:
            out.append(f"<details><summary>🧪 {escape(block['title'])}</summary><p>— no entries yet</p></details>")
            continue
        got = full = 0.0
        body = []
        for r in rows:
            body.append(
                "<tr>"
                f'<td>{escape(r["code"])}</td><td align="center">{escape(r["full"])}</td>'
                f'<td align="center"><b>{escape(r["obtained"])}</b></td></tr>'
            )
            try:
                full += float(r["full"])
                got += float(r["obtained"])
            except ValueError:
                pass
        total = f" · Σ {got:g}/{full:g}" if full else ""
        out.append(
            f"<details><summary>🧪 {escape(block['title'])} ({len(rows)}){total}</summary>"
            '<table bordered striped compact><tr><th>Course Code</th><th>Full Marks</th>'
            "<th>Obtained</th></tr>" + "".join(body) + "</table></details>"
        )
    out.append(buttons_html(semester_rows(options)))
    return "\n".join(out)


def semester_menu_rich() -> str:
    return "<h2>📝 Marks Record</h2><p>Choose a semester:</p>"


def menu_rich(name: str = "") -> str:
    who = f"<p><b>{escape(name)}</b></p>" if name else ""
    return "\n".join(["<h2>🏠 Menu</h2>", who, "<p>Choose what to view:</p>", buttons_html(NAV)])


def attendance_pick_rich() -> str:
    return "\n".join([
        "<h2>🎓 Attendance</h2>",
        "<p>Choose which attendance to view:</p>",
        buttons_html([
            [("📊 Current attendance", "att:cur")],
            [("📅 Semester-wise", "att:sw")],
            [("🏠 Menu", "menu")],
        ]),
    ])


def attendance_rich(data: dict, threshold: int, title: str = "Current semester") -> str:
    d = data
    att = d.get("attendance_pct")
    courses = d.get("courses", [])
    head = f"<h2>🎓 Attendance</h2><p><b>{escape(title)}</b>"
    if att:
        head += f" — overall <b>{escape(att)}%</b>"
    head += f"<br/><i>alert under {threshold}% · {len(courses)} papers</i></p>"
    if d.get("subtitle"):
        head += f"<p><i>{escape(d['subtitle'])}</i></p>"
    body = []
    for c in courses:
        pct = c["percent"]
        total = c["attended"].split("/")[-1]
        flag = ""
        if pct.isdigit() and int(pct) < threshold and total.isdigit() and int(total) > 0:
            flag = " ⚠️"
        body.append(
            "<tr>"
            f"<td>{escape(c['code'])}</td><td>{escape(c['name'])}</td>"
            f'<td align="center">{escape(c["attended"])}</td>'
            f'<td align="center"><b>{escape(pct)}%</b>{flag}</td></tr>'
        )
    if d.get("total"):
        t = d["total"]
        body.append(
            '<tr><td colspan="3" align="right"><b>Total</b></td>'
            f'<td align="center"><b>{escape(t["attended"])} · {escape(t["percent"])}%</b></td></tr>'
        )
    if not body:
        body.append('<tr><td colspan="4">— no attendance data for this selection —</td></tr>')
    return "\n".join([
        head,
        '<table bordered striped compact><tr><th>Course Code</th><th>Course Name</th>'
        "<th>Attended/Total</th><th>%</th></tr>" + "".join(body) + "</table>",
        buttons_html(NAV),
    ])


SEM_LABELS = {
    "1": "Semester I", "2": "Semester II", "3": "Semester III", "4": "Semester IV",
    "5": "Semester V", "6": "Semester VI", "14": "Semester VII", "15": "Semester VIII",
    "17": "Semester IX", "18": "Semester X",
}
GC_SEMS = {"O": ["1", "3", "5", "14", "17"], "E": ["2", "4", "6", "15", "18"]}
GC_PARITY_LABEL = {"O": "🌙 Odd or December", "E": "☀️ Even or June"}


def marks_pick_rich() -> str:
    return "\n".join([
        "<h2>📝 Marks</h2>",
        "<p>Choose which marks to view:</p>",
        buttons_html([
            [("📊 Current marks", "marks:cur")],
            [("🎓 Semester grade card", "gc")],
            [("🏠 Menu", "menu")],
        ]),
    ])


def gc_session_rows(state: dict) -> list:
    rows = [
        [("🌙 Odd or December", "gce:O"), ("☀️ Even or June", "gce:E")],
    ]
    year = state.get("year")
    btns = []
    for y in state.get("years", []):
        mark = " ✅" if y["value"] == year else ""
        btns.append((y["label"] + mark, f"gcy:{y['value']}"))
    rows.extend(btns[i:i + 2] for i in range(0, len(btns), 2))
    rows.append([("🏠 Menu", "menu")])
    return rows


def gc_session_rich(state: dict, note: str = "") -> str:
    sel = []
    if state.get("even_odd"):
        sel.append(GC_PARITY_LABEL[state["even_odd"]])
    if state.get("year_label") or state.get("year"):
        sel.append(escape(state.get("year_label") or state.get("year")))
    lines = ["<h2>🎓 Semester Grade Card</h2>"]
    if sel:
        lines.append(f"<p>Selected: <b>{' · '.join(sel)}</b></p>")
    if note:
        lines.append(f"<p>{note}</p>")
    lines.append("<p>🌙/☀️ exam session &amp; 📅 examination year:</p>")
    lines.append(buttons_html(gc_session_rows(state)))
    return "\n".join(lines)


def gc_sem_rows(parity: str) -> list:
    btns = [(SEM_LABELS.get(v, v), f"gcs:{v}") for v in GC_SEMS.get(parity, [])]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([("🏠 Menu", "menu")])
    return rows


def gc_sem_rich(parity: str) -> str:
    return "\n".join([
        f"<h2>🎓 Semester Grade Card</h2><p><b>{GC_PARITY_LABEL[parity]}</b></p>",
        "<p>Choose semester:</p>",
        buttons_html(gc_sem_rows(parity)),
    ])


def gc_year_rows(years: list) -> list:
    btns = [(y["label"], f"gcy:{y['value']}") for y in years]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([("🏠 Menu", "menu")])
    return rows


def gc_result_rich(rows: list, state: dict) -> str:
    parity = state.get("even_odd", "O")
    sem_label = state.get("sem_label") or SEM_LABELS.get(state.get("sem", ""), "?")
    year_label = state.get("year_label") or state.get("year") or "?"
    head = (f"<h2>🎓 Semester Grade Card</h2>"
            f"<p><b>{GC_PARITY_LABEL[parity]}</b> · <b>{escape(sem_label)}</b> · <b>{escape(year_label)}</b></p>")
    if not rows:
        return "\n".join([
            head,
            "<p><mark>⚠️ No grade card found for this selection.</mark></p>",
            buttons_html([
                [("🔀 Change session / year", "gc")],
                [("🏠 Menu", "menu")],
            ]),
        ])
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{escape(r['code'])}</td><td>{escape(r['name'])}</td>"
            f"<td>{escape(r['roll'])}</td><td>{escape(r['reg'])}</td>"
            f"<td>{escape(r['reg_date'])}</td></tr>"
        )
    return "\n".join([
        head,
        '<table bordered striped compact><tr><th>Code</th><th>Name</th><th>Roll</th><th>Reg. No</th><th>Reg. Date</th></tr>'
        + "".join(body) + "</table>",
        buttons_html([
            [("🎓 Download Grade Card", "gcd:1")],
            [("🏠 Menu", "menu")],
        ]),
    ])


def notices_rich(notices: list, base_url: str) -> str:
    items = []
    for n in notices[:10]:
        url = base_url.rstrip("/") + "/" + n["url"]
        items.append(
            f'<li><a href="{escape(url, quote=True)}">{escape(n["title"].rstrip(" -"))}</a>'
            f' — <i>{escape(n["board"])}</i></li>'
        )
    return "\n".join([
        "<h2>📢 Latest notices</h2>",
        "<ul>" + "".join(items) + "</ul>",
        buttons_html(NAV),
    ])


def logout_confirm_rich() -> str:
    return "\n".join([
        "<h2>🚪 Logout</h2>",
        "<p>End your portal session?</p>",
        buttons_html([[("✅ Yes, logout", "logout:yes"), ("❌ Cancel", "menu")]]),
    ])


def logged_out_rich() -> str:
    return "\n".join([
        "<h2>👋 Logged out</h2>",
        "<p>Your portal session has ended.<br/>Login again with <code>/login STUDENT_CODE:PASSWORD</code></p>",
    ])


def login_prompt_rich() -> str:
    return "\n".join([
        "<h2>🔑 Not logged in</h2>",
        "<p>Use <code>/login STUDENT_CODE:PASSWORD</code><br/>or <code>/login STUDENT_CODE PASSWORD</code></p>",
    ])


def login_ok_rich(code: str) -> str:
    return "\n".join([
        "<h2>✅ Logged in</h2>",
        f"<p>Welcome back, <code>{escape(code)}</code>!</p>",
        buttons_html(NAV),
    ])


def admin_rich(stats: dict) -> str:
    return "\n".join([
        "<h2>⚙️ Admin panel</h2>",
        '<table striped compact>'
        f"<tr><td>👥 Users with stored logins</td><td><b>{stats['users']}</b></td></tr>"
        f"<tr><td>🟢 Active within {stats['ttl_minutes']} min</td><td><b>{stats['active_within_ttl']}</b></td></tr>"
        f"<tr><td>🔐 Total logins</td><td><b>{stats['total_logins']}</b></td></tr>"
        "</table>",
        buttons_html([
            [("📣 Broadcast", "admin:broadcast"), ("🧹 Clear sessions", "admin:clear")],
            [("🏠 Menu", "menu")],
        ]),
    ])


def rich_to_plain(html: str) -> str:
    s = html
    for tag in ("tg-slideshow", "tg-button-row", "figure"):
        s = re.sub(rf"(?s)<{tag}[^>]*>.*?</{tag}>", "", s)
    s = s.replace("</td>", " | ").replace("</th>", " | ")
    s = s.replace("</tr>", "\n").replace("<tr>", "• ")
    s = re.sub(r"</?(table|thead|tbody|caption)[^>]*>", "\n", s)
    s = re.sub(r"<summary[^>]*>", "\n<b>", s).replace("</summary>", "</b>\n")
    s = re.sub(r"</?details[^>]*>", "\n", s)
    s = s.replace("<hr/>", "\n———\n")
    s = re.sub(r"<h[1-6][^>]*>", "\n<b>", s)
    s = re.sub(r"</h[1-6]>", "</b>\n", s)
    s = re.sub(r"<li[^>]*>", "\n• ", s)
    s = re.sub(r"</?(ul|ol|p|blockquote|aside|footer)[^>]*>", "\n", s)
    s = re.sub(r"(?s)<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", s)
    s = re.sub(r"<img[^>]*/?>", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())
