# -*- coding: utf-8 -*-
"""
Рубрика «💬 Сообщество CS2» — самое обсуждаемое из X за сутки.

1. Список проверенных аккаунтов (датамайнеры, новости, площадки) —
   ACCOUNTS; несуществующие отсеиваются сами при первой проверке.
2. Три раза в день берём их посты за последние сутки (X API v2) и считаем
   живость: лайки, репосты, ответы — относительно обычного для аккаунта.
3. Claude смотрит топ и решает, что интересно, проверяет, не старьё ли,
   и пишет пост. Утечки — с пометкой «⚠️ не подтверждено».
X API платный (~$0.005 за прочитанный пост, повторное чтение того же поста
в течение суток не тарифицируется).
"""
import html
import json
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import cs2_ai as ai
import rust_digest_bot as bot

RUBRIC = "💬 СООБЩЕСТВО CS2"
# Кандидаты; бот сам проверит, какие существуют (users/by).
ACCOUNTS = [
    "gabefollower", "aquaismissing", "ThourCS2",     # датамайнеры
    "SteamDB",                                       # Steam-изменения
    "HLTVorg", "ESLCS", "BLASTPremier", "PGLEsports",  # киберспорт
    "skinport", "pricempire",                        # рынок скинов
]
SLOTS = (13, 17, 21)       # по Киеву
MIN_ENGAGE = 50            # минимум лайков+репостов+ответов для поста


def x_get(token, path, params):
    url = f"https://api.x.com/2/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "User-Agent": bot.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def resolve(token, state):
    """Ник → id для существующих аккаунтов (кэш в state)."""
    ids = state.setdefault("comm_ids", {})
    need = [a for a in ACCOUNTS if a.lower() not in ids]
    if need:
        data = x_get(token, "users/by", {"usernames": ",".join(need),
                                         "user.fields": "public_metrics"})
        for u in data.get("data") or []:
            ids[u["username"].lower()] = {
                "id": u["id"], "name": u["username"],
                "followers": u.get("public_metrics", {}).get(
                    "followers_count", 0)}
        for e in data.get("errors") or []:
            print("X: аккаунт не найден:", e.get("value"))
            ids[(e.get("value") or "").lower()] = None
    return {k: v for k, v in ids.items() if v}


def recent(token, user, hours=24):
    """Посты аккаунта за последние hours часов (без ответов и ретвитов)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    data = x_get(token, f"users/{user['id']}/tweets", {
        "max_results": "10", "exclude": "replies,retweets",
        "start_time": since,
        "tweet.fields": "created_at,public_metrics,entities,attachments",
        "expansions": "attachments.media_keys",
        "media.fields": "type,url,preview_image_url,variants"})
    media = {m["media_key"]: m
             for m in data.get("includes", {}).get("media", [])}
    out = []
    for t in data.get("data") or []:
        pm = t.get("public_metrics") or {}
        keys = t.get("attachments", {}).get("media_keys", [])
        out.append({"id": t["id"], "author": user["name"],
                    "followers": user["followers"],
                    "text": t.get("text", ""), "created": t.get("created_at"),
                    "likes": pm.get("like_count", 0),
                    "reposts": pm.get("retweet_count", 0),
                    "replies": pm.get("reply_count", 0),
                    "quotes": pm.get("quote_count", 0),
                    "urls": t.get("entities", {}).get("urls", []),
                    "media": [media[k] for k in keys if k in media]})
    return out


def engage(p):
    return p["likes"] + 2 * p["reposts"] + p["replies"] + p["quotes"]


def gather(token, state):
    """Все свежие посты из списка, с оценкой «живости»."""
    users = resolve(token, state)
    posts = []
    for u in users.values():
        try:
            posts += recent(token, u)
        except Exception as e:
            print("X: не получили посты", u["name"], e)
        time.sleep(1)
    # живость относительно аудитории аккаунта: большой аккаунт набирает
    # лайки легче, поэтому делим на корень из подписчиков
    for p in posts:
        p["score"] = engage(p) / max(1.0, (p["followers"] or 1) ** 0.5) * 100
    return posts


PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "publish": {"type": "boolean"},
        "post_id": {"type": "string"},
        "unconfirmed": {"type": "boolean"},
        "headline": {"type": "string"},
        "text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["publish", "post_id", "unconfirmed", "headline", "text",
                 "reason"],
    "additionalProperties": False,
}


def choose(posts, posted):
    """Claude выбирает один пост из топа (или ничего) и пишет текст."""
    fresh = [p for p in posts if p["id"] not in posted
             and engage(p) >= MIN_ENGAGE]
    fresh.sort(key=lambda p: p["score"], reverse=True)
    top = fresh[:8]
    if not top:
        return None, None
    brief = [{"post_id": p["id"], "author": p["author"],
              "followers": p["followers"], "created": p["created"],
              "likes": p["likes"], "reposts": p["reposts"],
              "replies": p["replies"], "text": p["text"][:700],
              "has_media": bool(p["media"])} for p in top]
    prompt = f"""Рубрика «Сообщество CS2»: самое интересное и обсуждаемое из X за сутки.
Ниже — свежие посты проверенных аккаунтов с реакцией. Выбери ОДИН, который
стоит показать подписчикам (важные находки и изменения в игре, необычные
истории со скинами и рынком, находки датамайнеров, крупные события
сообщества), или ничего, если всё проходное. Не бери рекламу, конкурсы,
розыгрыши и мелочь. Старое и уже известное не бери. Только про CS2:
у SteamDB и датамайнеров бывают посты про другие игры — их пропускай.

Если это утечка/датамайн/слух — unconfirmed=true (пометим «не подтверждено»).
headline — заголовок по-русски до 70 знаков без эмодзи.
text — пост до 500 знаков, Telegram HTML, своими словами (не дословный
перевод), с контекстом «почему это интересно». Не выдумывай деталей,
которых нет в посте.
reason — одна строка для журнала. Если ничего не подходит — publish=false,
остальные поля пустые.

Посты: {json.dumps(brief, ensure_ascii=False)}"""
    res = ai.ask(prompt, PICK_SCHEMA, effort="medium")
    if not res or not res.get("publish"):
        print("Сообщество: Claude ничего не выбрал —",
              (res or {}).get("reason"))
        return None, res
    p = next((x for x in top if x["id"] == res.get("post_id")), None)
    return p, res


def compose(p, res, safe_html):
    lines = [f"<b>{RUBRIC}</b>", f"<b>{html.escape(res['headline'])}</b>", ""]
    if res.get("unconfirmed"):
        lines += ["⚠️ <i>Не подтверждено: это утечка или слух, официально "
                  "Valve этого не объявляла</i>", ""]
    lines += [safe_html(res["text"]), "",
              f"❤️ {bot.fmt_num(p['likes'])} · 🔁 {bot.fmt_num(p['reposts'])}"
              f" · 💬 {bot.fmt_num(p['replies'])}",
              f"🐦 <a href=\"https://x.com/{p['author']}/status/{p['id']}\">"
              f"Источник: @{html.escape(p['author'])}</a>", "",
              "#cs2 #сообщество_cs2"]
    return "\n".join(lines)
