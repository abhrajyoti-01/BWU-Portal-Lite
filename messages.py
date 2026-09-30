import re
from datetime import datetime, timedelta
from html import escape

BANNER_1 = "https://www.brainwareuniversity.ac.in/promote-news/image/portal-banner.jpg"
BANNER_2 = "https://www.brainwareuniversity.ac.in/studentselfservice/images/login.jpg"

NAV = [
    [("📊 Dashboard", "dash"), ("💳 Fees & Payments", "fees")],
    [("📝 Marks", "marks"), ("🎓 Attendance", "att")],
    [("📢 Notices", "notices"), ("🚪 Logout", "logout")],
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
        "<h2>🤖 BWU Portal Bot</h2>",
        "<tg-slideshow>",
        f'<img src="{BANNER_1}"/>',
        f'<img src="{BANNER_2}"/>',
        "<figcaption>BWU Student Self-Service<cite>Brainware University</cite></figcaption>",
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
    rows = [
        f"<tr><td>🎓 Attendance (current sem)</td><td><b>{escape(att)}%</b> <i>(alert under {threshold}%)</i></td></tr>",
        f"<tr><td>💳 Upcoming fee</td><td><b>₹{money(d.get('fee_amount') or '')}</b> due <b>{escape(d.get('fee_due') or '-')}</b></td></tr>",
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
        buttons_html(NAV),
    ])


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


def attendance_rich(data: dict, threshold: int) -> str:
    d = data
    att = d.get("attendance_pct") or "N/A"
    courses = d.get("courses", [])
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
    return "\n".join([
        f"<h2>🎓 Attendance</h2><p>Overall <b>{escape(att)}%</b> · alert under <b>{threshold}%</b> · {len(courses)} papers</p>",
        '<table bordered striped compact><tr><th>Course Code</th><th>Course Name</th>'
        "<th>Attended/Total</th><th>%</th></tr>" + "".join(body) + "</table>",
        buttons_html(NAV),
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
