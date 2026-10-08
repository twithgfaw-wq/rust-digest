# -*- coding: utf-8 -*-
"""
Новые рубрики Rust-канала (выбраны 08.10.2026):
  📰 новости Facepunch пересказывает Claude — по-человечески, с блоком
     «что это значит» для вайпа, фарма и скинов;
  🎨 «Скин дня» — витрина в стиле магазина: цена в магазине и на маркете,
     сколько продано, график цены с линией цены магазина;
  🗳 «Угадай цену» — опрос, какой из двух скинов подорожает за неделю;
     через неделю итог с реальными ценами и новый опрос.
  (📒 «Мы советовали — что вышло» публикует invest.py.)
Данные — rust.scmm.app (магазин, маркет, продажи) и Steam News.
"""
import functools
import html
import json
import os
import random
import re
import statistics
import tempfile
import time
import urllib.parse
from datetime import datetime

import cs2_ai as ai
import rust_cards as cards
import rust_digest_bot as bot

API = "https://api.scmm.app/api"
NEWS = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        "?appid=252490&count={n}&maxlength=0")
OFFICIAL = "steam_community_announcements"
NEWS_LIVE = True                # новости через Claude (одобрено 08.10)
DAY = 86400
LIVE = True                     # по расписанию (одобрено 08.10)
SOD_HOUR = 12                   # 🎨 скин дня — каждый день, по Киеву
DUEL_DAY, DUEL_HOUR = 1, 19     # 🗳 угадай цену — вторник


def get(path):
    return bot.http_get_json(path if path.startswith("http") else API + path,
                             timeout=40)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def icon(u):
    if u and not u.startswith("http"):
        return ("https://community.cloudflare.steamstatic.com/economy/image/"
                + u + "/360fx360f")
    return u or ""


def pct(v):
    return f"{v:+.0f}%".replace("-", "−")


def safe(s):
    """Текст модели → безопасный Telegram HTML (<b>, <i>, ссылки)."""
    s = html.escape(html.unescape(s or ""), quote=False)
    s = re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", s)
    s = re.sub(r'&lt;a href="(https?://[^"\s<>]+)"&gt;', r'<a href="\1">', s)
    return s.replace("&lt;/a&gt;", "</a>").strip()


def visible_len(text):
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def footer_lines(tags):
    return [bot.pick(bot.FOOTERS).format(tag=bot.CHANNEL_TAG), tags]


@functools.lru_cache(maxsize=256)
def history(name, days=-1):
    """Продажи на маркете Steam по дням: [(дата, медиана в центах, объём)]."""
    data = get(f"/item/{urllib.parse.quote(name, safe='')}/sales/market"
               f"?maxDays={days}")
    return sorted((p["date"][:10], p["median"], p.get("volume") or 0)
                  for p in data or [] if p.get("median"))


def week_median(name, back=0):
    """Медиана цены за 7 дней (back=7 — за неделю до этого), в центах."""
    hi = time.time() - back * DAY
    vals = [m for d, m, _ in history(name, 21)
            if hi - 7 * DAY <= ts(d + "T00:00:00Z") < hi]
    return statistics.median(vals) if vals else None


# ---------- 📰 новости через Claude ----------

NEWS_SCHEMA = {
    "type": "object",
    "properties": {"important": {"type": "boolean"},
                   "headline": {"type": "string"},
                   "body": {"type": "string"},
                   "meaning": {"type": "string"}},
    "required": ["important", "headline", "body", "meaning"],
    "additionalProperties": False,
}


def ai_ready():
    return NEWS_LIVE and ai.available()


def bb_text(s):
    """BBCode Steam → обычный текст."""
    s = re.sub(r"\[img[^\]]*\].*?\[/img\]", " ", s or "", flags=re.S)
    s = re.sub(r"\[/?[a-zA-Z0-9*]+(=[^\]]*)?\]", " ", s)
    s = re.sub(r"\{STEAM_CLAN_IMAGE\}\S*", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def bb_image(s):
    m = (re.search(r"\[img\]\s*([^\[\s]+)\s*\[/img\]", s or "")
         or re.search(r'\[img src="([^"]+)"', s or "")
         or re.search(r'<img[^>]+src="(https?://[^"]+)"', s or ""))
    if not m:
        return ""
    return m.group(1).replace("{STEAM_CLAN_IMAGE}",
                              "https://clan.fastly.steamstatic.com/images")


def fetch_news(n=6):
    data = bot.http_get_json(NEWS.format(n=n), timeout=20)
    return [{"id": "news_" + str(i.get("gid")), "title": i.get("title") or "",
             "url": i.get("url") or "", "date": i.get("date") or 0,
             "contents": i.get("contents") or "",
             "official": i.get("feedname") == OFFICIAL,
             "source": i.get("feedlabel") or "Steam"}
            for i in (data.get("appnews") or {}).get("newsitems") or []]


def news_post(item):
    """(картинка, подпись), "skip" для мелочи или None, если Claude молчит."""
    kind = ("официальная публикация Facepunch о Rust в Steam" if item["official"]
            else f"статья о Rust ({item['source']})")
    res = ai.ask(f"""Перед тобой {kind}.
Перескажи её для подписчиков своими словами — не переводи дословно.

Верни:
- headline: короткий цепляющий заголовок по сути (до 70 знаков, без эмодзи).
- body: главное для игроков. Для обновления или патча — 3–6 самых заметных
  изменений, каждое строкой с «▫️ », простыми словами: что это значит в
  игре; мелочи объединяй («плюс мелкие фиксы»). Для анонса, девблога или
  короткой статьи — 2–3 коротких абзаца. Не длиннее 650 знаков. Telegram
  HTML. Без ссылок и без упоминания источника — ссылку бот добавит сам.
  Пиши только то, что есть в тексте; не пиши «судя по заголовку»,
  «подробностей нет» — просто не упоминай то, чего не знаешь.
- meaning: 1–2 предложения «что это значит» — для вайпа, фарма, рейдов или
  скинов (новые скины, магазин, Twitch drops). Нечего сказать — пусто.
- important: false, если это мелочь без новой информации (хотфикс в строку,
  напоминание). Иначе true.

Заголовок публикации: {item['title']}
Ссылка: {item['url']}

Текст публикации:
{bb_text(item['contents'])[:12000]}""", NEWS_SCHEMA, effort="medium",
                 system=ai.RUST_STYLE)
    if not res:
        return None
    if not res.get("important"):
        return "skip"
    parts = ["<b>📰 НОВОСТИ RUST</b>",
             f"<b>{html.escape(res['headline'].strip())}</b>", "",
             safe(res["body"])]
    if (res.get("meaning") or "").strip():
        parts += ["", f"💡 <b>Что это значит:</b> {safe(res['meaning'])}"]
    src = "Steam" if item["official"] else html.escape(item["source"])
    parts += ["", f"🔗 <a href=\"{item['url']}\">Первоисточник — {src}</a>",
              ""] + footer_lines("#rust #раст #новости")
    text = "\n".join(parts)
    photo = bb_image(item["contents"]) or bot.NEWS_BANNER
    return (photo if visible_len(text) <= 1024 else ""), text


def post_news(tg, posted, dry=False):
    """Свежие (до 3 дней) новости Facepunch — по одной, от старых к новым."""
    try:
        items = fetch_news(6)
    except Exception as e:
        print("Новости Steam не загрузились:", e)
        return
    fresh = [i for i in items if i["id"] not in posted
             and time.time() - i["date"] < 3 * DAY]
    if not fresh:
        print("Новых официальных новостей нет.")
    for item in sorted(fresh, key=lambda i: i["date"])[-3:]:
        out = news_post(item)
        if out is None:
            return                     # Claude не ответил — повторим позже
        if out == "skip":
            print("Мелкая новость — пропускаем:", item["title"])
            posted.add(item["id"])
            continue
        photo, text = out
        res = tg.send_photo(photo, text) if photo else {}
        if not res.get("ok"):
            res = tg.send_message(text)
        if dry or res.get("ok"):
            posted.add(item["id"])
        time.sleep(2)


# ---------- 🎨 скин дня ----------

SOD_SCHEMA = {
    "type": "object",
    "properties": {"hook": {"type": "string"}, "fact": {"type": "string"},
                   "text": {"type": "string"}},
    "required": ["hook", "fact", "text"],
    "additionalProperties": False,
}


def pick_skin(items, state, today):
    """Ходовой скин прошлых недельных выпусков (вышел больше двух недель
    назад, уже торгуется), не показанный за последние 60 дней."""
    now, seen = time.time(), set(state.get("rsod_seen", [])[-60:])
    pool = [s for s in items if not s["current"] and s["price"] and s["store"]
            and s["sold"] and now - ts(s["start"]) > 14 * DAY
            and s["name"] not in seen]
    pool = sorted(pool, key=lambda s: -s["sold"])[:60]
    return random.Random(today).choice(pool) if pool else None


def compose_skin(s, date):
    h = history(s["name"])
    k = max(1, -(-len(h) // 40))         # ~40 точек на графике
    pts = [(h[i][0], statistics.median(x[1] for x in h[i:i + k]))
           for i in range(0, len(h), k)]
    spark, days = [m for _, m in pts], [d for d, _ in pts]
    roi = (s["price"] / s["store"] - 1) * 100
    usd = lambda c: round(c / 100, 2) if c else None
    back = lambda d: statistics.median(
        [x[1] for x in h if x[0] <= time.strftime(
            "%Y-%m-%d", time.gmtime(time.time() - d * DAY))][-3:] or [0])
    peak = max(pts, key=lambda x: x[1]) if pts else None
    low = min(pts, key=lambda x: x[1]) if pts else None
    facts = {"name": s["name"], "collection": s["collection"] or None,
             "released": s["start"][:10], "store_usd": usd(s["store"]),
             "market_now_usd": usd(s["price"]), "vs_store_pct": round(roi),
             "sold_in_store_estimate": s["sold"],
             "first_week_on_market_usd": usd(statistics.median(
                 x[1] for x in h[:7])) if h else None,
             "peak_usd": usd(peak[1]) if peak else None,
             "peak_date": peak[0] if peak else None,
             "low_usd": usd(low[1]) if low else None,
             "low_date": low[0] if low else None,
             "price_14_days_ago_usd": usd(back(14)),
             "price_30_days_ago_usd": usd(back(30)),
             "days_on_market": len(h)}
    res = ai.ask(f"""Рубрика «Скин дня» в канале @rust_news_Pro. Вот факты о скине:
{json.dumps(facts, ensure_ascii=False)}

Верни:
- hook: первая строка поста до 70 знаков — цепляющая, по фактам (сколько
  стоил в магазине и сколько сейчас, сколько продали). Без эмодзи.
- fact: 1–2 предложения до 160 знаков для картинки — история цены, которой
  нет в цифрах на картинке (там уже есть цена магазина, цена сейчас, % и
  продажи): как цена вела себя после выхода, где был пик и дно, что
  происходит последние 2–4 недели. Простыми словами.
- text: 2–3 коротких предложения до 300 знаков для подписи: что за скин,
  что видно по ценам, есть ли смысл его брать сейчас (без обещаний).
  Только из фактов, без повтора fact.""", SOD_SCHEMA, effort="medium",
                 system=ai.RUST_STYLE) or {}
    m = bot.money
    hook = (res.get("hook") or f"{s['name']}: {m(s['store'])} в магазине → "
            f"{m(s['price'])} сейчас").strip()
    card = os.path.join(tempfile.gettempdir(), "rust_skin.jpg")
    try:
        ok = cards.skin_card(card, date, {
            "name": s["name"], "image": icon(s["icon"]),
            "coll": (f"коллекция {s['collection']}" if s["collection"]
                     else ""),
            "store": m(s["store"]), "store_note": f"вышел {s['week']}",
            "market": m(s["price"]), "roi": pct(roi).replace("−", "-"),
            "roi_up": roi >= 0, "sold": f"~{bot.fmt_num(s['sold'])} шт.",
            "fact": (res.get("fact") or "").strip(), "spark": spark,
            "days": days, "store_cents": s["store"]}, m)
    except Exception as e:
        print("Карточка скина не собралась:", e)
        ok = False
    lines = ["<b>🎨 СКИН ДНЯ</b>", f"<b>{html.escape(hook)}</b>", ""]
    if res.get("text"):
        lines += [safe(res["text"]), ""]
    lines += [f"🛒 В магазине стоил {m(s['store'])} · сейчас {m(s['price'])}"
              f" ({pct(roi)})",
              f"📦 Продано в магазине: ~{bot.fmt_num(s['sold'])} шт.",
              f"🔗 <a href=\"{bot.market_url(s['name'])}\">Смотреть на "
              "маркете</a>", ""] + footer_lines("#rust #раст #скин_дня")
    return "\n".join(lines), (card if ok else "")


def skin_of_day(tg, state, kt):
    items, _ = bot.fetch_store_history(14)
    s = pick_skin(items, state, kt.strftime("%Y-%m-%d"))
    if not s:
        return True
    text, card = compose_skin(s, kt.strftime("%d.%m.%Y"))
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok"):
        res = tg.send_message(text)
    if not res.get("ok"):
        return False
    state["rsod_seen"] = (state.get("rsod_seen", []) + [s["name"]])[-120:]
    return True


# ---------- 🗳 угадай цену ----------

def pick_duel(items, state):
    """Два скина 3–13 недель от выхода, цена от $1 и похожа (±25%), разные
    коллекции, прошлая неделя спокойная (±8%) — подсказок нет."""
    now, used = time.time(), set(state.get("rduel_used", [])[-40:])
    pool = [s for s in items if not s["current"] and s["price"] >= 100
            and 21 * DAY < now - ts(s["start"]) < 91 * DAY
            and s["name"] not in used]
    random.Random(time.strftime("%Y-%W")).shuffle(pool)
    tries = 0
    for a in pool:
        for b in pool:
            if (b is a or (a["collection"] and a["collection"] == b["collection"])
                    or not 0.8 <= a["price"] / b["price"] <= 1.25):
                continue
            tries += 1
            if tries > 12:
                return None
            pa, pb = week_median(a["name"]), week_median(b["name"])
            qa, qb = week_median(a["name"], 7), week_median(b["name"], 7)
            if (pa and pb and qa and qb and abs(pa / qa - 1) <= 0.08
                    and abs(pb / qb - 1) <= 0.08):
                return [dict(a, now=pa), dict(b, now=pb)]
    return None


def compose_duel(pair, date):
    """(подпись, картинка, вопрос опроса, варианты)."""
    sides = [{"name": s["name"], "image": icon(s["icon"]),
              "price": bot.money(s["now"]), "sub": "средняя цена недели"}
             for s in pair]
    card = os.path.join(tempfile.gettempdir(), "rust_duel.jpg")
    try:
        ok = cards.duel_card(card, date, sides,
                             "Какой подорожает сильнее за неделю?",
                             "голосуй в опросе ниже · итог — через 7 дней")
    except Exception as e:
        print("Карточка опроса не собралась:", e)
        ok = False
    text = "\n".join([
        "<b>🗳 УГАДАЙ ЦЕНУ</b>",
        "<b>Два скина, почти одна цена. Какой через неделю будет дороже?</b>",
        "",
        f"🅰️ {html.escape(pair[0]['name'])} — {sides[0]['price']}",
        f"🅱️ {html.escape(pair[1]['name'])} — {sides[1]['price']}", "",
        "Прошлую неделю обе цены почти не двигались — только чутьё. "
        "Голосуй в опросе 👇 Через 7 дней покажем, кто был прав.", ""]
        + footer_lines("#rust #раст #угадай_цену"))
    options = [f"🅰️ {pair[0]['name']}"[:100], f"🅱️ {pair[1]['name']}"[:100]]
    return (text, (card if ok else ""),
            "Какой скин подорожает сильнее за неделю?", options)


def compose_result(old, votes, date):
    """Итог прошлого опроса: средняя цена недели после опроса."""
    res = []
    for d in old["items"]:
        p1 = week_median(d["name"])
        if not p1:
            return None
        res.append((d, p1, (p1 / d["price"] - 1) * 100))
    win = 0 if res[0][2] >= res[1][2] else 1
    sides = [{"name": d["name"], "image": icon(d.get("icon")),
              "price": bot.money(p1), "sub": f"было {bot.money(d['price'])}",
              "value": f"{ch:+.1f}%", "value_up": ch >= 0}
             for d, p1, ch in res]
    total = sum(votes or [])
    share = (f"{round(votes[win] * 100 / total)}% подписчиков угадали"
             if total else "голосов пока мало — дальше будет интереснее")
    card = os.path.join(tempfile.gettempdir(), "rust_duel_result.jpg")
    head = (f"Победил вариант {'AB'[win]}: {res[win][2]:+.1f}% за неделю"
            if res[win][2] >= 0 else
            f"Победил вариант {'AB'[win]}: подешевел меньше")
    try:
        ok = cards.duel_card(card, f"{old['date']} — {date}", sides, head,
                             share, win)
    except Exception as e:
        print("Карточка итога не собралась:", e)
        ok = False
    text = "\n".join([
        "<b>🗳 УГАДАЙ ЦЕНУ · ИТОГ</b>",
        f"<b>Победил {('🅰️', '🅱️')[win]} {html.escape(res[win][0]['name'])}</b>",
        "",
        f"🅰️ {html.escape(res[0][0]['name'])}: {bot.money(res[0][0]['price'])}"
        f" → {bot.money(res[0][1])} ({pct(res[0][2])})",
        f"🅱️ {html.escape(res[1][0]['name'])}: {bot.money(res[1][0]['price'])}"
        f" → {bot.money(res[1][1])} ({pct(res[1][2])})", "",
        f"🗳 {share}.", "", "Новый опрос — следующим постом 👇", ""]
        + footer_lines("#rust #раст #угадай_цену"))
    return text, (card if ok else "")


def duel_round(tg, state, kt):
    """Итог прошлого опроса (если ему неделя) и новый опрос."""
    old = state.get("rduel")
    if old and time.time() - old.get("ts", 0) < 5 * DAY:
        return True
    date = kt.strftime("%d.%m")
    if old:
        votes = None
        if old.get("poll_id"):
            r = tg._post("stopPoll", {"chat_id": tg.chat,
                                      "message_id": old["poll_id"]})
            if r.get("ok") and isinstance(r.get("result"), dict):
                votes = [o.get("voter_count", 0)
                         for o in r["result"].get("options", [])]
        out = compose_result(old, votes, date)
        if out:
            text, card = out
            r = tg.send_photo_file(card, text) if card else {}
            if not r.get("ok"):
                r = tg.send_message(text)
            if not r.get("ok"):
                return False
            time.sleep(2)
        state.pop("rduel", None)
    items, _ = bot.fetch_store_history(14)
    pair = pick_duel(items, state)
    if not pair:
        return True
    text, card, question, options = compose_duel(pair, date)
    r = tg.send_photo_file(card, text) if card else {}
    if not r.get("ok"):
        r = tg.send_message(text)
    if not r.get("ok"):
        return False
    r = tg._post("sendPoll", {
        "chat_id": tg.chat, "question": question, "is_anonymous": "true",
        "options": json.dumps([{"text": o} for o in options],
                              ensure_ascii=False)})
    state["rduel"] = {"date": date, "ts": int(time.time()),
                      "poll_id": (r.get("result") or {}).get("message_id"),
                      "items": [{"name": s["name"], "price": s["now"],
                                 "icon": s["icon"]} for s in pair]}
    state["rduel_used"] = (state.get("rduel_used", [])
                           + [s["name"] for s in pair])[-80:]
    return True


# ---------- расписание и примеры ----------

def tick(tg, state, forced=False):
    """Скин дня — каждый день в SOD_HOUR, «угадай цену» — раз в неделю."""
    kt = bot.kyiv_time()
    today, week = kt.strftime("%Y-%m-%d"), kt.strftime("%G-%V")
    if forced or (LIVE and kt.hour >= SOD_HOUR
                  and state.get("rsod_day") != today):
        try:
            if skin_of_day(tg, state, kt):
                state["rsod_day"] = today
        except Exception as e:
            print("Скин дня не вышел:", e)
    if forced or (LIVE and kt.weekday() == DUEL_DAY and kt.hour >= DUEL_HOUR
                  and state.get("rduel_week") != week):
        try:
            if duel_round(tg, state, kt):
                state["rduel_week"] = week
        except Exception as e:
            print("«Угадай цену» не вышла:", e)


def demo():
    """Примеры новых рубрик в лог (картинки — base64). Ничего не шлёт.
    Итог опроса и отчёт — иллюстрации на прошлых ценах."""
    def show(title, text, card):
        print(f"\n===== ПРИМЕР ({title}, длина {visible_len(text)}) ====="
              f"\n{text}")
        if card:
            cards.dump(card)

    kt = bot.kyiv_time()
    if ai.available():
        for item in sorted(fetch_news(6), key=lambda i: -i["date"])[:3]:
            out = news_post(item)
            if out and out != "skip":
                show(f"новость: {item['title']}", out[1], "")
                print("Картинка новости:", out[0] or "нет — текстом")
                break
            print("Пропущена как мелкая:", item["title"])
    items, _ = bot.fetch_store_history(14)
    s = pick_skin(items, {}, kt.strftime("%Y-%m-%d"))
    if s:
        show("скин дня", *compose_skin(s, kt.strftime("%d.%m.%Y")))
    pair = pick_duel(items, {})
    if pair:
        text, card, q, opts = compose_duel(pair, kt.strftime("%d.%m"))
        show("угадай цену", f"{text}\n[опрос] {q} — {' / '.join(opts)}", card)
        old = {"date": "01.10", "items": [
            {"name": p["name"], "icon": p["icon"],
             "price": week_median(p["name"], 7) or p["now"]} for p in pair]}
        out = compose_result(old, [31, 19], kt.strftime("%d.%m"))
        if out:
            show("угадай цену · итог (иллюстрация)", *out)
    import invest
    done = sorted((x for x in invest.get("/store")
                   if x.get("start") and x.get("end")),
                  key=lambda x: x["start"], reverse=True)
    if len(done) > 1:
        old = done[1]          # позапрошлый: первая неделя торгов прошла
        rot = invest.get(f"/store/{old['id']}?currency=USD")
        its = [i for i in rot.get("items") or []
               if (i.get("storePriceUsd") or i.get("storePrice"))
               and not i.get("isPermanent")][:6]
        codes = ["buy", "think", "no"]
        fake = {"start": old["start"], "items": [
            {"name": i["name"], "v": codes[k % 3], "net": None, "n10": None,
             "store": i.get("storePriceUsd") or i["storePrice"],
             "icon": i.get("iconUrl") or ""} for k, i in enumerate(its)]}
        out = invest.compose_report(fake)
        if out:
            show("мы советовали (иллюстрация, советы условные)", *out)
