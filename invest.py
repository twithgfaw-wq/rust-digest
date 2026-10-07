#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Инвест-разбор недельного выпуска скинов Rust — отдельная рубрика канала.

Раз в неделю, когда в магазине Rust новый недельный выпуск, бот:
  1. Берёт ВСЕ недельные скины за всю историю (rust.scmm.app): тип, цену
     в магазине, тираж и историю продаж Steam Community Market по дням.
  2. Считает, как вели себя прошлые выпуски: первая неделя на маркете,
     1/3/6/12/24 месяца после выхода — с учётом комиссии Steam
     (продавец получает ≈ цена / 1.15).
  3. Обучает логистическую регрессию «будет ли чистая прибыль через год»
     на выпусках, у которых год уже прошёл, и проверяет её на прошлом.
  4. По каждому скину нового выпуска даёт вывод и объясняет почему.

Запуск: python invest.py
  INVEST_FORCE=1 — разобрать текущий выпуск сразу, не дожидаясь графика;
  INVEST_DRY=1   — ничего не отправлять, только напечатать.
"""
import html
import io
import json
import math
import os
import statistics
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import rust_digest_bot as bot

API = "https://api.scmm.app/api"
STATE_FILE = "invest_state.json"
DAY = 86400
FEE = 1.15            # комиссия Steam + Rust: продавец получает цену / 1.15
HZ = (30, 90, 180, 365, 730)
MODERN = datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp()  # нынешний рынок
POST_AFTER_H = 72     # разбор через 3 дня после старта (продано ~70% тиража)
KNN = 25              # сколько похожих прошлых скинов берём для сравнения
BUY_P, RISK_P = 0.40, 0.25   # пороги шанса прибыли через год (по модели)

VERDICTS = {  # код: (эмодзи, вывод, надпись на картинке, цвет)
    "buy": ("\U0001f7e2", "интересно для покупки", "ИНТЕРЕСНО", (61, 220, 132)),
    "risk": ("\U0001f7e0", "высокий риск", "РИСК", (255, 166, 41)),
    "wait": ("\U0001f535", "лучше подождать", "ПОДОЖДАТЬ", (90, 160, 255)),
    "no": ("\U0001f534", "не стоит покупать", "НЕ БРАТЬ", (255, 82, 82)),
}
CAT_RU = {"Armour": "броня", "Clothing": "одежда", "Guns": "огнестрел",
          "Weapons": "оружие ближнего боя", "Tools": "инструменты",
          "Construction": "постройки", "Deployables": "предметы для базы",
          "Backpacks": "рюкзаки", "Horse Armor": "броня лошади",
          "Building Skins": "скины построек", "Special": "особые",
          "Other": "прочее"}


# ---------- данные ----------

def get(path, tries=4):
    url = path if path.startswith("http") else API + path
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": bot.UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def med(values):
    v = [x for x in values if x is not None]
    return statistics.median(v) if v else None


def share(values):
    v = [x for x in values if x is not None]
    return sum(1 for x in v if x > 0) / len(v) if v else None


def kyiv(t):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(t, ZoneInfo("Europe/Kyiv"))
    except Exception:
        return datetime.fromtimestamp(t + 3 * 3600, timezone.utc)


def category_map():
    cats = {}
    for c in get("/item/types"):
        for t in c.get("itemTypes") or []:
            cats[t["id"]] = c["name"]
    return cats


def category(cats, item_type):
    """Категория типа. Новые типы SCMM кладёт в «Special» — уточняем
    по названию (деревянная броня → броня, люки → постройки)."""
    c = cats.get(item_type)
    if c and c != "Special":
        return c
    low = item_type.lower()
    if any(w in low for w in ("armor", "armour", "chestplate", "helmet",
                              "gloves", "kilt")):
        return "Armour"
    if any(w in low for w in ("hatch", "door", "window", "wall", "gate",
                              "ladder", "barricade")):
        return "Construction"
    return c or "Other"


def fetch_weekly(cats):
    """Все недельные (не постоянные) скины магазина за всю историю."""
    out, page = [], 1
    while True:
        j = get(f"/item?pageSize=500&page={page}")
        items = j.get("items") or []
        for it in items:
            price = it.get("storePriceUsd") or it.get("storePrice")
            if price and not it.get("isPermanent") and it.get("timeAccepted"):
                kind = it.get("itemType") or ""
                out.append({
                    "name": it["name"], "type": kind,
                    "cat": category(cats, kind), "store": price,
                    "rel": ts(it["timeAccepted"]),
                    "supply": it.get("supplyTotalEstimated") or 0,
                    "glow": bool(it.get("hasGlow")),
                    "skip": bool(it.get("hasReturnedToStoreBefore")
                                 or it.get("isBeingManipulated")),
                })
        if not items or page * 500 >= (j.get("total") or 0):
            return out
        page += 1


def summarize(rel, hist, now):
    """История продаж Steam Market по дням → цена в первую неделю торгов,
    на горизонтах HZ (окно ±7 дней, средняя по объёму), дно и пик
    (по неделям) и ликвидность (продаж в день через 3–6 месяцев)."""
    pts = sorted((ts(p["date"]), p["median"], p.get("volume") or 0)
                 for p in hist if p.get("median"))
    if not pts:
        return {}

    def win(a, b):
        w = [p for p in pts if a <= p[0] < b]
        if not w:
            return None
        vol = sum(p[2] for p in w)
        if vol:
            return sum(p[1] * p[2] for p in w) / vol
        return statistics.median(p[1] for p in w)

    first = pts[0][0]
    s = {"launch": win(first, first + 7 * DAY), "hz": {}}
    for d in HZ:
        c = rel + d * DAY
        if c + 7 * DAY <= now:
            s["hz"][d] = win(c - 7 * DAY, c + 7 * DAY)
    if rel + 180 * DAY <= now:
        s["liq"] = sum(p[2] for p in pts
                       if rel + 90 * DAY <= p[0] < rel + 180 * DAY) / 90
    weeks = {}
    for t, m, v in pts:
        a = weeks.setdefault(int((t - first) // (7 * DAY)), [0.0, 0, []])
        a[0] += m * v
        a[1] += v
        a[2].append(m)
    val = {k: (a[0] / a[1] if a[1] else statistics.median(a[2]))
           for k, a in weeks.items()}
    lo, hi = min(val, key=val.get), max(val, key=val.get)
    s["trough"] = (val[lo], (first + lo * 7 * DAY - rel) / DAY)
    s["peak"] = (val[hi], (first + hi * 7 * DAY - rel) / DAY)
    return s


def load_history(items, now):
    def one(it):
        name = urllib.parse.quote(it["name"], safe="")
        try:
            it.update(summarize(it["rel"], get(
                f"/item/{name}/sales/market?maxDays=-1"), now))
        except Exception as e:
            print("Нет истории:", it["name"], e)

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, items))


def mark_popularity(items):
    """rs — во сколько раз скин купили больше (меньше), чем средний скин
    его же недели. Неделя = скины, принятые в пределах двух дней."""
    group = []
    for it in sorted(items, key=lambda i: i["rel"]) + [None]:
        if group and (it is None or it["rel"] - group[0]["rel"] > 2 * DAY):
            m = med([g["supply"] for g in group]) or 1
            for g in group:
                g["rs"] = max(0.05, g["supply"] / m)
                g["week"] = group[0]["rel"]
            group = []
        if it is not None:
            group.append(it)


def sales_fraction(done, hours):
    """Какую долю итогового тиража выпуск обычно набирает к этому часу
    продаж (медиана по 8 прошлым выпускам, таймлайн подписчиков SCMM)."""
    fr = []
    for st in done[:8]:
        try:
            data = get(f"/statistics/store/{st['id']}/subscribers")
        except Exception:
            continue
        cut = ts(st["start"]) + hours * 3600
        for it in data:
            tl = it.get("timeline") or []
            if not tl or not tl[-1].get("subscribers"):
                continue
            pt = [p for p in tl if ts(p["timestamp"]) <= cut]
            if pt:
                fr.append(pt[-1]["subscribers"] / tl[-1]["subscribers"])
    return min(1.0, max(0.2, med(fr) or 1.0))


# ---------- модель ----------

def ratio(it, key):
    p = it.get("launch") if key == "launch" else it.get("hz", {}).get(key)
    return p / it["store"] if p else None


def lagged(it, pool):
    """Как вели себя этот тип и категория по данным, которые были известны
    на момент выхода скина: средний log(цена через год / магазин) за три
    предыдущих года; при малой выборке подтягиваем к категории/ко всем."""
    t0 = it["rel"] - 372 * DAY
    tr = [r for r in pool if t0 - 3 * 365 * DAY <= r["rel"] < t0]
    glob = sum(r["lr"] for r in tr) / len(tr) if tr else 0.0
    gc = [r for r in tr if r["cat"] == it["cat"]]
    gt = [r for r in gc if r["type"] == it["type"]]

    def shrink(g, prior, k):
        return (sum(r["lr"] for r in g) + prior * k) / (len(g) + k)

    cat = shrink(gc, glob, 15)
    return {"typ": shrink(gt, cat, 10), "cat": cat,
            "n_type": len(gt), "n_cat": len(gc)}


def features(it, pool):
    if "x" not in it:
        it["lag"] = lagged(it, pool)
        it["x"] = [1.0, math.log(it["rs"]),
                   math.log(max(it["supply"], 500) / 12000),
                   math.log(it["store"] / 199), it["lag"]["typ"],
                   1.0 if it["glow"] else 0.0]
    return it["x"]


def fit(X, y, epochs=1500, lr=0.3, l2=1.0):
    """Логистическая регрессия: градиентный спуск, L2 без свободного члена."""
    w, n = [0.0] * len(X[0]), len(X)
    for _ in range(epochs):
        g = [0.0] * len(w)
        for x, t in zip(X, y):
            z = max(-30.0, min(30.0, sum(a * b for a, b in zip(x, w))))
            d = 1 / (1 + math.exp(-z)) - t
            for j, a in enumerate(x):
                g[j] += d * a
        for j in range(len(w)):
            w[j] -= lr * (g[j] / n + (l2 * w[j] / n if j else 0.0))
    return w


def predict(w, x):
    z = max(-30.0, min(30.0, sum(a * b for a, b in zip(x, w))))
    return 1 / (1 + math.exp(-z))


def backtest(pool, now):
    """Честная проверка: учим только на том, что было известно до периода
    проверки, и сравниваем с реальным результатом через год."""
    end = now - 372 * DAY
    start = end - 640 * DAY
    train = [r for r in pool if start - 372 * DAY - 3 * 365 * DAY
             <= r["rel"] < start - 372 * DAY]
    test = [r for r in pool if start <= r["rel"] < end]
    w = fit([features(r, pool) for r in train], [r["y"] for r in train])
    pr = sorted((predict(w, features(r, pool)), r["y"]) for r in test)
    k = max(1, len(pr) // 3)
    pos = sum(y for _, y in pr)
    rank = sum(i + 1 for i, (_, y) in enumerate(pr) if y)
    auc = ((rank - pos * (pos + 1) / 2) / (pos * (len(pr) - pos))
           if 0 < pos < len(pr) else None)
    return {"n": len(pr), "from": start, "to": end, "auc": auc,
            "low": sum(y for _, y in pr[:k]) / k,
            "high": sum(y for _, y in pr[-k:]) / k}


def comparables(it, pool):
    """Похожие прошлые скины нынешнего рынка (с 2022): тот же тип, если их
    хотя бы 12, иначе та же категория; ближайшие по популярности."""
    base = [r for r in pool if r["rel"] >= MODERN]
    g, scope = [r for r in base if r["type"] == it["type"]], "type"
    if len(g) < 12:
        g, scope = [r for r in base if r["cat"] == it["cat"]], "cat"
    if len(g) < 12:
        g, scope = base, "all"
    g = sorted(g, key=lambda r: abs(math.log(r["rs"] / it["rs"])))[:KNN]
    later = [r["hz"][365] / FEE / r["hz"][90] - 1
             for r in g if r["hz"].get(90) and r["hz"].get(365)]
    return {
        "scope": scope, "n": len(g),
        "launch": med(ratio(r, "launch") for r in g),
        "m3": med(ratio(r, 90) for r in g),
        "y1": med(ratio(r, 365) for r in g),
        "y1_share": share(ratio(r, 365) / FEE - 1 for r in g),
        "later": med(later), "later_share": share(later),
        "liq": med(r.get("liq") for r in g),
    }


def verdict(p, c):
    if p >= BUY_P and (c["y1_share"] or 0) >= 0.4:
        return "buy"
    if p >= RISK_P:
        return "risk"
    if (c["later_share"] or 0) >= 0.5:
        return "wait"
    return "no"


def strategy(items, buy, sell):
    """Чистый результат стратегии «купить в buy → продать в sell»."""
    out = []
    for r in items:
        b = r["store"] if buy == "store" else (
            r.get("launch") if buy == "launch" else r.get("hz", {}).get(buy))
        s = r.get("launch") if sell == "launch" else r.get("hz", {}).get(sell)
        if b and s:
            out.append(s / FEE / b - 1)
    return {"n": len(out), "share": share(out), "med": med(out)}


# ---------- текст и картинка ----------

def pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def roi(v):
    return "—" if v is None else bot.pct_text(v * 100)


def num(v):
    return bot.fmt_num(int(round(v, -2))) if v >= 1000 else str(int(v))


def times(v):
    return f"{v:.1f}".replace(".", ",")


def item_block(it, base, years):
    c, lag = it["comp"], it["lag"]
    emoji, label = VERDICTS[it["v"]][:2]
    url = "https://rust.scmm.app/item/" + urllib.parse.quote(it["name"])
    lines = [f"{emoji} <b><a href=\"{url}\">{html.escape(it['name'])}</a></b>"
             f" — {bot.money(it['store'])} · <b>{label}</b>"
             f" · шанс {pct(it['p'])}"]
    rs = it["rs"]
    if rs >= 1.1:
        pop = f"купили в {times(rs)} раза больше среднего скина недели"
    elif rs <= 0.9:
        pop = f"купили в {times(1 / rs)} раза меньше среднего скина недели"
    else:
        pop = "купили примерно как средний скин недели"
    lines.append(f"• {pop} (≈{num(it['supply'])} копий к концу продажи)")
    if lag["n_type"] >= 5:
        lines.append(f"• тип «{html.escape(it['type'])}» за 3 года: через год"
                     f" в среднем ~{pct(math.exp(lag['typ']))} цены магазина"
                     f" ({lag['n_type']} скинов)")
    else:
        cat = CAT_RU.get(it["cat"], it["cat"])
        lines.append(f"• тип новый — по категории «{cat}» за 3 года: через год"
                     f" в среднем ~{pct(math.exp(lag['cat']))} цены"
                     f" ({lag['n_cat']} скинов)")
    where = {"type": " того же типа", "cat": " той же категории"}.get(
        c["scope"], "")
    path = ", ".join(x for x in (
        c["launch"] and f"1-я неделя на маркете {pct(c['launch'])}",
        c["m3"] and f"3 мес {pct(c['m3'])}",
        c["y1"] and f"год {pct(c['y1'])}") if x)
    liq = f", ~{c['liq']:.0f} продаж/день" if c["liq"] else ""
    lines.append(f"• {c['n']} похожих{where} с близкой популярностью"
                 f" ({years}): {path} цены магазина{liq};"
                 f" в плюсе через год {pct(c['y1_share'])}")
    v = it["v"]
    if v == "buy":
        why = (f"модель и похожие скины сходятся: шанс заметно выше"
               f" среднего ({pct(base)})")
    elif v == "risk":
        why = (f"шанс выше среднего ({pct(base)}), но убыток всё равно"
               f" вероятнее — это ставка, а не расчёт")
    elif v == "wait":
        why = (f"в магазине переплата: если брать на маркете через 3 мес"
               f" и продать через год — у похожих в плюсе"
               f" {pct(c['later_share'])} (медиана {roi(c['later'])})")
    else:
        why = (f"даже покупка позже на маркете у похожих чаще в минусе:"
               f" в плюсе {pct(c['later_share'])}, медиана {roi(c['later'])}")
    lines.append("• " + why)
    lines.append("• безубыток с комиссией: продать дороже "
                 + bot.money(math.ceil(it["store"] * FEE)))
    return "\n".join(lines)


def build_card(title, subtitle, rows, footer, out_path):
    """Картинка-разбор: строка на скин — иконка, название, цена и тираж,
    справа цветная «таблетка» с выводом. Рисуем в 2×, как сводку маркета."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        return False
    S, W = 2, 1440
    H = 300 + 112 * len(rows) + 100
    p = lambda v: int(v * S)
    card_bg, line_c = (31, 34, 43), (48, 52, 64)
    muted, gold = (150, 156, 172), (240, 190, 70)
    grad = Image.linear_gradient("L").resize((p(W), p(H)))
    img = Image.composite(Image.new("RGB", (p(W), p(H)), (11, 12, 16)),
                          Image.new("RGB", (p(W), p(H)), (27, 29, 37)),
                          grad).convert("RGBA")
    glow = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 8 - 75, -55, W // 8 + 45, 45),
                                 fill=gold + (90,))
    glow = glow.filter(ImageFilter.GaussianBlur(14)).resize(
        (p(W), p(H)), Image.BICUBIC)
    img.alpha_composite(glow)
    draw = ImageDraw.Draw(img)

    def font(size, bold=False):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + name,
                                      p(size))
        except Exception:
            return ImageFont.load_default()

    def fit_text(text, fnt, width):
        if draw.textlength(text, font=fnt) <= width:
            return text
        while text and draw.textlength(text + "…", font=fnt) > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def icon(url, size):
        for u in dict.fromkeys((url.replace("_small.png", "_large.png"), url)):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": bot.UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    im = Image.open(io.BytesIO(r.read())).convert("RGBA")
                return im.resize((p(size), p(size)), Image.LANCZOS)
            except Exception:
                continue
        return None

    # шапка: золотая полоса, метка, заголовок, подзаголовок
    draw.rectangle((0, 0, p(W), p(12)), fill=gold)
    tag, tf = "ИНВЕСТ-РАЗБОР", font(22, True)
    tw = draw.textlength(tag, font=tf)
    draw.rounded_rectangle((p(64), p(52), p(64) + tw + p(40), p(94)),
                           radius=p(21), fill=gold)
    draw.text((p(64) + (tw + p(40)) / 2, p(73)), tag, font=tf,
              fill=(20, 20, 24), anchor="mm")
    draw.text((p(62), p(150)), fit_text(title, font(64, True), p(W - 128)),
              font=font(64, True), fill=(255, 255, 255), anchor="lm")
    draw.text((p(64), p(210)), fit_text(subtitle, font(27), p(W - 128)),
              font=font(27), fill=muted, anchor="lm")

    y = 262
    for name, it, sub, label, color in rows:
        draw.rounded_rectangle((p(56), p(y), p(W - 56), p(y + 100)),
                               radius=p(24), fill=card_bg, outline=line_c,
                               width=p(2))
        bg = it.get("bg") or "#2b2d33"
        draw.rounded_rectangle((p(72), p(y + 10), p(152), p(y + 90)),
                               radius=p(18),
                               fill=bg if bg.startswith("#") else "#" + bg)
        ic = icon(it["icon"], 72) if it.get("icon") else None
        if ic:
            img.alpha_composite(ic, (p(76), p(y + 14)))
        tint = tuple(int(c * 0.28 + b * 0.72) for c, b in zip(color, card_bg))
        pf = font(28, True)
        px1 = p(W - 76)
        px0 = px1 - draw.textlength(label, font=pf) - p(40)
        draw.rounded_rectangle((px0, p(y + 26), px1, p(y + 74)),
                               radius=p(24), fill=tint)
        draw.text(((px0 + px1) / 2, p(y + 50)), label, font=pf, fill=color,
                  anchor="mm")
        nf, sf = font(31, True), font(23)
        draw.text((p(174), p(y + 34)), fit_text(name, nf, px0 - p(194)),
                  font=nf, fill=(240, 242, 246), anchor="lm")
        draw.text((p(174), p(y + 72)), fit_text(sub, sf, px0 - p(194)),
                  font=sf, fill=muted, anchor="lm")
        y += 112

    draw.line((p(64), p(H - 80), p(W - 64), p(H - 80)), fill=line_c,
              width=p(2))
    draw.text((p(64), p(H - 44)), footer, font=font(23),
              fill=(120, 126, 142), anchor="lm")
    draw.text((p(W - 64), p(H - 44)), bot.CHANNEL_TAG, font=font(28, True),
              fill=gold, anchor="rm")
    img = img.convert("RGB").resize((W, H), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=95, subsampling=0)
    return True


def plain_len(text):
    import re
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


# ---------- главный сценарий ----------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run():
    now = time.time()
    forced = os.environ.get("INVEST_FORCE") == "1"
    dry = os.environ.get("INVEST_DRY") == "1"
    channel = os.environ.get("CHANNEL", "")
    if channel.startswith("@"):
        bot.CHANNEL_TAG = channel
    state = load_state()

    stores = get("/store")
    cur = next((s for s in stores if s.get("start") and not s.get("end")),
               None)
    if not cur:
        print("Текущий недельный выпуск не найден.")
        return
    if state.get("last") == cur["id"] and not forced:
        print("Этот выпуск уже разобран:", cur["id"])
        return
    start = ts(cur["start"])
    try:
        nxt = ts(get("/store/rotation")["nextUpdateTime"])
    except Exception:
        nxt = start + 7 * DAY
    due = ((now - start >= POST_AFTER_H * 3600 or nxt - now <= 30 * 3600)
           and 10 <= kyiv(now).hour < 22)
    if not (due or forced):
        print(f"Рано: выпуск {cur['id']}, прошло"
              f" {(now - start) / 3600:.0f} ч из {POST_AFTER_H}.")
        return

    cats = category_map()
    rot = get(f"/store/{cur['id']}?currency=USD")
    items = [i for i in rot.get("items") or []
             if (i.get("storePriceUsd") or i.get("storePrice"))
             and not i.get("isPermanent")]
    if not items:
        print("В выпуске нет недельных скинов.")
        return

    # 1) вся история недельных скинов
    hist = [h for h in fetch_weekly(cats) if h["rel"] < start - DAY]
    print("Недельных скинов в истории:", len(hist))
    load_history(hist, now)
    mark_popularity(hist)
    pool = []
    for h in hist:
        r = ratio(h, 365)
        if r and not h["skip"]:
            h["lr"], h["y"] = math.log(r), 1 if r > FEE else 0
            pool.append(h)
    print("С результатом через год:", len(pool))

    # 2) модель: проверка на прошлом + обучение на свежих данных
    bt = backtest(pool, now)
    print("Проверка на прошлом:", bt)
    train = [r for r in pool if now - 372 * DAY - 3 * 365 * DAY
             <= r["rel"] < now - 372 * DAY]
    w = fit([features(r, pool) for r in train], [r["y"] for r in train])
    base = sum(r["y"] for r in train) / len(train)
    print("Модель:", [round(v, 3) for v in w], "база:", round(base, 3))

    # 3) новый выпуск: прогноз тиража, популярность, вывод по каждому скину
    done = [s for s in stores if s.get("end") and s.get("start")]
    frac = sales_fraction(done, (now - start) / 3600)
    sup_now = [i.get("supplyTotalEstimated") or 0 for i in items]
    m = med(sup_now) or 1
    new = []
    for i, sup in zip(items, sup_now):
        kind = i.get("itemType") or ""
        it = {"name": i["name"], "type": kind, "cat": category(cats, kind),
              "store": i.get("storePriceUsd") or i["storePrice"], "rel": now,
              "supply": sup / frac, "rs": max(0.05, sup / m),
              "glow": bool(i.get("hasGlow")), "icon": i.get("iconUrl") or "",
              "bg": i.get("backgroundColour") or ""}
        it["p"] = predict(w, features(it, pool))
        it["comp"] = comparables(it, pool)
        it["v"] = verdict(it["p"], it["comp"])
        new.append(it)
        print(f"{it['name']}: шанс {it['p']:.3f}, {it['v']}, rs {it['rs']:.2f},"
              f" {it['comp']}")
    new.sort(key=lambda it: -it["p"])

    # 4) что говорит вся история
    modern = [h for h in hist if h["rel"] >= MODERN and not h["skip"]]
    st_all = strategy(pool, "store", 365)
    st_mod = strategy([r for r in pool if r["rel"] >= MODERN], "store", 365)
    later = strategy(modern, 90, 365)
    flip = strategy(modern, "store", "launch")
    n_data = sum(1 for h in hist if "launch" in h)
    first_year = kyiv(min(h["rel"] for h in hist)).year
    years = f"2022–{kyiv(now - 372 * DAY).year}"
    weeks = {}
    for h in hist:
        if h["rel"] >= now - 365 * DAY:
            weeks.setdefault(h["week"], []).append(h["supply"])
    week_meds = [med(v) for v in weeks.values()]
    rel_med = med([it["supply"] for it in new])
    beat = (sum(1 for v in week_meds if v < rel_med) / len(week_meds)
            if week_meds else None)

    counts = {k: sum(1 for it in new if it["v"] == k) for k in VERDICTS}
    end_k = kyiv(nxt)
    n = len(new)
    head = [
        "\U0001f4bc <b>ИНВЕСТ-РАЗБОР · НЕДЕЛЬНЫЙ ВЫПУСК</b>",
        f"\U0001f5d3 Выпуск {kyiv(start):%d.%m} · {n}"
        f" {bot.plural(n, 'скин', 'скина', 'скинов')} · в магазине до"
        f" ~{end_k:%d.%m %H:%M} (Киев)",
        "",
        f"\U0001f4da База: {bot.fmt_num(n_data)} недельных скинов"
        f" {first_year}–{kyiv(now).year}, продажи Steam Market по дням.",
        f"• Купить в магазине → продать через год: за всю историю в плюсе"
        f" {pct(st_all['share'])}, с 2022 — {pct(st_mod['share'])}"
        f" (медиана {roi(st_mod['med'])} чистыми)",
        f"• Купить на маркете через 3 мес → продать через год (с 2022):"
        f" в плюсе {pct(later['share'])}, медиана {roi(later['med'])}",
    ]
    optional = [
        f"• Перепродать в первую неделю на маркете: в плюсе {pct(flip['share'])}",
        f"\U0001f4e6 Тираж: ≈{num(rel_med)} копий на скин — больше, чем у"
        f" {pct(beat)} выпусков за год" if beat is not None else "",
        f"\U0001f9ea Модель проверена на {bt['n']} скинах"
        f" {kyiv(bt['from']).year}–{kyiv(bt['to']).year}: у трети с низкой"
        f" оценкой в плюсе {pct(bt['low'])}, с высокой — {pct(bt['high'])}",
    ]
    tail = [
        "",
        "  ".join(f"{VERDICTS[k][0]} {VERDICTS[k][1]}: {counts[k]}"
                  for k in VERDICTS if counts[k]),
        "Разбор каждого скина — ниже \U0001f447",
        "",
        "\U000026A0\U0000FE0F Статистика прошлых выпусков, не финансовый совет."
        " Комиссия Steam учтена (продавец получает ≈87% цены),"
        " продать купленное можно через 7 дней.",
        "#rust #раст #инвест #скины",
    ]
    optional = [x for x in optional if x]
    while True:
        caption = "\n".join(head + optional + tail)
        if plain_len(caption) <= 1024 or not optional:
            break
        optional.pop(0)

    blocks = [item_block(it, base, years) for it in new]
    msgs = [f"\U0001f4ca <b>Разбор по скинам</b> — шанс = вероятность чистой"
            f" прибыли через год по модели (у среднего скина {pct(base)})"]
    for b in blocks:
        if len(msgs[-1]) + len(b) + 2 > 3900:
            msgs.append(b)
        else:
            msgs[-1] += "\n\n" + b
    msgs[-1] += "\n\n" + bot.pick(bot.FOOTERS).format(tag=bot.CHANNEL_TAG)

    rows = [(it["name"], it,
             f"{bot.money(it['store'])} · ≈{num(it['supply'])} копий"
             f" · ×{times(it['rs'])} к средней недели",
             f"{VERDICTS[it['v']][2]} · {pct(it['p'])}", VERDICTS[it["v"]][3])
            for it in new]
    title = f"Недельный выпуск {kyiv(start):%d.%m.%Y}"
    subtitle = (f"{n} {bot.plural(n, 'скин', 'скина', 'скинов')} · шанс прибыли"
                f" через год после комиссии · в магазине до {end_k:%d.%m}")
    footer = (f"оценка по {bot.fmt_num(n_data)} недельным скинам"
              f" {first_year}–{kyiv(now).year} · rust.scmm.app / Steam Market")

    if dry:
        print("\n===== ПОДПИСЬ =====\n" + caption)
        for msg in msgs:
            print("\n===== СООБЩЕНИЕ =====\n" + msg)
    tg = bot.Telegram(os.environ.get("BOT_TOKEN", ""), channel, dry_run=dry)
    card = os.path.join(tempfile.gettempdir(), "rust_invest.jpg")
    res = {}
    try:
        if build_card(title, subtitle, rows, footer, card):
            res = tg.send_photo_file(card, caption)
    except Exception as e:
        print("Картинка не собралась:", e)
    if not res.get("ok"):
        res = tg.send_message(caption)
    ok = bool(res.get("ok"))
    for msg in msgs:
        time.sleep(1.5)
        r = tg._post("sendMessage", {
            "chat_id": tg.chat, "text": msg, "parse_mode": "HTML",
            "disable_web_page_preview": "true"})
        ok = ok and bool(r.get("ok"))
    if ok and not dry:
        state.update({"last": cur["id"], "ts": int(now)})
        save_state(state)
        print("Разбор опубликован:", cur["id"])


if __name__ == "__main__":
    run()
