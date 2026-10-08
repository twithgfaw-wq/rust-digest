#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Digest Bot — новости Counter-Strike 2 в Telegram-канал @cs2_me.

Что делает за один прогон (раз в 30 минут через GitHub Actions):
  1. Официальные новости CS2 из Steam: патчноуты (переведённый список
     изменений по разделам) и анонсы Valve (картинка, перевод, ссылка).
  2. Посты официального @CounterStrike из X — если задан X_BEARER_TOKEN.
  3. Онлайн CS2: раз в день вечером сводка, рекорд месяца — сразу.

Общие части (Telegram, перевод, подбор фраз) берём у Rust-бота.

Запуск: python cs2_bot.py
  CS2_DRY=1  — ничего не отправлять, только лог;
  CS2_DEMO=1 — показать в логе, как выглядели бы посты (последний патч,
               последний анонс, последний пост из X, онлайн), и проверить
               права бота в канале. Ничего не отправляет и не сохраняет.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import rust_digest_bot as bot

APPID = 730
STATE_FILE = "cs2_state.json"
CHANNEL_TAG = "@cs2_me"          # подпись в футере (обновляется в main)
HEADER = "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg"
NEWS_URL = "https://store.steampowered.com/news/app/730/view/{gid}"
X_NAME = "CounterStrike"
ONLINE_POST_HOUR = 20            # ежедневная сводка онлайна — вечером по Киеву
TAGS = "#cs2 #кс2 #counterstrike"

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


def compose_news(item):
    """Готовый пост: (картинка, подпись ≤ 1024) или (\"\", длинный текст)."""
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
        photo, text = compose_news(item)
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
    for item in (next((i for i in items if is_patch(i)), None),
                 next((i for i in items if not is_patch(i)), None)):
        if item:
            photo, text = compose_news(item)
            print(f"\n===== ПРИМЕР ({'патч' if is_patch(item) else 'анонс'},"
                  f" картинка: {photo or 'нет — текстом'},"
                  f" длина {visible_len(text)}) =====\n{text}")
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
    if not dry:
        save_state(state)


if __name__ == "__main__":
    main()
