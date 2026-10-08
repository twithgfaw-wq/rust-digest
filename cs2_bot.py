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
  5. 💼 Инвестиции: ежедневный ТОП-5 контейнеров (cs2_invest.py).
  6. 🎨 Мастерская: до трёх сильных работ в день (cs2_workshop.py).
  7. 💬 Сообщество: обсуждаемое из X, до трёх в день (cs2_community.py).

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
from datetime import datetime, timedelta, timezone

import cs2_ai as ai
import cs2_cards as cards
import cs2_community as comm
import cs2_formats as fmt
import cs2_invest as invest
import cs2_workshop as ws
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
AI_NEWS_LIVE = True              # пересказ от Claude (одобрено 08.10)

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


def ai_news(item, earlier=""):
    """Пост о новости, написанный Claude: (картинка, текст), "skip" для
    совсем мелкого патча или повтора, None — если ИИ недоступен."""
    kind = "патч" if is_patch(item) else "анонс"
    link = NEWS_URL.format(gid=item["gid"])
    res = ai.news_post(kind, item["title"], bb_strip(item["contents"]), link,
                       earlier)
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


def compose_news(item, use_ai=None, earlier=""):
    """Готовый пост: (картинка, подпись ≤ 1024) или (\"\", длинный текст).
    Сначала пробуем пересказ от Claude, иначе — шаблон с переводом."""
    if use_ai is None:
        use_ai = AI_NEWS_LIVE
    if use_ai and ai.available():
        out = ai_news(item, earlier)
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
    # что уже вышло за сутки: патч и анонс об одном обновлении не дублируем
    recent = [r for r in state.get("news_recent", []) if now - r["t"] < 86400]
    state["news_recent"] = recent
    for item in sorted(fresh, key=lambda i: i["date"]):
        earlier = "\n---\n".join(r["text"] for r in recent)
        out = compose_news(item, earlier=earlier)
        if out == "skip":
            print("Мелкий патч или повтор — не публикуем:", item["gid"])
            seen.append(item["gid"])
            continue
        photo, text = out
        if not send(tg, photo, text).get("ok"):
            break   # повторим со следующего запуска
        seen.append(item["gid"])
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        recent.append({"t": int(now), "text": plain[:700]})
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
        if not send_x(tg, p).get("ok"):
            break   # повторим со следующего запуска
        state["x_last_id"] = p["id"]
        time.sleep(2)


def send_x(tg, p):
    """Пост Valve из X — с видео или картинкой из твита, если они есть."""
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
    return res


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
    if send_online(tg, lines).get("ok"):
        state["online_daily"] = today


def send_online(tg, lines):
    outro = bot.pick(ONLINE_OUTROS)
    if outro:
        lines = lines + ["", outro]
    return tg.send_message(frame(bot.pick(ONLINE_HOOKS), "", "\n".join(lines),
                                 bot.pick(FOOTERS), TAGS + " #онлайн"))


# ---------- маркет: что дорожает и что дешевеет (Skinport) ----------
# Раз в день: ходовые предметы (от $3 и от 10 продаж за неделю на Skinport),
# цена за 7 дней против цены за 30 дней — по три вверх и вниз на картинке
# (cs2_cards.py) и простыми словами, почему цена могла так сдвинуться.

PRICES_LIVE = True       # одобрено 08.10
PRICE_HOUR = 16          # по Киеву
PRICE_MIN = 3.0          # $ — дешёвые предметы скачут от одной сделки
PRICE_MIN_SALES = 10     # продаж за неделю на Skinport
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


_SKINPORT = []


def fetch_skinport():
    """Продажи всех предметов CS2 на Skinport: медиана и число продаж за
    24 ч, 7, 30 и 90 дней. Skinport отдаёт этот список сжатым brotli.
    Один раз за запуск: у Skinport лимит — 8 запросов за 5 минут."""
    if _SKINPORT:
        return _SKINPORT[0]
    url = "https://api.skinport.com/v1/sales/history?app_id=730&currency=USD"
    req = urllib.request.Request(url, headers={"User-Agent": bot.UA,
                                               "Accept-Encoding": "br"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw, enc = r.read(), r.headers.get("Content-Encoding", "")
    if enc == "br":
        import brotli
        raw = brotli.decompress(raw)
    _SKINPORT.append(json.loads(raw.decode("utf-8", "replace")))
    return _SKINPORT[0]


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
                    "sales": w["volume"],
                    "usual": round(m["volume"] * 7 / 30)})   # обычно в неделю
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


MOVES_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "why": {"type": "string"}},
            "required": ["name", "why"],
            "additionalProperties": False}},
    },
    "required": ["intro", "items"],
    "additionalProperties": False,
}


def item_type(name):
    if name.startswith("Sticker |"):
        return "наклейка"
    if name.endswith((" Case", " Terminal")):
        return "кейс"
    if name.endswith((" Capsule", " Package")):
        return "капсула или набор"
    if "★" in name:
        return "нож или перчатки"
    return "скин оружия"


def move_why(m):
    """Почему цена могла сдвинуться — по правилам, если Claude недоступен."""
    more, less = m["sales"] >= m["usual"] * 1.3, m["sales"] <= m["usual"] * 0.8
    if m["name"] in invest.ACTIVE_POOL and m["ch"] < 0:
        return "Ещё выпадает в игре — их всё больше"
    if m["ch"] >= 0:
        return ("Покупают чаще обычного" if more
                else "Продавцов стало меньше" if less else "Спрос держится")
    return ("Похоже, многие продают" if more
            else "Покупать стали реже" if less else "Потихоньку дешевеет")


def explain_moves(moves):
    """Claude простыми словами объясняет движения цен — только по фактам из
    данных. {intro, items} или None."""
    if not ai.available():
        return None
    data = [{"name": m["name"], "type": item_type(m["name"]),
             "usual_price_month": round(m["was"], 2),
             "price_this_week": round(m["now"], 2),
             "change_pct": round(m["ch"] * 100),
             "sales_this_week": m["sales"], "sales_usual_week": m["usual"],
             "still_drops_in_game": m["name"] in invest.ACTIVE_POOL}
            for m in moves]
    prompt = f"""Рубрика «Маркет CS2»: что за неделю подорожало и что подешевело.
Читают обычные игроки, многие — школьники: пиши очень просто, как другу,
без терминов.

Для каждого предмета есть только факты: обычная цена за месяц и цена за эту
неделю (в долларах), сколько продаж за эту неделю и сколько обычно бывает
за неделю, тип предмета, выпадает ли он ещё в игре.
Объясни, почему цена могла так сдвинуться, ТОЛЬКО по этим фактам и мягко
(«похоже», «видимо»). Не придумывай новостей, обновлений, турниров и событий.
Подсказки: продаж больше обычного и цена растёт — спрос вырос; продаж больше
обычного и цена падает — многие продают; продаж меньше обычного и цена
растёт — продавцов стало меньше; продаж меньше обычного и цена падает —
покупателей стало меньше; ещё выпадает в игре — предметов становится больше.

Данные: {json.dumps(data, ensure_ascii=False)}

Верни:
- intro: одно предложение до 110 знаков — что видно на маркете за неделю.
- items: для каждого предмета в том же порядке: name — как во входе,
  why — до 45 знаков, простыми словами."""
    return ai.ask(prompt, MOVES_SCHEMA, effort="low")


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
                 key=lambda m: -m["ch"])[:3]
    downs = sorted((m for m in moves if m["ch"] <= -0.03),
                   key=lambda m: m["ch"])[:3]
    for m in ups + downs:
        m.update(steam_item(m["name"]))
        time.sleep(1)
    res = explain_moves(ups + downs) or {}
    said = res.get("items") or []
    for k, m in enumerate(ups + downs):
        why = (said[k].get("why") or "").strip() if len(said) == len(
            ups + downs) else ""
        m["why"] = why or move_why(m)
    pct = lambda v: f"{v * 100:+.0f}%".replace("-", "−")
    usd = lambda v: f"${v:,.2f}".replace(",", " ")
    link = lambda m: (f"<a href=\"{market_url(m['name'])}\">"
                      f"{html.escape(short_name(m['name']))}</a>")
    date = kt.strftime("%d.%m.%Y")

    def caption(intro, tip):
        lines = ["<b>💹 МАРКЕТ CS2 · ЗА НЕДЕЛЮ</b>", f"🗓 {date}", ""]
        if intro:
            lines += [html.escape(intro), ""]
        for head, group in (("📈 <b>Дорожают</b>", ups),
                            ("📉 <b>Дешевеют</b>", downs)):
            if group:
                lines.append(head)
                for m in group:
                    lines += [f"▫️ {link(m)} — {usd(m['was'])} → "
                              f"{usd(m['now'])} (<b>{pct(m['ch'])}</b>)",
                              f"      <i>{html.escape(m['why'])}</i>"]
                lines.append("")
        if tip:
            lines += ["💡 Подорожало — не значит «срочно покупать»: после "
                      "резкого скачка цена часто откатывается.", ""]
        lines += [f"<i>Цены — продажи на Skinport.</i> {CHANNEL_TAG}",
                  "#cs2 #скины #маркет"]
        return "\n".join(lines)

    intro = (res.get("intro") or "").strip()
    for args in ((intro, True), (intro, False), ("", False)):
        text = caption(*args)
        if visible_len(text) <= 1024:
            break

    def tile(m):
        return {"name": short_name(m["name"]),
                "icon": cards.STEAM_IMG.format(m["icon"]) if m.get("icon") else "",
                "rarity": m.get("color", ""),
                "prices": f"было {usd(m['was'])} · стало {usd(m['now'])}",
                "pct": f"{m['ch'] * 100:+.0f}%", "why": m["why"]}

    sections = [x for x in (
        ("ДОРОЖАЮТ", cards.GREEN, [tile(m) for m in ups]),
        ("ДЕШЕВЕЮТ", cards.RED, [tile(m) for m in downs])) if x[2]]
    card = os.path.join(tempfile.gettempdir(), "cs2_prices.jpg")
    try:
        ok = cards.market_card(
            "Маркет CS2 · за неделю",
            f"{date} · что подорожало и что подешевело", sections,
            "цены: продажи на Skinport · картинки Steam", card)
    except Exception as e:
        print("Картинка маркета не собралась:", e)
        ok = False
    return text, (card if ok else "")


def price_tick(tg, state, forced=False):
    """Раз в день (после PRICE_HOUR по Киеву) — сводка цен."""
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if not forced and (not PRICES_LIVE or kt.hour < PRICE_HOUR
                       or state.get("price_day") == today):
        return
    if post_prices(tg, kt) and not forced:   # ручной показ не отменяет вечернюю
        state["price_day"] = today


def post_prices(tg, kt):
    """Сводка цен: картинка с подписью (или текстом). True — вышла."""
    out = compose_prices(kt)
    if not out:
        return False
    text, card = out
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok"):
        res = tg.send_message(text)
    return bool(res.get("ok"))


# ---------- «💼 Инвестиции CS2»: ежедневный ТОП-5 (cs2_invest.py) ----------

INVEST_LIVE = True       # одобрено 08.10
INVEST_HOUR = 18         # по Киеву, каждый день
INVEST_ROTATE_DAYS = 2   # предмет из вчерашних/позавчерашних ТОП-5 — пропускаем


def send_album(tg, paths, caption):
    """Альбом из локальных картинок одним постом; подпись — на первой."""
    if tg.dry_run:
        print(f"[dry-run] альбом из {len(paths)} картинок: {caption[:120]}")
        return {"ok": True}
    boundary = "----CS2Bot" + str(int(time.time() * 1000))
    media, files = [], []
    for k, path in enumerate(paths[:10]):
        with open(path, "rb") as f:
            files.append((f"p{k}", f.read()))
        item = {"type": "photo", "media": f"attach://p{k}"}
        if k == 0:
            item.update(caption=caption, parse_mode="HTML")
        media.append(item)
    parts = [(f"--{boundary}\r\nContent-Disposition: form-data; "
              f"name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
             for k, v in (("chat_id", str(tg.chat)),
                          ("media", json.dumps(media, ensure_ascii=False)))]
    for name, data in files:
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                      f"name=\"{name}\"; filename=\"{name}.jpg\"\r\n"
                      "Content-Type: image/jpeg\r\n\r\n").encode("utf-8")
                     + data + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{tg.base}/sendMediaGroup", data=body,
        headers={"User-Agent": bot.UA,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        print("Telegram не принял альбом:", e.code,
              e.read().decode("utf-8", "replace")[:300])
        return {"ok": False}
    except Exception as e:
        print("Telegram не принял альбом:", e)
        return {"ok": False}
    if not res.get("ok"):
        print("Telegram ошибка (альбом):", res)
    return res


def recent_invest(state, today):
    """Предметы из ТОП-5 последних INVEST_ROTATE_DAYS дней (кроме сегодня)."""
    days = state.get("invest_days", {})
    keep = sorted(d for d in days if d < today)[-INVEST_ROTATE_DAYS:]
    return {n for d in keep for n in days[d]}


def invest_tick(tg, state, forced=False):
    """Каждый день: ТОП-5 предметов — альбом карточек с короткой подписью.
    Вчерашние позиции уступают место другим, чтобы подборка не
    повторялась изо дня в день."""
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if not forced and (not INVEST_LIVE or kt.hour < INVEST_HOUR
                       or state.get("invest_day") == today):
        return
    picks = post_invest(tg, state, kt, today)
    if picks and not forced:
        remember_invest(state, today, picks)


def post_invest(tg, state, kt, today):
    """ТОП-5: альбом (обзор и карточка на каждый) с короткой подписью.
    Вернёт советы [{name, verdict, price}] или None."""
    out = invest.compose(fetch_skinport(), kt, recent_invest(state, today))
    if not out:
        return None
    caption, pics, picks = out
    res = send_album(tg, pics, caption) if len(pics) >= 2 else {}
    if not res.get("ok") and pics:
        res = tg.send_photo_file(pics[0], caption)
    if not res.get("ok"):
        res = send(tg, "", caption)
    return picks if res.get("ok") else None


def remember_invest(state, today, picks):
    """Выпуск вышел: позиции — для ротации, советы с ценой — для отчёта
    «Мы советовали — что вышло»."""
    state["invest_day"] = today
    days = state.setdefault("invest_days", {})
    days[today] = [x["name"] for x in picks]
    for d in sorted(days)[:-7]:
        del days[d]
    log = state.setdefault("invest_log", [])
    log += [dict(x, date=today) for x in picks]
    del log[:-150]


# ---------- «🎨 Мастерская CS2» (cs2_workshop.py) ----------

WORKSHOP_LIVE = True           # одобрено 08.10
WORKSHOP_SLOTS = (12, 16, 20)  # по Киеву: до трёх постов в день


def workshop_slot(kt):
    hours = [h for h in WORKSHOP_SLOTS if kt.hour >= h]
    return f"{kt:%Y-%m-%d}-{hours[-1]}" if hours else None


def post_work(tg, best):
    """Альбом из 2–4 картинок работы с подписью (или одно фото)."""
    w, author, info, res = best
    caption = ws.compose(w, author, info, res)
    out = (tg.send_media_group(w["images"][:4], caption)
           if len(w["images"]) > 1 else {})
    if not out.get("ok"):
        out = send(tg, w["images"][0], caption)
    return out


def workshop_tick(tg, state, now, forced=False):
    """В каждый слот — лучшая новая работа с оценкой от 7 (если есть)."""
    key = os.environ.get("STEAM_API_KEY", "").strip()
    if not key or not ai.available():
        return
    slot = workshop_slot(bot.kyiv_time())
    if not forced and (not WORKSHOP_LIVE or not slot
                       or state.get("ws_slot") == slot):
        return
    best = ws.pick(key, state, now)
    if not best:
        print("Мастерская: достойных новых работ пока нет")
        return
    if post_work(tg, best).get("ok"):
        state["ws_posted"] = (state.get("ws_posted", []) + [best[0]["id"]])[-500:]
        if not forced:
            state["ws_slot"] = slot


# ---------- «💬 Сообщество CS2» (cs2_community.py) ----------

COMMUNITY_LIVE = True          # одобрено 08.10


def post_with_media(tg, p, text):
    """Пост с картинкой или видео из исходного твита (если есть)."""
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
        res = send(tg, "", text)
    return res


def community_tick(tg, state, now, forced=False):
    """В каждый слот — самый интересный пост сообщества (если есть)."""
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token or not ai.available():
        return
    kt = bot.kyiv_time()
    hours = [h for h in comm.SLOTS if kt.hour >= h]
    slot = f"{kt:%Y-%m-%d}-{hours[-1]}" if hours else None
    if not forced and (not COMMUNITY_LIVE or not slot
                       or state.get("comm_slot") == slot):
        return
    if not forced:
        state["comm_slot"] = slot      # одна попытка на слот — экономим X API
    posts = comm.gather(token, state)
    p, res = comm.choose(posts, set(state.get("comm_posted", [])))
    if not p:
        return
    if post_with_media(tg, p, comm.compose(p, res, safe_html)).get("ok"):
        state["comm_posted"] = (state.get("comm_posted", []) + [p["id"]])[-500:]


# ---------- новые рубрики (cs2_formats.py) ----------

FORMATS_LIVE = True              # одобрено 08.10
SOD_HOUR = 11                    # ✨ скин дня — каждый день
CASE_DAY, CASE_HOUR = 2, 19      # 🎰 открывать или нет — среда
DUEL_DAY, DUEL_HOUR = 3, 19      # 🗳 угадай цену — четверг (старт 08.10)
REPORT_DAY, REPORT_HOUR = 6, 15  # 📒 мы советовали — воскресенье


def post_card(tg, card, text):
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok"):
        res = send(tg, "", text)
    return res


def skin_of_day(tg, state, kt):
    """True — готово (вышел или нечего публиковать), False — не отправилось."""
    sp = fetch_skinport()
    s = fmt.pick_skin(sp, state, kt.strftime("%Y-%m-%d"))
    out = fmt.compose_skin(s, sp, kt.strftime("%d.%m.%Y"),
                           CHANNEL_TAG) if s else None
    if not out:
        return True
    if not post_card(tg, out[1], out[0]).get("ok"):
        return False
    state["sod_seen"] = (state.get("sod_seen", []) + [s["name"]])[-200:]
    return True


def case_of_week(tg, state, kt):
    st = fmt.pick_case(fetch_skinport(), state)
    if not st:
        return True
    text, card = fmt.compose_case(st, CHANNEL_TAG)
    if not post_card(tg, card, text).get("ok"):
        return False
    state["ev_seen"] = (state.get("ev_seen", []) + [st["case"]["name"]])[-40:]
    return True


def duel_round(tg, state, kt):
    """Итог прошлого опроса (если был) и новый опрос."""
    sp, date = fetch_skinport(), kt.strftime("%d.%m")
    old = state.get("duel")
    if old and time.time() - old.get("ts", 0) < 5 * 86400:
        return True       # прошлый опрос ещё идёт: итог — через неделю
    if old:
        votes = None
        if old.get("poll_id"):
            res = tg._post("stopPoll", {"chat_id": tg.chat,
                                        "message_id": old["poll_id"]})
            if res.get("ok") and isinstance(res.get("result"), dict):
                votes = [o.get("voter_count", 0)
                         for o in res["result"].get("options", [])]
        out = fmt.compose_duel_result(old, sp, votes, CHANNEL_TAG, date)
        if out:
            if not post_card(tg, out[1], out[0]).get("ok"):
                return False
            time.sleep(2)
        state.pop("duel", None)
    pair = fmt.pick_duel(sp, state)
    if not pair:
        return True
    text, card, question, options = fmt.compose_duel(pair, CHANNEL_TAG, date)
    if not post_card(tg, card, text).get("ok"):
        return False
    res = tg._post("sendPoll", {
        "chat_id": tg.chat, "question": question, "is_anonymous": "true",
        "options": json.dumps([{"text": o} for o in options],
                              ensure_ascii=False)})
    state["duel"] = {"date": date, "ts": int(time.time()),
                     "poll_id": (res.get("result") or {}).get("message_id"),
                     "items": [{"name": n, "price": p} for n, p, _ in pair]}
    state["duel_used"] = (state.get("duel_used", [])
                          + [fmt.base_name(n) for n, _, _ in pair])[-60:]
    return True


def advice_report(tg, state, kt):
    """Советы «Инвестиций», которым 7–14 дней: что с ними стало."""
    lo = (kt - timedelta(days=14)).strftime("%Y-%m-%d")
    hi = (kt - timedelta(days=7)).strftime("%Y-%m-%d")
    seen, recs = set(), []
    for r in sorted(state.get("invest_log", []), key=lambda r: r["date"]):
        if lo <= r["date"] <= hi and r["name"] not in seen:
            seen.add(r["name"])
            recs.append(r)
    out = fmt.compose_report(recs[-8:], kt.strftime("%d.%m"),
                             CHANNEL_TAG) if recs else None
    return not out or post_card(tg, out[1], out[0]).get("ok")


FORMATS = (("skin", None, SOD_HOUR, "sod_day", "%Y-%m-%d", skin_of_day),
           ("case", CASE_DAY, CASE_HOUR, "ev_week", "%G-%V", case_of_week),
           ("duel", DUEL_DAY, DUEL_HOUR, "duel_week", "%G-%V", duel_round),
           ("report", REPORT_DAY, REPORT_HOUR, "report_week", "%G-%V",
            advice_report))


def formats_tick(tg, state, forced=()):
    """Новые рубрики по расписанию; forced — какие выложить прямо сейчас."""
    kt = bot.kyiv_time()
    for name, wd, hour, key, stamp, fn in FORMATS:
        val = kt.strftime(stamp)
        if name not in forced and not (
                FORMATS_LIVE and (wd is None or kt.weekday() == wd)
                and kt.hour >= hour and state.get(key) != val):
            continue
        try:
            if fn(tg, state, kt):
                state[key] = val
        except Exception as e:
            print(f"Рубрика {name} не вышла:", e)
        time.sleep(3)


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


def demo_community():
    """Пример поста сообщества в лог: какие аккаунты нашлись, топ и выбор."""
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        print("Нет X_BEARER_TOKEN")
        return
    state = {}
    posts = comm.gather(token, state)
    print("Аккаунты:", ", ".join(v["name"] for v in state.get(
        "comm_ids", {}).values() if v))
    for p in sorted(posts, key=lambda p: p["score"], reverse=True)[:8]:
        print(f"· @{p['author']} ❤️{p['likes']} 🔁{p['reposts']} "
              f"💬{p['replies']} · {p['text'][:110]!r}")
    p, res = comm.choose(posts, set())
    if p:
        print(f"\n===== ПРИМЕР (сообщество) =====\n"
              f"{comm.compose(p, res, safe_html)}\nМедиа: {bot.x_media(p)[0]}")


def demo_workshop():
    """Пример поста мастерской в лог: какие работы оценены и лучшая."""
    key = os.environ.get("STEAM_API_KEY", "").strip()
    if not key:
        print("Нет STEAM_API_KEY")
        return
    best = ws.pick(key, {}, time.time(), judge_limit=5)
    if not best:
        print("\n===== МАСТЕРСКАЯ: работ с оценкой от 7 сейчас нет =====")
        return
    w, author, info, res = best
    caption = ws.compose(w, author, info, res)
    print(f"\n===== ПРИМЕР (мастерская, оценка {res['score']}/10, длина "
          f"{visible_len(caption)}) =====\n{caption}\nКартинки: {w['images']}")


def demo_invest():
    """Пример маркета и ТОП-5 в лог (картинки — в base64)."""
    out = compose_prices(bot.kyiv_time())
    if out:
        text, card = out
        print(f"\n===== ПРИМЕР (маркет, длина {visible_len(text)}) =====\n{text}")
        if card:
            dump_card(card)
    out = invest.compose(fetch_skinport(), bot.kyiv_time())
    if out:
        caption, pics, _ = out
        print(f"\n===== ПРИМЕР (инвестиции, подпись {visible_len(caption)},"
              f" картинок {len(pics)}) =====\n{caption}")
        for path in pics:
            dump_card(path)


def demo_formats():
    """Примеры новых рубрик в лог (картинки — base64). Ничего не шлёт.
    Итог опроса и отчёт — иллюстрации на ценах недельной давности."""
    def show(title, out):
        if not out:
            print(f"\n===== {title}: нет данных =====")
            return
        text, card = out
        print(f"\n===== ПРИМЕР ({title}, длина {visible_len(text)}) ====="
              f"\n{text}")
        if card:
            dump_card(card)

    sp, kt, state = fetch_skinport(), bot.kyiv_time(), load_state()
    s = fmt.pick_skin(sp, state, kt.strftime("%Y-%m-%d"))
    show("скин дня", fmt.compose_skin(s, sp, kt.strftime("%d.%m.%Y"),
                                      CHANNEL_TAG) if s else None)
    st = fmt.pick_case(sp, state)
    show("открывать или нет", fmt.compose_case(st, CHANNEL_TAG) if st else None)
    pair = fmt.pick_duel(sp, state)
    if pair:
        text, card, q, opts = fmt.compose_duel(pair, CHANNEL_TAG,
                                               kt.strftime("%d.%m"))
        show("угадай цену", (f"{text}\n[опрос] {q} — {' / '.join(opts)}",
                             card))
        month = {i["market_hash_name"]: (i.get("last_30_days") or {}).get(
            "median") for i in sp}
        old = {"date": (kt - timedelta(days=7)).strftime("%d.%m"),
               "items": [{"name": n, "price": month.get(n) or p}
                         for n, p, _ in pair]}
        show("угадай цену · итог (иллюстрация)",
             fmt.compose_duel_result(old, sp, [31, 19], CHANNEL_TAG,
                                     kt.strftime("%d.%m")))
    names = (sorted(state.get("invest_days", {}).items()) or [("", [])])[-1][1]
    recs = []
    for n in names[:5]:
        h = invest.history(n)
        m = invest.metrics(n, h)
        was = invest.wavg(h, invest.day(-14), invest.day(-7))
        if m and was:
            m["verdict"] = invest.verdict(m)
            recs.append({"name": n, "verdict": m["verdict"], "price": was,
                         "date": invest.day(-10)})
        time.sleep(0.5)
    show("мы советовали (иллюстрация)",
         fmt.compose_report(recs, kt.strftime("%d.%m"), CHANNEL_TAG)
         if recs else None)


def launch(tg, state, now):
    """Старт канала: по одному посту каждой рубрики прямо сейчас. Каждый
    записывается как обычный — сегодня ничего не повторится, дальше всё
    идёт по расписанию."""
    kt = bot.kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    last = lambda key: (state.get(key) or [None])[-1]
    done = []

    def news():
        items = sorted(fetch_announcements(), key=lambda i: i["date"],
                       reverse=True)
        for item in items[:4]:
            out = compose_news(item)
            if out == "skip":
                print("Мелкий патч — берём новость постарше:", item["title"])
                continue
            photo, text = out
            if not send(tg, photo, text).get("ok"):
                return False
            plain = html.unescape(re.sub(r"<[^>]+>", "", text))
            state.setdefault("news_recent", []).append(
                {"t": int(now), "text": plain[:700]})
            return True
        return False

    def x_post():
        token = os.environ.get("X_BEARER_TOKEN", "").strip()
        if not token:
            return False
        posts = fetch_x_posts(token, x_user_id(token, state), count=10)
        p = next((x for x in posts if not x_only_patch_link(x)), None)
        return bool(p) and send_x(tg, p).get("ok")

    def community():
        before = last("comm_posted")
        community_tick(tg, state, now, forced=True)
        return last("comm_posted") != before

    def workshop():
        before = last("ws_posted")
        workshop_tick(tg, state, now, forced=True)
        return last("ws_posted") != before

    def prices():
        if not post_prices(tg, kt):
            return False
        state["price_day"] = today      # вечером сегодня не повторяем
        return True

    def invest_post():
        names = post_invest(tg, state, kt, today)
        if names:
            remember_invest(state, today, names)
        return bool(names)

    def online():
        n = fetch_online()
        return send_online(tg, online_text(state, n, now)).get("ok")

    for name, fn in (("📰 новость Steam", news), ("🐦 пост Valve из X", x_post),
                     ("💬 сообщество", community), ("🎨 мастерская", workshop),
                     ("💹 цены", prices), ("💼 инвестиции", invest_post),
                     ("👥 онлайн", online)):
        try:
            ok = fn()
        except Exception as e:
            print(f"{name}: ошибка —", e)
            ok = False
        done.append(f"{'✅' if ok else '—'} {name}")
        time.sleep(3)
    print("Запуск канала:\n" + "\n".join(done))


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
    if os.environ.get("CS2_DEMO_WORKSHOP") == "1":
        demo_workshop()
        return
    if os.environ.get("CS2_DEMO_COMMUNITY") == "1":
        demo_community()
        return
    if os.environ.get("CS2_DEMO_FORMATS") == "1":
        demo_formats()
        return
    dry = os.environ.get("CS2_DRY") == "1"
    state = load_state()
    bot._RECENT[:] = state.get("recent_phrases", [])
    tg = bot.Telegram(token, channel, dry_run=dry)
    if os.environ.get("CS2_LAUNCH") == "1":
        launch(tg, state, now)
        if not dry:
            save_state(state)
        return
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
    try:
        workshop_tick(tg, state, now)
    except Exception as e:
        print("Мастерская не вышла:", e)
    try:
        community_tick(tg, state, now)
    except Exception as e:
        print("Сообщество не вышло:", e)
    now_formats = ("skin", "case", "duel", "report") if os.environ.get(
        "CS2_FORMATS_NOW") == "1" else ()
    formats_tick(tg, state, now_formats)
    if not dry:
        save_state(state)


if __name__ == "__main__":
    main()
