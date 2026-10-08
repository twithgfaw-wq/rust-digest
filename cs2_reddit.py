# -*- coding: utf-8 -*-
"""
📣 «Лучшее с Reddit» для @cs2_me — раз в день самая интересная история из
r/GlobalOffensive: находка, изменение в игре, громкий момент, история со
скинами. Топ дня берём из RSS (JSON Reddit закрыт для GitHub), Claude
выбирает один пост и пересказывает по-русски — только то, что в посте.
"""
import html
import json
import re
import urllib.request

import cs2_ai as ai
import rust_digest_bot as bot

LIVE = False               # по расписанию — после одобрения примера
HOUR = 14                  # по Киеву, раз в день
RSS = "https://www.reddit.com/r/GlobalOffensive/top/.rss?t=day&limit=15"
TAGS = "#cs2 #кс2 #reddit"

SCHEMA = {
    "type": "object",
    "properties": {"publish": {"type": "boolean"},
                   "id": {"type": "string"},
                   "headline": {"type": "string"},
                   "text": {"type": "string"},
                   "reason": {"type": "string"}},
    "required": ["publish", "id", "headline", "text", "reason"],
    "additionalProperties": False,
}


def fetch():
    """Топ дня r/GlobalOffensive: [{id, rank, title, text, author, link, image}]."""
    req = urllib.request.Request(RSS, headers={"User-Agent": bot.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        feed = r.read().decode("utf-8", "replace")
    out = []
    for rank, entry in enumerate(re.findall(r"<entry>(.*?)</entry>", feed,
                                            re.S), 1):
        get = lambda pat: (re.search(pat, entry, re.S) or [None, ""])[1]
        content = html.unescape(get(r"<content[^>]*>(.*?)</content>"))
        link = get(r'<link href="([^"]+)"')
        pid = re.search(r"/comments/([a-z0-9]+)/", link)
        if not pid:
            continue
        img = (re.search(r'href="(https://i\.redd\.it/[^"]+)"', content)
               or re.search(r'<img src="https://preview\.redd\.it/([^"?]+)',
                            content))
        image = ""
        if img:
            image = (img.group(1) if img.group(1).startswith("http")
                     else "https://i.redd.it/" + img.group(1))
        body = re.sub(r"\s+", " ", html.unescape(re.sub(
            r"<[^>]+>", " ", re.sub(r"<table.*?</table>", " ", content,
                                    flags=re.S)))).strip()
        body = re.sub(r"submitted by /u/\S+ \[link\] \[comments\]", "",
                      body).strip()
        out.append({"id": pid.group(1), "rank": rank,
                    "title": html.unescape(get(r"<title>(.*?)</title>")),
                    "text": body[:700],
                    "author": get(r"<name>/u/(.*?)</name>"),
                    "link": link, "image": html.unescape(image)})
    return out


def choose(posts, posted):
    fresh = [p for p in posts if p["id"] not in posted][:12]
    if not fresh:
        return None, None
    brief = [{"id": p["id"], "rank": p["rank"], "title": p["title"],
              "text": p["text"], "has_image": bool(p["image"])}
             for p in fresh]
    res = ai.ask(f"""Рубрика «Лучшее с Reddit» в канале @cs2_me: раз в день — самая интересная
история из r/GlobalOffensive (rank 1 — самый популярный пост дня).
Выбери ОДИН пост, который интереснее всего русскоязычным игрокам CS2:
находки и баги, изменения в игре, необычные моменты, истории со скинами и
рынком, заметные новости сообщества. Мемы — только если смешно и понятно
без контекста. Не бери рекламу, розыгрыши, жалобы «забанили меня»,
вопросы новичков и мелочь. Если всё проходное — publish=false.

headline — заголовок по-русски до 70 знаков без эмодзи.
text — 1–3 коротких предложения до 350 знаков, Telegram HTML: суть и почему
это интересно. Только то, что есть в посте; утверждения автора — «по
словам автора». Ничего не додумывай.
reason — одна строка для журнала.

Посты: {json.dumps(brief, ensure_ascii=False)}""", SCHEMA, effort="medium")
    if not res or not res.get("publish"):
        print("Reddit CS2: Claude ничего не выбрал —", (res or {}).get("reason"))
        return None, res
    return next((p for p in fresh if p["id"] == res.get("id")), None), res


def compose(p, res, safe_html, footer):
    top = "🔝 топ дня" if p["rank"] <= 3 else f"№{p['rank']} в топе дня"
    return "\n".join([
        "<b>📣 ЛУЧШЕЕ С REDDIT</b>",
        f"<b>{html.escape(res['headline'].strip())}</b>", "",
        safe_html(res["text"]), "",
        f"👤 u/{html.escape(p['author'])} · r/GlobalOffensive · {top}",
        f"💬 <a href=\"{p['link']}\">Обсуждение на Reddit</a>", "",
        footer, TAGS])


def tick(tg, state, safe_html, footer, forced=False):
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if not forced and not (LIVE and kt.hour >= HOUR
                           and state.get("reddit_day") != today):
        return
    if not ai.available():
        return
    try:
        posts = fetch()
    except Exception as e:
        print("Reddit CS2 не загрузился:", e)
        return
    p, res = choose(posts, set(state.get("reddit_posted", [])))
    state["reddit_day"] = today         # одна попытка в день
    if not p:
        return
    text = compose(p, res, safe_html, footer)
    out = tg.send_photo(p["image"], text) if p["image"] else {}
    if not out.get("ok"):
        out = tg.send_message(text)
    if out.get("ok"):
        state["reddit_posted"] = (state.get("reddit_posted", []) + [p["id"]])[-200:]


def demo(safe_html, footer):
    posts = fetch()
    print(f"Reddit CS2: {len(posts)} постов в топе дня")
    for p in posts[:8]:
        print(f"  #{p['rank']} {'🖼' if p['image'] else '  '} {p['title'][:90]}")
    p, res = choose(posts, set())
    if p:
        print(f"\n===== ПРИМЕР (лучшее с Reddit, картинка: "
              f"{p['image'] or 'нет'}) =====\n{compose(p, res, safe_html, footer)}")
