# -*- coding: utf-8 -*-
"""
Новые рубрики CS2-канала (выбраны 08.10.2026):
  🎰 «Открывать кейс или нет?» — сколько в среднем возвращает открытие
     кейса и какой шанс хотя бы окупиться;
  ✨ «Скин дня» — одна красивая карточка: цены по износу, история цены
     и факт из официального описания Valve;
  🗳 «Угадай цену» — опрос, какой из двух скинов подорожает за неделю,
     через неделю — итог с реальными ценами и следующий опрос;
  📒 «Мы советовали — что вышло» — честный отчёт по прошлым советам
     из «Инвестиций»: какая была цена тогда и какая сейчас.

Данные: состав кейсов, редкость, диапазон float и описания скинов —
ByMykel/CSGO-API (открытые JSON на GitHub); цены — продажи Skinport;
история цен — CSFloat. Шансы открытия — опубликованные Valve.
"""
import html
import json
import os
import random
import re
import tempfile
import time
import urllib.parse

import cs2_ai as ai
import cs2_cards as cards
import cs2_invest as invest
import rust_digest_bot as bot

API = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/{}.json"
KEY_PRICE = 2.49          # $ — ключ от кейса в Steam
WEARS = [("Factory New", "FN", 0.0, 0.07), ("Minimal Wear", "MW", 0.07, 0.15),
         ("Field-Tested", "FT", 0.15, 0.38), ("Well-Worn", "WW", 0.38, 0.45),
         ("Battle-Scarred", "BS", 0.45, 1.0)]
# Шансы открытия кейса (Valve): синий, фиолетовый, розовый, красный, нож.
TIERS = [("rarity_rare_weapon", "Синий", 0.7992, (75, 105, 255)),
         ("rarity_mythical_weapon", "Фиолетовый", 0.1598, (136, 71, 255)),
         ("rarity_legendary_weapon", "Розовый", 0.0320, (211, 44, 230)),
         ("rarity_ancient_weapon", "Красный", 0.0064, (235, 75, 75)),
         ("rare", "Нож или перчатки", 0.0026, (228, 174, 57))]
_api = {}


# ---------- данные ----------

def api(name):
    """crates / skins из ByMykel/CSGO-API (один раз за запуск)."""
    if name not in _api:
        _api[name] = bot.http_get_json(API.format(name), timeout=60)
    return _api[name]


def skins_by_name():
    out = {}
    for s in api("skins"):
        out.setdefault(s.get("name"), s)
    return out


def price_book(skinport):
    """market_hash_name → цена: медиана продаж за 30 дней (иначе 90 или 7)."""
    book = {}
    for i in skinport:
        for k in ("last_30_days", "last_90_days", "last_7_days"):
            v = (i.get(k) or {}).get("median")
            if v:
                book[i["market_hash_name"]] = v
                break
    return book


def market_name(name, wear=None, st=False):
    if st:
        name = ("★ StatTrak™ " + name[2:] if name.startswith("★ ")
                else "StatTrak™ " + name)
    return f"{name} ({wear})" if wear else name


def wear_odds(s):
    """Шанс каждого износа: float выпадает равномерно в [min, max]."""
    if not s.get("wears"):
        return [(None, 1.0)]
    lo = s.get("min_float") or 0.0
    hi = s.get("max_float") if s.get("max_float") is not None else 1.0
    span = max(hi - lo, 1e-9)
    out = []
    for wear, _, a, b in WEARS:
        part = max(0.0, min(hi, b) - max(lo, a)) / span
        if part > 0:
            out.append((wear, part))
    return out


def outcomes(s, book):
    """Что может выпасть из одного предмета: [(цена, шанс, название)] —
    по износам и StatTrak (10%). Пусто, если цен почти нет."""
    kinds = [(False, 0.9), (True, 0.1)] if s.get("stattrak") else [(False, 1)]
    out = []
    for st, share in kinds:
        for wear, pw in wear_odds(s):
            name = market_name(s["name"], wear, st)
            if book.get(name):
                out.append((book[name], share * pw, name))
    covered = sum(q for _, q, _ in out)
    return [(v, q / covered, n) for v, q, n in out] if covered >= 0.6 else []


def case_stats(crate, skins, book):
    """Сколько в среднем возвращает открытие кейса. None — если цен не
    хватает хотя бы на один цвет (иначе расчёт был бы враньём)."""
    case_price = book.get(crate.get("market_hash_name") or crate["name"])
    if not case_price:
        return None
    tiers, dist = [], []
    for rid, label, chance, color in TIERS:
        pool = (crate.get("contains_rare") or [] if rid == "rare" else
                [i for i in crate.get("contains") or []
                 if (i.get("rarity") or {}).get("id") == rid])
        # фазы Doppler в списке отдельными строками — это один дроп
        pool = list({i["name"]: i for i in pool}.values())
        items = []
        for it in pool:
            s = skins.get(it["name"])
            outs = outcomes(s, book) if s else []
            if outs:
                items.append((it, outs, sum(v * q for v, q, _ in outs)))
        if not items:
            return None
        best = max(items, key=lambda x: x[2])
        tiers.append({"label": label, "chance": chance, "color": color,
                      "avg": sum(x[2] for x in items) / len(items),
                      "best": best[0]["name"], "image": best[0].get("image")})
        for it, outs, _ in items:
            for v, q, n in outs:
                dist.append((v, chance / len(items) * q, n))
    cost = case_price + KEY_PRICE
    ev = sum(t["chance"] * t["avg"] for t in tiers)
    top = max(dist, key=lambda x: x[0])
    top_chance = sum(q for v, q, n in dist if n == top[2])
    return {"case": crate, "case_price": case_price, "cost": cost, "ev": ev,
            "ratio": ev / cost, "win": sum(q for v, q, _ in dist if v >= cost),
            "tiers": tiers, "top": top, "top_chance": top_chance}


# ---------- 🎰 открывать кейс или нет ----------

def money(v):
    return invest.money(v)


def odds_text(q):
    """0.00026 → «1 к 3 800»."""
    if q <= 0:
        return "почти никогда"
    n = 1 / q
    n = round(n, -2) if n >= 1000 else round(n)
    return f"1 к {bot.fmt_num(int(n))}"


def pick_case(skinport, state):
    """Кейс недели: из ходовых (по продажам на Skinport), давно не
    разобранных. Возвращает посчитанную статистику или None."""
    vol = {i["market_hash_name"]: (i.get("last_30_days") or {}).get("volume")
           or 0 for i in skinport}
    seen = set(state.get("ev_seen", [])[-12:])
    crates = [c for c in api("crates") if c.get("type") == "Case"
              and (c.get("contains") or [])]
    crates.sort(key=lambda c: vol.get(c.get("market_hash_name") or c["name"],
                                      0), reverse=True)
    skins, book = skins_by_name(), price_book(skinport)
    for c in [c for c in crates if c["name"] not in seen][:15] + crates[:5]:
        st = case_stats(c, skins, book)
        if st:
            return st
    return None


def compose_case(st, channel_tag):
    """Подпись и карточка «Открывать или нет?»."""
    c, ratio = st["case"], st["ratio"]
    back = ratio * 10
    if ratio >= 1:
        label, color = "ОКУПАЕТСЯ (РЕДКОСТЬ)", cards.GREEN
    elif ratio >= 0.8:
        label, color = "ПОЧТИ ОКУПАЕТСЯ", cards.AMBER
    else:
        label, color = "ОТКРЫВАТЬ НЕВЫГОДНО", cards.RED
    sub = f"С каждых $10 в среднем возвращается ${back:.2f}"
    tiles = [("Открытие стоит", money(st["cost"]),
              f"кейс {money(st['case_price'])} + ключ {money(KEY_PRICE)}",
              cards.TEXT),
             ("В среднем вернётся", money(st["ev"]),
              f"{ratio * 100:.0f}% от потраченного", color),
             ("Шанс окупить", f"{st['win'] * 100:.0f}%",
              f"≈ {odds_text(st['win'])}", cards.TEXT)]
    tiers = [(t["color"], t["label"],
              f"шанс {t['chance'] * 100:.2f}%".replace(".", ","),
              f"~{money(t['avg'])}", t["image"], f"лучший: {t['best']}")
             for t in st["tiers"]]
    top_v, _, top_name = st["top"]
    jackpot = (f"Самый дорогой дроп: {top_name} — {money(top_v)}, "
               f"шанс {odds_text(st['top_chance'])}")
    card = os.path.join(tempfile.gettempdir(), "cs2_case.jpg")
    try:
        ok = cards.case_card(card, c["name"], c.get("image"), tiles, label,
                             color, sub, tiers, jackpot)
    except Exception as e:
        print("Карточка кейса не собралась:", e)
        ok = False
    hooks = [f"Открыть {c['name']} стоит {money(st['cost'])}. "
             f"Вернётся в среднем {money(st['ev'])}.",
             f"Потратил $10 на {c['name']} — в среднем получил обратно "
             f"${back:.2f}.",
             f"{c['name']}: окупится примерно {odds_text(st['win'])} "
             "открытий."]
    syn = st["tiers"][0]
    lines = [f"<b>🎰 ОТКРЫВАТЬ ИЛИ НЕТ?</b>",
             f"<b>{html.escape(bot.pick(hooks))}</b>", "",
             f"▫️ В {syn['chance'] * 100:.0f}% случаев выпадает синий скин — "
             f"в среднем он стоит {money(syn['avg'])}.",
             f"▫️ Нож или перчатки — шанс 0,26%, примерно "
             f"{odds_text(0.0026)}.",
             f"▫️ Окупить открытие получается в {st['win'] * 100:.0f}% "
             "случаев.", "",
             ("Вывод: кейс — это лотерея. Хочешь конкретный скин — дешевле "
              "купить его сразу на маркете." if ratio < 1 else
              "Редкий случай: по нынешним ценам кейс в среднем отбивается. "
              "Но это среднее — большинство открытий всё равно в минус."),
             "", f"<i>Цены — продажи на Skinport, ключ {money(KEY_PRICE)}. "
             f"Шансы опубликованы Valve.</i>", f"{channel_tag} · #кейсы #cs2"]
    return "\n".join(lines), (card if ok else "")


# ---------- ✨ скин дня ----------

SOD_SCHEMA = {
    "type": "object",
    "properties": {"hook": {"type": "string"}, "fact": {"type": "string"},
                   "text": {"type": "string"}},
    "required": ["hook", "fact", "text"],
    "additionalProperties": False,
}


def base_name(n):
    n = n.replace("StatTrak™ ", "").replace("Souvenir ", "")
    return re.sub(r" \((Factory New|Minimal Wear|Field-Tested|Well-Worn|"
                  r"Battle-Scarred)\)$", "", n)


def pick_skin(skinport, state, today):
    """Скин дня: ходовой скин оружия, ножа или перчаток (от $3 и 100 продаж
    за месяц), не показанный за последние 90 дней. Выбор стабилен для даты."""
    skins = skins_by_name()
    vol = {}
    for i in skinport:
        n, m = i["market_hash_name"], i.get("last_30_days") or {}
        b = base_name(n)
        if (b in skins and " | " in b and not n.startswith("Sticker")
                and (m.get("median") or 0) >= 3):
            vol[b] = vol.get(b, 0) + (m.get("volume") or 0)
    seen = set(state.get("sod_seen", [])[-90:])
    pool = sorted((b for b, v in vol.items() if v >= 100 and b not in seen),
                  key=lambda b: -vol[b])[:150]
    if not pool:
        return None
    return skins[random.Random(today).choice(pool)]


def lore(s):
    """Подпись Valve к скину (курсив в описании) — источник «факта»."""
    m = re.search(r"<i>(.*?)</i>", (s.get("description") or "").replace(
        "\\n", "\n"), re.S)
    return m.group(1).strip() if m else ""


def compose_skin(s, skinport, date, channel_tag):
    book = price_book(skinport)
    wears = [(abbr, book[market_name(s["name"], wear)])
             for wear, abbr, _, _ in WEARS
             if s.get("wears") and book.get(market_name(s["name"], wear))]
    if not wears and book.get(s["name"]):
        wears = [("цена", book[s["name"]])]
    if not wears:
        return None
    vols = {i["market_hash_name"]: (i.get("last_30_days") or {}).get("volume")
            or 0 for i in skinport}
    main = max(((market_name(s["name"], w), vols.get(
        market_name(s["name"], w), 0)) for w, *_ in WEARS),
        key=lambda x: x[1])[0] if s.get("wears") else s["name"]
    try:
        h = invest.history(main)
        week = invest.weekly(h)
    except Exception as e:
        print("Нет истории CSFloat:", main, e)
        week = []
    spark, days = [p for _, p in week], [d for d, _ in week]
    rarity = (s.get("rarity") or {}).get("color", "").lstrip("#")
    cols = [c["name"] for c in s.get("collections") or []]
    crates = [c["name"] for c in s.get("crates") or []]
    facts = {"name": s["name"], "rarity": (s.get("rarity") or {}).get("name"),
             "weapon": (s.get("weapon") or {}).get("name"),
             "collection": cols[:1], "cases": crates[:3],
             "valve_description": re.sub(r"<[^>]+>", "", (s.get(
                 "description") or "").replace("\\n", " "))[:900],
             "valve_quote": lore(s),
             "prices_by_wear_usd": {a: round(v, 2) for a, v in wears},
             "price_history_weekly": [round(p, 2) for p in spark[::8]],
             "history_since": days[0] if days else None}
    res = ai.ask(f"""Рубрика «Скин дня» в канале @cs2_me. Читают обычные игроки,
многие — школьники: пиши просто, живо, как другу. Вот факты о скине:
{json.dumps(facts, ensure_ascii=False)}

Верни:
- hook: первая строка поста до 70 знаков — цепляющая, по фактам (цена,
  редкость, разница между износами, необычная подпись Valve). Без эмодзи.
- fact: 1–2 предложения до 170 знаков для картинки — самое интересное из
  описания Valve (переведи по-русски, можно пересказать подпись) или из цен.
- text: 2–3 коротких предложения до 330 знаков для подписи: что за скин,
  чем интересен, что видно по ценам. Только из фактов, ничего не придумывай.""",
                 SOD_SCHEMA, effort="medium") or {}
    hook = (res.get("hook") or f"{s['name']} — скин дня").strip()
    fact = (res.get("fact") or lore(s) or "Один из самых популярных скинов "
            "на маркете этого месяца.").strip()
    sub = " · ".join(x for x in [(s.get("rarity") or {}).get("name"),
                                 cols[0].replace("The ", "") if cols else "",
                                 crates[0] if crates else ""] if x)
    card = os.path.join(tempfile.gettempdir(), "cs2_skin.jpg")
    title = ("Цена за всё время" + (f" · {main.rsplit('(', 1)[-1].rstrip(')')}"
                                    if "(" in main else ""))
    try:
        ok = cards.skin_card(card, date, s["name"], rarity, sub, s.get("image"),
                             [(a, money(v)) for a, v in wears], fact, spark,
                             days, title, money)
    except Exception as e:
        print("Карточка скина не собралась:", e)
        ok = False
    lines = ["<b>✨ СКИН ДНЯ</b>", f"<b>{html.escape(hook)}</b>", ""]
    if res.get("text"):
        lines += [safe(res["text"]), ""]
    lines += ["💰 " + " · ".join(f"{a} {money(v)}" for a, v in wears),
              f"🔗 <a href=\"https://steamcommunity.com/market/listings/730/"
              f"{urllib.parse.quote(main)}\">Смотреть на маркете</a>", "",
              f"{channel_tag} · #скин_дня #cs2"]
    return "\n".join(lines), (card if ok else "")


def safe(s):
    """Текст модели → безопасный Telegram HTML."""
    s = html.escape(html.unescape(s or ""), quote=False)
    return re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", s).strip()


# ---------- 🗳 угадай цену ----------

def pick_duel(skinport, state):
    """Два ходовых скина с похожей ценой (±25%) и спокойной прошлой неделей
    (изменение не больше 5%) — честная игра без очевидного ответа."""
    skins = skins_by_name()
    pool = []
    for i in skinport:
        n = i["market_hash_name"]
        w, m = i.get("last_7_days") or {}, i.get("last_30_days") or {}
        b = base_name(n)
        if (b in skins and " | " in b and "StatTrak" not in n
                and "Souvenir" not in n and not n.startswith("Sticker")
                and 5 <= (w.get("median") or 0) <= 150
                and (w.get("volume") or 0) >= 40 and m.get("median")
                and abs(w["median"] / m["median"] - 1) <= 0.05):
            pool.append((n, w["median"], skins[b]))
    used = set(state.get("duel_used", [])[-40:])
    pool = [x for x in pool if base_name(x[0]) not in used]
    rnd = random.Random(time.strftime("%Y-%W"))
    rnd.shuffle(pool)
    for a in pool:
        for b in pool:
            if (b is not a and base_name(a[0]) != base_name(b[0])
                    and 0.8 <= a[1] / b[1] <= 1.25
                    and (a[2].get("weapon") or {}).get("name")
                    != (b[2].get("weapon") or {}).get("name")):
                return [a, b]
    return None


def nice(n):
    """«AK-47 | Redline (Field-Tested)» → «AK-47 | Redline · FT»."""
    for wear, abbr, _, _ in WEARS:
        n = n.replace(f" ({wear})", f" · {abbr}")
    return n.replace("StatTrak™ ", "ST™ ")


def duel_side(n, price, s, line, line_color=None):
    return {"name": nice(n),
            "rarity": (s.get("rarity") or {}).get("color", "").lstrip("#"),
            "icon": s.get("image"), "price": money(price), "line": line,
            "line_color": line_color or cards.MUTED}


def compose_duel(pair, channel_tag, date):
    """Новый опрос: (подпись, картинка, вопрос, варианты)."""
    sides = [duel_side(n, p, s, "цена за неделю") for n, p, s in pair]
    card = os.path.join(tempfile.gettempdir(), "cs2_duel.jpg")
    try:
        ok = cards.duel_card(card, "Угадай цену", f"{date} · новая неделя",
                             sides, "Какой подорожает сильнее за неделю?",
                             "голосуй в опросе ниже · итог — через 7 дней")
    except Exception as e:
        print("Карточка опроса не собралась:", e)
        ok = False
    text = "\n".join([
        "<b>🗳 УГАДАЙ ЦЕНУ</b>",
        "<b>Два скина, почти одна цена. Какой через неделю будет дороже?</b>",
        "",
        f"🅰️ {html.escape(sides[0]['name'])} — {sides[0]['price']}",
        f"🅱️ {html.escape(sides[1]['name'])} — {sides[1]['price']}", "",
        "Обе цены прошлую неделю почти не менялись — подсказок нет, "
        "только чутьё. Голосуй в опросе 👇 Через 7 дней покажем, "
        "кто был прав.", "", f"{channel_tag} · #угадай_цену #cs2"])
    options = [f"🅰️ {sides[0]['name']}"[:100], f"🅱️ {sides[1]['name']}"[:100]]
    return text, (card if ok else ""), "Какой скин подорожает сильнее за неделю?", options


def compose_duel_result(duel, skinport, votes, channel_tag, date):
    """Итог прошлого опроса: реальные цены через неделю."""
    skins = skins_by_name()
    now = {i["market_hash_name"]: (i.get("last_7_days") or {}).get("median")
           for i in skinport}
    res = []
    for d in duel["items"]:
        p1 = now.get(d["name"])
        if not p1:
            return None
        res.append((d, p1, (p1 / d["price"] - 1) * 100))
    win = 0 if res[0][2] >= res[1][2] else 1
    sides = []
    for d, p1, ch in res:
        s = skins.get(base_name(d["name"])) or {}
        sides.append(duel_side(d["name"], p1, s, f"{ch:+.1f}%",
                               cards.GREEN if ch >= 0 else cards.RED))
    total = sum(votes or [])
    share = (f"{round(votes[win] * 100 / total)}% подписчиков угадали"
             if total else "голосов пока мало — дальше будет интереснее")
    card = os.path.join(tempfile.gettempdir(), "cs2_duel_result.jpg")
    try:
        ok = cards.duel_card(card, "Угадай цену · итог",
                             f"{duel['date']} — {date}", sides,
                             f"Сильнее подорожал {'AB'[win]}", share, win)
    except Exception as e:
        print("Карточка итога не собралась:", e)
        ok = False
    pct = lambda v: f"{v:+.1f}%".replace("-", "−")
    text = "\n".join([
        "<b>🗳 УГАДАЙ ЦЕНУ · ИТОГ</b>",
        f"<b>Победил {('🅰️', '🅱️')[win]} "
        f"{html.escape(sides[win]['name'])}</b>", "",
        f"🅰️ {html.escape(sides[0]['name'])}: {money(res[0][0]['price'])} → "
        f"{sides[0]['price']} ({pct(res[0][2])})",
        f"🅱️ {html.escape(sides[1]['name'])}: {money(res[1][0]['price'])} → "
        f"{sides[1]['price']} ({pct(res[1][2])})", "",
        f"🗳 {share}.", "", "Новый опрос — следующим постом 👇", "",
        f"{channel_tag} · #угадай_цену #cs2"])
    return text, (card if ok else "")


# ---------- 📒 мы советовали — что вышло ----------

def compose_report(log, date, channel_tag):
    """Отчёт по советам «Инвестиций» за прошлую неделю (7–14 дней назад):
    цена тогда (из записи) против цены сейчас (CSFloat, неделя). Хорошо —
    если «брать» подорожал, а «подождать»/«не брать» не подорожал."""
    rows = []
    for rec in log:
        try:
            m = invest.metrics(rec["name"], invest.history(rec["name"]))
        except Exception as e:
            print("Нет истории CSFloat:", rec["name"], e)
            m = None
        if not m:
            continue
        ch = (m["now"] / rec["price"] - 1) * 100
        ok = ch > 0 if rec["verdict"] == "buy" else ch <= 0
        rows.append({"name": invest.short_name(rec["name"]),
                     "icon": invest.steam_icon(rec["name"]),
                     "verdict": rec["verdict"], "was": money(rec["price"]),
                     "now": money(m["now"]), "pct": f"{ch:+.1f}%",
                     "pct_color": cards.GREEN if ch >= 0 else cards.RED,
                     "good": ok, "ch": ch, "date": rec["date"]})
        time.sleep(1)
    if not rows:
        return None
    rows = rows[:8]
    good = sum(r["good"] for r in rows)
    summary = f"Угадали {good} из {len(rows)}"
    dd = lambda d: f"{d[8:10]}.{d[5:7]}"
    card = os.path.join(tempfile.gettempdir(), "cs2_report.jpg")
    try:
        ok = cards.report_card(card, "Мы советовали — что вышло",
                               f"советы за {dd(rows[0]['date'])} — "
                               f"{dd(rows[-1]['date'])} · цены на {date}",
                               rows, summary)
    except Exception as e:
        print("Карточка отчёта не собралась:", e)
        ok = False
    pct = lambda v: f"{v:+.1f}%".replace("-", "−")
    word = {"buy": "брать", "watch": "подождать", "avoid": "не брать"}
    lines = ["<b>📒 МЫ СОВЕТОВАЛИ — ЧТО ВЫШЛО</b>",
             f"<b>{summary}. Без подтасовок: вот все советы недели.</b>", ""]
    for r in rows:
        lines.append(f"{'✅' if r['good'] else '❌'} {html.escape(r['name'])} — "
                     f"{word[r['verdict']]} по {r['was']}, сейчас {r['now']} "
                     f"({pct(r['ch'])})")
    lines += ["", "«Брать» засчитываем, если цена выросла; «подождать» и "
              "«не брать» — если не выросла.", "",
              f"{channel_tag} · #отчёт #инвестиции_cs2"]
    return "\n".join(lines), (card if ok else "")
