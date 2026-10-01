import re
from html import unescape

_COMMENTS = re.compile(r"(?s)<!--.*?-->")
_INPUT = re.compile(r"<input[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

ATT_RE = re.compile(
    r'(?s)<div class="small-box bg-green">\s*<div class="inner">\s*<h3>\s*(\d+)\s*<sup.*?</sup>\s*</h3>'
    r"\s*<p>\s*Attendance \(current semester\)\s*</p>"
)
FEE_RE = re.compile(r"Payment\s*\(Rs\.?:\s*([\d,]+)\)\s*\[([^\]]+)\]")
ACT_RE = re.compile(r"<h3>\s*(\d+)\s*</h3>\s*<p>\s*Number of Activities\s*</p>")
EXAM_RE = re.compile(
    r'(?s)<div class="small-box bg-red">\s*<div class="inner">\s*<h3>\s*([^<]*?)\s*</h3>\s*<p>\s*([^<]*?)\s*</p>'
)
COURSE_RE = re.compile(
    r"(?s)<tr>\s*<td>([^<]+?)</td>\s*<td>([^<]+?)</td>\s*<td>([^<]+?)</td>\s*<td>([^<]+?)</td>\s*</tr>"
)
NOTICE_RE = re.compile(
    r"(?s)<tr><td><a href='(student-student-forum-new\.php[^']*)'>\s*([^<]*?)\s*<b>([^<]*)</b>\s*</a></td>"
)
NAME_H1_RE = re.compile(r"(?s)<h1>([^<]*)</h1>")
SEM_OPTION_RE = re.compile(r"<option value=['\"](-?\d+)['\"][^>]*>([^<]+)</option>")
SEM_SELECT_RE = re.compile(r"(?s)<select name=\"module_semester_id\".*?</select>")
BOX_TITLE_RE = re.compile(r'<h3 class="box-title">([^<]+)</h3>')
ROW_RE = re.compile(r"(?s)<tr>(.*?)</tr>")
CELL_RE = re.compile(r"(?s)<td[^>]*>(.*?)</td>")
DETAIL_RE = re.compile(
    r"(?s)<strong>\s*(?:Name|Programme|Semester)\s*(?:&nbsp;|\s)*:\s*</strong>\s*([^<]+)"
)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']")
RECEIPT_LINK_RE = re.compile(r"receipt-stud-print\.php\?id=([^\"\s>]+)")
FB_COURSE_SELECT_RE = re.compile(r"(?s)<select name=\"topic_paper_id\".*?</select>")
FB_OPTION_RE = re.compile(r"<option value=['\"]([^'\"]+)['\"][^>]*>([^<]+)</option>")
FB_Q_META_RE = re.compile(
    r"(?s)<em>\s*(\d+)\s*</em></td><td[^>]*>\s*<em></em>\s*(.*?)"
    r'<input type="hidden" name="question_bank_id_(\d+)" value="(\d+)">'
)
FB_HIDDEN_RE = re.compile(
    r'<input type="hidden" name="(insert_counter|course_structure_id|module_semester_id|batch_id)" value="([^"]*)"'
)
FB_TITLE_RE = re.compile(r'bgcolor="gray"><strong>([^<]+)</strong>')
CHROME_TITLES = {"Marks Record", "Student Details", "Marks Details"}


def clean(fragment: str) -> str:
    s = _INPUT.sub(" ", fragment)
    s = _TAG.sub(" ", s)
    s = unescape(s).replace("\xa0", " ")
    return _WS.sub(" ", s).strip()


def strip_comments(html: str) -> str:
    return _COMMENTS.sub("", html)


def parse_dashboard(html: str) -> dict:
    doc = strip_comments(html)
    out = {"attendance_pct": None, "fee_amount": None, "fee_due": None,
           "activities": None, "exam_score": None, "exam_status": None,
           "courses": [], "notices": []}
    m = ATT_RE.search(doc)
    if m:
        out["attendance_pct"] = m.group(1)
    m = FEE_RE.search(doc)
    if m:
        out["fee_amount"], out["fee_due"] = m.group(1), clean(m.group(2))
    m = ACT_RE.search(doc)
    if m:
        out["activities"] = m.group(1)
    m = EXAM_RE.search(doc)
    if m:
        out["exam_score"], out["exam_status"] = clean(m.group(1)), clean(m.group(2))
    out["courses"] = [
        {"code": clean(a), "name": clean(b), "attended": clean(c), "percent": clean(d)}
        for a, b, c, d in COURSE_RE.findall(doc)
    ]
    out["notices"] = [
        {"url": u, "title": clean(t), "board": clean(b)}
        for u, t, b in NOTICE_RE.findall(doc)
    ]
    return out


def parse_payments(html: str) -> dict:
    doc = strip_comments(html)
    rows = []
    for tr in ROW_RE.findall(doc):
        if "table-header" in tr:
            continue
        cells = CELL_RE.findall(tr)
        if len(cells) < 7:
            continue
        vals = [clean(c) for c in cells[:7]]
        if not vals[0] or vals[0] == "Particulars":
            continue
        fee = re.match(r"([\d,]+)", vals[1])
        fee_amount = fee.group(1) if fee else ""
        status = vals[6]
        if not fee_amount and not status:
            continue
        pay_href = None
        if len(cells) > 7:
            hm = HREF_RE.search(cells[7])
            if hm and not hm.group(1).startswith("javascript"):
                pay_href = hm.group(1)
        receipt_ref = None
        rm = RECEIPT_LINK_RE.search(cells[5])
        if rm:
            receipt_ref = rm.group(1).strip("'\".")
        rows.append({
            "particulars": vals[0],
            "fee_amount": fee_amount or vals[1],
            "due_on": vals[2],
            "received": vals[3],
            "received_on": vals[4],
            "receipt": vals[5],
            "status": status,
            "pay_href": pay_href,
            "receipt_ref": receipt_ref,
        })
    upcoming = FEE_RE.search(doc)
    return {
        "rows": rows,
        "upcoming_amount": upcoming.group(1) if upcoming else None,
        "upcoming_due": clean(upcoming.group(2)) if upcoming else None,
    }


def parse_feedback_courses(html: str) -> list:
    doc = strip_comments(html)
    sel = FB_COURSE_SELECT_RE.search(doc)
    if not sel:
        return []
    return [
        {"value": v, "label": clean(label)}
        for v, label in FB_OPTION_RE.findall(sel.group(0))
        if v != "-1" and clean(label)
    ]


def feedback_status(html: str) -> str:
    if "Your feedback has been taken" in html:
        return "taken"
    if "submitted successfully" in html:
        return "success"
    return ""


def parse_feedback_questions(html: str) -> dict:
    doc = strip_comments(html)
    out = {"title": "", "hidden": {}, "questions": []}
    m = FB_TITLE_RE.search(doc)
    if m:
        out["title"] = clean(m.group(1))
    out["hidden"] = {name: value for name, value in FB_HIDDEN_RE.findall(doc)}
    for qm in FB_Q_META_RE.finditer(doc):
        num, text, qnum, qbank = qm.groups()
        tail = doc[qm.end(): qm.end() + 5000]
        teacher = re.search(r"<strong>([^<]+)</strong>", tail)
        theory = re.search(rf'name="theory_lab_{qnum}" value="([^"]*)"', tail)
        faculty = re.search(rf'name="faculty_id_{qnum}" value="([^"]*)"', tail)
        sel = re.search(rf'(?s)<select name="answer_no\[{qnum}\]\[\]".*?</select>', tail)
        options = []
        if sel:
            for ov, ol in re.findall(r'<option value="([^"]*)"[^>]*>\s*([^<]+?)\s*</option>', sel.group(0)):
                if ov:
                    options.append({"value": ov, "label": clean(ol)})
        out["questions"].append({
            "n": int(qnum),
            "text": clean(text),
            "question_bank_id": qbank,
            "theory_lab": theory.group(1) if theory else "",
            "faculty_id": faculty.group(1) if faculty else "",
            "teacher": clean(teacher.group(1)) if teacher else "",
            "options": options,
        })
    return out


def parse_marks(html: str) -> dict:
    doc = strip_comments(html)
    out = {"name": None, "programme": None, "semester": None, "options": [], "blocks": []}
    details = [clean(x) for x in DETAIL_RE.findall(doc)]
    if len(details) >= 3:
        out["name"], out["programme"], out["semester"] = details[0], details[1], details[2]
    sel = SEM_SELECT_RE.search(doc)
    if sel:
        out["options"] = [
            {"value": v, "label": clean(label)}
            for v, label in SEM_OPTION_RE.findall(sel.group(0))
            if v != "-1"
        ]
    parts = BOX_TITLE_RE.split(doc)
    for i in range(1, len(parts), 2):
        title = clean(parts[i])
        if title in CHROME_TITLES:
            continue
        rows = []
        for tr in ROW_RE.findall(parts[i + 1]):
            cells = [clean(c) for c in CELL_RE.findall(tr)]
            if len(cells) == 3 and cells[0]:
                rows.append({"code": cells[0], "full": cells[1], "obtained": cells[2]})
        out["blocks"].append({"title": title, "rows": rows})
    return out
