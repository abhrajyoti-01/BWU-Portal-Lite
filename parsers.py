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
        if len(cells) < 8:
            continue
        vals = [clean(c) for c in cells[:8]]
        if not vals[0] or vals[0] == "Particulars":
            continue
        fee = re.match(r"([\d,]+)", vals[1])
        pay_href = None
        hm = HREF_RE.search(cells[7])
        if hm and not hm.group(1).startswith("javascript"):
            pay_href = hm.group(1)
        rows.append({
            "particulars": vals[0],
            "fee_amount": fee.group(1) if fee else vals[1],
            "due_on": vals[2],
            "received": vals[3],
            "received_on": vals[4],
            "receipt": vals[5],
            "status": vals[6],
            "pay_href": pay_href,
        })
    upcoming = FEE_RE.search(doc)
    return {
        "rows": rows,
        "upcoming_amount": upcoming.group(1) if upcoming else None,
        "upcoming_due": clean(upcoming.group(2)) if upcoming else None,
    }


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
