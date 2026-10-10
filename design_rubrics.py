# -*- coding: utf-8 -*-
"""
Рубрики @Her_Design за розкладом (за Києвом):
  🔤 Шрифт дня — щодня о 09:00: безкоштовний шрифт із Google Fonts з
     кирилицею. Картка набрана самим шрифтом; факти (тип, автори,
     накреслення) — з Google Fonts, опис Claude пише, дивлячись на зразок.
  🎨 Кейс дня — щодня об 11:00: сильний проєкт із Behance чи Abduzeedo; пн
     сайти й застосунки, вт анімація, ср логотипи й айдентика, чт упаковка,
     пт постери, сб–нд найкраще з будь-якої категорії. Claude дивиться на
     самі зображення; автор — лише якщо названий у джерелі.
  🎨 Палітра дня — щодня о 13:00: 5 кольорів із HEX (копіюються натиском)
     і пораховано найкращий контраст для тексту (WCAG).
  🧠 Вікторина — щодня о 15:00: «Вгадай бренд» за 2–5 фірмовими кольорами
     (лише бренди — так вирішили 10.10; «Вгадай шрифт» лишається в коді, але
     не публікується). Картка + опитування-квіз Telegram (з поясненням).
     Неправильні варіанти — бренди з іншими кольорами, щоб відповідь була
     одна.
"""
import base64
import colorsys
import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import cs2_ai as ai
import design_cards as cards
import quiz

LIVE = True                      # увімкнено 10.10 («вмикай»)
WINDOW_H = 4                     # рубрика виходить лише в перші 4 год від свого часу
FONT_HOUR = 9
QUIZ_HOUR = 15
CASE_HOUR = 11
PALETTE_HOUR = 13
CASE_FEEDS = [("Behance", "https://www.behance.net/feeds/projects"),
              ("Abduzeedo", "https://abduzeedo.com/rss.xml")]
# категорія кейсу → (назва, хештег); по днях тижня (пн = 0), сб–нд — будь-яка
CASE_CATS = {"web": ("Сайти й застосунки", "#вебдизайн"),
             "motion": ("Анімація", "#моушн"),
             "identity": ("Логотипи й айдентика", "#айдентика"),
             "packaging": ("Упаковка", "#упаковка"),
             "poster": ("Постери", "#постери")}
CASE_DAYS = ["web", "motion", "identity", "packaging", "poster", None, None]
# набори символів Google Fonts → мови словами
SUBSETS = [("cyrillic", "кирилиця (українська та інші)"),
           ("cyrillic-ext", "розширена кирилиця"),
           ("latin", "латиниця (англійська та інші)"),
           ("latin-ext", "розширена латиниця (польська, чеська, турецька…)"),
           ("greek", "грецька"), ("vietnamese", "в'єтнамська"),
           ("hebrew", "іврит"), ("arabic", "арабська")]
GF_META = "https://fonts.google.com/metadata/fonts"
SAMPLE = "Аа Бб Ґґ Її Єє"
SAMPLE_LAT = "Aa Bb Gg Rr Ss"
PANGRAM = "Чуєш їх, доцю, га? Кумедна ж ти, прощайся без ґольфів!"
PANGRAM_LAT = "Sphinx of black quartz, judge my vow"
CATEGORY = {"Sans Serif": "гротеск (sans serif)", "Serif": "антиква (serif)",
            "Display": "акцидентний (display)", "Handwriting": "рукописний",
            "Monospace": "моноширинний"}
CAT_SHORT = {"Sans Serif": "Sans", "Serif": "Serif", "Display": "Display",
             "Handwriting": "Script", "Monospace": "Mono"}
PINK_LIGHT, PINK_INK = (249, 211, 230), (138, 31, 85)
BLUE_LIGHT, YELLOW_INK = (220, 230, 252), (90, 67, 0)

# Бренди для «Вгадай бренд»: (назва, фірмові кольори, як їх назвати словами).
# Кольори на картці — без кодів: це впізнавання, а не довідник.
BRANDS = [
    ("McDonald's", ["#DA291C", "#FFC72C"], "червоний і жовтий"),
    ("Burger King", ["#D62300", "#FF8732", "#502314"],
     "червоний, помаранчевий і коричневий"),
    ("IKEA", ["#0058A3", "#FFDB00"], "синій і жовтий"),
    ("Lidl", ["#0050AA", "#FFF000", "#E60A14"], "синій, жовтий і червоний"),
    ("Google", ["#4285F4", "#EA4335", "#FBBC05", "#34A853"],
     "синій, червоний, жовтий і зелений"),
    ("Microsoft", ["#F25022", "#7FBA00", "#00A4EF", "#FFB900"],
     "червоно-помаранчевий, салатовий, блакитний і жовтий"),
    ("Slack", ["#36C5F0", "#2EB67D", "#ECB22E", "#E01E5A"],
     "блакитний, зелений, жовтий і малиновий"),
    ("Figma", ["#F24E1E", "#FF7262", "#A259FF", "#1ABCFE", "#0ACF83"],
     "червоно-помаранчевий, кораловий, фіолетовий, блакитний і зелений"),
    ("Mastercard", ["#EB001B", "#F79E1B", "#FF5F00"],
     "червоний, жовто-помаранчевий і помаранчевий на перетині кіл"),
    ("Visa", ["#1A1F71", "#F7B600"], "темно-синій і золотий"),
    ("FedEx", ["#4D148C", "#FF6600"], "фіолетовий і помаранчевий"),
    ("DHL", ["#FFCC00", "#D40511"], "жовтий і червоний"),
    ("UPS", ["#351C15", "#FFB500"], "коричневий і золотисто-жовтий"),
    ("LEGO", ["#E3000B", "#FFED00", "#000000"], "червоний, жовтий і чорний"),
    ("Red Bull", ["#DB0A40", "#FFC906", "#001E3C"],
     "червоний, жовтий і темно-синій"),
    ("Spotify", ["#1DB954", "#191414"], "зелений і чорний"),
    ("WhatsApp", ["#25D366", "#075E54"], "яскраво-зелений і темно-бірюзовий"),
    ("Snapchat", ["#FFFC00", "#000000"], "яскраво-жовтий і чорний"),
    ("TikTok", ["#25F4EE", "#FE2C55", "#000000"],
     "блакитний, червоно-рожевий і чорний"),
    ("Netflix", ["#E50914", "#000000"], "червоний і чорний"),
    ("Coca-Cola", ["#F40009", "#FFFFFF"], "червоний і білий"),
    ("Pepsi", ["#004B93", "#E32934", "#FFFFFF"], "синій, червоний і білий"),
    ("Amazon", ["#FF9900", "#232F3E"], "помаранчевий і темно-синій"),
    ("NASA", ["#0B3D91", "#FC3D21", "#FFFFFF"], "синій, червоний і білий"),
    ("Subway", ["#008C15", "#FFC600"], "зелений і жовтий"),
    ("Starbucks", ["#00704A", "#FFFFFF"], "зелений і білий"),
    ("Twitch", ["#9146FF", "#FFFFFF"], "фіолетовий і білий"),
    ("Ryanair", ["#073590", "#F1C933"], "темно-синій і жовтий"),
]

_meta = []


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# ---------- Google Fonts ----------

def gf_families():
    """Сім'ї Google Fonts без іконок, Noto, кольорових і нелатинських."""
    if _meta:
        return _meta
    req = urllib.request.Request(GF_META, headers={"User-Agent": cards.UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    data = json.loads(raw[raw.index("{"):])
    for f in data.get("familyMetadataList", []):
        name = f.get("family", "")
        if (f.get("isNoto") or f.get("isBrandFont") or f.get("colorCapabilities")
                or f.get("isOpenSource") is False
                or f.get("primaryScript", "") not in ("", "Cyrl")
                or re.search(r"Icons|Symbols|Emoji|Barcode", name)):
            continue
        _meta.append(f)
    print(f"Google Fonts: {len(_meta)} сімей")
    return _meta


def styles(f):
    keys = list((f.get("fonts") or {}).keys())
    weights = sorted({int(k.rstrip("i")) for k in keys if k.rstrip("i").isdigit()})
    return keys, weights, any(k.endswith("i") for k in keys)


def sample_weight(f):
    _, weights, _ = styles(f)
    return 400 if 400 in weights or not weights else weights[0]


def has_cyr(f):
    return "cyrillic" in (f.get("subsets") or [])


def languages(f):
    subs = f.get("subsets") or []
    return ", ".join(name for key, name in SUBSETS if key in subs)


# ---------- 🔤 шрифт дня ----------

DESC_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def pick_font(state, rnd):
    done = set(state.get("fonts_posted", []))
    fams = [f for f in gf_families() if has_cyr(f)
            and f["family"] not in done]
    good = [f for f in fams if f.get("popularity", 9999) <= 600] or fams
    year = time.gmtime().tm_year
    fresh = [f for f in good if f.get("dateAdded", "") >= str(year - 3)]
    pool = fresh if fresh and rnd.random() < 0.5 else good
    return rnd.choice(pool) if pool else None


def font_facts(f):
    keys, weights, italic = styles(f)
    n = len(keys)
    span = (f"{weights[0]}–{weights[-1]}" if len(weights) > 1
            else str(weights[0]) if weights else "")
    axes = [a.get("tag") for a in (f.get("axes") or [])]
    parts = [f"{n} {plural(n, 'накреслення', 'накреслення', 'накреслень')}"]
    if span:
        parts.append(f"вага {span}")
    if italic:
        parts.append("є курсив")
    if axes:
        parts.append("variable (" + ", ".join(axes) + ")")
    return {
        "category": CATEGORY.get(f.get("category"), f.get("category", "")),
        "styles": ", ".join(parts),
        "designers": ", ".join(f.get("designers") or []),
        "added": (f.get("dateAdded") or "")[:4],
        "n": n,
        "variable": bool(axes),
    }


def font_card(f, out_path, handle):
    path = cards.gfont(f["family"], sample_weight(f))
    if not path:
        return False
    facts = font_facts(f)
    chips = [("Безкоштовний", cards.YELLOW, YELLOW_INK),
             ("Кирилиця: так", PINK_LIGHT, PINK_INK),
             (CAT_SHORT.get(f.get("category"), "Font"), BLUE_LIGHT, cards.INK),
             (f"{facts['n']} {plural(facts['n'], 'накреслення', 'накреслення', 'накреслень')}",
              BLUE_LIGHT, cards.INK)]
    if facts["variable"]:
        chips.append(("Variable", BLUE_LIGHT, cards.INK))
    return cards.font_card(f["family"], path, chips, out_path, handle=handle,
                           sample=SAMPLE, line=PANGRAM)


def describe_font(f, card_path, style):
    """2–3 речення про характер шрифту — Claude дивиться на сам зразок."""
    if not ai.available():
        return None
    facts = font_facts(f)
    prompt = f"""На картинці — картка «Шрифт дня» для шрифту {f['family']}. Великий
рядок «{SAMPLE}» і панграма під ним набрані саме цим шрифтом. Назва шрифту,
мітки й таблички — фірмовим шрифтом каналу, їх не оцінюй.

Дані з Google Fonts: тип — {facts['category']}; {facts['styles']};
автори — {facts['designers'] or 'не вказані'}; у Google Fonts з {facts['added']}.

Напиши 2–3 короткі речення українською: який у шрифту характер — що видно на
зразку (форма літер, контраст, ширина, засічки чи їх відсутність, настрій), і
де він доречний (заголовки, основний текст, айдентика, UI, упаковка тощо).
Тільки те, що видно на зразку або є в даних; не вигадуй історію створення,
роки чи факти про авторів. Telegram HTML: лише <b> та <i>."""
    try:
        import anthropic
        with open(card_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        r = anthropic.Anthropic().beta.messages.create(
            model=ai.MODEL, max_tokens=4000, system=style,
            betas=[ai.FALLBACK_BETA], fallbacks="default",
            output_config={"effort": "medium", "format": {
                "type": "json_schema", "schema": DESC_SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg",
                                             "data": b64}},
                {"type": "text", "text": prompt}]}])
        text = "".join(b.text for b in r.content if b.type == "text")
        return json.loads(text)["text"].strip()
    except Exception as e:
        print("Опис шрифту не вийшов:", type(e).__name__, str(e)[:200])
        return None


def font_caption(f, desc, foot):
    import html as h
    facts = font_facts(f)
    url = "https://fonts.google.com/specimen/" + f["family"].replace(" ", "+")
    lines = ["<b>🔤 ШРИФТ ДНЯ</b>", f"<b>{h.escape(f['family'])}</b>", ""]
    if desc:
        lines += [desc, ""]
    lines += [f"▫️ Тип: {facts['category']}",
              f"▫️ Мови: {languages(f)}",
              f"▫️ Накреслення: {facts['styles']}"]
    if facts["designers"]:
        lines.append(f"▫️ Автор: {h.escape(facts['designers'])}")
    lines += ["▫️ Ліцензія: безкоштовний для особистого й комерційного "
              "використання (відкрита ліцензія Google Fonts)",
              f'🔗 <a href="{url}">Завантажити на Google Fonts</a>',
              "", foot, "#шрифт_дня #шрифти"]
    return "\n".join(lines)


def make_font_post(state, rnd, handle, foot, style):
    for _ in range(5):                       # шрифт не скачався — інший
        f = pick_font(state, rnd)
        if not f:
            return None
        path = cards.tmp_path("font")
        if font_card(f, path, handle):
            desc = describe_font(f, path, style)
            return f, path, font_caption(f, desc, foot)
        state.setdefault("fonts_posted", []).append(f["family"])
    return None


# ---------- 🧠 вікторина ----------

def bucket(c):
    """Грубий «кошик» кольору — щоб неправильні варіанти мали інші кольори."""
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if light < 0.15:
        return "black"
    if light > 0.92:
        return "white"
    if sat < 0.2:
        return "gray"
    hue *= 360
    if hue < 20 or hue >= 335:
        return "red"
    if hue < 45:
        return "orange"
    if hue < 70:
        return "yellow"
    if hue < 170:
        return "green"
    if hue < 200:
        return "cyan"
    if hue < 255:
        return "blue"
    if hue < 290:
        return "purple"
    return "pink"


def brand_quiz(state, rnd):
    recent = state.get("quiz_brands", [])[-20:]
    pool = [b for b in BRANDS if b[0] not in recent] or BRANDS
    name, colors, words = rnd.choice(pool)
    mine = {bucket(c) for c in colors}
    near, far = [], []
    for other, oc, _ in BRANDS:
        if other == name:
            continue
        common = len(mine & {bucket(c) for c in oc})
        if common == 1:
            near.append(other)
        elif common == 0:
            far.append(other)
    rnd.shuffle(near)
    rnd.shuffle(far)
    wrong = (near[:2] + far)[:3]
    opts, right = quiz.shuffle(name, wrong, rnd)
    return {"kind": "brand", "name": name, "colors": colors,
            "question": "Чиї це фірмові кольори?", "options": opts,
            "correct": right, "explain": f"Це {name}: {words}."}


def font_quiz(state, rnd):
    recent = state.get("quiz_fonts", [])[-40:]
    top = sorted(gf_families(), key=lambda f: f.get("popularity", 9999))[:150]
    pool = [f for f in top if f["family"] not in recent] or top
    f = rnd.choice(pool)
    same = [x["family"] for x in top if x.get("category") == f.get("category")
            and x["family"] != f["family"]]
    rnd.shuffle(same)
    if len(same) < 3:
        return None
    opts, right = quiz.shuffle(f["family"], same[:3], rnd)
    facts = font_facts(f)
    who = f" Автор: {facts['designers']}." if facts["designers"] else ""
    return {"kind": "font", "name": f["family"], "family": f,
            "question": "Що це за шрифт?", "options": opts, "correct": right,
            "explain": f"Це {f['family']} — {facts['category']}.{who}"[:200]}


def quiz_card(q, handle):
    path = cards.tmp_path("quiz")
    if q["kind"] == "brand":
        ok = cards.quiz_card("ВГАДАЙ БРЕНД", "Чиї це кольори?", path,
                             colors=q["colors"], handle=handle)
    else:
        f = q["family"]
        fp = cards.gfont(f["family"], sample_weight(f))
        word = "Дизайн" if has_cyr(f) else "Design"
        line = SAMPLE if has_cyr(f) else SAMPLE_LAT
        ok = fp and cards.quiz_card("ВГАДАЙ ШРИФТ", "Що це за шрифт?", path,
                                    font_path=fp, sample=word, line=line,
                                    handle=handle)
    return path if ok else None


def quiz_caption(q, foot):
    what = ("Вгадай бренд за фірмовими кольорами" if q["kind"] == "brand"
            else "Вгадай шрифт за написом")
    tags = ("#вікторина #вгадай_бренд" if q["kind"] == "brand"
            else "#вікторина #вгадай_шрифт")
    return f"<b>🧠 ВІКТОРИНА</b>\n{what} — відповідай в опитуванні 👇\n\n{foot}\n{tags}"


def make_quiz(state, rnd, kind="brand"):
    try:
        q = brand_quiz(state, rnd) if kind == "brand" else font_quiz(state, rnd)
    except Exception as e:
        print("Вікторина не зібралась:", type(e).__name__, e)
        return None
    return q if q and len(set(q["options"])) == 4 else None


# ---------- 🎨 палітра дня ----------

PALETTE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "about": {"type": "string"},
        "colors": {"type": "array", "items": {
            "type": "object",
            "properties": {"hex": {"type": "string"},
                           "name": {"type": "string"}},
            "required": ["hex", "name"],
            "additionalProperties": False}},
    },
    "required": ["name", "about", "colors"],
    "additionalProperties": False,
}
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = cards.hex_rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    """Контраст двох кольорів за WCAG (1–21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def make_palette(state, style):
    recent = state.get("palettes", [])[-40:]
    prompt = f"""Склади «палітру дня» для дизайнерів: 5 кольорів, які гарно
працюють разом. Тема — свіжа й конкретна (сезон, місце, настрій, епоха,
матеріал, кухня, природне явище). Не повторюй теми: {", ".join(recent) or "—"}.

- name: коротка назва українською, до 28 знаків;
- about: 1–2 речення — настрій і де ця палітра доречна (айдентика, лендінг,
  упаковка, постер тощо);
- colors: рівно 5 кольорів від найсвітлішого до найтемнішого: hex у форматі
  #RRGGBB і коротка назва кольору українською (1–2 слова)."""
    res = ai.ask(prompt, PALETTE_SCHEMA, effort="low", max_tokens=3000,
                 system=style)
    if not res:
        return None
    cols = [(c["hex"].upper(), c["name"].strip()) for c in res.get("colors", [])
            if HEX_RE.match(c.get("hex", ""))]
    if len(cols) != 5 or len({c[0] for c in cols}) != 5:
        print("Палітра не підійшла:", res)
        return None
    return {"name": res["name"].strip(), "about": res["about"].strip(),
            "colors": cols}


def palette_caption(pal, foot):
    pairs = [(a, b) for a in pal["colors"] for b in pal["colors"] if a != b]
    a, b = max(pairs, key=lambda x: contrast(x[0][0], x[1][0]))
    text, bg = (a, b) if luminance(a[0]) < luminance(b[0]) else (b, a)
    c = contrast(a[0], b[0])
    level = ("AAA" if c >= 7 else "AA" if c >= 4.5
             else "лише для великих заголовків")
    lines = ["<b>🎨 ПАЛІТРА ДНЯ</b>",
             f"<b>{html.escape(pal['name'], quote=False)}</b>", "",
             html.escape(pal["about"], quote=False), ""]
    lines += [f"<code>{hx}</code> — {html.escape(nm, quote=False)}"
              for hx, nm in pal["colors"]]
    lines += ["", f"▫️ Для тексту: {html.escape(text[1], quote=False)} на тлі "
              f"«{html.escape(bg[1], quote=False)}» — контраст {c:.1f}:1 "
              f"({level})",
              "Натисни на код кольору, щоб скопіювати.", "", foot,
              "#палітра #кольори"]
    return "\n".join(lines)


def make_palette_post(state, handle, foot, style):
    pal = make_palette(state, style)
    if not pal:
        return None
    path = cards.tmp_path("palette")
    if not cards.palette_card(pal["name"], pal["colors"], path, handle=handle):
        return None
    return pal, path, palette_caption(pal, foot)


def post_palette(tg, state, handle, foot, style):
    out = make_palette_post(state, handle, foot, style)
    if out and tg.send_photo_file(out[1], out[2]).get("ok"):
        state.setdefault("palettes", []).append(out[0]["name"])
        state["palettes"] = state["palettes"][-100:]
        print("Палітра дня:", out[0]["name"])
        return True
    return False


# ---------- 🎨 кейс дня ----------

CASE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "idx": {"type": "integer"},
            "cat": {"type": "string", "enum": ["web", "motion", "identity",
                                               "packaging", "poster", "other"]},
            "score": {"type": "integer"},
        },
        "required": ["idx", "cat", "score"],
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}
CASE_POST_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"},
                   "card_title": {"type": "string"},
                   "body": {"type": "string"},
                   "credit": {"type": "string"}},
    "required": ["title", "card_title", "body", "credit"],
    "additionalProperties": False,
}
IMG_ALL = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def clean_html(s):
    """Лишаємо тільки <b> та <i>, решту екрануємо."""
    s = html.escape(html.unescape(s or ""), quote=False)
    for t in ("b", "i"):
        s = s.replace(f"&lt;{t}&gt;", f"<{t}>").replace(f"&lt;/{t}&gt;",
                                                        f"</{t}>")
    return s.strip()


def working(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": cards.UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def case_items():
    """Проєкти з RSS Behance (обрані) і Abduzeedo: назва, текст, усі фото."""
    import xml.etree.ElementTree as ET
    import design_bot as db
    out = []
    for name, url in CASE_FEEDS:
        try:
            root = ET.fromstring(db.http_get(url).lstrip(b"\xef\xbb\xbf \t\r\n"))
        except Exception as e:
            print(f"{name}: не прочитався ({type(e).__name__})")
            continue
        for e in [x for x in root.iter() if db.local(x.tag) == "item"][:40]:
            t, ln = db.child(e, "title"), db.child(e, "link")
            if t is None or ln is None or not (ln.text or "").strip():
                continue
            link = ln.text.strip()
            raw = max(("".join(c.itertext()) for c in e if db.local(c.tag) in
                       ("encoded", "description")), key=len, default="")
            imgs = []
            for u in [db.item_image(e, raw)] + IMG_ALL.findall(raw):
                if not u:
                    continue
                u = urllib.parse.urljoin(link, html.unescape(u))
                if (u.startswith("http") and u not in imgs
                        and not re.search(r"\.(gif|svg)(\?|$)", u, re.I)):
                    imgs.append(u)
            if imgs:
                out.append({"src": name, "link": link,
                            "title": db.strip_html("".join(t.itertext())),
                            "text": db.strip_html(raw)[:5000],
                            "images": imgs[:8]})
    print("Кейси:", len(out))
    return out


def pick_case(state, kt, style):
    done = set(state.get("cases_posted", []))
    items = [i for i in case_items() if i["link"] not in done][:60]
    if not items:
        return None
    lines = "\n".join(f"[{i}] {it['src']} | {it['title']} | "
                      + it["text"][:300].replace("\n", " ")
                      for i, it in enumerate(items))
    prompt = f"""Ось свіжі проєкти з Behance та Abduzeedo. Для кожного визнач категорію
і оціни від 1 до 10, наскільки це сильна робота, яку варто показати дизайнерам.

cat: «web» — сайти, застосунки, UI/UX; «motion» — анімація, моушн, 3D-анімація;
«identity» — логотипи, айдентика, брендинг; «packaging» — упаковка;
«poster» — постери, афіші; «other» — усе інше (ілюстрація, фото, архітектура).
score: 9–10 — вражає й надихає; 7–8 — сильна якісна робота; 1–6 — рядова.

Проєкти:
{lines}"""
    res = ai.ask(prompt, CASE_SCHEMA, effort="low", max_tokens=6000,
                 system=style)
    if not res:
        return None
    scored = [(r, items[r["idx"]]) for r in res.get("items", [])
              if 0 <= r.get("idx", -1) < len(items)]
    good = [x for x in scored if x[0]["cat"] != "other" and x[0]["score"] >= 7]
    want = CASE_DAYS[kt.weekday()]
    pool = [x for x in good if x[0]["cat"] == want] if want else good
    if not pool:
        pool = good
    if not pool:
        return None
    r, it = max(pool, key=lambda x: x[0]["score"])
    imgs = []
    for u in it["images"]:              # обкладинка Behance у RSS — 404 px
        big = u.replace("/projects/404/", "/projects/808/")
        imgs.append(big if big != u and working(big) else u)
    return dict(it, images=imgs, cat=r["cat"], score=r["score"])


def write_case(c, style):
    cat = CASE_CATS[c["cat"]][0]
    prompt = f"""Перед тобою проєкт із {c['src']} (категорія: {cat}) — його зображення
і текст. Напиши пост «Кейс дня» українською, своїми словами.
- title: назва проєкту як в оригіналі;
- card_title: заголовок для картинки українською, до 55 знаків;
- body: 2–3 короткі речення, до 400 знаків: що це за проєкт і що в ньому
  варто роздивитися (ідея, шрифт, колір, композиція). Тільки те, що видно на
  зображеннях або сказано в тексті. Telegram HTML, лише <b> та <i>;
- credit: студія чи дизайнер, якщо прямо названі в тексті; інакше порожньо.
Нічого не вигадуй: ні імен, ні клієнтів, ні фактів.

Назва: {c['title']}
Посилання: {c['link']}
Текст:
{c['text'][:5000] or '(опису немає)'}"""
    return (ai.ask(prompt, CASE_POST_SCHEMA, effort="medium", max_tokens=4000,
                   images=c["images"][:3], system=style)
            or ai.ask(prompt, CASE_POST_SCHEMA, effort="medium",
                      max_tokens=4000, system=style))


def case_caption(c, post, foot):
    name, tag = CASE_CATS[c["cat"]]
    lines = [f"<b>🎨 КЕЙС ДНЯ · {name.upper()}</b>",
             f"<b>{html.escape(post['title'].strip(), quote=False)}</b>", "",
             clean_html(post["body"]), ""]
    credit = (post.get("credit") or "").strip()
    if credit:
        lines.append("🎨 Автор: " + html.escape(credit, quote=False))
    lines += [f'🔗 <a href="{html.escape(c["link"])}">Дивитися кейс на '
              f'{c["src"]}</a>', "", foot, f"#кейс {tag}"]
    return "\n".join(lines)


def make_case(state, kt, handle, foot, style):
    c = pick_case(state, kt, style)
    if not c:
        print("Кейс дня: немає підходящих проєктів")
        return None
    post = write_case(c, style)
    if not post:
        return None
    name, tag = CASE_CATS[c["cat"]]
    path = cards.tmp_path("case")
    ok = cards.news_card("КЕЙС ДНЯ", post["card_title"] or post["title"],
                         f"{c['src']} · {name}", c["images"][0], path,
                         tag=tag, handle=handle,
                         note=("більше фото — далі" if len(c["images"]) > 1
                               else "деталі — в пості"))
    return c, post, (path if ok else None), case_caption(c, post, foot)


def send_album(tg, card, urls, caption):
    """Альбом: наша картка (файлом) + фото проєкту (посиланнями)."""
    if tg.dry_run:
        print(f"[dry-run] альбом: картка + {len(urls)} фото")
        return {"ok": True}
    media = ([{"type": "photo", "media": "attach://card", "caption": caption,
               "parse_mode": "HTML"}]
             + [{"type": "photo", "media": u} for u in urls])
    with open(card, "rb") as f:
        img = f.read()
    boundary = "----HerDesignAlbum" + str(int(time.time() * 1000))
    head = "".join(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f"name=\"{k}\"\r\n\r\n{v}\r\n" for k, v in
                   (("chat_id", str(tg.chat)),
                    ("media", json.dumps(media, ensure_ascii=False))))
    body = ((head + f"--{boundary}\r\nContent-Disposition: form-data; "
             "name=\"card\"; filename=\"card.jpg\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n").encode("utf-8") + img
            + f"\r\n--{boundary}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        f"{tg.base}/sendMediaGroup", data=body,
        headers={"User-Agent": cards.UA,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
        if not res.get("ok"):
            print("Telegram (альбом):", str(res)[:300])
        return res
    except urllib.error.HTTPError as e:
        print("Telegram (альбом):", e.code,
              e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        print("Альбом не надіслався:", type(e).__name__)
    return {"ok": False}


def post_case(tg, state, kt, handle, foot, style):
    out = make_case(state, kt, handle, foot, style)
    if not out or not out[2]:
        return False
    c, post, card, text = out
    res = send_album(tg, card, c["images"][1:4], text) if len(c["images"]) > 1 else {}
    if not res.get("ok"):
        res = tg.send_photo_file(card, text)
    if not res.get("ok"):
        return False
    state.setdefault("cases_posted", []).append(c["link"])
    state["cases_posted"] = state["cases_posted"][-300:]
    print("Кейс дня:", c["cat"], c["title"][:80])
    return True


# ---------- розклад ----------

def tick(tg, state, kt, handle, foot, style, font_now=False, quiz_now=False,
         case_now=False, palette_now=False):
    today = kt.strftime("%Y-%m-%d")
    rnd = random.Random(f"{today}-{time.time() // 3600}")

    def due(hour, key):
        return (LIVE and hour <= kt.hour < hour + WINDOW_H
                and state.get(key) != today)

    if font_now or due(FONT_HOUR, "font_day"):
        out = make_font_post(state, rnd, handle, foot, style)
        if out:
            f, path, text = out
            if tg.send_photo_file(path, text).get("ok"):
                state["font_day"] = today
                state.setdefault("fonts_posted", []).append(f["family"])
                state["fonts_posted"] = state["fonts_posted"][-500:]
                print("Шрифт дня:", f["family"])
    if case_now or due(CASE_HOUR, "case_day"):
        if post_case(tg, state, kt, handle, foot, style):
            state["case_day"] = today
    if palette_now or due(PALETTE_HOUR, "palette_day"):
        if post_palette(tg, state, handle, foot, style):
            state["palette_day"] = today
    if quiz_now or due(QUIZ_HOUR, "quiz_day"):
        q = make_quiz(state, rnd, "brand")   # лише «Вгадай бренд» (10.10)
        card = q and quiz_card(q, handle)
        if q and card and tg.send_photo_file(card, quiz_caption(q, foot)).get("ok"):
            if quiz.send(tg, q).get("ok"):
                state["quiz_day"] = today
                key = "quiz_brands" if q["kind"] == "brand" else "quiz_fonts"
                state.setdefault(key, []).append(q["name"])
                state[key] = state[key][-60:]
                print("Вікторина:", q["kind"], q["name"])


def demo(dump, handle, foot, style):
    """Приклади рубрик у лог (картки як CARD_B64). Нічого не надсилає."""
    rnd = random.Random()
    state = {}
    out = make_font_post(state, rnd, handle, foot, style)
    if out:
        f, path, text = out
        print(f"\n===== ПРИКЛАД (шрифт дня: {f['family']}) =====\n{text}")
        dump(path)
    for kind in ("brand",):
        q = make_quiz(state, rnd, kind)
        card = q and quiz_card(q, handle)
        if not q:
            continue
        marks = ["✅" if j == q["correct"] else "▫️"
                 for j in range(len(q["options"]))]
        print(f"\n===== ПРИКЛАД (вікторина: {q['kind']}) =====\n"
              f"{quiz_caption(q, foot)}\n--- опитування ---\n{q['question']}\n"
              + "\n".join(f"{m} {o}" for m, o in zip(marks, q["options"]))
              + f"\n💡 {q['explain']}")
        if card:
            dump(card)
    import rust_digest_bot as bot
    out = make_case(state, bot.kyiv_time(), handle, foot, style)
    if out:
        c, post, card, text = out
        print(f"\n===== ПРИКЛАД (кейс дня: {c['cat']}, оцінка {c['score']}) "
              f"=====\n{text}\n--- фото в альбомі ---\n"
              + "\n".join(c["images"][:4]))
        if card:
            dump(card)
    out = make_palette_post(state, handle, foot, style)
    if out:
        pal, path, text = out
        print(f"\n===== ПРИКЛАД (палітра дня) =====\n{text}")
        dump(path)
