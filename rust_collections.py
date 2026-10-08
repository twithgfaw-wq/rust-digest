# -*- coding: utf-8 -*-
"""
📚 Лучшие коллекции Rust для покупки: какие коллекции мастерской выгодно
брать в магазине, когда выходит их новая часть. По истории всех недельных
скинов с 2023 года (rust.scmm.app):
  • «в плюс N из 10» — сколько частей коллекции в первую неделю торгов
    (сразу после трейд-бана) продавались дороже цены магазина с учётом
    комиссии Steam;
  • прибыль первой недели — медиана по частям, комиссия уже вычтена;
  • через 3 месяца — держать дольше или продавать сразу;
  • сколько скинов уже вышло, когда последний и ждут ли ещё работы этой
    коллекции в мастерской.
Места — по «оценке»: медиана, притянутая к обычному скину (см. analyze).
Запуск: python rust_collections.py (COLL_DRY=1 — только лог и картинка).
"""
import html
import json
import os
import re
import statistics
import tempfile
import time
from datetime import datetime, timezone

import invest as iv
import rust_digest_bot as bot

SINCE = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
MIN_PARTS = 3              # минимум скинов с ценой первой недели
ACTIVE_DAYS = 365          # последняя часть — не старше года
SHRINK = 5                 # «вес» обычного скина в оценке коллекции
DAY = 86400


def fetch_weekly():
    """Недельные скины магазина с 2023 г. с коллекцией: цена магазина,
    дата, автор, картинка."""
    out, page = [], 1
    while True:
        j = iv.get(f"/item?pageSize=500&page={page}")
        items = j.get("items") or []
        for it in items:
            price = it.get("storePriceUsd") or it.get("storePrice")
            coll = (it.get("itemCollection") or "").strip()
            if not (price and coll and it.get("timeAccepted")
                    and not it.get("isPermanent")):
                continue
            rel = iv.ts(it["timeAccepted"])
            if rel >= SINCE:
                out.append({"name": it["name"], "store": price, "rel": rel,
                            "coll": coll, "creator": it.get("creatorId") or "",
                            "icon": iv.full_icon(it.get("iconUrl")),
                            "skip": bool(it.get("hasReturnedToStoreBefore")
                                         or it.get("isBeingManipulated"))})
        if not items or page * 500 >= (j.get("total") or 0):
            return out
        page += 1


def load(now):
    """Скины с историей продаж. COLL_CACHE=файл — сохранить/взять готовое
    (для проверки, чтобы не качать историю заново)."""
    cache = os.environ.get("COLL_CACHE")
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    items = [h for h in fetch_weekly() if h["rel"] < now - 10 * DAY]
    print("Недельных скинов с коллекцией с 2023 г.:", len(items))
    iv.load_history(items, now)
    for h in items:   # ключи горизонтов — строками, как после json
        h["hz"] = {str(k): v for k, v in (h.get("hz") or {}).items()}
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
    return items


def net(price, store):
    return price / iv.FEE / store - 1


def clean(name):
    """«Sinotype collection.» → «Sinotype», «Copper /» → «Copper»."""
    name = re.sub(r"\s+[cс]ollection\W*$", "", name.strip(), flags=re.I)
    return name.strip(" ./!") or name


def baseline(items):
    """Обычный недельный скин: медиана первой недели и доля «в плюс»."""
    flips = [net(h["launch"], h["store"]) for h in items
             if h.get("launch") and not h["skip"]]
    return {"flip": statistics.median(flips),
            "win": sum(1 for f in flips if f > 0) / len(flips),
            "n": len(flips)}


def analyze(items, now, base):
    """Статистика по каждой коллекции с MIN_PARTS скинами. score —
    медиана, «притянутая» к обычному скину: у коллекции из 3 скинов
    случайный успех весит меньше, чем у коллекции из 25."""
    groups = {}
    for h in items:
        groups.setdefault(h["coll"].lower(), []).append(h)
    rows = []
    for key, hs in groups.items():
        parts = sorted((h for h in hs if h.get("launch") and not h["skip"]),
                       key=lambda h: h["rel"])
        if len(parts) < MIN_PARTS:
            continue
        flips = [net(h["launch"], h["store"]) for h in parts]
        holds = [net(h["hz"]["90"], h["store"]) for h in parts
                 if h["hz"].get("90")]
        ws = iv.waves(sorted(h["rel"] for h in hs))
        names = [h["coll"] for h in hs]
        latest = max(hs, key=lambda h: h["rel"])
        recent = [net(h["launch"], h["store"]) for h in parts[-3:]]
        flip = statistics.median(flips)
        rows.append({
            "key": key, "name": clean(max(set(names), key=names.count)),
            "skins": len(parts), "waves": len(ws),
            "since": parts[0]["rel"],
            "win": sum(1 for f in flips if f > 0) / len(flips),
            "flip": flip,
            "score": (len(flips) * flip + SHRINK * base["flip"])
                     / (len(flips) + SHRINK),
            "recent": statistics.median(recent),
            "hold": statistics.median(holds) if len(holds) >= 2 else None,
            "price": statistics.median(h["store"] for h in parts),
            "last": ws[-1],
            "icon": latest["icon"], "latest": latest["name"],
            "creators": sorted({h["creator"] for h in hs if h["creator"]}),
            "active": now - ws[-1] <= ACTIVE_DAYS * DAY})
    return rows


def pick(rows, now):
    """Топ-5 «брать» и 3 «не брать» среди живых коллекций, которые
    выходят частями (от 3 выходов и 4 скинов)."""
    live = [r for r in rows if r["active"] and r["waves"] >= 3
            and r["skins"] >= 4]
    good = []
    for r in sorted((r for r in live if r["win"] >= 0.6 and r["flip"] > 0
                     and r["recent"] >= 0), key=lambda r: -r["score"]):
        # ждут ли ещё части в мастерской (запросы — только для кандидатов);
        # коллекция без новых частей полгода и без очереди — скорее всего всё
        subs = [s for c in r["creators"] for s in iv.submissions(c)]
        r["pending"] = iv.pending(subs, r["key"], now) if subs else 0
        if r["pending"] or now - r["last"] <= 180 * DAY:
            good.append(r)
        if len(good) == 5:
            break
    bad = sorted((r for r in live if r["win"] <= 0.3 and r["flip"] < 0
                  and r["skins"] >= 5),
                 key=lambda r: r["score"])[:3]
    return good, bad


def pct(v):
    n = round(v * 100)
    return "0%" if n == 0 else f"{n:+d}%".replace("-", "−")


def when(r):
    last = datetime.fromtimestamp(r["last"], timezone.utc).strftime("%d.%m.%Y")
    since = datetime.fromtimestamp(r["since"], timezone.utc).year
    return (f"{r['skins']} {bot.plural(r['skins'], 'скин', 'скина', 'скинов')}"
            f" с {since} · последний {last}")


def queue(r, short=False):
    n = r.get("pending") or 0
    if not n:
        return ""
    if short:
        return f"ещё {n} в мастерской"
    return (f"в мастерской ждут ещё {n}"
            f" {bot.plural(n, 'часть', 'части', 'частей')}")


# ---------- картинка ----------

def card(out_path, date, good, bad, base):
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    import rust_cards as rc
    from cs2_cards import p, font, wrap
    W, RH = 1200, 150
    top = 120
    y = top + 150
    H = y + len(good) * RH + 30 + (90 if bad else 0) + 170 + 24 + 64 + 6 + 70
    img, draw = rc.canvas(W, H)
    rc.nav(draw, W, "ИНВЕСТИЦИИ")
    y1 = H - 70
    rc.panel(img, draw, (48, top, W - 48, y1), "ЛУЧШИЕ КОЛЛЕКЦИИ", date)
    draw.text((p(76), p(top + 112)), "ЧЬЮ НОВУЮ ЧАСТЬ БРАТЬ В МАГАЗИНЕ · "
              "МЕСТА — ПО НАДЁЖНОСТИ · ИСТОРИЯ С 2023 ГОДА", font=font(21),
              fill=rc.MUTED, anchor="lm")
    green = (61, 220, 132)
    for k, r in enumerate(good):
        img.paste(rc.gradient(p(124), p(124), *rc.RED_TILE), (p(76), p(y + 13)))
        rc.base.place_item(img, rc.fetch_image(r["icon"]), 138, y + 75, 104,
                           104)
        if k < 3:
            rc.medal(draw, 94, y + 30, k, 22)
        else:
            draw.ellipse((p(72), p(y + 8), p(116), p(y + 52)),
                         fill=(90, 86, 80), outline=(16, 12, 10), width=p(3))
            draw.text((p(94), p(y + 30)), str(k + 1), font=font(26, True),
                      fill=rc.WHITE, anchor="mm")
        x, w = 226, 548
        draw.text((p(x), p(y + 42)),
                  wrap(draw, rc.safe_text(r["name"]).upper(), font(36, True),
                       w, 1)[0],
                  font=font(36, True), fill=rc.WHITE, anchor="lm")
        draw.text((p(x), p(y + 84)), wrap(draw, when(r), font(21), w, 1)[0],
                  font=font(21), fill=rc.MUTED, anchor="lm")
        if queue(r):
            draw.text((p(x), p(y + 114)), queue(r).upper(),
                      font=font(20, True), fill=rc.GOLD, anchor="lm")
        rx = 800
        rc.arrow(draw, rx, y + 48, True, green, 26)
        draw.text((p(rx + 38), p(y + 48)), pct(r["flip"]), font=font(56, True),
                  fill=green, anchor="lm")
        n10 = round(r["win"] * 10)
        rc.dots(draw, rx, y + 106, n10, green)
        draw.text((p(rx + 228), p(y + 106)), f"в плюс {n10}/10",
                  font=font(22, True), fill=green, anchor="lm")
        draw.line((p(76), p(y + RH - 1), p(W - 76), p(y + RH - 1)),
                  fill=(66, 56, 38), width=p(1))
        y += RH
    y += 30
    if bad:
        red = (255, 82, 82)
        draw.rectangle((p(76), p(y), p(W - 76), p(y + 70)),
                       fill=tuple(int(c * 0.22 + 20) for c in red))
        draw.rectangle((p(76), p(y), p(84), p(y + 70)), fill=red)
        head = "НЕ СТОИТ БРАТЬ:"
        draw.text((p(104), p(y + 35)), head, font=font(26, True), fill=red,
                  anchor="lm")
        tx = 104 + draw.textlength(head, font=font(26, True)) / rc.S + 18
        txt = " · ".join(f"{rc.safe_text(r['name'])} {pct(r['flip'])}"
                         for r in bad)
        draw.text((p(tx), p(y + 35)),
                  wrap(draw, txt.upper(), font(23, True), W - 100 - tx, 1)[0],
                  font=font(23, True), fill=rc.WHITE, anchor="lm")
        y += 90
    half = (W - 152 - 24) / 2
    for i in range(2):
        bx = 76 + i * (half + 24)
        rc.base.overlay(img, "rectangle", (p(bx), p(y), p(bx + half),
                                           p(y + 170)), (0, 0, 0, 90))
    ex = pct(good[0]["flip"]) if good else "+20%"
    b10 = round(base["win"] * 10)
    blocks = [(f"{ex} — ЭТО", ["купил новую часть в магазине и продал",
                               "в первую неделю после трейд-бана,",
                               "комиссия Steam уже вычтена"]),
              (f"ОБЫЧНЫЙ СКИН — {pct(base['flip'])}",
               [f"в плюс только {b10} из 10 недельных",
                "скинов: брать всё подряд невыгодно,",
                "выбирай коллекцию"])]
    for i, (head, lines) in enumerate(blocks):
        bx = 76 + i * (half + 24) + 24
        draw.text((p(bx), p(y + 34)), head, font=font(28, True),
                  fill=rc.WHITE, anchor="lm")
        for j, t in enumerate(lines):
            draw.text((p(bx), p(y + 74 + j * 30)), t, font=font(22),
                      fill=rc.MUTED, anchor="lm")
    rc.bar(draw, (51, y1 - 67, W - 51, y1 - 3),
           "новая часть этих коллекций — кандидат на покупку")
    rc.footer(draw, W, H, "rust.scmm.app · недельные скины с 2023 года")
    return rc.save(img, W, H, out_path)


# ---------- подпись ----------

def compose(good, bad, base, footer):
    lines = ["📚 <b>ЛУЧШИЕ КОЛЛЕКЦИИ RUST ДЛЯ ПОКУПКИ</b>",
             "Вышла новая часть коллекции — брать или нет? Разобрали"
             f" {base['n']} скинов с 2023 года, места — по надёжности.", ""]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for m, r in zip(medals, good):
        lines.append(f"{m} <b>{html.escape(r['name'])}</b> — 📈 {pct(r['flip'])}"
                     f" · в плюс {round(r['win'] * 10)} из 10")
        info = " · ".join(filter(None, [when(r), queue(r, True)]))
        lines.append(f"└ {html.escape(info)}")
    if bad:
        lines += ["", "🚫 <b>Мимо:</b> " + ", ".join(
            f"{html.escape(r['name'])} ({pct(r['flip'])})" for r in bad)]
    lines += ["", f"📉 Для сравнения, обычный скин: {pct(base['flip'])},"
                  f" в плюс {round(base['win'] * 10)} из 10."]
    holds = [r["hold"] for r in good if r["hold"] is not None]
    if holds and statistics.median(holds) < 0:
        lines.append("💡 Продавай сразу: через 3 месяца эти коллекции"
                     f" в среднем {pct(statistics.median(holds))}.")
    elif holds:
        lines.append("💡 Через 3 месяца эти коллекции в среднем"
                     f" {pct(statistics.median(holds))} — можно не спешить.")
    note = ("<i>% — купил в магазине, продал в первую неделю после бана,"
            " комиссия вычтена. Это история, а не гарантия.</i>")
    tail = ["", footer, "#rust #раст #инвест #коллекции"]
    # подпись к фото — не длиннее 1024 знаков: сначала жертвуем футером
    for extra in ([note] + tail, [note, ""] + tail[2:], [note]):
        text = "\n".join(lines + extra)
        if iv.plain_len(text) <= 1024:
            return text
    return text


def report(rows, base):
    print(f"Обычный скин: {pct(base['flip'])}, в плюс {base['win']:.0%},"
          f" скинов {base['n']}")
    for r in sorted(rows, key=lambda r: -r["score"]):
        print(f"{r['name'][:26]:26} оценка {pct(r['score']):>5}"
              f" скинов {r['skins']:3} выходов {r['waves']:2}"
              f" в плюс {r['win']:4.0%} неделя {pct(r['flip']):>6}"
              f" свежие {pct(r['recent']):>6} 3мес "
              f"{pct(r['hold']) if r['hold'] is not None else '—':>6}"
              f" цена ${r['price'] / 100:.2f}"
              f" посл {datetime.fromtimestamp(r['last'], timezone.utc):%d.%m.%y}"
              f" авторов {len(r['creators'])}{'' if r['active'] else ' (давно)'}")


def build(footer):
    now = time.time()
    items = load(now)
    base = baseline(items)
    rows = analyze(items, now, base)
    report(rows, base)
    good, bad = pick(rows, now)
    if not good:
        return None
    text = compose(good, bad, base, footer)
    path = os.path.join(tempfile.gettempdir(), "rust_collections.jpg")
    try:
        ok = card(path, bot.kyiv_time().strftime("%d.%m.%Y"), good, bad, base)
    except Exception as e:
        print("Картинка коллекций не собралась:", e)
        ok = False
    return text, (path if ok else "")


def main():
    dry = os.environ.get("COLL_DRY") == "1"
    channel = os.environ.get("CHANNEL", "")
    if channel.startswith("@"):
        bot.CHANNEL_TAG = channel
    out = build(bot.pick(bot.FOOTERS).format(tag=bot.CHANNEL_TAG))
    if not out:
        print("Нет коллекций, которые проходят отбор.")
        return
    text, path = out
    print("\n===== ПОСТ =====\n" + text)
    print("Длина подписи:", iv.plain_len(text))
    if dry:
        if path:
            iv.dump_card(path)
        return
    tg = bot.Telegram(os.environ.get("BOT_TOKEN", ""), channel)
    res = tg.send_photo_file(path, text) if path else {}
    if not res.get("ok"):
        res = tg.send_message(text)
    print("Опубликовано:", res.get("ok"))


if __name__ == "__main__":
    main()
