# -*- coding: utf-8 -*-
"""
Рубрики @Her_Design за розкладом (за Києвом):
  🔤 Шрифт дня — щодня о 09:00: безкоштовний шрифт із Google Fonts з
     кирилицею. Картка набрана самим шрифтом; факти (тип, автори,
     накреслення) — з Google Fonts, опис Claude пише, дивлячись на зразок.
  🧠 Вікторина — щодня о 15:00, по черзі: «Вгадай бренд» за 2–5 кольорами
     і «Вгадай шрифт». Картка + опитування-квіз Telegram (з поясненням).
     Неправильні варіанти — бренди з іншими кольорами, щоб відповідь була
     одна.
"""
import base64
import colorsys
import json
import random
import re
import time
import urllib.request

import cs2_ai as ai
import design_cards as cards
import quiz

LIVE = False                     # увімкнемо після схвалення прикладів
FONT_HOUR = 9
QUIZ_HOUR = 15
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
              "▫️ Кирилиця: є, з українськими літерами",
              f"▫️ Накреслення: {facts['styles']}"]
    if facts["designers"]:
        lines.append(f"▫️ Автор: {h.escape(facts['designers'])}")
    lines += ["▫️ Ліцензія: безкоштовний, відкрита ліцензія",
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


def make_quiz(state, rnd, kind):
    for k in (kind, "font" if kind == "brand" else "brand"):
        try:
            q = brand_quiz(state, rnd) if k == "brand" else font_quiz(state, rnd)
        except Exception as e:
            print("Вікторина не зібралась:", type(e).__name__, e)
            q = None
        if q and len(set(q["options"])) == 4:
            return q
    return None


# ---------- розклад ----------

def tick(tg, state, kt, handle, foot, style, font_now=False, quiz_now=False):
    today = kt.strftime("%Y-%m-%d")
    rnd = random.Random(f"{today}-{time.time() // 3600}")
    if font_now or (LIVE and kt.hour >= FONT_HOUR
                    and state.get("font_day") != today):
        out = make_font_post(state, rnd, handle, foot, style)
        if out:
            f, path, text = out
            if tg.send_photo_file(path, text).get("ok"):
                state["font_day"] = today
                state.setdefault("fonts_posted", []).append(f["family"])
                state["fonts_posted"] = state["fonts_posted"][-500:]
                print("Шрифт дня:", f["family"])
    if quiz_now or (LIVE and kt.hour >= QUIZ_HOUR
                    and state.get("quiz_day") != today):
        kind = "brand" if kt.toordinal() % 2 == 0 else "font"
        q = make_quiz(state, rnd, kind)
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
    for kind in ("brand", "font"):
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
