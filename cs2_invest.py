# -*- coding: utf-8 -*-
"""
Рубрика «💼 Инвестиции CS2» — ТОП-5 предметов, за которыми стоит следить.

Все цифры считает бот, а не модель:
  • история цен — CSFloat (дневные продажи с июня 2023, ключ не нужен);
  • текущие цены и объём — Steam (priceoverview) и CSFloat;
  • статус предложения — в дропе или нет (список ACTIVE_POOL);
  • зона покупки, сценарии и итоговое решение — по правилам ниже.
Claude Opus 5.5 только объясняет эти данные человеческим языком.

Чистая сумма после продажи: CSFloat — минус 2% (реальные деньги),
Steam — цена / 1.15 (только на кошелёк Steam).
"""
import html
import io
import json
import os
import statistics
import tempfile
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import cs2_ai as ai
import rust_digest_bot as bot

CSFLOAT = "https://csfloat.com/api/v1/history/{}/graph"
STEAM_PRICE = ("https://steamcommunity.com/market/priceoverview/"
               "?appid=730&currency=1&market_hash_name={}")
# Активный еженедельный дроп (по трекерам сообщества, сверено 08.10.2026).
# Предметы отсюда пополняются каждую неделю — их запас растёт.
ACTIVE_POOL = {"Sealed Dead Hand Terminal", "Sealed Genesis Terminal",
               "Kilowatt Case", "Revolution Case", "Dreams & Nightmares Case"}
RUBRIC = "💼 ИНВЕСТИЦИИ CS2"
MIN_PRICE = 1.0          # $ на CSFloat — копеечные предметы не берём
MIN_SALES = 5            # продаж в день на CSFloat за последний месяц
CSFLOAT_FEE = 0.02
STEAM_FEE = 1.15
VERDICTS = {"buy": ("🟢", "ПОКУПАТЬ", (61, 220, 132)),
            "watch": ("🟡", "НАБЛЮДАТЬ", (255, 200, 61)),
            "avoid": ("🔴", "ИЗБЕГАТЬ", (255, 82, 82))}


# ---------- данные ----------

def history(name):
    """Дневная история продаж CSFloat: [(дата, средняя цена $, продаж)]."""
    data = bot.http_get_json(CSFLOAT.format(urllib.parse.quote(name)),
                             timeout=30)
    return [(d["day"][:10], d["avg_price"] / 100, d["count"])
            for d in reversed(data or []) if d.get("avg_price")]


def steam_price(name):
    """Steam: самое дешёвое предложение, медиана и продажи за сутки."""
    try:
        d = bot.http_get_json(STEAM_PRICE.format(urllib.parse.quote(name)))
    except Exception:
        return {}
    num = lambda s: float(s.replace("$", "").replace(",", "")) if s else None
    return {"low": num(d.get("lowest_price")), "median": num(d.get("median_price")),
            "volume": int((d.get("volume") or "0").replace(",", ""))}


def steam_icon(name):
    q = urllib.parse.urlencode({"query": name, "appid": 730, "norender": 1,
                                "count": 10})
    try:
        data = bot.http_get_json(
            f"https://steamcommunity.com/market/search/render/?{q}")
    except Exception:
        return ""
    for r in data.get("results") or []:
        if r.get("hash_name") == name:
            icon = (r.get("asset_description") or {}).get("icon_url")
            if icon:
                return ("https://community.cloudflare.steamstatic.com/economy/"
                        f"image/{icon}/256fx256f")
    return ""


def universe(skinport):
    """Кейсы, терминалы, капсулы и сувенирные пакеты, которые реально
    продаются (от 20 продаж за месяц на Skinport)."""
    out = []
    for i in skinport:
        n = i.get("market_hash_name") or ""
        m = i.get("last_30_days") or {}
        if (n.endswith((" Case", " Terminal", " Capsule", " Package"))
                and (m.get("volume") or 0) >= 20):
            out.append(n)
    return out


# ---------- метрики ----------

def day(off):
    return (datetime.now(timezone.utc) + timedelta(days=off)).strftime("%Y-%m-%d")


def wavg(h, a, b):
    """Средняя цена за период [a, b) с весом по числу продаж."""
    w = [x for x in h if a <= x[0] < b]
    c = sum(x[2] for x in w)
    return sum(x[1] * x[2] for x in w) / c if c else None


def weekly(h):
    """Медиана дневных цен по неделям — для графика, максимумов и минимумов.
    Медиана не даёт одной странной сделке нарисовать фальшивый пик."""
    return [(h[i][0], statistics.median(x[1] for x in h[i:i + 7]))
            for i in range(0, len(h) - 6, 7)]


def pct(a, b):
    return round((a / b - 1) * 100) if a and b else None


def metrics(name, h):
    now = wavg(h, day(-7), day(1))
    if not now or len(h) < 120:
        return None
    w = weekly(h)
    year = [p for d, p in w if d >= day(-365)]
    sales = sum(x[2] for x in h if x[0] >= day(-30)) / 30
    q = statistics.quantiles(year, n=4) if len(year) >= 8 else [now] * 3
    peak = max(w, key=lambda x: x[1])
    m = {
        "name": name, "now": round(now, 2), "sales_day": round(sales),
        "in_drop": name in ACTIVE_POOL,
        "ch_1m": pct(now, wavg(h, day(-37), day(-23))),
        "ch_3m": pct(now, wavg(h, day(-97), day(-83))),
        "ch_1y": pct(now, wavg(h, day(-372), day(-358))),
        "low_1y": round(min(year), 2) if year else None,
        "high_1y": round(max(year), 2) if year else None,
        "q1_1y": round(q[0], 2), "median_1y": round(q[1], 2),
        "peak": round(peak[1], 2), "peak_week": peak[0],
        "first_day": h[0][0], "first_price": round(h[0][1], 2),
        "spark": [round(p, 2) for _, p in w],
    }
    periods = []
    for y in range(int(h[0][0][:4]), datetime.now(timezone.utc).year + 1):
        for a, b, lab in ((f"{y}-01-01", f"{y}-07-01", f"{y} I пол."),
                          (f"{y}-07-01", f"{y + 1}-01-01", f"{y} II пол.")):
            v = wavg(h, a, b)
            if v:
                periods.append((lab, round(v, 2)))
    m["periods"] = periods
    return m


def verdict(m):
    """Решение по правилам (модель его не меняет):
    избегать — предмет в активном дропе (запас растёт) или падает
      больше чем на 25% за 3 месяца;
    покупать — дропа нет, месяц без падения (не хуже −3%), три месяца
      не хуже −10%, цена уже в зоне покупки (не дороже нижней четверти
      цен за год + 5%) и не меньше 5 продаж в день;
    иначе — наблюдать."""
    if m["in_drop"] or (m["ch_3m"] is not None and m["ch_3m"] <= -25):
        return "avoid"
    if ((m["ch_1m"] or 0) >= -3 and (m["ch_3m"] or 0) >= -10
            and m["now"] <= m["q1_1y"] * 1.05 and m["sales_day"] >= MIN_SALES):
        return "buy"
    return "watch"


def scenarios(m):
    """Три сценария — уровни, где цена уже была за последний год."""
    s = {"optimistic": (m["high_1y"], "максимум за год"),
         "base": (m["median_1y"], "медиана за год"),
         "negative": (m["low_1y"], "минимум за год")}
    return {k: {"price": v, "pct": pct(v, m["now"]), "basis": why}
            for k, (v, why) in s.items()}


def score(m):
    """Для отбора ТОП-5: устойчивость за год, стабилизация за месяц,
    ликвидность и дисконт к пику; предметы в дропе — в конец."""
    if m["in_drop"]:
        return -999
    s = (m["ch_1y"] or 0) * 0.5 + (m["ch_1m"] or 0) * 1.0
    s += min(m["sales_day"], 200) ** 0.5
    s += max(0, pct(m["peak"], m["now"]) or 0) * 0.1
    return s


def pick_top(items, n=5):
    ok = [m for m in items if m["now"] >= MIN_PRICE
          and m["sales_day"] >= MIN_SALES and m["ch_1y"] is not None]
    return sorted(ok, key=score, reverse=True)[:n]


def market_context(items):
    """Как ведёт себя рынок контейнеров в целом (медианы по всем)."""
    med = lambda k: statistics.median([m[k] for m in items
                                       if m[k] is not None] or [0])
    return {"items": len(items), "median_ch_1m": med("ch_1m"),
            "median_ch_3m": med("ch_3m"), "median_ch_1y": med("ch_1y")}


# ---------- текст (Claude) ----------

INVEST_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "short": {"type": "string"},
                           "details": {"type": "string"}},
            "required": ["name", "short", "details"],
            "additionalProperties": False}},
    },
    "required": ["intro", "items"],
    "additionalProperties": False,
}


def write_post(top, context):
    """Claude объясняет готовые цифры. Решения и уровни уже посчитаны."""
    data = []
    for m in top:
        d = {k: m[k] for k in ("name", "now", "sales_day", "in_drop", "ch_1m",
                               "ch_3m", "ch_1y", "low_1y", "high_1y",
                               "median_1y", "q1_1y", "peak", "peak_week",
                               "first_day", "first_price", "periods")}
        d.update({"verdict": VERDICTS[m["verdict"]][1].lower(),
                  "steam": m.get("steam"), "net": m["net"],
                  "buy_zone_to": m["q1_1y"], "scenarios": m["scenarios"]})
        data.append(d)
    prompt = f"""Рубрика «Инвестиции CS2»: еженедельный ТОП-5 предметов, за которыми
стоит следить. Ниже — уже посчитанные данные. Цены — в долларах, основная
цена (now) — средняя продажа на CSFloat за неделю (реальные деньги).
net — сколько продавец получит на руки: CSFloat минус 2% (деньги),
Steam — цена / 1.15 (только на кошелёк Steam, вывести нельзя).
sales_day — продаж в день на CSFloat. in_drop — выпадает ли предмет в
еженедельном дропе (запас растёт). periods — средние цены по полугодиям.
Решение (verdict) и сценарии уже рассчитаны по правилам — не меняй их и не
добавляй своих чисел.

Контекст рынка контейнеров: {json.dumps(context, ensure_ascii=False)}

Важное о рынке (проверено на данных CSFloat): с января 2026 старые кейсы
вообще не выпадают — их запас может только уменьшаться; весной на этом был
всплеск цен, к осени большинство откатилось. Новые терминалы дешевеют на
90%+ за первые месяцы.

Данные: {json.dumps(data, ensure_ascii=False)}

Напиши:
- intro: 1–2 предложения о состоянии рынка по контексту (без воды).
- items: для каждого предмета в том же порядке:
  • name — как во входе;
  • short — одна строка до 90 знаков: главная причина следить/не брать;
  • details — разбор (до 650 знаков, Telegram HTML), строки:
    «💵 Цена: …» (CSFloat и Steam, на руки после комиссии),
    «📈 История: …» (коротко путь цены по periods + пик),
    «💧 Ликвидность: …» (продаж в день),
    «✅ За: …» (почему может расти — только из данных),
    «⚠️ Риски: …» (почему может падать),
    «🎯 Зона покупки: до …» (buy_zone_to), «⏳ Горизонт: …»
    (оцени по истории колебаний: месяцы или год+, объясни одним словом),
    «🔮 Сценарии: ↑ … / → … / ↓ …» (цены и % из scenarios),
    «Итог: <b>…</b>» (verdict).
"""
    return ai.ask(prompt, INVEST_SCHEMA, effort="high")


# ---------- картинка ----------

def build_card(title, subtitle, rows, out_path):
    """Карточка ТОП-5: иконка, название, цены, график за всё время и
    плашка решения. Рисуем в 2× и уменьшаем."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        return False
    S, W = 2, 1440
    RH, TOP = 168, 270
    H = TOP + len(rows) * RH + 120
    p = lambda v: int(v * S)
    gold, card_bg = (240, 190, 70), (31, 34, 43)
    line_c, muted = (48, 52, 64), (150, 156, 172)
    grad = Image.linear_gradient("L").resize((p(W), p(H)))
    img = Image.composite(Image.new("RGB", (p(W), p(H)), (11, 12, 16)),
                          Image.new("RGB", (p(W), p(H)), (27, 29, 37)),
                          grad).convert("RGBA")
    glow = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 8 - 75, -55, W // 8 + 45, 45),
                                 fill=gold + (100,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)).resize(
        (p(W), p(H)), Image.BICUBIC))
    draw = ImageDraw.Draw(img)

    def font(size, bold=False):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/"
                                      + name, p(size))
        except Exception:
            return ImageFont.load_default()

    def fit(text, fnt, width):
        if draw.textlength(text, font=fnt) <= width:
            return text
        while text and draw.textlength(text + "…", font=fnt) > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def icon(url, size):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": bot.UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGBA")
            im.thumbnail((p(size), p(size)), Image.LANCZOS)
            return im
        except Exception:
            return None

    draw.rectangle((0, 0, p(W), p(12)), fill=gold)
    tag, tf = "ИНВЕСТИЦИИ CS2", font(22, True)
    tw = draw.textlength(tag, font=tf)
    draw.rounded_rectangle((p(64), p(52), p(64) + tw + p(40), p(94)),
                           radius=p(21), fill=gold)
    draw.text((p(64) + (tw + p(40)) / 2, p(73)), tag, font=tf,
              fill=(20, 20, 24), anchor="mm")
    draw.text((p(62), p(150)), title, font=font(64, True),
              fill=(255, 255, 255), anchor="lm")
    draw.text((p(64), p(212)), fit(subtitle, font(28), p(W - 128)),
              font=font(28), fill=muted, anchor="lm")

    y = TOP
    for k, r in enumerate(rows):
        emoji, label, color = VERDICTS[r["verdict"]]
        draw.rounded_rectangle((p(56), p(y), p(W - 56), p(y + RH - 14)),
                               radius=p(26), fill=card_bg, outline=line_c,
                               width=p(2))
        draw.text((p(84), p(y + 77)), str(k + 1), font=font(40, True),
                  fill=gold, anchor="mm")
        draw.rounded_rectangle((p(114), p(y + 22), p(224), p(y + 132)),
                               radius=p(20), fill=(45, 49, 60))
        ic = icon(r["icon"], 100) if r.get("icon") else None
        if ic:
            img.alpha_composite(ic, (p(114) + (p(110) - ic.width) // 2,
                                     p(y + 22) + (p(110) - ic.height) // 2))
        draw.text((p(248), p(y + 46)), fit(r["name"], font(34, True), p(560)),
                  font=font(34, True), fill=(240, 242, 246), anchor="lm")
        draw.text((p(248), p(y + 92)), fit(r["prices"], font(25), p(560)),
                  font=font(25), fill=muted, anchor="lm")
        draw.text((p(248), p(y + 126)), fit(r["change"], font(24), p(560)),
                  font=font(24), fill=muted, anchor="lm")
        # график цены за всё время (по неделям)
        sp = r["spark"]
        gx0, gx1, gy0, gy1 = 840, 1130, y + 26, y + 128
        if len(sp) >= 2:
            lo, hi = min(sp), max(sp)
            pts = [(p(gx0 + (gx1 - gx0) * i / (len(sp) - 1)),
                    p(gy1 - (gy1 - gy0) * ((v - lo) / (hi - lo) if hi > lo
                                           else 0.5)))
                   for i, v in enumerate(sp)]
            draw.line(pts, fill=color, width=p(3), joint="curve")
            draw.ellipse((pts[-1][0] - p(6), pts[-1][1] - p(6),
                          pts[-1][0] + p(6), pts[-1][1] + p(6)), fill=color)
            draw.text((p(gx0), p(gy1 + 18)), r["since"], font=font(18),
                      fill=(110, 116, 132), anchor="lm")
        bf = font(24, True)
        bw = draw.textlength(label, font=bf)
        bx1 = p(W - 80)
        draw.rounded_rectangle((bx1 - bw - p(40), p(y + 56), bx1,
                                p(y + 100)), radius=p(22), fill=color)
        draw.text((bx1 - bw / 2 - p(20), p(y + 78)), label, font=bf,
                  fill=(20, 20, 24), anchor="mm")
        y += RH

    draw.line((p(64), p(H - 80), p(W - 64), p(H - 80)), fill=line_c,
              width=p(2))
    draw.text((p(64), p(H - 44)), "цены: CSFloat (история с 2023) и Steam",
              font=font(24), fill=(120, 126, 142), anchor="lm")
    draw.text((p(W - 64), p(H - 44)), "@cs2_me", font=font(28, True),
              fill=gold, anchor="rm")
    img = img.convert("RGB").resize((W, H), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=95, subsampling=0)
    return True


# ---------- сборка поста ----------

def money(v):
    return f"${v:,.2f}".replace(",", " ")


def short_name(n):
    """Короче для картинки: «… Souvenir Package» → «… Souvenir» и т. п."""
    for a, b in ((" Souvenir Highlight Package", " Souvenir"),
                 (" Souvenir Package", " Souvenir"),
                 (" Collection Package", " Package"),
                 (" Weapon Case", " Case"), (" Sticker Capsule", " Capsule"),
                 (" Autograph Capsule", " Autographs"),
                 ("Operation ", "Op. ")):
        n = n.replace(a, b)
    return n


def signed(v):
    return "—" if v is None else f"{v:+d}%".replace("-", "−")


def visible_len(text):
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def safe_html(s):
    """Текст от модели → безопасный Telegram HTML (только <b>, <i>, ссылки)."""
    s = html.escape(html.unescape(s or ""), quote=False)
    s = re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", s)
    s = re.sub(r'&lt;a href="(https?://[^"\s<>]+)"&gt;', r'<a href="\1">', s)
    return s.replace("&lt;/a&gt;", "</a>").strip()


def compose(skinport, kyiv_now):
    """Готовый пост: (подпись к картинке, путь к картинке, подробный разбор)
    или None. Всё считается заново из свежих данных."""
    names = universe(skinport)
    print(f"Инвестиции: {len(names)} контейнеров в выборке")
    items = []
    for n in names:
        try:
            m = metrics(n, history(n))
        except Exception as e:
            print("Нет истории CSFloat:", n, e)
            m = None
        if m:
            items.append(m)
        time.sleep(0.4)
    if len(items) < 15:
        print("Мало данных для разбора:", len(items))
        return None
    top = pick_top(items)
    for m in top:
        m["verdict"] = verdict(m)
        m["scenarios"] = scenarios(m)
        st = steam_price(m["name"])
        m["steam"] = st
        m["net"] = {"csfloat": round(m["now"] * (1 - CSFLOAT_FEE), 2),
                    "steam_wallet": (round((st.get("median") or st.get("low"))
                                           / STEAM_FEE, 2)
                                     if (st.get("median") or st.get("low"))
                                     else None)}
        m["icon"] = steam_icon(m["name"])
        time.sleep(2)
    context = market_context(items)
    print("Рынок:", context)
    for m in top:
        print(f"{m['name']}: ${m['now']} · {m['verdict']} · 1м {m['ch_1m']}% ·"
              f" 3м {m['ch_3m']}% · год {m['ch_1y']}% · {m['sales_day']}/день")
    text = write_post(top, context)
    if not text or len(text.get("items") or []) != len(top):
        print("Claude не написал разбор — пост не собираем")
        return None
    date = kyiv_now.strftime("%d.%m.%Y")

    def make_caption(intro, short):
        lines = [f"<b>{RUBRIC} · ТОП-5 НЕДЕЛИ</b>", f"🗓 {date}", ""]
        if intro:
            lines += [html.escape(text["intro"].strip()), ""]
        for k, (m, t) in enumerate(zip(top, text["items"])):
            e = VERDICTS[m["verdict"]][0]
            tail = f" · {html.escape(t['short'].strip())}" if short else ""
            lines.append(f"{k + 1}. {e} <b>{html.escape(m['name'])}</b> — "
                         f"{money(m['now'])}{tail}")
        lines += ["", "🟢 покупать · 🟡 наблюдать · 🔴 избегать",
                  "Подробный разбор каждого — ниже 👇", "",
                  "#cs2 #инвестиции_cs2"]
        return "\n".join(lines)

    for intro, short in ((True, True), (False, True), (False, False)):
        caption = make_caption(intro, short)
        if visible_len(caption) <= 1024:
            break
    details = [f"<b>{RUBRIC} · РАЗБОР</b>", ""]
    for k, (m, t) in enumerate(zip(top, text["items"])):
        details += [f"<b>{k + 1}. {html.escape(m['name'])}</b>",
                    safe_html(t["details"]), ""]
    details += ["<i>Цифры — продажи CSFloat с 2023 года и цены Steam. "
                "Решение считается по правилам, это не обещание дохода.</i>"]
    rows = []
    for m in top:
        st = m["steam"]
        rows.append({
            "name": short_name(m["name"]), "icon": m["icon"],
            "verdict": m["verdict"],
            "prices": (f"CSFloat {money(m['now'])}"
                       + (f" · Steam {money(st['median'] or st['low'])}"
                          if st.get("median") or st.get("low") else "")),
            "change": (f"год {signed(m['ch_1y'])} · 3 мес {signed(m['ch_3m'])}"
                       f" · {m['sales_day']} продаж/день"),
            "spark": m["spark"],
            "since": f"с {m['first_day'][:7]}",
        })
    card = os.path.join(tempfile.gettempdir(), "cs2_invest.jpg")
    try:
        ok = build_card("ТОП-5 НЕДЕЛИ", f"{date} · кейсы, капсулы и пакеты",
                        rows, card)
    except Exception as e:
        print("Карточка не собралась:", e)
        ok = False
    return caption, (card if ok else ""), "\n".join(details)
