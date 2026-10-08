# -*- coding: utf-8 -*-
"""
🎮 Киберспорт CS2 для @cs2_me: новости HLTV (трансферы, итоги топ-турниров,
громкие истории) — коротко, по-русски, за пару минут после выхода.

Claude оценивает важность каждой новости для русскоязычных зрителей CS2:
важные (от MIN_SCORE) — сразу отдельным постом (не больше MAX_DAY в день,
ночью не публикуем), остальные заметные — вечером одним постом «Киберспорт
за день». Картинку даёт предпросмотр ссылки HLTV — чужие фото не
перезаливаем. Только факты из заголовка и описания новости.
"""
import html
import re
import time
import urllib.request
from email.utils import parsedate_to_datetime

import cs2_ai as ai
import rust_digest_bot as bot

RSS = "https://www.hltv.org/rss/news"
WORKER = "https://rust-votes.twithgfaw.workers.dev/hltv"  # если HLTV не пускает
LIVE = True              # по расписанию (одобрено 08.10)
MIN_SCORE = 7            # с какой важности — отдельным постом
DIGEST_SCORE = 4         # с какой — в вечерний дайджест
MAX_DAY = 6              # отдельных постов в день
MAX_RUN = 2              # за один запуск
QUIET = (1, 8)           # по Киеву: ночью копим, утром — в дайджест
DIGEST_HOUR = 21
TAGS = "#cs2 #кс2 #киберспорт"

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "score": {"type": "integer"},
                       "headline": {"type": "string"},
                       "text": {"type": "string"}},
        "required": ["id", "score", "headline", "text"],
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}


def fetch():
    """Новости HLTV: [{id, title, desc, link, ts}] — новые первыми."""
    page = ""
    for url in (RSS, WORKER):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "Chrome/126 Safari/537.36"})
            with urllib.request.urlopen(req, timeout=20) as r:
                page = r.read().decode("utf-8", "replace")
            if "<item>" in page:
                break
        except Exception as e:
            print("HLTV не ответил:", url, e)

    def get(block, tag):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S)
        return html.unescape(m.group(1)).strip() if m else ""

    out = []
    for block in re.findall(r"<item>(.*?)</item>", page, re.S):
        guid, link = get(block, "guid"), get(block, "link")
        try:
            ts = parsedate_to_datetime(get(block, "pubDate")).timestamp()
        except Exception:
            ts = time.time()
        if guid and link:
            out.append({"id": guid, "title": get(block, "title"),
                        "desc": get(block, "description"), "link": link,
                        "ts": ts})
    return out


def rate(items):
    """Claude: важность 1–10, заголовок и 1–2 предложения по-русски."""
    lines = "\n".join(f"- id={i['id']} | {i['title']} | {i['desc']}"
                      for i in items)
    res = ai.ask(f"""Новые новости HLTV о профессиональном CS2:
{lines}

Для каждой новости верни:
- score: важность 1–10 для русскоязычных зрителей CS2. 8–10: итоги и
  громкие матчи топ-турниров (мейджор, IEM, BLAST, ESL Pro League — плей-офф
  и финалы), трансферы и замены в топ-командах, громкие скандалы, новости
  NAVI, Spirit, Virtus.pro, FaZe, Vitality, MOUZ, G2, Falcons, The MongolZ
  и топ-игроков (s1mple, donk, m0NESY, ZywOo и т.п.). 5–7: заметные
  результаты, анонсы турниров, слухи о трансферах. 1–4: интервью, тир-2,
  мелкие объявления, подборки хайлайтов.
- headline: заголовок по-русски до 90 знаков, без эмодзи. Команды, игроков
  и турниры — как в оригинале (латиницей).
- text: 1–2 коротких предложения до 220 знаков — суть и почему это важно.
  Только факты из заголовка и описания. Слухи — «по данным источников».
  Ничего не додумывай: ни счёта, ни дат, если их нет в тексте.""",
                 SCHEMA, effort="low")
    if not res:
        return None
    known = {i["id"]: i for i in items}
    return [dict(known[r["id"]], **r) for r in res.get("items", [])
            if r.get("id") in known]


def compose(it, footer):
    return "\n".join([
        "<b>🎮 КИБЕРСПОРТ</b>",
        f"<b>{html.escape(it['headline'].strip())}</b>", "",
        html.escape(it["text"].strip()), "",
        f"🔗 <a href=\"{it['link']}\">Подробнее — HLTV</a>", "",
        footer, TAGS])


def compose_digest(items, footer, date):
    lines = [f"<b>🎮 КИБЕРСПОРТ ЗА ДЕНЬ</b> · {date}", ""]
    for it in items[:8]:
        lines.append(f"▫️ <a href=\"{it['link']}\">"
                     f"{html.escape(it['headline'].strip())}</a>")
    lines += ["", "Всё самое важное — отдельными постами в течение дня ⚡",
              "", footer, TAGS]
    return "\n".join(lines)


def tick(tg, state, footer, forced=False):
    """Новые новости HLTV: важные — сразу, остальные — в вечерний дайджест."""
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    seen = state.setdefault("hltv_seen", [])
    items = fetch()
    if not items:
        return
    if not seen and not forced:              # первый запуск — без завала
        state["hltv_seen"] = [i["id"] for i in items]
        print("HLTV: запомнил текущие новости, дальше — только новые.")
        return
    fresh = [i for i in items if i["id"] not in seen
             and time.time() - i["ts"] < 12 * 3600]
    if not fresh:
        print("HLTV: новых новостей нет.")
    elif LIVE or forced:
        rated = rate(fresh[:10])
        if rated is None:
            return                            # Claude не ответил — позже
        if state.get("hltv_day") != today:
            state["hltv_day"], state["hltv_count"] = today, 0
        quiet = QUIET[0] <= kt.hour < QUIET[1] and not forced
        sent = 0
        for it in sorted(rated, key=lambda r: -r["score"]):
            seen.append(it["id"])
            if (it["score"] >= MIN_SCORE and not quiet and sent < MAX_RUN
                    and state["hltv_count"] < MAX_DAY):
                res = tg.send_message(compose(it, footer))
                if res.get("ok"):
                    sent += 1
                    state["hltv_count"] += 1
                    time.sleep(2)
                    continue
            if it["score"] >= DIGEST_SCORE:
                state.setdefault("hltv_digest", []).append(
                    {"headline": it["headline"], "link": it["link"],
                     "score": it["score"]})
        state["hltv_seen"] = seen[-300:]
    digest = state.get("hltv_digest", [])
    if (digest and (LIVE or forced) and kt.hour >= DIGEST_HOUR
            and state.get("hltv_digest_day") != today):
        top = sorted(digest, key=lambda d: -d["score"])
        if tg.send_message(compose_digest(top, footer,
                                          kt.strftime("%d.%m"))).get("ok"):
            state["hltv_digest"], state["hltv_digest_day"] = [], today


def demo(footer):
    """Пример: оценки свежих новостей и посты — в лог."""
    items = fetch()
    print(f"HLTV: {len(items)} новостей в ленте")
    rated = rate(items[:10]) or []
    for it in sorted(rated, key=lambda r: -r["score"]):
        print(f"[{it['score']}] {it['title']}")
    best = [r for r in sorted(rated, key=lambda r: -r["score"])
            if r["score"] >= MIN_SCORE]
    for it in best[:2]:
        print("\n===== ПРИМЕР (киберспорт) =====\n" + compose(it, footer))
    rest = [r for r in rated if DIGEST_SCORE <= r["score"]]
    if rest:
        print("\n===== ПРИМЕР (киберспорт за день) =====\n"
              + compose_digest(sorted(rest, key=lambda d: -d["score"]), footer,
                               bot.kyiv_time().strftime("%d.%m")))
