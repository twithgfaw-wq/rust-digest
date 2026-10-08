# -*- coding: utf-8 -*-
"""
📈 Индекс рынка — одна понятная цифра в день для каждого канала:
  CS2:  из 100 ходовых предметов (Skinport, от 20 продаж в неделю) — сколько
        сейчас дороже, чем в среднем за месяц; плюс кейсы, ножи и перчатки,
        наклейки, скины отдельно;
  Rust: из 100 скинов магазина последних 12 недель — сколько подорожали за
        неделю на маркете Steam; плюс сколько из них дороже цены магазина.
0–20 «мороз» (почти всё дешевеет) … 80–100 «жара» (почти всё дорожает).
Картинка-шкала со стрелкой: CS2 — светлый стиль, Rust — стиль магазина.
"""
import math
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

LIVE = False                 # по расписанию — после одобрения примеров
CS2_HOUR, RUST_HOUR = 10, 10  # по Киеву, каждый день

ZONES = [  # (до, название, пояснение, совет)
    (20, "МОРОЗ", "почти всё дешевеет",
     "Рынок распродают. Для покупки «для себя» — хороший момент, но не "
     "торопись: может упасть ещё."),
    (40, "ХОЛОДНО", "дешевеет чаще, чем дорожает",
     "Покупать для себя сейчас выгоднее, чем обычно. Продавать — не лучший "
     "момент."),
    (60, "СПОКОЙНО", "рост и падение примерно поровну",
     "Ровный рынок: резких движений нет, можно спокойно выбирать."),
    (80, "ТЕПЛО", "дорожает чаще, чем дешевеет",
     "Продавать сейчас выгоднее, чем обычно. Покупать — без спешки, "
     "сравнивай цены."),
    (101, "ЖАРА", "почти всё дорожает",
     "На пике легко переплатить — не покупай на эмоциях."),
]
COLORS = [(56, 118, 220), (84, 170, 214), (150, 150, 140), (236, 160, 40),
          (222, 72, 48)]


def zone(v):
    for i, (hi, name, what, tip) in enumerate(ZONES):
        if v < hi:
            return i, name, what, tip
    return 4, *ZONES[4][1:]


def breadth(changes, min_n=10):
    """Из 100 — сколько выросли (больше +1%), без «на месте»."""
    up = sum(1 for c in changes if c > 0.01)
    down = sum(1 for c in changes if c < -0.01)
    return round(100 * up / (up + down)) if up + down >= min_n else None


def remember(state, key, value, kt):
    hist = state.setdefault(key, {})
    hist[kt.strftime("%Y-%m-%d")] = value
    for d in sorted(hist)[:-30]:
        del hist[d]
    days = sorted(hist)
    prev = hist[days[-2]] if len(days) > 1 else None
    return [hist[d] for d in days[-14:]], prev


# ---------- CS2 ----------

CS2_CATS = [("Кейсы", lambda n: n.endswith((" Case", " Terminal", " Capsule",
                                           " Package"))),
            ("Ножи и перчатки", lambda n: "★" in n),
            ("Наклейки", lambda n: n.startswith("Sticker |")),
            ("Скины", lambda n: True)]


def cs2_index(sp):
    rows = []
    for i in sp:
        w, m = i.get("last_7_days") or {}, i.get("last_30_days") or {}
        if not (w.get("median") and m.get("median")):
            continue
        if w["median"] < 0.5 or (w.get("volume") or 0) < 20:
            continue
        ch = w["median"] / m["median"] - 1
        if abs(ch) > 0.8:
            continue
        rows.append((i["market_hash_name"], ch))
    cats = {}
    for name, ch in rows:
        cat = next(c for c, fn in CS2_CATS if fn(name))
        cats.setdefault(cat, []).append(ch)
    return {"value": breadth([c for _, c in rows]), "n": len(rows),
            "median": statistics.median([c for _, c in rows]) if rows else 0,
            "cats": [(c, breadth(cats.get(c, []), 5)) for c, _ in CS2_CATS]}


# ---------- Rust ----------

def rust_index(weeks=12):
    import rust_digest_bot as bot
    import rust_formats as rf
    items, _ = bot.fetch_store_history(weeks)
    past = [s for s in items if not s["current"] and s["price"]]

    def change(s):
        try:
            a, b = rf.week_median(s["name"]), rf.week_median(s["name"], 7)
            return a / b - 1 if a and b else None
        except Exception:
            return None

    with ThreadPoolExecutor(6) as ex:
        ch = list(ex.map(change, past))
    pairs = [(s, c) for s, c in zip(past, ch) if c is not None]
    above = sum(1 for s in past if s["price"] > s["store"])
    return {"value": breadth([c for _, c in pairs]), "n": len(pairs),
            "median": statistics.median([c for _, c in pairs]) if pairs else 0,
            "above": round(100 * above / len(past)) if past else None,
            "best": max(pairs, key=lambda x: x[1]) if pairs else None,
            "worst": min(pairs, key=lambda x: x[1]) if pairs else None}


# ---------- картинка ----------

def gauge(draw, p, font, cx, cy, r, value, text, muted, track):
    """Полукруг из 5 зон и стрелка; под ней — крупное число и зона."""
    w = r * 0.22
    box = (p(cx - r), p(cy - r), p(cx + r), p(cy + r))
    draw.arc(box, 180, 360, fill=track, width=p(w + 10))
    for i, c in enumerate(COLORS):
        draw.arc(box, 180 + 36 * i + 1, 180 + 36 * (i + 1) - 1, fill=c,
                 width=p(w))
    for v in (0, 20, 40, 60, 80, 100):
        a = math.radians(180 + 1.8 * v)
        x, y = cx + math.cos(a) * (r + 26), cy + math.sin(a) * (r + 26)
        draw.text((p(x), p(y)), str(v), font=font(20), fill=muted, anchor="mm")
    a = math.radians(180 + 1.8 * max(0, min(100, value)))
    L = r - w - 18
    tip = (cx + math.cos(a) * L, cy + math.sin(a) * L)
    side = (math.cos(a + math.pi / 2) * 14, math.sin(a + math.pi / 2) * 14)
    draw.polygon([(p(tip[0]), p(tip[1])), (p(cx + side[0]), p(cy + side[1])),
                  (p(cx - side[0]), p(cy - side[1]))], fill=text)
    draw.ellipse((p(cx - 22), p(cy - 22), p(cx + 22), p(cy + 22)), fill=text)


def spark(draw, p, font, box, vals, color, muted):
    x0, y0, x1, y1 = box
    if len(vals) < 3:
        return
    lo, hi = max(0, min(vals) - 8), min(100, max(vals) + 8)
    X = lambda i: x0 + 60 + (x1 - x0 - 60) * i / (len(vals) - 1)
    Y = lambda v: y1 - (y1 - y0) * (v - lo) / ((hi - lo) or 1)
    for v in (min(vals), max(vals)):
        draw.line((p(x0 + 60), p(Y(v)), p(x1), p(Y(v))), fill=muted,
                  width=p(1))
        draw.text((p(x0 + 44), p(Y(v))), str(v), font=font(20), fill=color,
                  anchor="rm")
    draw.line([(p(X(i)), p(Y(v))) for i, v in enumerate(vals)], fill=color,
              width=p(4), joint="curve")
    draw.ellipse((p(X(len(vals) - 1) - 7), p(Y(vals[-1]) - 7),
                  p(X(len(vals) - 1) + 7), p(Y(vals[-1]) + 7)), fill=color)


def cs2_card(out_path, date, idx, hist):
    import cs2_cards as c
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, H = 1200, 1180
    img, draw = c.canvas(W, H)
    c.header(draw, W, "ИНДЕКС РЫНКА CS2", f"{date} · из 100 ходовых предметов "
             "— сколько сейчас дороже, чем в среднем за месяц")
    v = idx["value"]
    zi, zname, what, _ = zone(v)
    c.panel(img, 48, 170, W - 48, 770)
    gauge(draw, c.p, c.font, W / 2, 540, 300, v, c.TEXT, c.MUTED, (226, 227, 231))
    draw.text((c.p(W / 2), c.p(640)), str(v), font=c.font(96, True),
              fill=COLORS[zi], anchor="mm")
    draw.text((c.p(W / 2), c.p(726)), f"{zname} — {what}".upper(),
              font=c.font(28, True), fill=c.TEXT, anchor="mm")
    tw = (W - 96 - 48) / 4
    for k, (name, val) in enumerate(idx["cats"]):
        x0 = 48 + k * (tw + 16)
        c.panel(img, x0, 790, x0 + tw, 920)
        draw.text((c.p(x0 + tw / 2), c.p(824)), name.upper(), font=c.font(21),
                  fill=c.MUTED, anchor="mm")
        draw.text((c.p(x0 + tw / 2), c.p(876)), "—" if val is None else str(val),
                  font=c.font(48, True),
                  fill=c.MUTED if val is None else COLORS[zone(val)[0]],
                  anchor="mm")
    c.panel(img, 48, 940, W - 48, 1110)
    draw.text((c.p(76), c.p(968)), "ИНДЕКС ПО ДНЯМ", font=c.font(20, True),
              fill=c.MUTED, anchor="lm")
    if len(hist) >= 3:
        spark(draw, c.p, c.font, (76, 994, W - 76, 1090), hist, COLORS[zi],
              c.LINE)
    else:
        draw.text((c.p(W / 2), c.p(1040)), "график появится через пару дней",
                  font=c.font(24), fill=c.MUTED, anchor="mm")
    c.footer(draw, W, H, f"Skinport · {idx['n']} предметов от 20 продаж в неделю")
    return c.save(img, W, H, out_path)


def rust_card(out_path, date, idx, hist):
    import rust_cards as r
    from cs2_cards import p, font
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, H = 1200, 1200
    img, draw = r.canvas(W, H)
    r.nav(draw, W, "МАРКЕТ")
    r.panel(img, draw, (48, 120, W - 48, H - 70), "ИНДЕКС РЫНКА", date)
    v = idx["value"]
    zi, zname, what, _ = zone(v)
    draw.text((p(76), p(228)), "ИЗ 100 СКИНОВ МАГАЗИНА ЗА 12 НЕДЕЛЬ — СКОЛЬКО "
              "ПОДОРОЖАЛИ ЗА НЕДЕЛЮ", font=font(21), fill=r.MUTED, anchor="lm")
    gauge(draw, p, font, W / 2, 580, 280, v, r.WHITE, r.MUTED, (40, 36, 30))
    draw.text((p(W / 2), p(672)), str(v), font=font(96, True),
              fill=COLORS[zi], anchor="mm")
    draw.text((p(W / 2), p(756)), f"{zname} — {what}".upper(),
              font=font(28, True), fill=r.WHITE, anchor="mm")
    tw = (W - 152 - 32) / 3
    tiles = [("дороже магазина", f"{idx['above']} из 100"),
             ("средне за неделю",
              f"{idx['median'] * 100:+.1f}%".replace("-", "−")),
             ("скинов в расчёте", str(idx["n"]))]
    for k, (name, val) in enumerate(tiles):
        x0 = 76 + k * (tw + 16)
        r.base.overlay(img, "rectangle", (p(x0), p(800), p(x0 + tw), p(916)),
                       (0, 0, 0, 90))
        draw.text((p(x0 + tw / 2), p(828)), name.upper(), font=font(20),
                  fill=r.MUTED, anchor="mm")
        draw.text((p(x0 + tw / 2), p(878)), val, font=font(42, True),
                  fill=r.WHITE, anchor="mm")
    r.base.overlay(img, "rectangle", (p(76), p(936), p(W - 76), p(1106)),
                   (0, 0, 0, 90))
    draw.text((p(100), p(964)), "ИНДЕКС ПО ДНЯМ", font=font(20, True),
              fill=r.MUTED, anchor="lm")
    if len(hist) >= 3:
        spark(draw, p, font, (100, 990, W - 100, 1086), hist, COLORS[zi],
              (70, 60, 40))
    else:
        draw.text((p(W / 2), p(1036)), "ГРАФИК ПОЯВИТСЯ ЧЕРЕЗ ПАРУ ДНЕЙ",
                  font=font(22), fill=r.MUTED, anchor="mm")
    r.footer(draw, W, H, "маркет Steam · rust.scmm.app")
    return r.save(img, W, H, out_path)


# ---------- подписи ----------

def delta(v, prev):
    if prev is None:
        return ""
    d = v - prev
    return f" Вчера — {prev} ({'+' if d >= 0 else '−'}{abs(d)})."


def cs2_post(sp, state, kt, footer, save=True):
    """(подпись, картинка) или None."""
    idx = cs2_index(sp)
    if idx["value"] is None:
        return None
    hist, prev = (remember(state, "cs2_index", idx["value"], kt) if save
                  else ([idx["value"]], None))
    zi, zname, what, tip = zone(idx["value"])
    cats = " · ".join(f"{n} {v}" for n, v in idx["cats"] if v is not None)
    text = "\n".join([
        f"<b>📈 ИНДЕКС РЫНКА CS2: {idx['value']} — {zname}</b>",
        f"Из 100 ходовых предметов {idx['value']} сейчас дороже, чем в среднем"
        f" за месяц.{delta(idx['value'], prev)}", "",
        f"▫️ {cats}", f"💡 {tip}", "",
        "<i>0 — всё дешевеет, 100 — всё дорожает. Считаем каждый день по"
        " продажам Skinport.</i>", "", footer, "#cs2 #кс2 #индекс"])
    card = os.path.join(tempfile.gettempdir(), "cs2_index.jpg")
    try:
        ok = cs2_card(card, kt.strftime("%d.%m.%Y"), idx, hist)
    except Exception as e:
        print("Картинка индекса CS2 не собралась:", e)
        ok = False
    return text, (card if ok else "")


def rust_post(state, kt, footer, save=True):
    import html
    idx = rust_index()
    if idx["value"] is None:
        return None
    hist, prev = (remember(state, "rust_index", idx["value"], kt) if save
                  else ([idx["value"]], None))
    zi, zname, what, tip = zone(idx["value"])
    lines = [
        f"<b>📈 ИНДЕКС РЫНКА RUST: {idx['value']} — {zname}</b>",
        f"Из 100 скинов магазина последних 12 недель {idx['value']} за неделю"
        f" подорожали на маркете.{delta(idx['value'], prev)}", "",
        f"🛒 Дороже, чем стоили в магазине: {idx['above']} из 100"]
    if idx["best"] and idx["best"][1] > 0.05:
        s, c = idx["best"]
        lines.append(f"🚀 Сильнее всех вырос: {html.escape(s['name'])} "
                     f"({c * 100:+.0f}%)")
    if idx["worst"] and idx["worst"][1] < -0.05:
        s, c = idx["worst"]
        lines.append(f"🧊 Сильнее всех упал: {html.escape(s['name'])} "
                     f"({c * 100:+.0f}%)".replace("-", "−"))
    lines += [f"💡 {tip}", "",
              "<i>0 — всё дешевеет, 100 — всё дорожает. Считаем каждый день"
              " по маркету Steam.</i>", "", footer, "#rust #раст #индекс"]
    card = os.path.join(tempfile.gettempdir(), "rust_index.jpg")
    try:
        ok = rust_card(card, kt.strftime("%d.%m.%Y"), idx, hist)
    except Exception as e:
        print("Картинка индекса Rust не собралась:", e)
        ok = False
    return "\n".join(lines), (card if ok else "")


def tick(tg, state, kind, footer, get_sp=None, forced=False):
    """kind — "cs2" или "rust": раз в день после *_HOUR по Киеву."""
    import rust_digest_bot as bot
    kt = bot.kyiv_time()
    today, key = kt.strftime("%Y-%m-%d"), f"{kind}_index_day"
    hour = CS2_HOUR if kind == "cs2" else RUST_HOUR
    if not forced and not (LIVE and kt.hour >= hour and state.get(key) != today):
        return
    out = (cs2_post(get_sp(), state, kt, footer) if kind == "cs2"
           else rust_post(state, kt, footer))
    if not out:
        return
    text, card = out
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok"):
        res = tg.send_message(text)
    if res.get("ok"):
        state[key] = today
