#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Инвест-разбор недельного выпуска скинов Rust — отдельная рубрика канала.

Раз в неделю, когда в магазине Rust новый недельный выпуск, бот:
  1. Берёт ВСЕ недельные скины за всю историю (rust.scmm.app): тип, цену
     в магазине, тираж, коллекцию и историю продаж Steam Market по дням.
  2. Считает, как вели себя прошлые выпуски в первую неделю после
     трейд-бана (продать можно через 7 дней после покупки) и через год —
     с учётом комиссии Steam (продавец получает ≈ цена / 1.15).
  3. Обучает модели на выпусках последнего года (рынок быстро меняется)
     и проверяет их на прошлом:
     • шанс — продастся ли скин в плюс в первую неделю после бана;
     • прибыль — какую цену он, скорее всего, наберёт (→ % после комиссии).
     Плюс модель «через год» — чтобы сказать, стоит ли держать дольше.
  4. Учитывает коллекцию: какая это часть, давно ли вышла прошлая и как
     стартовали прошлые части, ждут ли в мастерской автора ещё её части;
     для новой коллекции — как часто у таких потом выходит продолжение
     (если первым приняли один скин или сразу несколько).
  5. Пост: картинка-плитка и подпись — у каждого скина прибыль в % после
     комиссии и шанс «N из 10»; цвет: можно брать / подумать / не стоит.

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
POST_AFTER_H = 1      # разбор через час после старта выпуска
KNN = 25              # сколько похожих прошлых скинов берём для сравнения
BUY_P = 0.40          # шанс прибыли через год, с которого «держать» имеет смысл

VERDICTS = {  # код: (эмодзи, раздел в посте, плашка на картинке, цвет)
    "buy": ("\U0001f7e2", "МОЖНО БРАТЬ", "МОЖНО БРАТЬ", (61, 220, 132)),
    "think": ("\U0001f7e1", "ПОДУМАТЬ", "ПОДУМАТЬ", (255, 200, 61)),
    "no": ("\U0001f534", "БРАТЬ НЕ СТОИТ", "БРАТЬ НЕ СТОИТ", (255, 82, 82)),
}
COLL_COLORS = {  # цвет строки о коллекции на плитке
    "strong": (61, 220, 132), "weak": (255, 120, 120), "rare": (255, 120, 120),
    "new": (110, 175, 255), "whole": (255, 200, 61),
}


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
                    "coll": it.get("itemCollection") or "",
                    "creator": it.get("creatorId") or "",
                    "skip": bool(it.get("hasReturnedToStoreBefore")
                                 or it.get("isBeingManipulated")),
                })
        if not items or page * 500 >= (j.get("total") or 0):
            return out
        page += 1


def summarize(rel, hist, now):
    """История продаж Steam Market по дням → цена и продажи в первую неделю
    торгов (сразу после трейд-бана), цены на горизонтах HZ (окно ±7 дней,
    средняя по объёму), дно и пик (по неделям)."""
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
    s = {"launch": win(first, first + 7 * DAY), "hz": {},
         "lvol": sum(p[2] for p in pts if p[0] < first + 7 * DAY) / 7}
    for d in HZ:
        c = rel + d * DAY
        if c + 7 * DAY <= now:
            s["hz"][d] = win(c - 7 * DAY, c + 7 * DAY)
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
    return min(1.0, max(0.01, med(fr) or 1.0))


# ---------- модель ----------

def ratio(it, key):
    p = it.get("launch") if key == "launch" else it.get("hz", {}).get(key)
    return p / it["store"] if p else None


def collections(items):
    """Коллекция → её скины, у которых уже известна цена первой недели."""
    idx = {}
    for h in items:
        if h["coll"] and h.get("launch"):
            idx.setdefault(h["coll"], []).append(h)
    return idx


def coll_dates(items):
    """Коллекция → даты выхода всех её скинов (по возрастанию)."""
    idx = {}
    for h in items:
        if h["coll"]:
            idx.setdefault(h["coll"], []).append(h["rel"])
    for v in idx.values():
        v.sort()
    return idx


def waves(times):
    """Даты выхода частей коллекции: скины в пределах двух дней — одна часть."""
    out = []
    for t in times:
        if not out or t - out[-1] > 2 * DAY:
            out.append(t)
    return out


def mark_collection(it, idx, dates):
    """Продолжает ли скин коллекцию, какая это часть, давно ли вышла прошлая
    и как стартовали прошлые части."""
    prev = [h for h in idx.get(it["coll"], [])
            if h["rel"] < it["rel"] - 5 * DAY]
    it["prev_n"] = len(prev)
    it["prev_l"] = med(ratio(h, "launch") for h in prev)
    w = waves([t for t in dates.get(it["coll"], []) if t < it["rel"] - 2 * DAY])
    it["parts"] = len(w)
    it["gap"] = (it["rel"] - w[-1]) / DAY if w else None


def continuation(dates, now):
    """Как часто у новой коллекции за полгода выходит следующая часть:
    (первым приняли один скин, приняли сразу несколько) — «N из 10»."""
    one, many = [], []
    for times in dates.values():
        w = waves(times)
        if w[0] < MODERN or w[0] > now - 180 * DAY:
            continue
        first = sum(1 for t in times if t - w[0] <= 2 * DAY)
        y = 1 if len(w) > 1 and w[1] - w[0] <= 180 * DAY else 0
        (one if first == 1 else many).append(y)
    return tuple(round(10 * sum(v) / len(v)) if v else None
                 for v in (one, many))


def coll_status(it, same):
    """Что сказать о коллекции скина: код значка и строка для плитки.
    same — сколько скинов этой коллекции в нынешнем выпуске."""
    if not it["coll"]:
        return "none", "Без коллекции"
    if not it["parts"]:
        if same > 1:
            return "whole", "Новая коллекция, принята целиком"
        return "new", "Новая коллекция"
    pl = it.get("prev_l")
    if pl and pl >= FEE:
        return "strong", "Прошлые части дороже магазина"
    if (it["gap"] or 0) > 180:
        return "rare", f"Прошлая часть — {round(it['gap'] / 30.4)} мес назад"
    if pl and pl < 0.85:
        return "weak", "Прошлые части дешевле магазина"
    if pl:
        return "even", "Прошлые части — около магазина"
    return "even", f"{it['parts'] + 1}-я часть коллекции"


def submissions(creator):
    """Все работы автора в мастерской, принятые и нет: коллекция, тип,
    файл, когда загружена и когда принята."""
    try:
        rows = get(f"/workshop/creator/{creator}")
    except Exception:
        return []
    return [{"coll": (s.get("itemCollection") or "").strip().lower(),
             "type": s.get("itemType") or "",
             "file": str(s.get("workshopFileId") or ""),
             "made": ts(s["createdOn"]),
             "acc": ts(s["acceptedOn"]) if s.get("acceptedOn") else None}
            for s in rows or [] if s.get("createdOn")]


def pending(subs, coll, t, done=(), skip=()):
    """Сколько новых частей коллекции ждали в мастерской на момент t:
    загружены за год до t, ещё не приняты, и такого типа в коллекции
    ещё нет (done — типы, принятые прямо сейчас; skip — их файлы)."""
    coll = coll.strip().lower()
    mine = [s for s in subs if s["coll"] == coll]
    have = set(done) | {s["type"] for s in mine
                        if s["acc"] and s["acc"] <= t + 2 * DAY}
    return len({s["type"] for s in mine
                if t - 365 * DAY <= s["made"] < t and s["type"] not in have
                and not (s["acc"] and s["acc"] <= t + 2 * DAY)
                and s["file"] not in skip})


def pending_rates(dates, owners, subs, now):
    """Как часто за полгода выходила следующая часть, когда в мастерской
    ждали ещё работы коллекции и когда нет — «N из 10» (с 2022 г.)."""
    out = {True: [], False: []}
    for coll, times in dates.items():
        mine = [s for c in owners.get(coll, ()) for s in subs.get(c, [])]
        if not mine:
            continue
        w = waves(times)
        for k, t in enumerate(w):
            if t < MODERN or t > now - 180 * DAY:
                continue
            y = 1 if k + 1 < len(w) and w[k + 1] - t <= 180 * DAY else 0
            out[pending(mine, coll, t) > 0].append(y)
    return {k: round(10 * sum(v) / len(v)) if v else None
            for k, v in out.items()}


def coll_feats(it):
    return [1.0 if it.get("prev_n") else 0.0,
            math.log(it["prev_l"]) if it.get("prev_l") else 0.0]


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
    """Признаки модели «через год»."""
    if "x" not in it:
        it["lag"] = lagged(it, pool)
        it["x"] = [1.0, math.log(it["rs"]),
                   math.log(max(it["supply"], 500) / 12000),
                   math.log(it["store"] / 199), it["lag"]["typ"],
                   1.0 if it["glow"] else 0.0] + coll_feats(it)
    return it["x"]


def flip_rate(it, flips, k=8):
    """Как часто скины этого типа за последний год (до выхода скина)
    продавались с прибылью сразу после бана — с подтяжкой к среднему."""
    t1 = it["rel"] - 14 * DAY
    tr = [h for h in flips if t1 - 365 * DAY <= h["rel"] < t1]
    base = sum(h["yf"] for h in tr) / len(tr) if tr else 0.3
    g = [h for h in tr if h["type"] == it["type"]]
    return (sum(h["yf"] for h in g) + base * k) / (len(g) + k)


def wipe_week(t):
    """Выпуск в неделю форс-вайпа (первый четверг месяца): игроков больше,
    скинов покупают больше — после бана они чаще дешевле."""
    d = datetime.fromtimestamp(t - 6 * 3600, timezone.utc)
    return d.weekday() == 3 and d.day <= 7


def flip_features(it, flips):
    """Признаки моделей «после бана» (шанс и цена)."""
    if "xf" not in it:
        f = min(0.95, max(0.05, flip_rate(it, flips)))
        it["xf"] = [1.0, math.log(it["rs"]),
                    math.log(max(it["supply"], 500) / 12000),
                    math.log(it["store"] / 199), 1.0 if it["glow"] else 0.0,
                    math.log(f / (1 - f))] + coll_feats(it) + [
                    1.0 if it.get("wipe") else 0.0]
    return it["xf"]


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


def ridge(X, y, lam=1.0):
    """Линейная регрессия с L2 (решение нормальных уравнений Гауссом)."""
    k = len(X[0])
    a = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for x, t in zip(X, y):
        for i in range(k):
            b[i] += x[i] * t
            for j in range(k):
                a[i][j] += x[i] * x[j]
    for i in range(1, k):
        a[i][i] += lam
    m = [row + [bi] for row, bi in zip(a, b)]
    for i in range(k):
        piv = max(range(i, k), key=lambda r: abs(m[r][i]))
        m[i], m[piv] = m[piv], m[i]
        for r in range(k):
            if r != i:
                f = m[r][i] / m[i][i]
                for c in range(i, k + 1):
                    m[r][c] -= f * m[i][c]
    return [m[i][k] / m[i][i] for i in range(k)]


def linear(w, x):
    return sum(a * b for a, b in zip(x, w))


def evaluate(train, test, feat, key):
    """Честная проверка: учим на том, что было известно раньше, и
    сравниваем прогноз с тем, что случилось на самом деле."""
    w = fit([feat(r) for r in train], [r[key] for r in train])
    pr = sorted((predict(w, feat(r)), r[key]) for r in test)
    k = max(1, len(pr) // 3)
    pos = sum(y for _, y in pr)
    rank = sum(i + 1 for i, (_, y) in enumerate(pr) if y)
    auc = ((rank - pos * (pos + 1) / 2) / (pos * (len(pr) - pos))
           if 0 < pos < len(pr) else None)
    return {"n": len(pr), "auc": auc,
            "low": sum(y for _, y in pr[:k]) / k,
            "high": sum(y for _, y in pr[-k:]) / k}


def comparables(it, pool):
    """Похожие прошлые скины нынешнего рынка (с 2022) с известной ценой
    через год: тот же тип (если их хотя бы 12), иначе та же категория;
    ближайшие по популярности."""
    base = [r for r in pool if r["rel"] >= MODERN]
    g = [r for r in base if r["type"] == it["type"]]
    if len(g) < 12:
        g = [r for r in base if r["cat"] == it["cat"]]
    if len(g) < 12:
        g = base
    g = sorted(g, key=lambda r: abs(math.log(r["rs"] / it["rs"])))[:KNN]
    return {"y1": med(ratio(r, 365) for r in g),
            "y1_share": share(ratio(r, 365) / FEE - 1 for r in g)}


def verdict(n10, net):
    """Зелёный — 6+ из 10 похожих продались в плюс и в среднем есть прибыль;
    красный — 4 и меньше из 10 или в среднем убыток больше 5%;
    жёлтый — всё между («около нуля» или «50 на 50»)."""
    if n10 >= 6 and net > 0:
        return "buy"
    if n10 <= 4 or net <= -0.05:
        return "no"
    return "think"


# ---------- текст и картинка ----------

def signed(v):
    """0.09 → «+9%», −0.08 → «−8%», около нуля → «0%»."""
    n = round(v * 100)
    return "0%" if n == 0 else f"{n:+d}%".replace("-", "−")


def trend(net):
    """(эмодзи для подписи, стрелка для картинки, пояснение)."""
    if net > 0:
        return "\U0001f4c8", "▲", "прибыль после комиссии"
    if net > -0.05:
        return "\U00002796", "►", "почти в ноль"
    return "\U0001f4c9", "▼", "скорее убыток"


def build_card(title, subtitle, tiles, example, footer, out_path):
    """Картинка-разбор: плитки по 3 в ряд (картинка скина, цена в магазине,
    крупно — прибыль после комиссии, 10 кружков шанса), внизу «как читать».
    Рамка и плашка — цвет вывода. Рисуем в 2×."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        return False
    S, W, COLS, TW, TH, GAP, TOP, HOW = 2, 1440, 3, 432, 528, 24, 300, 230
    rows = (len(tiles) + COLS - 1) // COLS
    H = TOP + rows * (TH + GAP) + HOW + 96
    p = lambda v: int(v * S)
    card_bg, line_c = (31, 34, 43), (48, 52, 64)
    muted, gold = (150, 156, 172), (240, 190, 70)
    light, dark = (240, 242, 246), (20, 20, 24)
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

    def wrap(text, fnt, width):
        lines = [""]
        for word in text.split():
            t = (lines[-1] + " " + word).strip()
            if not lines[-1] or draw.textlength(t, font=fnt) <= width:
                lines[-1] = t
            else:
                lines.append(word)
        if len(lines) > 2:
            lines = [lines[0], fit_text(" ".join(lines[1:]), fnt, width)]
        return [fit_text(t, fnt, width) for t in lines]

    def dots(x, y, n, color, rest=None):
        """10 кружков: n закрашено цветом, остальные — пустые или rest."""
        for i in range(10):
            cx = x + 9 + i * 24
            box = (p(cx - 9), p(y - 9), p(cx + 9), p(y + 9))
            if i < n:
                draw.ellipse(box, fill=color)
            elif rest:
                draw.ellipse(box, fill=rest)
            else:
                draw.ellipse(box, outline=(110, 116, 132), width=p(2))

    def tint(color):
        return tuple(int(c * 0.28 + b * 0.72) for c, b in zip(color, card_bg))

    # шапка: золотая полоса, метка, заголовок, подзаголовок, легенда цветов
    draw.rectangle((0, 0, p(W), p(12)), fill=gold)
    tag, tf = "ИНВЕСТ-РАЗБОР", font(22, True)
    tw = draw.textlength(tag, font=tf)
    draw.rounded_rectangle((p(48), p(48), p(48) + tw + p(40), p(90)),
                           radius=p(21), fill=gold)
    draw.text((p(48) + (tw + p(40)) / 2, p(69)), tag, font=tf, fill=dark,
              anchor="mm")
    draw.text((p(46), p(142)), fit_text(title, font(58, True), p(W - 96)),
              font=font(58, True), fill=(255, 255, 255), anchor="lm")
    draw.text((p(48), p(198)), fit_text(subtitle, font(26), p(W - 96)),
              font=font(26), fill=muted, anchor="lm")
    lx, lf = p(48), font(24, True)
    for code in VERDICTS:
        color, text = VERDICTS[code][3], VERDICTS[code][1].capitalize()
        draw.ellipse((lx, p(240), lx + p(24), p(264)), fill=color)
        draw.text((lx + p(36), p(252)), text, font=lf, fill=(225, 228, 235),
                  anchor="lm")
        lx += p(36) + draw.textlength(text, font=lf) + p(44)

    # плитки: рамка цвета вывода, картинка, цена, прибыль %, шанс из 10
    for k, t in enumerate(tiles):
        x = 48 + k % COLS * (TW + GAP)
        y = TOP + k // COLS * (TH + GAP)
        color = t["color"]
        edge = tuple(int(c * 0.65 + b * 0.35) for c, b in zip(color, card_bg))
        draw.rounded_rectangle((p(x), p(y), p(x + TW), p(y + TH)),
                               radius=p(26), fill=card_bg, outline=edge,
                               width=p(3))
        bg = t["bg"] or "#2b2d33"
        draw.rounded_rectangle((p(x + 16), p(y + 16), p(x + TW - 16),
                                p(y + 256)), radius=p(20),
                               fill=bg if bg.startswith("#") else "#" + bg)
        ic = icon(t["icon"], 220) if t["icon"] else None
        if ic:
            img.alpha_composite(ic, (p(x + (TW - 220) / 2), p(y + 26)))
        bf = font(20, True)
        bw = draw.textlength(t["label"], font=bf)
        draw.rounded_rectangle((p(x + 28), p(y + 28), p(x + 28) + bw + p(28),
                                p(y + 62)), radius=p(17), fill=color)
        draw.text((p(x + 42) + bw / 2, p(y + 45)), t["label"], font=bf,
                  fill=dark, anchor="mm")
        nf = font(25, True)
        for j, line in enumerate(wrap(t["name"], nf, p(TW - 40))):
            draw.text((p(x + 20), p(y + 284 + j * 31)), line, font=nf,
                      fill=light, anchor="lm")
        draw.text((p(x + 20), p(y + 350)), f"В магазине {t['price']}",
                  font=font(21), fill=muted, anchor="lm")
        draw.text((p(x + 20), p(y + 398)), t["net"], font=font(48, True),
                  fill=color, anchor="lm")
        draw.text((p(x + 20), p(y + 436)),
                  fit_text(t["note"], font(19), p(TW - 40)), font=font(19),
                  fill=t.get("ncolor") or muted, anchor="lm")
        if t.get("wait"):
            draw.text((p(x + 20), p(y + 462)),
                      fit_text(t["wait"], font(19), p(TW - 40)), font=font(19),
                      fill=muted, anchor="lm")
        dots(x + 20, y + 500, t["n10"], color)
        draw.text((p(x + 274), p(y + 500)), f"шанс {t['n10']} из 10",
                  font=font(20, True), fill=color, anchor="lm")

    # «как читать»: что значит прибыль % и что значит «N из 10»
    y0 = TOP + rows * (TH + GAP)
    half = (W - 96 - GAP) / 2
    for i in range(2):
        bx = 48 + i * (half + GAP)
        draw.rounded_rectangle((p(bx), p(y0), p(bx + half), p(y0 + HOW - 24)),
                               radius=p(22), fill=card_bg, outline=line_c,
                               width=p(2))
    good, bad = VERDICTS["buy"][3], VERDICTS["no"][3]
    ok = example["back"] >= 100
    tx = 48 + 24
    draw.text((p(tx), p(y0 + 40)), f"{example['net']} — что это",
              font=font(28, True), fill=light, anchor="lm")
    draw.text((p(tx), p(y0 + 82)), "купил сейчас, продал через неделю,",
              font=font(21), fill=muted, anchor="lm")
    draw.text((p(tx), p(y0 + 110)), "комиссия Steam уже вычтена",
              font=font(21), fill=muted, anchor="lm")
    cf = font(22, True)
    chips = [("вложил 100", (45, 49, 60), (225, 228, 235)),
             (f"вернулось {example['back']}", tint(good if ok else bad),
              good if ok else bad)]
    cx = p(tx)
    for n, (text, fill, fg) in enumerate(chips):
        cw = draw.textlength(text, font=cf)
        draw.rounded_rectangle((cx, p(y0 + 140), cx + cw + p(28), p(y0 + 184)),
                               radius=p(12), fill=fill)
        draw.text((cx + p(14), p(y0 + 162)), text, font=cf, fill=fg,
                  anchor="lm")
        cx += cw + p(28)
        if n == 0:
            draw.text((cx + p(14), p(y0 + 162)), "→", font=cf, fill=muted,
                      anchor="lm")
            cx += draw.textlength("→", font=cf) + p(28)
    rx = 48 + half + GAP + 24
    n10 = example["n10"]
    draw.text((p(rx), p(y0 + 40)), f"{n10} из 10 — что это",
              font=font(28, True), fill=light, anchor="lm")
    draw.text((p(rx), p(y0 + 82)), "из 10 похожих скинов прошлых недель",
              font=font(21), fill=muted, anchor="lm")
    draw.text((p(rx), p(y0 + 110)),
              f"{n10} продались в плюс, {10 - n10} — в минус",
              font=font(21), fill=muted, anchor="lm")
    dots(rx, y0 + 162, n10, good, rest=bad)

    draw.line((p(48), p(H - 80), p(W - 48), p(H - 80)), fill=line_c,
              width=p(2))
    draw.text((p(48), p(H - 44)), fit_text(footer, font(22), p(W - 400)),
              font=font(22), fill=(120, 126, 142), anchor="lm")
    draw.text((p(W - 48), p(H - 44)), bot.CHANNEL_TAG, font=font(28, True),
              fill=gold, anchor="rm")
    img = img.convert("RGB").resize((W, H), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=95, subsampling=0)
    return True


def dump_card(path):
    """Для теста: уменьшенная картинка в лог (base64), чтобы её посмотреть."""
    import base64
    try:
        from PIL import Image
        im = Image.open(path)
        im = im.resize((720, im.height * 720 // im.width), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        print("CARD_B64:" + base64.b64encode(buf.getvalue()).decode())
    except Exception as e:
        print("Не удалось вывести картинку:", e)


def plain_len(text):
    """Длина подписи так, как её считает Telegram (без тегов, UTF-16)."""
    import re
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


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


# ---------- 📒 «мы советовали — что вышло» ----------
# Через REPORT_AFTER_D дней после старта выпуска первая неделя торгов уже
# прошла: сравниваем совет и прогноз с тем, что вышло на самом деле
# (купил в магазине → продал в первую неделю торгов, комиссия вычтена).
REPORT_LIVE = False       # публиковать — после одобрения примера
REPORT_AFTER_D = 15
REPORT_HOURS = (12, 22)   # по Киеву


def full_icon(u):
    if u and not u.startswith("http"):
        return ("https://community.cloudflare.steamstatic.com/economy/image/"
                + u + "/360fx360f")
    return u or ""


def compose_report(pk, now=None):
    """(подпись, картинка) по сохранённым советам выпуска или None."""
    import rust_cards
    now = now or time.time()
    start = ts(pk["start"])
    rows = []
    for it in pk["items"]:
        try:
            s = summarize(start, get("/item/"
                                     + urllib.parse.quote(it["name"], safe="")
                                     + "/sales/market?maxDays=-1"), now)
        except Exception as e:
            print("Нет истории:", it["name"], e)
            continue
        if s.get("launch"):
            rows.append(dict(it, real=s["launch"] / FEE / it["store"] - 1))
    if len(rows) < max(2, len(pk["items"]) // 2):
        return None
    order = list(VERDICTS)
    rows.sort(key=lambda r: (order.index(r["v"]), -r["real"]))
    right = lambda r: (None if r["v"] == "think" else
                       (r["real"] > 0) == (r["v"] == "buy"))
    tiles = [{"name": r["name"], "image": full_icon(r["icon"]),
              "tag": VERDICTS[r["v"]][2], "tag_color": VERDICTS[r["v"]][3],
              "value": signed(r["real"]).replace("−", "-"),
              "value_up": r["real"] > 0, "mark": right(r),
              "sub": (f"прогноз {signed(r['net'])} · магазин "
                      f"{bot.money(r['store'])}" if r.get("net") is not None
                      else f"в магазине {bot.money(r['store'])}")}
             for r in rows]
    judged = [r for r in rows if right(r) is not None]
    hits = sum(1 for r in judged if right(r))
    date = kyiv(start).strftime("%d.%m")
    summary = (f"совет сбылся: {hits} из {len(judged)}" if judged
               else "все скины были «подумать»")
    card = os.path.join(tempfile.gettempdir(), "rust_report.jpg")
    try:
        ok = rust_cards.report_card(card, f"ВЫПУСК {date}", tiles, summary)
    except Exception as e:
        print("Картинка отчёта не собралась:", e)
        ok = False
    dot = "\U000025AB\U0000FE0F"
    best = max(rows, key=lambda r: r["real"])

    def compose(show_was, limit):
        lines = [f"\U0001f4d2 <b>МЫ СОВЕТОВАЛИ — ЧТО ВЫШЛО</b> · выпуск {date}",
                 "Честно проверяем свой разбор: купил в магазине, продал в"
                 " первую неделю торгов, комиссия Steam вычтена."]
        for code in VERDICTS:
            group = [r for r in rows if r["v"] == code]
            if not group:
                continue
            lines += ["", f"{VERDICTS[code][0]} <b>{VERDICTS[code][1]}</b>"]
            for r in group[:limit]:
                mk = {True: " ✅", False: " ❌", None: ""}[right(r)]
                was = (f"прогноз {signed(r['net'])} → "
                       if show_was and r.get("net") is not None else "")
                lines.append(f"{dot} {html.escape(r['name'])} — {was}вышло "
                             f"<b>{signed(r['real'])}</b>{mk}")
            if len(group) > limit:
                lines.append(f"{dot} и ещё {len(group) - limit} — на картинке")
        lines.append("")
        if judged:
            lines.append(f"\U0001f3af Совет сбылся: {hits} из {len(judged)}"
                         " (жёлтые не считаем — там был честный «50 на 50»)")
        if best["real"] > 0:
            lines.append(f"\U0001f3c6 Лучший: {html.escape(best['name'])} —"
                         f" вложил 100 → вернулось"
                         f" {round(100 * (1 + best['real']))}")
        lines += ["", "#rust #раст #инвест #итоги"]
        return "\n".join(lines)

    for show_was, limit in ((True, 99), (False, 99), (False, 4), (False, 2)):
        text = compose(show_was, limit)
        if plain_len(text) <= 1024:
            break
    return text, (card if ok else "")


def report_tick(state, tg, now, dry=False):
    """Один отчёт за запуск: выпуск, которому REPORT_AFTER_D дней и больше."""
    h = kyiv(now).hour
    if not (REPORT_LIVE and REPORT_HOURS[0] <= h < REPORT_HOURS[1]):
        return
    picks = state.get("picks") or {}
    for rid in sorted(picks):
        pk = picks[rid]
        if pk.get("reported") or now - ts(pk["start"]) < REPORT_AFTER_D * DAY:
            continue
        out = compose_report(pk, now)
        if not out:
            pk["tries"] = pk.get("tries", 0) + 1
            if pk["tries"] >= 6:             # история так и не появилась
                pk["reported"] = True
            save_state(state)
            continue
        text, card = out
        res = tg.send_photo_file(card, text) if card else {}
        if not res.get("ok"):
            res = tg.send_message(text)
        if res.get("ok") and not dry:
            pk["reported"] = True
            save_state(state)
            print("Отчёт опубликован:", rid)
        return


def run():
    now = time.time()
    forced = os.environ.get("INVEST_FORCE") == "1"
    dry = os.environ.get("INVEST_DRY") == "1"
    channel = os.environ.get("CHANNEL", "")
    if channel.startswith("@"):
        bot.CHANNEL_TAG = channel
    state = load_state()
    tg = bot.Telegram(os.environ.get("BOT_TOKEN", ""), channel, dry_run=dry)
    try:
        report_tick(state, tg, now, dry)
    except Exception as e:
        print("Отчёт «что вышло» не удался:", e)

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
    due = now - start >= POST_AFTER_H * 3600 or nxt - now <= 30 * 3600
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
    if (sum(1 for i in items if i.get("supplyTotalEstimated")) < len(items) / 2
            and not forced):
        print("SCMM ещё не посчитал продажи — подождём.")
        return

    # 1) вся история недельных скинов: продажи, популярность, коллекции
    hist = [h for h in fetch_weekly(cats) if h["rel"] < start - DAY]
    print("Недельных скинов в истории:", len(hist))
    load_history(hist, now)
    mark_popularity(hist)
    colls = collections([h for h in hist if not h["skip"]])
    dates = coll_dates(hist)
    for h in hist:
        mark_collection(h, colls, dates)
        h["wipe"] = wipe_week(h["rel"])
    pool, flips = [], []
    for h in hist:
        if h["skip"]:
            continue
        r = ratio(h, 365)
        if r:
            h["lr"], h["y"] = math.log(r), 1 if r > FEE else 0
            pool.append(h)
        rl = ratio(h, "launch")
        if rl:
            h["ll"], h["yf"] = math.log(rl), 1 if rl > FEE else 0
            flips.append(h)
    print("С результатом через год:", len(pool), "· после бана:", len(flips))

    # 2) модели: проверка на прошлом + обучение на свежих данных
    fend = now - 21 * DAY
    old = [h for h in flips if fend - 730 * DAY <= h["rel"] < fend - 365 * DAY]
    ftrain = [h for h in flips if fend - 365 * DAY <= h["rel"] < fend]
    ff = lambda h: flip_features(h, flips)
    print("Проверка шанса «после бана»:", evaluate(old, ftrain, ff, "yf"))
    wl = ridge([ff(h) for h in old], [h["ll"] for h in old])
    err = med(abs(math.exp(linear(wl, ff(h)) - h["ll"]) - 1) for h in ftrain)
    print("Проверка цены «после бана»: медианная ошибка", round(err, 3))
    wf = fit([ff(h) for h in ftrain], [h["yf"] for h in ftrain])
    wl = ridge([ff(h) for h in ftrain], [h["ll"] for h in ftrain])
    train = [r for r in pool if now - 372 * DAY - 3 * 365 * DAY
             <= r["rel"] < now - 372 * DAY]
    w = fit([features(r, pool) for r in train], [r["y"] for r in train])
    print("Модели:", [round(v, 3) for v in wf], [round(v, 3) for v in wl],
          "база после бана:",
          round(sum(h["yf"] for h in ftrain) / len(ftrain), 3))

    # 3) новый выпуск: прогноз тиража, популярность, коллекция, шанс, прибыль
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
              "glow": bool(i.get("hasGlow")),
              "coll": i.get("itemCollection") or "",
              "creator": i.get("creatorId") or "",
              "file": str(i.get("workshopFileId") or ""),
              "icon": i.get("iconUrl") or "",
              "bg": i.get("backgroundColour") or "",
              "wipe": wipe_week(start)}
        mark_collection(it, colls, dates)
        it["pf"] = predict(wf, ff(it))
        it["n10"] = max(0, min(10, int(it["pf"] * 10 + 0.5)))
        it["net"] = math.exp(linear(wl, ff(it))) / FEE - 1
        it["ph"] = predict(w, features(it, pool))
        it["comp"] = comparables(it, pool)
        it["v"] = verdict(it["n10"], it["net"])
        new.append(it)
    # мастерская: ждут ли ещё части коллекции (и как часто тогда выходит
    # продолжение — по истории с 2022 г.)
    owners = {}
    for h in hist:
        if h["coll"] and h["creator"] and h["rel"] >= MODERN:
            owners.setdefault(h["coll"], set()).add(h["creator"])
    for it in new:
        if it["coll"] and it["creator"]:
            owners.setdefault(it["coll"], set()).add(it["creator"])
    with ThreadPoolExecutor(8) as ex:
        people = sorted({c for v in owners.values() for c in v})
        subs = dict(zip(people, ex.map(submissions, people)))
    rates = pending_rates(dates, owners, subs, now)
    print("Продолжение за полгода, если в мастерской ждут части / нет:", rates)
    for it in new:
        same = [o for o in new if it["coll"] and o["coll"] == it["coll"]]
        it["cs"], it["ctext"] = coll_status(it, len(same))
        mine = [s for c in owners.get(it["coll"], ()) for s in subs.get(c, [])]
        it["wait"] = (pending(mine, it["coll"], now,
                              done={o["type"] for o in same},
                              skip={o["file"] for o in same})
                      if it["coll"] else None)
        print(f"{it['name']}: шанс {it['n10']}/10 ({it['pf']:.3f}), прибыль"
              f" {signed(it['net'])}, за год {it['ph']:.3f}, {it['v']},"
              f" коллекция {it['coll']!r} ({it['prev_n']}, {it['prev_l']},"
              f" часть {it['parts'] + 1}, пауза {it['gap']}, ждут {it['wait']})"
              f" → {it['cs']}")
    cont = continuation(dates, now)
    print("Продолжение новых коллекций за полгода (из 10):", cont)
    order = list(VERDICTS)
    new.sort(key=lambda it: (order.index(it["v"]), -it["net"]))

    # 4) пост: картинка-плитка + подпись по цветам
    n_data = sum(1 for h in hist if "launch" in h)
    first_year = kyiv(min(h["rel"] for h in hist)).year
    end_k = kyiv(nxt)
    groups = {k: [it for it in new if it["v"] == k] for k in VERDICTS}
    marks = {"strong": " \U0001f9e9", "weak": " ⚠️",
             "rare": " ⚠️", "new": " \U0001f195", "whole": " \U0001f51a"}
    seen = {it["cs"] for it in new}
    legend = []
    if "strong" in seen:
        legend.append("\U0001f9e9 — прошлые части коллекции продавались дороже"
                      " магазина")
    if {"weak", "rare"} <= seen:
        legend.append("⚠️ — прошлые части дешевле магазина или новые"
                      " части выходят редко")
    elif "weak" in seen:
        legend.append("⚠️ — прошлые части коллекции продавались"
                      " дешевле магазина")
    elif "rare" in seen:
        legend.append("⚠️ — части коллекции выходят редко: прошлая"
                      " — больше полугода назад")
    if "new" in seen and cont[0] is not None:
        legend.append(f"\U0001f195 — новая коллекция: у {cont[0]} из 10 таких"
                      f" потом выходят новые части")
    if "whole" in seen and cont[1] is not None:
        legend.append(f"\U0001f51a — новую коллекцию приняли сразу целиком:"
                      f" продолжение бывает у {cont[1]} из 10")
    best = max(groups["buy"] or new, key=lambda it: it["net"])
    ex = {"net": signed(best["net"]), "n10": best["n10"],
          "back": round(100 * (1 + best["net"]))}
    holds = [it for it in new
             if it["ph"] >= BUY_P and (it["comp"]["y1_share"] or 0) >= 0.4]
    y1 = med(it["comp"]["y1"] for it in new) or 1
    if holds:
        hold = ("\U0001f4a1 Держать год имеет смысл только: "
                + ", ".join(html.escape(it["name"]) for it in holds))
    elif y1 < 1:
        hold = ("\U0001f4a1 Держать дольше не стоит — через год такие обычно"
                " дешевле магазина")
    else:
        hold = ("\U0001f4a1 Через год такие обычно стоят около цены магазина"
                " — выгоднее продать сразу")

    def compose(explain, word, limit, wipe, keep_hold=True):
        dot = "\U000025AB\U0000FE0F"
        lines = [f"\U0001f4bc <b>ИНВЕСТ-РАЗБОР НЕДЕЛИ</b> · выпуск"
                 f" {kyiv(start):%d.%m}",
                 f"Купить можно до {end_k:%d.%m} · продать — через 7 дней"
                 f" после покупки"]
        if wipe:
            lines.append("\U0001f504 Неделя вайпа: скинов покупают больше"
                         " обычного — после бана они чаще дешевле")
        for code, group in groups.items():
            if not group:
                continue
            lines += ["", f"{VERDICTS[code][0]} <b>{VERDICTS[code][1]}</b>"]
            for it in group[:limit]:
                mark = marks.get(it["cs"], "")
                lines.append(f"{dot} {html.escape(it['name'])} —"
                             f" {trend(it['net'])[0]} {signed(it['net'])}"
                             f" · {word}{it['n10']} из 10{mark}")
            if len(group) > limit:
                lines.append(f"{dot} и ещё {len(group) - limit} — на картинке")
        lines.append("")
        if explain:
            lines += [f"\U0001f4cc {ex['net']} — купил сейчас, продал через"
                      f" неделю, комиссия Steam уже вычтена (вложил 100 →"
                      f" вернулось {ex['back']})",
                      f"\U0001f3af {ex['n10']} из 10 — столько похожих скинов"
                      f" прошлых недель продались в плюс"]
        if keep_hold:
            lines.append(hold)
        lines += legend
        lines.append("#rust #раст #инвест #скины")
        return "\n".join(lines)

    wipe = wipe_week(start)
    # в неделю вайпа строка про вайп важнее обычной строки «держать»
    for explain, word, limit, wp, kh in ((True, "шанс ", 99, wipe, True),
                                         (False, "шанс ", 99, wipe, True),
                                         (False, "шанс ", 99, wipe, False),
                                         (False, "шанс ", 99, False, True),
                                         (False, "", 99, False, True),
                                         (False, "", 6, False, True),
                                         (False, "", 3, False, True)):
        caption = compose(explain, word, limit, wp, kh)
        if plain_len(caption) <= 1024:
            break

    tiles = [{
        "name": it["name"], "icon": it["icon"], "bg": it["bg"],
        "price": bot.money(it["store"]),
        "net": f"{trend(it['net'])[1]} {signed(it['net'])}",
        "note": it["ctext"], "ncolor": COLL_COLORS.get(it["cs"]),
        "wait": ("" if it["wait"] is None else
                 f"В мастерской ждут ещё {it['wait']} "
                 f"{bot.plural(it['wait'], 'часть', 'части', 'частей')}"
                 if it["wait"] else "В мастерской новых частей нет"),
        "n10": it["n10"],
        "label": VERDICTS[it["v"]][2], "color": VERDICTS[it["v"]][3],
    } for it in new]
    n = len(new)
    title = f"Недельный выпуск {kyiv(start):%d.%m.%Y}"
    subtitle = (f"{n} {bot.plural(n, 'скин', 'скина', 'скинов')} · купить до"
                f" {end_k:%d.%m} · продать через 7 дней после покупки"
                + (" · неделя вайпа" if wipe else ""))
    footer = (f"по истории {bot.fmt_num(n_data)} недельных скинов"
              f" {first_year}–{kyiv(now).year} · rust.scmm.app")

    if dry:
        print("\n===== ПОДПИСЬ =====\n" + caption)
        print("Длина подписи:", plain_len(caption))
    card = os.path.join(tempfile.gettempdir(), "rust_invest.jpg")
    res = {}
    try:
        if build_card(title, subtitle, tiles, ex, footer, card):
            if dry:
                dump_card(card)
            res = tg.send_photo_file(card, caption)
    except Exception as e:
        print("Картинка не собралась:", e)
    if not res.get("ok"):
        res = tg.send_message(caption)
    if res.get("ok") and not dry:
        state.update({"last": cur["id"], "ts": int(now)})
        # советы выпуска — для отчёта «что вышло» через REPORT_AFTER_D дней
        picks = state.setdefault("picks", {})
        picks[cur["id"]] = {"start": cur["start"], "items": [
            {"name": it["name"], "v": it["v"], "net": round(it["net"], 4),
             "n10": it["n10"], "store": it["store"], "icon": it["icon"]}
            for it in new]}
        for rid in sorted(picks)[:-12]:
            del picks[rid]
        save_state(state)
        print("Разбор опубликован:", cur["id"])


if __name__ == "__main__":
    run()
