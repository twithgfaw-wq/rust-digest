# -*- coding: utf-8 -*-
"""
Рубрика «💼 Инвестиции CS2» — ТОП-5 предметов, за которыми стоит следить.

Все цифры считает бот, а не модель:
  • история цен — CSFloat (дневные продажи с июня 2023, ключ не нужен);
  • статус предложения — в дропе или нет (список ACTIVE_POOL);
  • выгодная цена, сценарии и итоговое решение — по правилам ниже.
Claude Opus 5.5 только объясняет решение простыми словами.

Пост — альбом картинок (cs2_cards.py): обзор ТОП-5 и по карточке на
каждый предмет (цена, решение, график с выгодной зоной, что может быть
дальше). Сумма «на руки» — после комиссии CSFloat 2%.
"""
import html
import json
import os
import statistics
import tempfile
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import cs2_ai as ai
import cs2_cards as cards
import rust_digest_bot as bot

CSFLOAT = "https://csfloat.com/api/v1/history/{}/graph"
# Активный еженедельный дроп (по трекерам сообщества, сверено 08.10.2026).
# Предметы отсюда пополняются каждую неделю — их запас растёт.
ACTIVE_POOL = {"Sealed Dead Hand Terminal", "Sealed Genesis Terminal",
               "Kilowatt Case", "Revolution Case", "Dreams & Nightmares Case"}
RUBRIC = "💼 ИНВЕСТИЦИИ CS2"
MIN_PRICE = 1.0          # $ на CSFloat — копеечные предметы не берём
MIN_SALES = 5            # продаж в день на CSFloat за последний месяц
CSFLOAT_FEE = 0.02
VERDICTS = {"buy": ("🟢", "МОЖНО БРАТЬ"), "watch": ("🟡", "ПОДОЖДАТЬ"),
            "avoid": ("🔴", "НЕ БРАТЬ")}
HORIZONS = ["несколько месяцев", "год и больше"]


# ---------- данные ----------

def history(name):
    """Дневная история продаж CSFloat: [(дата, средняя цена $, продаж)]."""
    data = bot.http_get_json(CSFLOAT.format(urllib.parse.quote(name)),
                             timeout=30)
    return [(d["day"][:10], d["avg_price"] / 100, d["count"])
            for d in reversed(data or []) if d.get("avg_price")]


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
                return cards.STEAM_IMG.format(icon)
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
        "spark_days": [d for d, _ in w],
    }
    m["buy_to"] = round(m["q1_1y"] * 1.05, 2)
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
    не брать — предмет в активном дропе (запас растёт) или падает
      больше чем на 25% за 3 месяца;
    можно брать — дропа нет, месяц без падения (не хуже −3%), три месяца
      не хуже −10%, цена уже выгодная (buy_to: нижняя четверть цен за год
      + 5%) и не меньше 5 продаж в день;
    иначе — подождать."""
    if m["in_drop"] or (m["ch_3m"] is not None and m["ch_3m"] <= -25):
        return "avoid"
    if ((m["ch_1m"] or 0) >= -3 and (m["ch_3m"] or 0) >= -10
            and m["now"] <= m["buy_to"] and m["sales_day"] >= MIN_SALES):
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


def pick_top(items, n=5, recent=()):
    """Лучшие n по score; недавно показанные (recent) — только если без них
    не набирается n."""
    ok = [m for m in items if m["now"] >= MIN_PRICE
          and m["sales_day"] >= MIN_SALES and m["ch_1y"] is not None]
    ok.sort(key=score, reverse=True)
    fresh = [m for m in ok if m["name"] not in recent]
    return (fresh + [m for m in ok if m["name"] in recent])[:n]


def market_context(items):
    """Как ведёт себя рынок контейнеров в целом (медианы по всем)."""
    med = lambda k: statistics.median([m[k] for m in items
                                       if m[k] is not None] or [0])
    return {"items": len(items), "median_ch_1m": med("ch_1m"),
            "median_ch_3m": med("ch_3m"), "median_ch_1y": med("ch_1y")}


def kind(n):
    """Что это за предмет — по-русски, для карточки."""
    if n.endswith("Terminal"):
        return "терминал"
    if "Souvenir" in n:
        return "сувенирный набор"
    if n.endswith("Collection Package"):
        return "набор коллекции"
    if n.endswith("Capsule"):
        return "капсула"
    return "кейс"


def easy_sell(n):
    """Как быстро продаётся — словами, без слова «ликвидность»."""
    return ("очень быстро" if n >= 100 else "быстро" if n >= 30
            else "нормально" if n >= 10 else "медленно")


# ---------- текст (Claude) ----------

INVEST_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "why": {"type": "string"},
                           "horizon": {"type": "string", "enum": HORIZONS}},
            "required": ["name", "why", "horizon"],
            "additionalProperties": False}},
    },
    "required": ["intro", "items"],
    "additionalProperties": False,
}


def write_post(top, context):
    """Claude объясняет готовые решения простыми словами."""
    data = []
    for m in top:
        d = {k: m[k] for k in ("name", "now", "sales_day", "in_drop", "ch_1m",
                               "ch_3m", "ch_1y", "low_1y", "high_1y",
                               "median_1y", "buy_to", "peak", "peak_week",
                               "first_day", "first_price", "periods")}
        d["verdict"] = VERDICTS[m["verdict"]][1].lower()
        d["cheap_but_still_falling"] = still_falling(m)
        data.append(d)
    prompt = f"""Рубрика «Инвестиции CS2»: ежедневный ТОП-5 кейсов и наборов.
Читают обычные игроки, многие — школьники. Пиши очень просто, как другу,
без терминов (никаких «ликвидность», «медиана», «квартиль», «волатильность»).

Данные уже посчитаны. Цены — в долларах, now — средняя цена продаж на CSFloat
за неделю. buy_to — до какой цены брать выгодно. in_drop — предмет ещё
выпадает в игре (запас растёт). periods — средние цены по полугодиям.
Решение (verdict) уже принято по правилам — не меняй его и не придумывай
своих чисел, бери только числа из данных. cheap_but_still_falling — цена
уже низкая, но всё ещё падает: поэтому «подождать», а не «брать».

Контекст рынка контейнеров: {json.dumps(context, ensure_ascii=False)}
Важное (проверено на данных CSFloat): с января 2026 старые кейсы вообще не
выпадают — их запас только уменьшается; весной на этом был всплеск цен,
к осени большинство откатилось. Новые терминалы дешевеют на 90%+ за первые
месяцы.

Данные: {json.dumps(data, ensure_ascii=False)}

Верни:
- intro: одно короткое предложение (до 110 знаков) — что сейчас с ценами
  на кейсы, простыми словами.
- items: для каждого предмета в том же порядке:
  • name — как во входе;
  • why — главная причина решения, до 70 знаков, простыми словами
    (пример: «Подешевел вдвое от пика и стоит почти на дне года»);
  • horizon — сколько, скорее всего, придётся держать: «{HORIZONS[0]}»
    или «{HORIZONS[1]}» — оцени по тому, как цена ходила раньше (periods).
"""
    return ai.ask(prompt, INVEST_SCHEMA, effort="medium")


def fallback_why(m):
    """Если Claude недоступен — короткая причина по правилам."""
    if m["verdict"] == "avoid":
        return ("Ещё выпадает в игре — предметов становится больше"
                if m["in_drop"] else "Цена быстро падает последние месяцы")
    if m["verdict"] == "buy":
        return "Цена у нижней границы за год и не падает"
    if m["now"] <= m["buy_to"]:
        return "Цена низкая, но ещё снижается — лучше дождаться дна"
    return "Сейчас дороже выгодной цены — лучше дождаться скидки"


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
    """Процент для картинки — обычный дефис: «−» есть не во всех шрифтах."""
    return "—" if v is None else f"{v:+d}%"


def visible_len(text):
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def still_falling(m):
    """«Подождать», хотя цена уже в выгодной зоне: она ещё падает."""
    return m["verdict"] == "watch" and m["now"] <= m["buy_to"]


def advice(m):
    """Что делать — одной строкой (для карточки)."""
    if still_falling(m):
        return "Цена уже низкая, но ещё падает — ждём, когда остановится"
    return {"buy": f"Хорошая цена — брать до {money(m['buy_to'])}",
            "watch": f"Дороговато. Ждём {money(m['buy_to'])} или дешевле",
            "avoid": ("Ещё выпадает в игре — предметов всё больше"
                      if m["in_drop"] else "Цена быстро падает — лучше не трогать")
            }[m["verdict"]]


def hint(m):
    """Что делать — коротко (обзор и подпись)."""
    if still_falling(m):
        return "ещё падает — ждём"
    return {"buy": f"можно брать до {money(m['buy_to'])}",
            "watch": f"ждём {money(m['buy_to'])}",
            "avoid": ("ещё выпадает в игре" if m["in_drop"]
                      else "цена падает")}[m["verdict"]]


def make_cards(top, said, date):
    """Обзор ТОП-5 и по карточке на каждый предмет — пути к картинкам."""
    out, tmp = [], tempfile.gettempdir()
    overview = [{"name": short_name(m["name"]), "icon": m["icon"],
                 "verdict": m["verdict"], "price": money(m["now"]),
                 "hint": hint(m)} for m in top]
    path = os.path.join(tmp, "cs2_invest.jpg")
    try:
        if cards.top5_card("Инвестиции · ТОП-5 дня",
                           f"{date} · что можно купить и что лучше не трогать",
                           overview, path):
            out.append(path)
    except Exception as e:
        print("Обзорная карточка не собралась:", e)
    for k, (m, t) in enumerate(zip(top, said)):
        sc = m["scenarios"]
        val = lambda s: money(s["price"]) if s["price"] else "—"
        path = os.path.join(tmp, f"cs2_invest_{k + 1}.jpg")
        try:
            if cards.item_card(
                    path, k + 1, len(top), short_name(m["name"]),
                    kind(m["name"]), m["icon"], money(m["now"]),
                    money(m["now"] * (1 - CSFLOAT_FEE)), m["verdict"],
                    advice(m), t["why"].strip(), m["spark"], m["spark_days"],
                    m["buy_to"] if m["verdict"] != "avoid" else None,
                    f"выгодно — до {money(m['buy_to'])}",
                    [("Если повезёт", val(sc["optimistic"]),
                      signed(sc["optimistic"]["pct"]), cards.GREEN),
                     ("Скорее всего", val(sc["base"]),
                      signed(sc["base"]["pct"]), cards.TEXT),
                     ("Если не повезёт", val(sc["negative"]),
                      signed(sc["negative"]["pct"]), cards.RED)],
                    [f"Продаётся {easy_sell(m['sales_day'])}: "
                     f"~{m['sales_day']} в день", f"Держать: {t['horizon']}"],
                    money):
                out.append(path)
        except Exception as e:
            print("Карточка не собралась:", m["name"], e)
    return out


def compose(skinport, kyiv_now, recent=()):
    """Готовый пост: (подпись, [картинки: обзор + карточка на каждый],
    советы [{name, verdict, price}]) или None. Всё считается заново;
    recent — показанные в последние дни, их ставим в конец очереди."""
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
    top = pick_top(items, recent=set(recent))
    for m in top:
        m["verdict"] = verdict(m)
        m["scenarios"] = scenarios(m)
        m["icon"] = steam_icon(m["name"])
        time.sleep(1)
    context = market_context(items)
    print("Рынок:", context)
    for m in top:
        print(f"{m['name']}: ${m['now']} · {m['verdict']} · 1м {m['ch_1m']}% ·"
              f" 3м {m['ch_3m']}% · год {m['ch_1y']}% · {m['sales_day']}/день")
    text = write_post(top, context) or {}
    said = text.get("items") or []
    if len(said) != len(top):
        print("Claude не объяснил — причины по правилам")
        said = [{"why": fallback_why(m), "horizon": HORIZONS[0]} for m in top]
    date = kyiv_now.strftime("%d.%m.%Y")

    lines = [f"<b>{RUBRIC} · ТОП-5 ДНЯ</b>", f"🗓 {date}", ""]
    if (text.get("intro") or "").strip():
        lines += [html.escape(text["intro"].strip()), ""]
    for k, m in enumerate(top):
        lines.append(f"{k + 1}. {VERDICTS[m['verdict']][0]} "
                     f"<b>{html.escape(short_name(m['name']))}</b> — "
                     f"{money(m['now'])} · {hint(m)}")
    lines += ["", "🟢 можно брать · 🟡 подождать · 🔴 не брать",
              "👉 Листай карточки: график и что может быть дальше",
              "<i>Не финансовый совет. Цены — продажи на CSFloat.</i>", "",
              "#cs2 #инвестиции_cs2"]
    picks = [{"name": m["name"], "verdict": m["verdict"], "price": m["now"]}
             for m in top]
    return "\n".join(lines), make_cards(top, said, date), picks
