#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Digest Bot — новости Counter-Strike 2 в Telegram-канал @cs2_me.

Что делает за один прогон (раз в 30 минут через GitHub Actions):
  1. Официальные новости CS2 из Steam: патчноуты (переведённый список
     изменений по разделам) и анонсы Valve (картинка, перевод, ссылка).
  2. Посты официального @CounterStrike из X — если задан X_BEARER_TOKEN.
  3. Онлайн CS2: раз в день вечером сводка, рекорд месяца — сразу.
  4. Цены: раз в день — что подорожало и подешевело за неделю (продажи
     на Skinport, иконки из Steam) — пост с картинкой-отчётом.

Общие части (Telegram, перевод, подбор фраз) берём у Rust-бота.

Запуск: python cs2_bot.py
  CS2_DRY=1    — ничего не отправлять, только лог;
  CS2_PRICES=1 — сводку цен выложить сейчас, не дожидаясь вечера;
  CS2_DEMO=1   — показать в логе, как выглядели бы посты (последний патч,
                 последний анонс, последний пост из X, онлайн, цены),
                 и проверить права бота в канале. Ничего не отправляет.
"""
import html
import io
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import cs2_ai as ai
import cs2_invest as invest
import rust_digest_bot as bot

APPID = 730
STATE_FILE = "cs2_state.json"
CHANNEL_TAG = "@cs2_me"          # подпись в футере (обновляется в main)
HEADER = "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg"
NEWS_URL = "https://store.steampowered.com/news/app/730/view/{gid}"
X_NAME = "CounterStrike"
ONLINE_POST_HOUR = 20            # ежедневная сводка онлайна — вечером по Киеву
TAGS = "#cs2 #кс2 #counterstrike"
RUBRIC_NEWS = "📰 НОВОСТИ CS2"   # у каждой рубрики своя узнаваемая шапка
AI_NEWS_LIVE = False             # пересказ от Claude — после одобрения примера

# ---------- стиль постов (как в Rust-канале) ----------

FOOTERS = [
    "👉 Подписывайся на {tag}",
    "🔔 Больше CS2 — в {tag}",
    "📢 Подписывайся: {tag}",
    "🎯 Свежий CS2 каждый день — {tag}",
    "📡 Не пропусти важное: {tag}",
    "🔥 {tag} — CS2 без воды",
    "👀 Следи за CS2 вместе с {tag}",
    "⚡️ Всё самое свежее по CS2 — {tag}",
    "💣 Твой канал про CS2 — {tag}",
    "📌 Сохрани себе {tag}",
]
PATCH_HOOKS = [
    "🛠 VALVE ВЫКАТИЛИ ОБНОВЛЕНИЕ CS2",
    "🔧 Новый патч CS2 — что поменяли",
    "📝 Патчноут CS2: коротко о главном",
    "⚙️ Valve снова что-то подкрутили в CS2",
    "🆕 Свежее обновление Counter-Strike 2",
    "🧰 CS2 обновился — разбираем изменения",
    "👀 Что нового в CS2 после патча",
    "💣 Обнова CS2 уже в игре",
    "🛎 Valve обновили CS2 — список изменений",
    "📦 Патч CS2 подъехал",
]
BLOG_HOOKS = [
    "📢 ВАЖНОЕ ОТ VALVE",
    "🗞 Новости Counter-Strike 2 от Valve",
    "🔥 Valve анонсировали новое для CS2",
    "👀 Свежий анонс CS2 — смотрим",
    "📣 Valve вышли на связь",
    "⚡️ Большая новость для CS2",
    "🎉 В CS2 кое-что новое",
    "🚨 АНОНС CS2",
]
NEWS_OUTROS = [
    "Что думаете — к лучшему? 🤔", "Ставь 🔥, если ждал",
    "Ставь 👍, если полезно", "Берём на заметку 📌", "Valve, мы следим 👀",
    "Неплохо, неплохо 😎", "Уже опробовал? 🎮", "", "",
]
X_HOOKS = [
    "🐦 Counter-Strike написали в X",
    "🗞 Новости из X от Valve",
    "📲 Свежий пост официального CS2",
    "👀 Что пишет официальный аккаунт CS2",
    "📣 CS2 в X: свежак",
]
ONLINE_HOOKS = [
    "📊 ОНЛАЙН CS2 ПРЯМО СЕЙЧАС",
    "👥 Сколько людей сейчас в CS2",
    "📈 Сводка онлайна CS2 за сегодня",
    "🔢 Онлайн Counter-Strike 2: свежие цифры",
    "⚡️ CS2 сегодня: сколько игроков в сети",
    "🛰 Мониторинг онлайна CS2",
]
RECORD_HOOKS = [
    "🚀 РЕКОРД ОНЛАЙНА CS2 ЗА МЕСЯЦ!",
    "🔥 CS2 обновил максимум онлайна за месяц",
    "📈 Новый пик онлайна в CS2",
    "🤯 Столько игроков в CS2 не было весь месяц",
]
ONLINE_OUTROS = [
    "А ты сейчас в игре? 🎮", "Сервера не пустуют 💪",
    "Ставь 🔥, если тоже катаешь прямо сейчас",
    "Самое время зайти в матч 😏", "", "",
]
SECTIONS = {  # разделы патчноутов Valve → по-русски
    "MAPS": "🗺 Карты", "MAP": "🗺 Карты", "GAMEPLAY": "🎯 Геймплей",
    "MISC": "🔧 Разное", "GENERAL": "🔧 Общее", "AUDIO": "🔊 Звук",
    "SOUND": "🔊 Звук", "ANIMATION": "🏃 Анимации", "UI": "🖥 Интерфейс",
    "INTERFACE": "🖥 Интерфейс", "ITEMS": "🎁 Предметы",
    "GRAPHICS": "🎨 Графика", "RENDERING": "🎨 Графика",
    "NETWORKING": "🌐 Сеть", "MATCHMAKING": "🏆 Матчмейкинг",
    "PREMIER": "🏆 Премьер", "COMPETITIVE": "🏆 Соревновательный",
    "WORKSHOP": "🛠 Мастерская", "WEAPONS": "🔫 Оружие",
    "INVENTORY": "🎒 Инвентарь", "ARMORY": "🎁 Armory", "RUSH": "🏰 Rush",
    "PERFORMANCE": "🚀 Производительность", "LINUX": "🐧 Linux",
    "MACOS": "🍏 macOS", "STEAM DECK": "🎮 Steam Deck",
}


def frame(kicker, title, body, footer, tags=TAGS):
    """Каркас поста: заход жирным, заголовок, тело, подпись канала и
    хэштеги. body — уже готовый HTML (не экранируем)."""
    parts = [f"<b>{kicker}</b>"]
    if title:
        parts.append(html.escape(title))
    parts += ["", body, "", footer.format(tag=CHANNEL_TAG), tags]
    return "\n".join(parts)


def visible_len(text):
    """Длина подписи так, как её считает Telegram (без тегов, UTF-16)."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def kdate(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Kyiv"))
    except Exception:
        return datetime.fromtimestamp(ts + 3 * 3600, timezone.utc)


# ---------- состояние ----------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    state["news_seen"] = state.get("news_seen", [])[-300:]
    state["recent_phrases"] = bot._RECENT[-500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- официальные новости из Steam ----------

def fetch_announcements(count=10):
    """Официальная лента CS2 в Steam: патчноуты и анонсы Valve."""
    url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
           f"?appid={APPID}&count={count}&maxlength=0"
           "&feeds=steam_community_announcements")
    items = bot.http_get_json(url).get("appnews", {}).get("newsitems", [])
    return [{"gid": str(i.get("gid")), "title": i.get("title") or "",
             "date": int(i.get("date") or 0),
             "contents": i.get("contents") or ""} for i in items]


def is_patch(item):
    return item["title"].lower().startswith("counter-strike 2 update")


def bb_strip(s):
    """Убираем разметку Steam (BBCode), ссылки оставляем текстом."""
    s = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", s, flags=re.S)
    s = re.sub(r"\[(img|video|previewyoutube)[^\]]*\].*?\[/\1\]", "", s,
               flags=re.S)
    s = re.sub(r"\[/?[a-z0-9*]+(=[^\]]*)?[^\]]*\]", "", s)
    return html.unescape(s)


def patch_items(contents):
    """Патчноут → [(раздел, пункт), …] в исходном порядке. Разделы Valve
    пишет как «\\[ MISC ]», пункты — списком [*] или строками с «-»."""
    s = contents.replace("\\[", "⟦").replace("\\]", "⟧")
    s = re.sub(r"\[\*\]", "\n• ", s)
    s = re.sub(r"\[/\*\]|\[/?p\]|\[/?list\]|<br\s*/?>", "\n", s)
    out, section = [], ""
    for line in bb_strip(s).split("\n"):
        line = line.strip()
        m = re.fullmatch(r"⟦\s*(.+?)\s*[⟧\]]", line) or re.fullmatch(
            r"\[\s*([A-Z0-9 &/\-]+?)\s*\]", line)
        if m:
            section = m.group(1).strip()
            continue
        line = re.sub(r"^[•\-–—*]\s*", "", line).strip()
        if len(line) > 2:
            out.append((section, line.replace("⟦", "[").replace("⟧", "]")))
    return out


def section_name(sec):
    if not sec:
        return ""
    return SECTIONS.get(sec.upper(), "🔹 " + sec.title())


def bb_image(contents):
    """Первая картинка анонса: [img] или постер видео."""
    m = (re.search(r"\[img\]\s*(\S+?)\s*\[/img\]", contents)
         or re.search(r'poster="([^"]+)"', contents))
    if not m:
        return ""
    url = m.group(1).replace("{STEAM_CLAN_IMAGE}",
                             "https://clan.fastly.steamstatic.com/images")
    return url if url.startswith("http") else ""


def blog_text(contents, chars=550):
    """Первые абзацы анонса простым текстом (не длиннее chars)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", bb_strip(contents))]
    out = ""
    for p in paras:
        if len(p) < 3:
            continue
        if out and len(out) + len(p) > chars:
            break
        out += ("\n\n" if out else "") + p
    if len(out) > chars:
        out = out[:chars].rsplit(" ", 1)[0] + "…"
    return out


def translate_lines(lines):
    """Переводим пачкой одним запросом, при сбое — по одному."""
    if not lines:
        return []
    lines = [re.sub(r"\bVK\b", "Vulkan", x) for x in lines]
    out = bot.translate_to_ru("\n".join(lines)).split("\n")
    if len(out) == len(lines):
        return [o.strip() for o in out]
    return [bot.translate_to_ru(x) for x in lines]


def build_patch_caption(item, limit, hook, outro, footer, ru=None):
    """Пост о патче: разделы и пункты по-русски, остальное — ссылкой."""
    rows = patch_items(item["contents"])
    shown = rows[:limit]
    ru = ru or translate_lines([t for _, t in shown])
    body, last = [], None
    for (sec, _), text in zip(shown, ru):
        if sec != last:
            if body:
                body.append("")
            if sec:
                body.append(f"<b>{section_name(sec)}</b>")
            last = sec
        body.append(f"▫️ {html.escape(text)}")
    link = NEWS_URL.format(gid=item["gid"])
    tail = []
    more = len(rows) - len(shown)
    if more > 0:
        tail.append(f"…и ещё {more} "
                    f"{bot.plural(more, 'изменение', 'изменения', 'изменений')}")
    tail.append(f"📄 <a href=\"{link}\">Полный список изменений</a>")
    text = "\n".join(body) + "\n\n" + "\n".join(tail)
    if outro:
        text += f"\n\n{outro}"
    title = f"Обновление от {kdate(item['date']):%d.%m.%Y}"
    return frame(hook, title, text, footer)


def build_blog_caption(item, chars, hook, outro, footer):
    """Пост об анонсе: заголовок и начало текста по-русски + ссылка."""
    title = bot.translate_to_ru(item["title"])
    text = bot.translate_to_ru(blog_text(item["contents"], chars))
    link = NEWS_URL.format(gid=item["gid"])
    body = (f"<b>{html.escape(title)}</b>\n\n{html.escape(text)}\n\n"
            f"📖 <a href=\"{link}\">Читать полностью</a>")
    if outro:
        body += f"\n\n{outro}"
    return frame(hook, "", body, footer)


def safe_html(s):
    """Текст от модели → безопасный Telegram HTML: оставляем только <b>,
    <i> и ссылки, всё остальное экранируем."""
    s = html.escape(html.unescape(s or ""), quote=False)
    s = re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", s)
    s = re.sub(r'&lt;a href="(https?://[^"\s<>]+)"&gt;', r'<a href="\1">', s)
    return s.replace("&lt;/a&gt;", "</a>").strip()


def ai_news(item):
    """Пост о новости, написанный Claude: (картинка, текст), "skip" для
    совсем мелкого патча или None, если ИИ недоступен."""
    kind = "патч" if is_patch(item) else "анонс"
    link = NEWS_URL.format(gid=item["gid"])
    res = ai.news_post(kind, item["title"], bb_strip(item["contents"]), link)
    if not res:
        return None
    if not res.get("important"):
        return "skip"
    parts = [f"<b>{RUBRIC_NEWS} · {kind.upper()}</b>",
             f"<b>{html.escape(res['headline'].strip())}</b>", "",
             safe_html(res["body"])]
    if res.get("market", "").strip():
        parts += ["", f"💼 <b>Для рынка:</b> {safe_html(res['market'])}"]
    parts += ["", f"🔗 <a href=\"{link}\">Первоисточник — Steam</a>", "",
              bot.pick(FOOTERS).format(tag=CHANNEL_TAG), "#cs2 #новости_cs2"]
    text = "\n".join(parts)
    photo = HEADER if is_patch(item) else (bb_image(item["contents"]) or HEADER)
    return (photo if visible_len(text) <= 1024 else ""), text


def compose_news(item, use_ai=None):
    """Готовый пост: (картинка, подпись ≤ 1024) или (\"\", длинный текст).
    Сначала пробуем пересказ от Claude, иначе — шаблон с переводом."""
    if use_ai is None:
        use_ai = AI_NEWS_LIVE
    if use_ai and ai.available():
        out = ai_news(item)
        if out:
            return out
    outro, footer = bot.pick(NEWS_OUTROS), bot.pick(FOOTERS)
    if is_patch(item):
        hook = bot.pick(PATCH_HOOKS)
        rows = patch_items(item["contents"])
        ru = translate_lines([t for _, t in rows[:12]])
        for limit in (12, 10, 8, 6, 5, 4, 3):
            cap = build_patch_caption(item, limit, hook, outro, footer,
                                      ru[:limit])
            if visible_len(cap) <= 1024:
                return HEADER, cap
        return "", build_patch_caption(item, 12, hook, outro, footer, ru)
    hook = bot.pick(BLOG_HOOKS)
    photo = bb_image(item["contents"]) or HEADER
    for chars in (550, 400, 280, 180):
        cap = build_blog_caption(item, chars, hook, outro, footer)
        if visible_len(cap) <= 1024:
            return photo, cap
    return "", build_blog_caption(item, 1200, hook, outro, footer)


def send(tg, photo, text):
    res = tg.send_photo(photo, text) if photo else {}
    if not res.get("ok"):
        res = tg.send_message(text[:4096])
    if not res.get("ok"):   # сломанная разметка — шлём без тегов
        plain = html.escape(html.unescape(re.sub(r"<[^>]+>", "", text)))
        res = tg.send_message(plain[:4096])
    return res


def post_steam_news(tg, state, now):
    """Новые патчи и анонсы — по порядку, от старых к новым. Первый запуск
    публикует только самую свежую запись (если ей меньше суток)."""
    try:
        items = fetch_announcements()
    except Exception as e:
        print("Новости Steam не загрузились:", e)
        return
    seen = state.setdefault("news_seen", [])
    fresh = [i for i in items if i["gid"] not in seen]
    if "news_init" not in state:
        state["news_init"] = int(now)
        newest = max(fresh, key=lambda i: i["date"], default=None)
        keep = [newest] if newest and now - newest["date"] < 86400 else []
        seen += [i["gid"] for i in fresh if i not in keep]
        fresh = keep
    for item in sorted(fresh, key=lambda i: i["date"]):
        out = compose_news(item)
        if out == "skip":
            print("Мелкий технический патч — не публикуем:", item["gid"])
            seen.append(item["gid"])
            continue
        photo, text = out
        if not send(tg, photo, text).get("ok"):
            break   # повторим со следующего запуска
        seen.append(item["gid"])
        time.sleep(2)


# ---------- официальный X @CounterStrike ----------

def x_get(token, path, params):
    url = f"https://api.x.com/2/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "User-Agent": bot.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_x_posts(token, uid, since_id=None, count=5):
    """Собственные посты аккаунта (без ответов и ретвитов), новые первыми."""
    params = {"max_results": str(count), "exclude": "replies,retweets",
              "tweet.fields": "created_at,entities,attachments",
              "expansions": "attachments.media_keys",
              "media.fields": "type,url,preview_image_url,variants"}
    if since_id:
        params["since_id"] = since_id
    data = x_get(token, f"users/{uid}/tweets", params)
    media = {m["media_key"]: m
             for m in data.get("includes", {}).get("media", [])}
    posts = []
    for t in data.get("data", []):
        keys = t.get("attachments", {}).get("media_keys", [])
        posts.append({"id": t["id"], "text": t.get("text", ""),
                      "created": t.get("created_at", ""),
                      "urls": t.get("entities", {}).get("urls", []),
                      "media": [media[k] for k in keys if k in media]})
    return posts


def build_x_caption(p):
    """Новость из твита: перевод текста, ссылки из твита и оригинал."""
    text, links = p["text"], []
    for u in p["urls"]:
        text = text.replace(u.get("url", ""), "")
        exp = u.get("expanded_url") or ""
        if exp and not u.get("media_key") and "/status/" not in exp:
            links.append(exp)
    text = "\n".join(line.rstrip() for line in text.strip().splitlines())
    kind = bot.x_media(p)[0]
    if text:
        body = html.escape(bot.translate_to_ru(text))
    elif kind == "video":
        body = "🎬 Новое видео от Valve — смотри ☝️"
    else:
        body = "🖼 Новая картинка от Valve ☝️"
    extra = []
    for link in links[:2]:
        href = html.escape(link, quote=True)
        if "store.steampowered.com" in link:
            extra.append(f"🛒 <a href=\"{href}\">Открыть в Steam</a>")
        else:
            extra.append(f"🔗 <a href=\"{href}\">Подробнее</a>")
    extra.append(f"🐦 <a href=\"https://x.com/{X_NAME}/status/{p['id']}\">"
                 "Оригинал в X</a>")
    body += "\n\n" + "\n".join(extra)
    outro = bot.pick(NEWS_OUTROS)
    if outro:
        body += f"\n\n{outro}"
    return frame(bot.pick(X_HOOKS), "", body, bot.pick(FOOTERS))


def x_only_patch_link(p):
    """Твит вида «Release notes are up» со ссылкой на патч в Steam: сам
    патч мы публикуем из ленты Steam, такой твит не дублируем."""
    links = [u.get("expanded_url") or "" for u in p["urls"]]
    rest = re.sub(r"https?://\S+", "", p["text"]).strip()
    return (bool(links) and len(rest) < 120 and not p["media"]
            and all("store.steampowered.com/news" in x or "/status/" in x
                    for x in links))


def x_user_id(token, state):
    if not state.get("x_uid"):
        state["x_uid"] = x_get(token, f"users/by/username/{X_NAME}", {})[
            "data"]["id"]
    return state["x_uid"]


def post_x_news(tg, state):
    """Новые посты @CounterStrike — в канал, по порядку. Первый запуск
    публикует только самый свежий (если ему меньше суток)."""
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return
    last = state.get("x_last_id")
    try:
        posts = fetch_x_posts(token, x_user_id(token, state), last)
    except urllib.error.HTTPError as e:
        print("X API ошибка:", e.code, e.read().decode("utf-8", "replace")[:300])
        return
    except Exception as e:
        print("X не ответил:", e)
        return
    if not posts:
        return
    if last is None:
        newest = posts[0]
        state["x_last_id"] = newest["id"]
        born = datetime.strptime(newest["created"][:19], "%Y-%m-%dT%H:%M:%S")
        age = time.time() - born.replace(tzinfo=timezone.utc).timestamp()
        posts = [newest] if age < 86400 else []
    for p in sorted(posts, key=lambda p: int(p["id"])):   # от старых к новым
        if x_only_patch_link(p):
            state["x_last_id"] = p["id"]
            continue
        text = build_x_caption(p)
        kind, url, preview = bot.x_media(p)
        res = {}
        if kind == "video" and url:
            res = tg._post("sendVideo", {
                "chat_id": tg.chat, "video": url, "caption": text,
                "parse_mode": "HTML", "supports_streaming": "true"})
        image = url if kind == "photo" else preview
        if not res.get("ok") and image:
            res = tg.send_photo(image, text)
        if not res.get("ok"):   # подпись длинная или медиа не прошло
            res = tg.send_message(text)
        if not res.get("ok"):
            break   # повторим со следующего запуска
        state["x_last_id"] = p["id"]
        time.sleep(2)


# ---------- онлайн CS2 ----------

def fetch_online():
    """Сколько людей прямо сейчас играет в CS2 (Steam, ключ не нужен)."""
    url = ("https://api.steampowered.com/ISteamUserStats/"
           f"GetNumberOfCurrentPlayers/v1/?appid={APPID}")
    return int(bot.http_get_json(url, timeout=15)["response"]["player_count"])


def online_text(state, n, now):
    """Строки сводки: сейчас, к этому времени вчера, пик за сутки."""
    log = state.get("online_log", [])
    lines = [f"👥 Сейчас в игре: <b>{bot.fmt_num(n)}</b>"]
    if log:
        ago = min(log, key=lambda x: abs(x[0] - (now - 86400)))
        if abs(ago[0] - (now - 86400)) <= 5400 and ago[1]:
            diff = (n - ago[1]) * 100 / ago[1]
            arrow = "📈" if diff >= 0 else "📉"
            lines.append(f"{arrow} {diff:+.0f}% к этому времени вчера")
        day = [c for t, c in log if now - t <= 86400]
        if day:
            lines.append(f"🏔 Пик за сутки: {bot.fmt_num(max(day + [n]))}")
    return lines


def online_tick(tg, state, now):
    """Каждый запуск: замер онлайна. Раз в день вечером — сводка, а если
    онлайн выше максимума за прошлые 30 дней — пост о рекорде."""
    n = fetch_online()
    lines = online_text(state, n, now)
    log = [x for x in state.get("online_log", []) if now - x[0] < 8 * 86400]
    log.append([int(now), n])
    state["online_log"] = log
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    month_ago = time.strftime("%Y-%m-%d", time.gmtime(now - 30 * 86400))
    peaks = state.setdefault("online_peaks", {})
    prev = [p for d, p in peaks.items() if month_ago <= d < day]
    peaks[day] = max(peaks.get(day, 0), n)
    for d in sorted(peaks)[:-400]:
        del peaks[d]

    # рекорд месяца: истории хватает (2+ недели), пост не чаще раза в сутки
    if (len(prev) >= 14 and n > max(prev)
            and now - state.get("online_record_ts", 0) > 86400):
        body = (f"👥 Сейчас в игре: <b>{bot.fmt_num(n)}</b>\n"
                f"📊 Прошлый максимум за месяц: {bot.fmt_num(max(prev))}")
        outro = bot.pick(ONLINE_OUTROS)
        if outro:
            body += f"\n\n{outro}"
        res = tg.send_message(frame(bot.pick(RECORD_HOOKS), "", body,
                                    bot.pick(FOOTERS), TAGS + " #онлайн"))
        if res.get("ok"):
            state["online_record_ts"] = int(now)
        return

    # ежедневная сводка — вечером, один раз за день
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if kt.hour < ONLINE_POST_HOUR or state.get("online_daily") == today:
        return
    outro = bot.pick(ONLINE_OUTROS)
    if outro:
        lines += ["", outro]
    res = tg.send_message(frame(bot.pick(ONLINE_HOOKS), "", "\n".join(lines),
                                bot.pick(FOOTERS), TAGS + " #онлайн"))
    if res.get("ok"):
        state["online_daily"] = today


# ---------- цены: что дорожает и что дешевеет (Skinport) ----------
# Раз в день: ходовые предметы (от $3 и от 10 продаж за неделю на Skinport),
# цена за 7 дней против цены за 30 дней — топ-5 вверх и вниз на картинке.

PRICES_LIVE = False      # по расписанию — после одобрения примера
PRICE_HOUR = 16          # по Киеву
PRICE_MIN = 3.0          # $ — дешёвые предметы скачут от одной сделки
PRICE_MIN_SALES = 10     # продаж за неделю на Skinport
ACCENT = (222, 155, 53)  # фирменный оранжевый CS2
PRICE_HOOKS = [
    "📈 РЫНОК CS2: кто дорожает, кто дешевеет",
    "💹 Маркет CS2 — главные движения цен за неделю",
    "💰 Что творится с ценами на скины CS2",
    "📊 Биржевая сводка CS2: скины на взлёте и в падении",
    "🎢 Качели маркета CS2: итоги недели",
    "💸 Для инвесторов в скины: сводка цен CS2",
    "🔥 Скины CS2, которые взлетели в цене",
    "🧾 Сводка по маркету CS2",
]
PRICE_OUTROS = [
    "Кто успел закупиться? 😏", "Держим или продаём? 🤔",
    "Ставь 🔥, если следишь за маркетом",
    "Инвестиции в скины — дело тонкое 💼", "А у тебя что в инвентаре? 👀", "",
]
WEAR = {"Factory New": "FN", "Minimal Wear": "MW", "Field-Tested": "FT",
        "Well-Worn": "WW", "Battle-Scarred": "BS"}


def short_name(name):
    """«AK-47 | Redline (Field-Tested)» → «AK-47 | Redline · FT»."""
    m = re.match(r"^(.*) \(([^)]+)\)$", name)
    if m and m.group(2) in WEAR:
        name = f"{m.group(1)} · {WEAR[m.group(2)]}"
    return name.replace("StatTrak™ ", "ST™ ")


def market_url(name):
    return ("https://steamcommunity.com/market/listings/730/"
            + urllib.parse.quote(name))


def fetch_skinport():
    """Продажи всех предметов CS2 на Skinport: медиана и число продаж за
    24 ч, 7, 30 и 90 дней. Skinport отдаёт этот список сжатым brotli."""
    url = "https://api.skinport.com/v1/sales/history?app_id=730&currency=USD"
    req = urllib.request.Request(url, headers={"User-Agent": bot.UA,
                                               "Accept-Encoding": "br"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw, enc = r.read(), r.headers.get("Content-Encoding", "")
    if enc == "br":
        import brotli
        raw = brotli.decompress(raw)
    return json.loads(raw.decode("utf-8", "replace"))


def price_moves(items):
    """Ходовые предметы: цена за 7 дней против цены за 30 дней и движение
    за сутки (если за сутки было хотя бы 10 продаж)."""
    out = []
    for i in items:
        w = i.get("last_7_days") or {}
        m = i.get("last_30_days") or {}
        d = i.get("last_24_hours") or {}
        if not (w.get("median") and m.get("median")):
            continue
        if (w["median"] < PRICE_MIN or (w.get("volume") or 0) < PRICE_MIN_SALES
                or (m.get("volume") or 0) < 2 * PRICE_MIN_SALES):
            continue
        ch = w["median"] / m["median"] - 1
        if abs(ch) > 0.8 and w["volume"] < 25:   # пара странных сделок
            continue
        day = (d["median"] / w["median"] - 1
               if d.get("median") and (d.get("volume") or 0) >= 10 else None)
        out.append({"name": i["market_hash_name"], "now": w["median"],
                    "was": m["median"], "ch": ch, "day": day,
                    "sales": w["volume"]})
    return out


def steam_item(name):
    """Иконка и цвет редкости предмета — из поиска по маркету Steam."""
    q = urllib.parse.urlencode({"query": name, "appid": APPID,
                                "norender": 1, "count": 10})
    try:
        data = bot.http_get_json(
            f"https://steamcommunity.com/market/search/render/?{q}")
    except Exception:
        return {}
    for r in data.get("results") or []:
        if r.get("hash_name") == name:
            d = r.get("asset_description") or {}
            return {"icon": d.get("icon_url") or "",
                    "color": d.get("name_color") or ""}
    return {}


def build_price_card(title, subtitle, sections, footer, out_path):
    """Картинка-сводка 1440×1800 в стиле Rust-канала, акцент — оранжевый
    CS2. sections: [(заголовок, цвет, [(название, иконка, цвет редкости,
    подпись, справа)])]. Рисуем в 2× и уменьшаем — чёткий текст."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        return False
    S, W, H = 2, 1440, 1800
    p = lambda v: int(v * S)
    card_bg, line_c, muted = (31, 34, 43), (48, 52, 64), (150, 156, 172)
    grad = Image.linear_gradient("L").resize((p(W), p(H)))
    img = Image.composite(Image.new("RGB", (p(W), p(H)), (11, 12, 16)),
                          Image.new("RGB", (p(W), p(H)), (27, 29, 37)),
                          grad).convert("RGBA")
    glow = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 8 - 75, -55, W // 8 + 45, 45),
                                 fill=ACCENT + (110,))
    glow = glow.filter(ImageFilter.GaussianBlur(14)).resize(
        (p(W), p(H)), Image.BICUBIC)
    img.alpha_composite(glow)
    draw = ImageDraw.Draw(img)

    def font(size, bold=False):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/"
                                      + name, p(size))
        except Exception:
            return ImageFont.load_default()

    def fit(text, fnt, width):
        if draw.textlength(text, font=fnt) <= width:
            return text
        while text and draw.textlength(text + "…", font=fnt) > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def icon(url, size):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": bot.UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGBA")
            im.thumbnail((p(size), p(size)), Image.LANCZOS)
            return im
        except Exception:
            return None

    def hexrgb(h, default=(176, 195, 217)):
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return default

    # шапка: оранжевая полоса, метка, заголовок, подзаголовок
    draw.rectangle((0, 0, p(W), p(12)), fill=ACCENT)
    tag, tf = "СВОДКА РЫНКА", font(22, True)
    tw = draw.textlength(tag, font=tf)
    draw.rounded_rectangle((p(64), p(52), p(64) + tw + p(40), p(94)),
                           radius=p(21), fill=ACCENT)
    draw.text((p(64) + (tw + p(40)) / 2, p(73)), tag, font=tf,
              fill=(20, 20, 24), anchor="mm")
    draw.text((p(62), p(150)), title, font=font(70, True),
              fill=(255, 255, 255), anchor="lm")
    draw.text((p(64), p(214)), fit(subtitle, font(30), p(W - 128)),
              font=font(30), fill=muted, anchor="lm")

    y = 262
    for head, color, rows in sections:
        hf = font(34, True)
        draw.text((p(64), p(y + 22)), head, font=hf, fill=color, anchor="lm")
        hw = draw.textlength(head, font=hf)
        draw.line((p(64) + hw + p(24), p(y + 22), p(W - 64), p(y + 22)),
                  fill=line_c, width=p(2))
        y += 58
        tint = tuple(int(c * 0.3 + b * 0.7) for c, b in zip(color, card_bg))
        for name, src, rarity, sub, right in rows:
            draw.rounded_rectangle((p(56), p(y), p(W - 56), p(y + 118)),
                                   radius=p(26), fill=card_bg, outline=line_c,
                                   width=p(2))
            # плитка в цвет редкости предмета и иконка по центру
            rc = hexrgb(rarity)
            tile = tuple(int(c * 0.35 + b * 0.65) for c, b in zip(rc, card_bg))
            draw.rounded_rectangle((p(76), p(y + 11), p(172), p(y + 107)),
                                   radius=p(20), fill=tile)
            ic = icon(src, 88) if src else None
            if ic:
                img.alpha_composite(ic, (p(76) + (p(96) - ic.width) // 2,
                                         p(y + 11) + (p(96) - ic.height) // 2))
            # процент — цветная «таблетка» справа
            pf = font(38, True)
            px1 = p(W - 80)
            px0 = px1 - draw.textlength(right, font=pf) - p(44)
            draw.rounded_rectangle((px0, p(y + 30), px1, p(y + 88)),
                                   radius=p(29), fill=tint)
            draw.text(((px0 + px1) / 2, p(y + 59)), right, font=pf, fill=color,
                      anchor="mm")
            nf = font(36, True)
            draw.text((p(198), p(y + 40)), fit(name, nf, px0 - p(218)),
                      font=nf, fill=(240, 242, 246), anchor="lm")
            sf = font(26)
            draw.text((p(198), p(y + 82)), fit(sub, sf, px0 - p(218)),
                      font=sf, fill=muted, anchor="lm")
            y += 130
        y += 10

    # подвал
    draw.line((p(64), p(H - 80), p(W - 64), p(H - 80)), fill=line_c,
              width=p(2))
    draw.text((p(64), p(H - 44)), footer, font=font(26),
              fill=(120, 126, 142), anchor="lm")
    draw.text((p(W - 64), p(H - 44)), CHANNEL_TAG, font=font(28, True),
              fill=ACCENT, anchor="rm")
    img = img.convert("RGB").resize((W, H), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=95, subsampling=0)
    return True


def compose_prices(kt):
    """Сводка цен: (подпись ≤ 1024, путь к картинке или "") или None."""
    try:
        moves = price_moves(fetch_skinport())
    except Exception as e:
        print("Skinport не ответил:", e)
        return None
    if len(moves) < 50:
        print("Мало данных Skinport:", len(moves))
        return None
    ups = sorted((m for m in moves if m["ch"] >= 0.03),
                 key=lambda m: -m["ch"])[:5]
    downs = sorted((m for m in moves if m["ch"] <= -0.03),
                   key=lambda m: m["ch"])[:5]
    for m in ups + downs:
        m.update(steam_item(m["name"]))
        time.sleep(1)
    pct = lambda v: f"{v * 100:+.0f}%".replace("-", "−")
    usd = lambda v: f"${v:,.2f}".replace(",", " ")
    link = lambda m: (f"<a href=\"{market_url(m['name'])}\">"
                      f"{html.escape(short_name(m['name']))}</a>")
    line = lambda m: (f"▫️ {link(m)} — {usd(m['was'])} → {usd(m['now'])}"
                      f" (<b>{pct(m['ch'])}</b>)")

    def row(m):
        src = (("https://community.cloudflare.steamstatic.com/economy/image/"
                f"{m['icon']}/256fx256f") if m.get("icon") else "")
        return (short_name(m["name"]), src, m.get("color", ""),
                f"{usd(m['was'])} → {usd(m['now'])}  ·  {m['sales']} продаж"
                " за неделю", pct(m["ch"]))

    sections = [x for x in (
        ("▲ ДОРОЖАЮТ", (61, 220, 132), [row(m) for m in ups]),
        ("▼ ДЕШЕВЕЮТ", (255, 82, 82), [row(m) for m in downs])) if x[2]]
    blocks = []
    if ups:
        blocks.append("\n".join(["📈 <b>Дорожают</b>"]
                                + [line(m) for m in ups[:3]]))
    if downs:
        blocks.append("\n".join(["📉 <b>Дешевеют</b>"]
                                + [line(m) for m in downs[:3]]))
    # дополнительные строки — по важности; не влезут — отрежем с конца
    extras = []
    shown = {m["name"] for m in ups[:3] + downs[:3]}
    cases = [m for m in moves
             if m["name"].endswith(" Case") and m["name"] not in shown]
    if cases:
        top = max(cases, key=lambda m: abs(m["ch"]))
        if abs(top["ch"]) >= 0.03:
            extras.append(f"📦 Кейс недели: {link(top)} {pct(top['ch'])}"
                          f" ({usd(top['now'])})")
    day = [m for m in moves if m["day"] is not None and abs(m["day"]) >= 0.05
           and m["name"] not in shown]
    if day:
        d = max(day, key=lambda m: abs(m["day"]))
        extras.append(f"⚡ За сутки сильнее всех: {link(d)} {pct(d['day'])}")
    hook, outro = bot.pick(PRICE_HOOKS), bot.pick(PRICE_OUTROS)
    footer = bot.pick(FOOTERS)
    date = kt.strftime("%d.%m.%Y")

    def compose(ex):
        parts = blocks + (["\n".join(ex)] if ex else [])
        if outro:
            parts.append(outro)
        return frame(hook, f"🗓 {date} · за неделю, продажи Skinport",
                     "\n\n".join(parts), footer, TAGS + " #скины #маркет")

    text = compose(extras)
    while extras and visible_len(text) > 1024:
        extras.pop()
        text = compose(extras)
    card = os.path.join(tempfile.gettempdir(), "cs2_prices.jpg")
    try:
        ok = build_price_card(
            "РЫНОК СКИНОВ CS2",
            f"{date} · цена за 7 дней против цены за 30 дней", sections,
            "по продажам на Skinport · иконки Steam", card)
    except Exception as e:
        print("Картинка цен не собралась:", e)
        ok = False
    return text, (card if ok else "")


def price_tick(tg, state, forced=False):
    """Раз в день (после PRICE_HOUR по Киеву) — сводка цен."""
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if not forced and (not PRICES_LIVE or kt.hour < PRICE_HOUR
                       or state.get("price_day") == today):
        return
    out = compose_prices(kt)
    if not out:
        return
    text, card = out
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok"):
        res = tg.send_message(text)
    if res.get("ok") and not forced:   # ручной показ не отменяет вечернюю
        state["price_day"] = today


# ---------- «💼 Инвестиции CS2»: еженедельный ТОП-5 (cs2_invest.py) ----------

INVEST_LIVE = False      # по расписанию — после одобрения примера
INVEST_WEEKDAY = 6       # воскресенье
INVEST_HOUR = 18         # по Киеву


def send_long(tg, text, limit=4000):
    """Длинный текст — несколькими сообщениями, режем по пустым строкам."""
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    parts.append(cur)
    res = {}
    for part in parts:
        res = send(tg, "", part)
        time.sleep(1)
    return res


def invest_tick(tg, state, forced=False):
    """Раз в неделю: ТОП-5 предметов — картинка с короткой сводкой и
    подробный разбор следующим сообщением."""
    kt = bot.kyiv_time()
    week = kt.strftime("%G-%V")
    if not forced and (not INVEST_LIVE or kt.weekday() != INVEST_WEEKDAY
                       or kt.hour < INVEST_HOUR
                       or state.get("invest_week") == week):
        return
    out = invest.compose(fetch_skinport(), kt)
    if not out:
        return
    caption, card, details = out
    res = tg.send_photo_file(card, caption) if card else {}
    if not res.get("ok"):
        res = send(tg, "", caption)
    if res.get("ok"):
        time.sleep(2)
        send_long(tg, details)
        if not forced:
            state["invest_week"] = week


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


# ---------- проверка и демонстрация ----------

def check_rights(token, chat):
    """Может ли бот публиковать в канале (только чтение, ничего не шлёт)."""
    base = f"https://api.telegram.org/bot{token}"
    try:
        me = bot.http_get_json(f"{base}/getMe")["result"]
        q = urllib.parse.urlencode({"chat_id": chat, "user_id": me["id"]})
        m = bot.http_get_json(f"{base}/getChatMember?{q}")["result"]
        print(f"Бот @{me.get('username')} в {chat}: статус {m.get('status')},"
              f" может публиковать: {m.get('can_post_messages')}")
    except urllib.error.HTTPError as e:
        print("Проверка прав: Telegram ответил", e.code,
              e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("Проверка прав не удалась:", type(e).__name__)


def demo(token, chat):
    """Примеры постов в лог — чтобы показать их до запуска канала."""
    check_rights(token, chat)
    items = fetch_announcements(30)
    patches = [i for i in items if is_patch(i)]
    month = [i for i in patches if time.time() - i["date"] < 30 * 86400]
    picks = (max(month or patches[:1], key=lambda i: len(i["contents"]),
                 default=None),
             patches[0] if patches else None,
             next((i for i in items if not is_patch(i)), None))
    for item in picks:
        if item:
            out = compose_news(item, use_ai=True)
            if out == "skip":
                print(f"\n===== ПРИМЕР: «{item['title']}» "
                      f"{kdate(item['date']):%d.%m} — Claude решил не публиковать"
                      " (мелкий технический патч) =====")
                continue
            photo, text = out
            print(f"\n===== ПРИМЕР ({'патч' if is_patch(item) else 'анонс'}"
                  f" от {kdate(item['date']):%d.%m}, картинка: "
                  f"{photo or 'нет — текстом'}, длина {visible_len(text)})"
                  f" =====\n{text}")
    xt = os.environ.get("X_BEARER_TOKEN", "").strip()
    if xt:
        try:
            posts = fetch_x_posts(xt, x_user_id(xt, {}), count=10)
            for post in posts:
                if x_only_patch_link(post):
                    print("X: пропускаем (ссылка на патч):", post["id"])
            p = [x for x in posts if not x_only_patch_link(x)][:1]
            for post in p:
                print(f"\n===== ПРИМЕР (X, медиа: {bot.x_media(post)[0] or 'нет'})"
                      f" =====\n{build_x_caption(post)}")
        except Exception as e:
            print("X:", e)
    n = fetch_online()
    print("\n===== ПРИМЕР (онлайн) =====\n" + frame(
        bot.pick(ONLINE_HOOKS), "", "\n".join(online_text({}, n, time.time())),
        bot.pick(FOOTERS), TAGS + " #онлайн"))
    out = compose_prices(bot.kyiv_time())
    if out:
        text, card = out
        print(f"\n===== ПРИМЕР (цены, длина {visible_len(text)}) =====\n{text}")


def demo_invest():
    """Пример еженедельного ТОП-5 в лог (с картинкой в base64)."""
    out = invest.compose(fetch_skinport(), bot.kyiv_time())
    if out:
        caption, card, details = out
        print(f"\n===== ПРИМЕР (инвестиции, подпись {visible_len(caption)},"
              f" разбор {visible_len(details)}) =====\n{caption}"
              f"\n\n----- РАЗБОР -----\n{details}")
        if card:
            dump_card(card)


def main():
    global CHANNEL_TAG
    now = time.time()
    token = os.environ.get("BOT_TOKEN", "").strip()
    channel = os.environ.get("CHANNEL", "").strip() or CHANNEL_TAG
    if channel.startswith("@"):
        CHANNEL_TAG = channel
    if os.environ.get("CS2_DEMO") == "1":
        demo(token, channel)
        return
    if os.environ.get("CS2_DEMO_INVEST") == "1":
        demo_invest()
        return
    dry = os.environ.get("CS2_DRY") == "1"
    state = load_state()
    bot._RECENT[:] = state.get("recent_phrases", [])
    tg = bot.Telegram(token, channel, dry_run=dry)
    post_steam_news(tg, state, now)
    post_x_news(tg, state)
    try:
        online_tick(tg, state, now)
    except Exception as e:
        print("Онлайн не получен:", e)
    try:
        price_tick(tg, state, os.environ.get("CS2_PRICES") == "1")
    except Exception as e:
        print("Сводка цен не вышла:", e)
    try:
        invest_tick(tg, state, os.environ.get("CS2_INVEST") == "1")
    except Exception as e:
        print("Инвест-разбор не вышел:", e)
    if not dry:
        save_state(state)


if __name__ == "__main__":
    main()
