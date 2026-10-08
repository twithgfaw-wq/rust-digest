# -*- coding: utf-8 -*-
"""
Рубрика «💬 Сообщество Rust» — самые популярные посты про Rust из X.

1. Аккаунты: Facepunch и разработчики, известные стримеры и ютуберы Rust,
   сервера и сообщества (ACCOUNTS). Берём только те, у кого в имени или
   описании есть Rust/Facepunch — так не зацепим однофамильцев.
2. Плюс поиск X по #playrust / Facepunch / «rust wipe» — самое обсуждаемое
   за сутки (sort_order=relevancy).
3. «Живость» поста — лайки, репосты, ответы относительно аудитории; Claude
   выбирает один пост про игру Rust (не про язык программирования) и
   пересказывает по-русски. Утечки — «⚠️ не подтверждено».
X API платный (~$0.005 за прочитанный пост), поэтому два слота в день.
"""
import html
import json
import time
from datetime import datetime, timedelta, timezone

import cs2_ai as ai
import cs2_community as cc
import rust_digest_bot as bot

LIVE = False               # по расписанию — после одобрения примера
RUBRIC = "💬 СООБЩЕСТВО RUST"
ACCOUNTS = [
    "Facepunch", "garrynewman", "Helk",                   # разработчики
    "HedgesnVideos",                                      # скины и магазин
    "hJune", "Spoonkid", "Blooprint", "willjum", "Stevious",
    "shadowfrax", "Trausi", "Posty", "Welyn",             # стримеры, ютуберы
    "Rustafied", "RustoriaCo", "RustLabs",                # сервера, базы
]
QUERY = ("(#playrust OR #rustgame OR facepunch OR \"rust wipe\" OR "
         "\"rust devblog\" OR \"rust update\") -is:retweet -is:reply")
SLOTS = (14, 20)           # по Киеву
MIN_ENGAGE = 25            # минимум «живости» (лайки + 2×репосты + ответы)
MIN_FOLLOWERS = 2000       # мелкие однофамильцы из списка не нужны
TAGS = "#rust #раст #сообщество"


def resolve(token, state):
    """Ник → id для аккаунтов из списка (от MIN_FOLLOWERS подписчиков).
    Посты не про игру Rust отсеет Claude при выборе."""
    ids = state.setdefault("rcomm_ids", {})
    need = [a for a in ACCOUNTS if a.lower() not in ids]
    if need:
        data = cc.x_get(token, "users/by", {
            "usernames": ",".join(need), "user.fields": "public_metrics"})
        for u in data.get("data") or []:
            fol = u.get("public_metrics", {}).get("followers_count", 0)
            ids[u["username"].lower()] = ({
                "id": u["id"], "name": u["username"], "followers": fol}
                if fol >= MIN_FOLLOWERS else None)
        for e in data.get("errors") or []:
            ids[(e.get("value") or "").lower()] = None
    return {k: v for k, v in ids.items() if v}


def search(token, hours=24, n=20):
    """Самое обсуждаемое по запросу QUERY за сутки."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    data = cc.x_get(token, "tweets/search/recent", {
        "query": QUERY, "max_results": str(n), "sort_order": "relevancy",
        "start_time": since,
        "tweet.fields": "created_at,public_metrics,entities,attachments,"
                        "author_id,lang",
        "expansions": "attachments.media_keys,author_id",
        "user.fields": "public_metrics",
        "media.fields": "type,url,preview_image_url,variants"})
    inc = data.get("includes", {})
    media = {m["media_key"]: m for m in inc.get("media", [])}
    users = {u["id"]: u for u in inc.get("users", [])}
    out = []
    for t in data.get("data") or []:
        pm, u = t.get("public_metrics") or {}, users.get(t.get("author_id"), {})
        keys = t.get("attachments", {}).get("media_keys", [])
        out.append({"id": t["id"], "author": u.get("username", ""),
                    "followers": (u.get("public_metrics") or {}).get(
                        "followers_count", 0),
                    "text": t.get("text", ""), "created": t.get("created_at"),
                    "likes": pm.get("like_count", 0),
                    "reposts": pm.get("retweet_count", 0),
                    "replies": pm.get("reply_count", 0),
                    "quotes": pm.get("quote_count", 0),
                    "urls": t.get("entities", {}).get("urls", []),
                    "media": [media[k] for k in keys if k in media]})
    return out


def gather(token, state):
    posts = []
    for u in resolve(token, state).values():
        try:
            posts += cc.recent(token, u)
        except Exception as e:
            print("X: не получили посты", u["name"], e)
        time.sleep(1)
    try:
        posts += search(token)
    except Exception as e:
        print("X: поиск не удался:", e)
    seen, uniq = set(), []
    for p in posts:
        if p["id"] not in seen and p["author"]:
            seen.add(p["id"])
            p["score"] = (cc.engage(p) / max(1.0, (p["followers"] or 1) ** 0.5)
                          * 100)
            uniq.append(p)
    return uniq


def choose(posts, posted):
    fresh = [p for p in posts if p["id"] not in posted
             and cc.engage(p) >= MIN_ENGAGE]
    # «очень популярное»: сначала по абсолютным реакциям, потом по живости
    fresh.sort(key=lambda p: (cc.engage(p), p["score"]), reverse=True)
    top = fresh[:10]
    if not top:
        return None, None
    brief = [{"post_id": p["id"], "author": p["author"],
              "followers": p["followers"], "created": p["created"],
              "likes": p["likes"], "reposts": p["reposts"],
              "replies": p["replies"], "text": p["text"][:700],
              "has_media": bool(p["media"])} for p in top]
    res = ai.ask(f"""Рубрика «Сообщество Rust»: самое популярное и обсуждаемое про игру Rust
(Facepunch) в X за сутки. Ниже — свежие посты с реакциями. Выбери ОДИН,
который стоит показать подписчикам: громкие моменты и клипы, рейды и
истории с серверов, тизеры и слова разработчиков, находки и утечки,
истории со скинами и рынком, крупные события сообщества. Или ничего, если
всё проходное.
Важно: «Rust» — это ещё и язык программирования; такие посты пропускай.
Не бери рекламу, розыгрыши, конкурсы, ставки, продажу аккаунтов и мелочь.
Старое и уже известное не бери.

Если это утечка/слух — unconfirmed=true (пометим «не подтверждено»).
headline — заголовок по-русски до 70 знаков без эмодзи.
text — пост до 450 знаков, Telegram HTML, своими словами (не дословный
перевод), с контекстом «почему это интересно». Не выдумывай деталей.
reason — одна строка для журнала. Если ничего не подходит — publish=false,
остальные поля пустые.

Посты: {json.dumps(brief, ensure_ascii=False)}""", cc.PICK_SCHEMA,
                 effort="medium", system=ai.RUST_STYLE)
    if not res or not res.get("publish"):
        print("Сообщество Rust: Claude ничего не выбрал —",
              (res or {}).get("reason"))
        return None, res
    return next((x for x in top if x["id"] == res.get("post_id")), None), res


def compose(p, res, safe_html, footer):
    lines = [f"<b>{RUBRIC}</b>", f"<b>{html.escape(res['headline'])}</b>", ""]
    if res.get("unconfirmed"):
        lines += ["⚠️ <i>Не подтверждено: это утечка или слух, Facepunch "
                  "официально этого не объявляли</i>", ""]
    lines += [safe_html(res["text"]), "",
              f"❤️ {bot.fmt_num(p['likes'])} · 🔁 {bot.fmt_num(p['reposts'])}"
              f" · 💬 {bot.fmt_num(p['replies'])}",
              f"🐦 <a href=\"https://x.com/{p['author']}/status/{p['id']}\">"
              f"Источник: @{html.escape(p['author'])}</a>", "", footer, TAGS]
    return "\n".join(lines)


def post_with_media(tg, p, text):
    kind, url, preview = bot.x_media(p)
    res = {}
    if kind == "video" and url:
        res = tg._post("sendVideo", {
            "chat_id": tg.chat, "video": url, "caption": text,
            "parse_mode": "HTML", "supports_streaming": "true"})
    image = url if kind == "photo" else preview
    if not res.get("ok") and image:
        res = tg.send_photo(image, text)
    if not res.get("ok"):
        res = tg.send_message(text)
    return res


def tick(tg, state, safe_html, footer, forced=False):
    """В каждый слот — самый популярный пост сообщества (если есть)."""
    import os
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token or not ai.available():
        return
    kt = bot.kyiv_time()
    hours = [h for h in SLOTS if kt.hour >= h]
    slot = f"{kt:%Y-%m-%d}-{hours[-1]}" if hours else None
    if not forced and (not LIVE or not slot
                       or state.get("rcomm_slot") == slot):
        return
    if not forced:
        state["rcomm_slot"] = slot      # одна попытка на слот — экономим X API
    p, res = choose(gather(token, state), set(state.get("rcomm_posted", [])))
    if p and post_with_media(tg, p, compose(p, res, safe_html, footer)).get("ok"):
        state["rcomm_posted"] = (state.get("rcomm_posted", []) + [p["id"]])[-300:]


def demo(safe_html, footer):
    import os
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        print("Нет X_BEARER_TOKEN — пример сообщества Rust пропущен.")
        return
    state = {}
    posts = gather(token, state)
    print("Сообщество Rust: аккаунты —",
          ", ".join(v["name"] for v in state.get("rcomm_ids", {}).values()
                    if v), f"· постов: {len(posts)}")
    for q in sorted(posts, key=lambda q: -cc.engage(q))[:8]:
        print(f"  @{q['author']}: {cc.engage(q)} · {q['text'][:90]!r}")
    p, res = choose(posts, set())
    if p:
        kind, url, _ = bot.x_media(p)
        print(f"\n===== ПРИМЕР (сообщество Rust, медиа: {kind or 'нет'}) ====="
              f"\n{compose(p, res, safe_html, footer)}")
