import re

IDS = {
    "⏳": "5451732530048802485",
    "⚙": "4904936030232117798",
    "⚠": "6181222675050926329",
    "⛔": "6181439154287546448",
    "✅": "6266967801580231067",
    "❌": "6111517649349383216",
    "🎓": "5375163339154399459",
    "🏅": "5321235094130662506",
    "🏠": "5395831812704452001",
    "👋": "5413694143601842851",
    "👤": "6021386648246294190",
    "👥": "5942877472163892475",
    "💳": "5472250091332993630",
    "📊": "6059654836918423763",
    "📚": "5373098009640836781",
    "📝": "4979199472228631981",
    "📢": "5774015846464622793",
    "📣": "6267129592998270736",
    "🔐": "5897604269141398480",
    "🔑": "5307843983102204243",
    "🖼": "5350693961281314631",
    "🚀": "5145427681680032825",
    "🚪": "5474536392618949163",
    "🟢": "5978626091286269288",
    "🤖": "5287684458881756303",
    "🧩": "6024065724291488135",
    "🧪": "5283069434917836059",
    "🧹": "5280603307646149925",
    "🧾": "5444856076954520455",
    "↪️": "5467657491393300116",
}

_PATTERN = re.compile(
    "|".join(re.escape(k) + "\uFE0F?" for k in sorted(IDS, key=len, reverse=True))
)
_BUTTON_SEG = re.compile(r"(<tg-button[^>]*>.*?</tg-button>)", re.S)


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _wrap_segment(text: str) -> str:
    def repl(m):
        span = m.group(0)
        base = span.replace("\uFE0F", "")
        emoji_id = IDS.get(base)
        if not emoji_id:
            return span
        return f'<tg-emoji emoji-id="{emoji_id}">{span}</tg-emoji>'

    return _PATTERN.sub(repl, text)


def wrap_rich(html: str) -> str:
    parts = _BUTTON_SEG.split(html)
    for i in range(0, len(parts), 2):
        parts[i] = _wrap_segment(parts[i])
    return "".join(parts)


def plain(text: str):
    entities = []
    for m in _PATTERN.finditer(text):
        span = m.group(0)
        base = span.replace("\uFE0F", "")
        emoji_id = IDS.get(base)
        if not emoji_id:
            continue
        entities.append({
            "type": "custom_emoji",
            "offset": _utf16_len(text[: m.start()]),
            "length": _utf16_len(span),
            "custom_emoji_id": emoji_id,
        })
    return text, entities
