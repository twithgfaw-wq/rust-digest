#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust Digest Bot — автоматическая сводка новостей по игре Rust в Telegram.

Что делает за один прогон:
  1. Берёт свежие ОФИЦИАЛЬНЫЕ новости Rust из Steam News API.
  2. Берёт топ "крутых работ" из r/playrust (базы, билды, арт, моменты).
  3. Берёт ЛУЧШИЕ видео дня у YouTube-блогеров по Rust (по просмотрам).
  4. Мастерская Steam: работы "мастеров" постит сразу отдельно; плюс
     конкурс — коллаж из 5 скинов РАЗНЫХ авторов с голосованием.
  5. Публикует всё это в твой Telegram-канал в едином стиле.

Английские заголовки автоматически переводятся на русский.

Только стандартная библиотека Python 3; для коллажа нужен Pillow.
"""

import random
import argparse
import configparser
import datetime
import html
import io
import json
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

RUST_APPID = 252490
UA = "RustDigestBot/1.0 (personal Telegram digest)"
STATE_FILE = "posted_state.json"   # чтобы не постить одно и то же дважды

# --- единый фирменный стиль постов (в духе офиц. страницы Rust) ---
BRAND = "\U0001f7e5"                 # 🟥 — красная метка, акцент Rust
DIVIDER = "━" * 13              # ━━━━━━━━━━━━━ разделитель
CHANNEL_TAG = "@rust_news_Pro"       # подпись в футере (обновляется в main)
NEWS_BANNER = ("https://cdn.cloudflare.steamstatic.com/steam/apps/"
               "252490/header.jpg")  # фирменная шапка Rust для новостей

# YouTube-блогеры по Rust: (отображаемое имя, channel_id).
# Чтобы добавить блогера — пришли ссылку на его канал, впишу сюда ID.
YT_CHANNELS = [
    ("Hedge", "UCftwbY3DWqa5QWxZtA_BuvQ"),
    ("Shadowfrax", "UCRsrOaKEdy0ymNqR7Urqa2Q"),
    ("Jfarr", "UCKfZk_0k5C7WajsNeHXtASw"),
]

# Видео блогеров берём только про Rust — проверяем по ключевым словам
# в заголовке (чтобы не постить их ролики про другие игры).
RUST_KEYWORDS = ("rust", "раст", "facepunch", "фейспанч", "wipe", "вайп",
                 "devblog", "девблог", "roam", "zerg")

# «Мастер» — автор, у которого в свежем списке принятых не меньше
# ELITE_MIN скинов. Его новые работы постим сразу, отдельными постами.
ELITE_MIN = 25
ELITE_MAX_PER_RUN = 3    # сколько работ мастеров постить за один прогон

# ---------- вспомогательное ----------

def http_get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted_ids": []}

def save_state(state):
    try:
        state["posted_ids"] = state.get("posted_ids", [])[-500:]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Не смог сохранить состояние:", e)

def clean(text, limit=None):
    t = html.unescape(text or "").strip()
    if limit and len(t) > limit:
        t = t[:limit - 1].rstrip() + "…"
    return t

# ---------- перевод на русский ----------

def is_mostly_cyrillic(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return cyr / len(letters) > 0.3

def translate_to_ru(text):
    """Переводит английский текст на русский. Если текст уже русский
    или перевод не удался — возвращает исходный."""
    text = (text or "").strip()
    if not text or is_mostly_cyrillic(text):
        return text
    q = urllib.parse.quote(text)

    # 1) основной: бесплатный endpoint Google Translate
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               f"?client=gtx&sl=auto&tl=ru&dt=t&q={q}")
        data = http_get_json(url, timeout=15)
        segs = data[0] or []
        out = "".join(s[0] for s in segs if s and s[0]).strip()
        if out:
            return out
    except Exception:
        pass

    # 2) запасной: MyMemory
    try:
        url = (f"https://api.mymemory.translated.net/get?q={q}"
               f"&langpair=en|ru")
        data = http_get_json(url, timeout=15)
        out = data.get("responseData", {}).get("translatedText", "")
        if out and "MYMEMORY WARNING" not in out.upper():
            return html.unescape(out).strip()
    except Exception:
        pass

    return text  # не смогли перевести — оставляем как есть

# ---------- источники контента ----------

def fetch_official_news(count=3):
    """Официальные новости Rust из Steam News API."""
    url = (f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
           f"?appid={RUST_APPID}&count={count}&maxlength=400&format=json")
    try:
        data = http_get_json(url)
        items = data.get("appnews", {}).get("newsitems", [])
    except Exception as e:
        print("Новости Steam не загрузились:", e)
        return []
    out = []
    for it in items:
        title_ru = translate_to_ru(clean(it.get("title"), 200))
        out.append({
            "id": "news_" + str(it.get("gid")),
            "title": clean(title_ru, 120),
            "url": it.get("url"),
            "date": it.get("date", 0),
        })
    return out

def fetch_top_works(period="day", limit=12, min_score=300):
    """Топ постов r/playrust — базы, билды, арт, моменты."""
    t = "day" if period not in ("day", "week") else period
    url = (f"https://www.reddit.com/r/playrust/top.json"
           f"?t={t}&limit={limit}")
    try:
        data = http_get_json(url, headers={"User-Agent": UA})
        children = data.get("data", {}).get("children", [])
    except urllib.error.HTTPError as e:
        print(f"Reddit вернул {e.code}. Если это 429/403 — он режет "
              f"запросы; попробуй позже или реже. Работы пропущены.")
        return []
    except Exception as e:
        print("Reddit не загрузился:", e)
        return []

    works = []
    for ch in children:
        d = ch.get("data", {})
        if d.get("stickied") or d.get("over_18"):
            continue
        if d.get("score", 0) < min_score:
            continue
        img = pick_image(d)
        if not img:
            continue  # нам нужны именно "работы" с картинкой
        works.append({
            "id": "work_" + str(d.get("id")),
            "title": translate_to_ru(clean(d.get("title"), 200)),
            "author": clean(d.get("author"), 40),
            "score": d.get("score", 0),
            "flair": clean(d.get("link_flair_text"), 30),
            "image": img,
            "url": "https://reddit.com" + d.get("permalink", ""),
        })
    return works

def is_rust_video(title):
    t = (title or "").lower()
    return any(k in t for k in RUST_KEYWORDS)

def fetch_youtube(channels, max_age_days=4):
    """Видео блогеров за последние max_age_days дней — ТОЛЬКО про Rust,
    с числом просмотров из RSS. Возвращает отсортированными по просмотрам
    (лучшие первыми), чтобы постить только топовые, а не всё подряд."""
    atom = "{http://www.w3.org/2005/Atom}"
    ytns = "{http://www.youtube.com/xml/schemas/2015}"
    media = "{http://search.yahoo.com/mrss/}"
    now = time.time()
    out = []
    for name, cid in channels:
        try:
            url = ("https://www.youtube.com/feeds/videos.xml?channel_id="
                   + cid)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            print(f"YouTube не загрузился ({name}):", e)
            continue
        for entry in root.findall(atom + "entry"):
            vid_el = entry.find(ytns + "videoId")
            title_el = entry.find(atom + "title")
            pub_el = entry.find(atom + "published")
            if vid_el is None or title_el is None:
                continue
            import re
            # хэштеги из названия (#shorts #fyp …) в посте не нужны
            title = re.sub(r"\s*#\w+", "", title_el.text or "").strip()
            pub = pub_el.text if pub_el is not None else ""
            # 1) только свежие
            try:
                dt = datetime.datetime.fromisoformat(
                    pub.replace("Z", "+00:00"))
                if (now - dt.timestamp()) / 86400 > max_age_days:
                    continue
            except Exception:
                pass
            # 2) только про Rust
            if not is_rust_video(title):
                continue
            # 3) число просмотров (для выбора лучших)
            views = 0
            grp = entry.find(media + "group")
            comm = grp.find(media + "community") if grp is not None else None
            stat = comm.find(media + "statistics") if comm is not None else None
            if stat is not None:
                try:
                    views = int(stat.get("views") or 0)
                except ValueError:
                    views = 0
            vid = vid_el.text
            out.append({
                "id": "yt_" + vid,
                "title": translate_to_ru(clean(title, 200)),
                "author": name,
                "views": views,
                "url": "https://www.youtube.com/watch?v=" + vid,
                "image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "published": pub,
            })
    out.sort(key=lambda x: x["views"], reverse=True)
    return out

def resolve_steam_names(api_key, steamids):
    """SteamID -> ник автора. GetPlayerSummaries берёт до 100 за раз,
    поэтому режем на пачки."""
    uniq = sorted({str(s) for s in steamids if s})
    out = {}
    for i in range(0, len(uniq), 100):
        batch = ",".join(uniq[i:i + 100])
        url = ("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/"
               f"v2/?key={api_key}&steamids={batch}")
        try:
            data = http_get_json(url, timeout=15)
            for p in data.get("response", {}).get("players", []):
                out[p.get("steamid")] = p.get("personaname", "")
        except Exception:
            pass
    return out

def _query_files(api_key, query_type, per, cursor):
    url = ("https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
           f"?key={api_key}&appid={RUST_APPID}&query_type={query_type}"
           f"&numperpage={per}&cursor={urllib.parse.quote(cursor)}"
           "&return_previews=true&return_metadata=true&requiredtags%5B0%5D=Skin")
    return http_get_json(url, timeout=20).get("response", {})

def fetch_accepted_authors(api_key, pages=10, per=100):
    """Сколько принятых в игру скинов у каждого автора (по свежему
    списку принятых). dict author_id -> count. Ключи = проверенные
    авторы; большой count = «мастер»."""
    counts, cursor = {}, "*"
    for _ in range(pages):
        try:
            resp = _query_files(api_key, 2, per, cursor)
        except Exception as e:
            print("Список принятых не загрузился:", e)
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            c = it.get("creator")
            if c:
                counts[str(c)] = counts.get(str(c), 0) + 1
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    return counts

def fetch_new_submissions(api_key, pages=6, per=50, max_age_days=14):
    """Все свежие НОВЫЕ заявки скинов (query_type=1), новейшие первыми."""
    out, cursor, seen = [], "*", set()
    now = time.time()
    for _ in range(pages):
        try:
            resp = _query_files(api_key, 1, per, cursor)
        except Exception as e:
            print("Новые заявки не загрузились:", e)
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            pid = it.get("publishedfileid")
            preview = it.get("preview_url")
            title = it.get("title")
            if not pid or not preview or not title or pid in seen:
                continue
            tc = it.get("time_created", 0) or 0
            if tc and (now - tc) / 86400 > max_age_days:
                continue
            seen.add(pid)
            out.append({
                "id": "ws_" + str(pid),
                "title_raw": title,
                "author_id": str(it.get("creator") or ""),
                "author": "",
                "image": preview,
                "created": tc,
                "url": ("https://steamcommunity.com/sharedfiles/filedetails/"
                        "?id=" + str(pid)),
            })
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    out.sort(key=lambda x: x["created"], reverse=True)
    return out

def fetch_top_week(api_key, per=30):
    """Самые популярные скины недели (по голосам, RankedByTrend за 7 дней)."""
    url = ("https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
           f"?key={api_key}&appid={RUST_APPID}&query_type=3&days=7"
           f"&numperpage={per}&cursor=*"
           "&return_previews=true&return_metadata=true&requiredtags%5B0%5D=Skin")
    try:
        items = http_get_json(url, timeout=20).get("response", {}).get(
            "publishedfiledetails", [])
    except Exception as e:
        print("Топ недели не загрузился:", e)
        return []
    return [{"id": "ws_" + str(it["publishedfileid"]),
             "title_raw": it.get("title") or "",
             "author_id": str(it.get("creator") or ""),
             "author": "",
             "image": it.get("preview_url") or "",
             "url": ("https://steamcommunity.com/sharedfiles/filedetails/"
                     "?id=" + str(it["publishedfileid"]))}
            for it in items
            if it.get("publishedfileid") and it.get("title")
            and it.get("preview_url")]

def fetch_accepted_pids(api_key, pages=10, per=100):
    """ID (ws_...) скинов, которые УЖЕ приняли в игру — для подсчёта,
    кто из голосовавших угадал."""
    pids, cursor = set(), "*"
    for _ in range(pages):
        try:
            resp = _query_files(api_key, 2, per, cursor)
        except Exception:
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            p = it.get("publishedfileid")
            if p:
                pids.add("ws_" + str(p))
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    return pids

def fetch_recent_accepted(api_key, pages=2, per=100):
    """Принятые в игру скины (query_type=2), последние принятые первыми —
    с названием, автором и картинкой, для поста «кого приняли»."""
    out, cursor = [], "*"
    for _ in range(pages):
        try:
            resp = _query_files(api_key, 2, per, cursor)
        except Exception as e:
            print("Принятые скины не загрузились:", e)
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            pid = it.get("publishedfileid")
            if not pid:
                continue
            out.append({
                "id": "ws_" + str(pid),
                "title_raw": it.get("title") or "",
                "author_id": str(it.get("creator") or ""),
                "author": "",
                "image": it.get("preview_url") or "",
                "url": ("https://steamcommunity.com/sharedfiles/filedetails/"
                        "?id=" + str(pid)),
            })
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    return out

def pick_image(d):
    """Достаём прямую ссылку на картинку из поста Reddit."""
    # 1) прямая ссылка на картинку
    u = d.get("url_overridden_by_dest") or d.get("url") or ""
    if u.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
        return u
    # 2) превью из preview
    try:
        src = d["preview"]["images"][0]["source"]["url"]
        return html.unescape(src)
    except Exception:
        pass
    # 3) галерея / медиа-метаданные
    try:
        for m in d.get("media_metadata", {}).values():
            if m.get("e") == "Image":
                return html.unescape(m["s"]["u"])
    except Exception:
        pass
    return None

# ---------- отправка в Telegram ----------

class Telegram:
    def __init__(self, token, chat, dry_run=False):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat = chat
        self.dry_run = dry_run

    def _post(self, method, params):
        if self.dry_run:
            print(f"[dry-run] {method}: "
                  f"{clean(params.get('text') or params.get('caption'), 160)}")
            return {"ok": True}
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/{method}", data=data,
                                     headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read().decode("utf-8", "replace"))
            if not res.get("ok"):
                print("Telegram ошибка:", res)
            return res
        except urllib.error.HTTPError as e:
            print("Telegram HTTP ошибка:", e.code, e.read().decode("utf-8", "replace"))
            return {"ok": False}
        except Exception as e:
            print("Telegram не ответил:", e)
            return {"ok": False}

    def send_message(self, text):
        return self._post("sendMessage", {
            "chat_id": self.chat, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "false",
        })

    def send_photo(self, photo_url, caption):
        return self._post("sendPhoto", {
            "chat_id": self.chat, "photo": photo_url,
            "caption": caption, "parse_mode": "HTML",
        })

    def send_photo_file(self, file_path, caption, reply_markup=None):
        """Отправка локальной картинки (коллажа) + подпись + кнопки —
        всё одним постом. Нужен multipart/form-data."""
        if self.dry_run:
            print(f"[dry-run] sendPhoto(file): {clean(caption, 120)}")
            return {"ok": True}
        try:
            with open(file_path, "rb") as f:
                img = f.read()
        except Exception:
            return {"ok": False}
        boundary = "----RustBot" + str(int(time.time() * 1000))
        fields = {"chat_id": str(self.chat), "caption": caption,
                  "parse_mode": "HTML"}
        if reply_markup:
            fields["reply_markup"] = reply_markup
        head = "".join(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"{k}\"\r\n\r\n{v}\r\n" for k, v in fields.items()
        ).encode("utf-8")
        filehead = (f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"photo\"; filename=\"c.jpg\"\r\n"
                    f"Content-Type: image/jpeg\r\n\r\n").encode("utf-8")
        body = head + filehead + img + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/sendPhoto", data=body,
            headers={"User-Agent": UA,
                     "Content-Type":
                         f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8", "replace"))
            if not res.get("ok"):
                print("Telegram ошибка (коллаж):", res)
            return res
        except Exception as e:
            print("Telegram не принял коллаж:", e)
            return {"ok": False}

    def send_media_group(self, photo_urls, caption):
        """Один пост-альбом из нескольких фото. Подпись — на первом фото."""
        media = []
        for i, u in enumerate(photo_urls[:10]):
            item = {"type": "photo", "media": u}
            if i == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media.append(item)
        if self.dry_run:
            print(f"[dry-run] sendMediaGroup ({len(media)} фото): "
                  f"{clean(caption, 160)}")
            return {"ok": True}
        return self._post("sendMediaGroup", {
            "chat_id": self.chat, "media": json.dumps(media),
        })

    def send_vote_buttons(self, text, labels, rid):
        """Запасной путь: отдельное сообщение с кнопками (если коллаж не
        собрался). Номера + кнопка подтверждения."""
        kb = {"inline_keyboard": [
            [{"text": lbl, "callback_data": f"v{rid}_{i}"}
             for i, lbl in enumerate(labels)],
            [{"text": "✅ Подтвердить голос", "callback_data": f"c{rid}"}]]}
        if self.dry_run:
            print(f"[dry-run] голосование (кнопки): {clean(text, 120)}")
            return {"ok": True}
        return self._post("sendMessage", {
            "chat_id": self.chat, "text": text, "parse_mode": "HTML",
            "reply_markup": json.dumps(kb, ensure_ascii=False),
        })

    def get_updates(self, offset):
        """Получаем обновления бота (нам нужны нажатия — callback_query)."""
        if self.dry_run:
            return []
        params = {"timeout": "0",
                  "allowed_updates": json.dumps(["callback_query"])}
        if offset:
            params["offset"] = str(offset)
        res = self._post("getUpdates", params)
        return res.get("result", []) if isinstance(res, dict) else []

    def answer_callback(self, cq_id, text):
        """Всплывашка-подтверждение в ответ на нажатие. Сработает только
        если бот успел ответить за пару секунд после нажатия (при запуске
        раз в 30 мин обычно не успевает) — поэтому ошибки глотаем тихо."""
        if self.dry_run or not cq_id:
            return
        try:
            data = urllib.parse.urlencode(
                {"callback_query_id": cq_id, "text": text}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base}/answerCallbackQuery", data=data,
                headers={"User-Agent": UA})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            pass

    def edit_caption(self, message_id, caption):
        """Меняем подпись уже отправленного поста — для живого счётчика
        голосов под конкурсом."""
        if self.dry_run or not message_id:
            return {"ok": True}
        return self._post("editMessageCaption", {
            "chat_id": self.chat, "message_id": str(message_id),
            "caption": caption, "parse_mode": "HTML",
        })

# ---------- сборка постов ----------
# Пишем живо, как в больших фан-каналах: цепляющий заход с эмоцией, пара
# слов от себя, ссылки и подпись. У каждого типа поста несколько вариантов
# фраз — каждый раз берём случайный, чтобы лента не выглядела под копирку.
# Смысл и хэштеги при этом не меняются.

def today_str():
    return time.strftime("%d.%m.%Y")

# Чтобы посты не были одинаковыми, текст собирается из частей (заход,
# заголовок, концовка, подпись) — получаются тысячи сочетаний. А ещё бот
# помнит недавно выпавшие фразы (state["recent_phrases"]) и не берёт их снова,
# пока не выйдет хотя бы половина остальных вариантов из того же списка.
_RECENT = []

def pick(options):
    used = [r for r in _RECENT if r in options]
    ban = set(used[-(len(options) // 2):]) if len(options) > 1 else set()
    choice = random.choice([o for o in options if o not in ban] or list(options))
    _RECENT.append(choice)
    del _RECENT[:-500]
    return choice

FOOTERS = [
    "👉 Подписывайся на {tag}",
    "🔔 Больше Rust — в {tag}",
    BRAND + " {tag} — всё о Rust",
    "📢 Подписывайся: {tag}",
    "🪓 Свежий Rust каждый день — {tag}",
    "📡 Не пропусти важное: {tag}",
    "🔥 {tag} — Rust без воды",
    "👀 Следи за Rust вместе с {tag}",
    "⚡️ Всё самое свежее по Rust — {tag}",
    "🛡 Твой канал про Rust — {tag}",
    "🎮 Новости, скины и видео по Rust — {tag}",
    "📌 Сохрани себе {tag}",
]

def frame(kicker, title, body, hashtags):
    """Каркас поста: цепляющий заход жирным, заголовок, тело, подпись
    канала и хэштеги. body — уже готовый HTML (не экранируем)."""
    parts = [f"<b>{kicker}</b>"]
    if title:
        parts.append(html.escape(title))
    parts += ["", body, "", pick(FOOTERS).format(tag=CHANNEL_TAG), hashtags]
    return "\n".join(parts)

NEWS_HOOKS = [
    "🛠 Facepunch снова что-то накрутили — свежие новости Rust",
    "📢 ВАЖНОЕ ИЗ RUST — читаем, пока не вайпнуло",
    "👀 Разработчики подкинули новостей, разбираем",
    "⚡️ Пока вы фармили серу, Facepunch выкатили новости",
    "🗞 СВЕЖАК ОТ РАЗРАБОТЧИКОВ RUST",
    "📰 Новости Rust подъехали — делимся",
    "🔔 Facepunch опубликовали новое — смотрим",
    "🧐 Что там у Facepunch? Свежие новости",
    "🚨 НОВОСТИ RUST: есть что обсудить",
    "📣 Разработчики Rust вышли на связь",
    "🛎 Свежие вести с острова от Facepunch",
    "🗒 Facepunch поделились новостями — коротко о главном",
    "☕️ Новости Rust к вашему кофе",
    "🔧 Facepunch не дремлют — новости по Rust",
    "🏝 С острова пришли новости — читаем",
    "💬 Facepunch снова на связи: что нового в Rust",
    "📦 Свежая порция новостей от разработчиков Rust",
    "🧭 Главное из Rust прямо сейчас",
]
NEWS_OUTROS = [
    "Что думаете — к лучшему? 🤔", "Ставь 🔥, если ждал",
    "Готовимся к вайпу 🪓", "Ждём подробностей 👀",
    "Ставь 👍, если полезно", "Интересно, как это скажется на вайпе 🤔",
    "Берём на заметку 📌", "Посмотрим, что из этого выйдет 😏",
    "Facepunch, мы следим 👀", "Неплохо, неплохо 😎", "", "",
]
NEWS_BULLETS = ["🔹", "📌", "▪️", "➤", "🔸", "▫️"]

def build_news_caption(news):
    bullet = pick(NEWS_BULLETS)
    body = "\n".join(
        f"{bullet} <a href=\"{n['url']}\">{html.escape(n['title'])}</a>"
        for n in news)
    outro = pick(NEWS_OUTROS)
    if outro:
        body += f"\n\n{outro}"
    return frame(pick(NEWS_HOOKS), f"🗓 {today_str()}", body,
                 "#rust #раст #новости")

FLAIR_EMOJI = {
    "Base Design": "🏰", "Image": "🖼", "Video": "🎬",
    "Work in Progress": "🔨", "Art": "🎨", "Discussion": "💬",
}
WORK_HOOKS = [
    "😳 Игроки опять строят невозможное", "🔥 РАБОТА ДНЯ С R/PLAYRUST",
    "👏 Сообщество снова удивляет", "🏆 Такое не каждый день увидишь",
    "🤯 Reddit снова выдал шедевр", "👀 Нашли на r/playrust — зацените",
    "🎨 Творчество игроков Rust, которое стоит увидеть",
    "💪 Вот это уровень, сообщество", "📸 Кадр дня от игроков Rust",
    "🧱 Когда в Rust есть фантазия и время", "🌟 Лучшее от сообщества за сегодня",
    "😮 Игроки Rust не перестают удивлять",
]

def build_work_caption(w, index):
    hook = pick(WORK_HOOKS)
    if w["flair"]:
        emoji = FLAIR_EMOJI.get(w["flair"], "🔥")
        hook += f" · {emoji} {html.escape(w['flair'])}"
    body = (f"👤 u/{html.escape(w['author'])}   ⬆️ {w['score']}\n"
            f"💬 <a href=\"{w['url']}\">Обсуждение на Reddit</a>")
    return frame(hook, w["title"], body, "#rust #раст #работы")

def fmt_views(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n // 1000}K"
    return str(n)

VIDEO_HOOKS = [
    "🎬 У {author} новый ролик — и он того стоит",
    "🍿 Есть что посмотреть вечером: новое видео от {author}",
    "📺 {author} снова в деле",
    "🔥 ЛУЧШЕЕ ВИДЕО ДНЯ — ОТ {author}",
    "▶️ Новое видео от {author} — включаем",
    "🍿 Запасайтесь попкорном: свежий ролик от {author}",
    "📺 Свежее видео от {author} уже на YouTube",
    "🎥 {author} снова радует новым роликом",
    "🎬 Время для просмотра: новинка от {author}",
    "👀 У {author} вышло новое видео — смотрим",
    "⚡️ Только вышло: свежее видео от {author}",
    "🏆 Видео дня по Rust — {author}",
    "🎞 Новый ролик на канале {author}",
    "📡 {author} снова на связи — новое видео",
    "😎 Свежий контент по Rust от {author}",
    "🔥 Не пропустите: новое видео {author}",
]
VIDEO_OUTROS = ["Приятного просмотра 🍿", "Ставь 🔥, если зашло",
                "Отличный повод отвлечься от фарма 😄", "Кто уже посмотрел? 👀",
                "Годнота, рекомендуем 👍", "", ""]

def build_video_caption(v):
    hook = pick(VIDEO_HOOKS).format(author=html.escape(v["author"]))
    views = f"   👁 {fmt_views(v['views'])}" if v.get("views") else ""
    body = f"📹 <a href=\"{v['url']}\">YouTube</a>{views}"
    outro = pick(VIDEO_OUTROS)
    if outro:
        body += f"\n\n{outro}"
    return frame(hook, v["title"], body, "#rust #раст #видео")

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣",
             "5️⃣", "6️⃣", "7️⃣", "8️⃣",
             "9️⃣", "\U0001f51f"]

CONTEST_HOOKS = [
    "🎯 КОНКУРС: УГАДАЕТЕ, КАКОЙ СКИН ПРИМУТ В ИГРУ?",
    "🎲 КОНКУРС — пять новых скинов, а в игру попадёт не каждый",
    "🤔 КОНКУРС: Facepunch отберут не всех. Ваш прогноз?",
    "🏆 КОНКУРС: какой из этих скинов окажется в игре?",
    "🔮 КОНКУРС — включаем интуицию: что примут Facepunch?",
    "🎯 КОНКУРС НЕДЕЛИ: угадай будущий скин Rust",
    "🧠 КОНКУРС: проверим, кто лучше чувствует вкус Facepunch",
    "🎰 КОНКУРС — пять скинов, одна ставка. Твой выбор?",
    "👀 КОНКУРС: какой скин, по-твоему, попадёт в магазин?",
    "🥇 КОНКУРС: угадай скин, который примут в игру",
    "🎲 КОНКУРС — делай прогноз, итоги в воскресенье",
    "🤝 КОНКУРС: выбираем фаворита среди новинок воркшопа",
]
CONTEST_TITLES = [
    "5 новых работ — у каждого свой автор",
    "Пять свежих скинов от пяти разных авторов",
    "5 новинок воркшопа — 5 разных авторов",
    "Пять работ, пять авторов, один фаворит",
    "Свежие работы из мастерской — выбирай фаворита",
]
CONTEST_CTAS = [
    "Жми номер, затем «Подтвердить» 👇 Итоги — в воскресенье 🏆",
    "Выбирай номер и подтверждай 👇 Угадавших покажем в конце недели 🥇",
    "Ставь на фаворита: номер → «Подтвердить» 👇 Рейтинг — в воскресенье 📊",
    "Номер → «Подтвердить» 👇 Кто угадает — попадёт в рейтинг недели 🏆",
    "Голосуй кнопками ниже 👇 Результаты — в воскресенье 📊",
    "Выбери номер и не забудь подтвердить 👇 Итоги подведём в воскресенье 🥇",
    "Твой прогноз — кнопкой ниже 👇 В воскресенье узнаем, кто был прав 🔮",
    "Жми на номер фаворита и подтверждай 👇 Лучших отметим в итогах 🏆",
    "Один голос — один номер 👇 Не забудь «Подтвердить» ✅",
]

def build_workshop_caption(skins):
    lines = []
    for i, s in enumerate(skins):
        title = html.escape(translate_to_ru(clean(s["title_raw"], 80)))
        author = html.escape(s["author"] or "автор неизвестен")
        lines.append(f"{NUM_EMOJI[i]} <b>{title}</b> — {author}")
    lines.append("")
    lines.append(pick(CONTEST_CTAS))
    return frame(pick(CONTEST_HOOKS), pick(CONTEST_TITLES),
                 "\n".join(lines), "#rust #раст #скины #конкурс")

ELITE_EMOJI = ["🔥", "💎", "😮", "👀", "🎨", "⚡️", "✨", "🤩", "💥", "🖌", "🏆", "😍"]
SEPS = [": ", " — "]
ELITE_PHRASES = [
    "свежая работа", "выглядит дорого", "вот это детализация", "зацените",
    "новинка, которая цепляет", "такое хочется в игру", "автор знает толк",
    "качество на уровне", "глаз не оторвать", "чистая эстетика",
    "сильная работа", "просто посмотрите на это", "стильно и со вкусом",
    "всё продумано до мелочей", "годнота подъехала", "красиво сделано",
    "смотрится как официальный скин", "детали решают", "вот это уровень",
    "очень достойно", "эффектно, ничего не скажешь", "мимо такого не пройти",
    "свежий взгляд на привычную вещь", "аккуратно и со вкусом",
    "красота в деталях", "мощно сделано", "вот это я понимаю скин",
    "свежак из мастерской", "такое мы любим", "сделано с душой",
    "достойно магазина", "топовая работа", "хочется в инвентарь",
    "выглядит свежо", "атмосферно вышло", "новый фаворит",
]
SET_PHRASES = [
    "сразу комплект", "целый сет от автора", "выглядят дорого",
    "комплект, который хочется целиком", "набор в одном стиле",
    "автор выкатил сет", "сразу несколько новинок",
    "сет, который смотрится вместе", "зацените весь набор",
    "всё в одном стиле", "обновка комплектом", "вот это сет",
    "полный комплект от одного автора", "стильный набор",
    "детализация во всём сете", "несколько работ, одна идея",
    "сет, мимо которого не пройти",
]
ELITE_OUTROS = [
    "Как думаете, добавят в игру? 🤔", "Ставь 🔥, если хочешь такой в игре",
    "Берём или пропускаем? 👀", "Купили бы такой? 💸", "Ставь 👍, если зашло",
    "Достоин магазина? Ставь 🔥", "Ждём в игре? 👀",
    "Facepunch, обратите внимание 😏", "Такой бы в инвентарь 😎",
    "Оценим реакциями: 🔥 или 👎?", "Красиво же? 😍", "В магазин его! 🛒",
    "Как вам такой скин? 🤔", "Примут или нет — ваш прогноз? 🔮",
]
SET_OUTROS = [
    "Какой из них забрали бы себе? 🤔", "Ставь 🔥, если хочешь этот сет в игре",
    "Как думаете, примут весь набор? 🤔", "Целиком или по частям? 🛒",
    "Ставь 👍, если сет зашёл", "Достоин магазина? Ставь 🔥",
    "Facepunch, берите весь комплект 😏", "Какой вариант нравится больше? 🔥",
    "Красиво же вместе смотрится? 😍",
]
SET_TITLES = [
    "Сразу {n} {works} от одного автора", "{n} {works} в одном посте",
    "Комплект из {n} работ", "Подборка за неделю: {n} {works}",
    "Целый сет — {n} {works}",
]

def elite_hook(phrases):
    return f"{pick(ELITE_EMOJI)} ЛУЧШЕЕ ИЗ ВОРКШОПА{pick(SEPS)}{pick(phrases)}"

def build_elite_caption(s):
    title = translate_to_ru(clean(s["title_raw"], 90))
    body = (f"🎨 <b>{html.escape(s['author'] or 'автор')}</b>\n"
            f"🔗 <a href=\"{s['url']}\">Мастерская Steam</a>\n\n"
            f"{pick(ELITE_OUTROS)}")
    return frame(elite_hook(ELITE_PHRASES), title, body,
                 "#rust #раст #воркшоп #скин")

# «Лучшее из воркшопа» — по графику: ELITE_SLOTS раз в день (часы по Киеву).
# Пропущенный слот не догоняем: если GitHub запустил бота поздно, выйдет
# один пост, а не пачка.
ELITE_SLOTS = (11, 16, 21)

def elite_slot():
    """Последний наступивший сегодня слот ('ГГГГ-ММ-ДД-час' по Киеву)
    или '' — если первый слот дня ещё не наступил."""
    kt = kyiv_time()
    hours = [h for h in ELITE_SLOTS if h <= kt.hour]
    return f"{kt:%Y-%m-%d}-{hours[-1]}" if hours else ""

ELITE_FRESH_D = (3, 7)   # свежесть работ: сначала за 3 дня, не хватает — за 7

def pick_elite_sets(newest, counts, posted, skip, now):
    """До ELITE_BATCH разных авторов, у которых уже есть принятые в игру
    скины (у кого больше — те первые), у каждого до 3 его свежих работ:
    сначала за 3 дня, если авторов не хватает — за неделю. skip — то, что
    уже было в канале иначе (принятые скины, топ-3 недели)."""
    sets, used = [], set()
    for days in ELITE_FRESH_D:
        by = {}
        for s in newest:
            a = s["author_id"]
            if (not counts.get(a) or a in used or s["id"] in posted
                    or s["id"] in skip or s["url"] in skip
                    or now - (s.get("created") or 0) > days * 86400):
                continue
            by.setdefault(a, []).append(s)
        for a in sorted(by, key=lambda a: -counts[a]):
            if len(sets) >= ELITE_BATCH:
                break
            used.add(a)
            sets.append(by[a][:3])
    return sets

def build_elite_set_caption(works):
    n = len(works)
    lines = [f"🎨 <b>{html.escape(works[0]['author'] or 'автор')}</b>", ""]
    for i, s in enumerate(works):
        name = html.escape(translate_to_ru(clean(s["title_raw"], 60)))
        lines.append(f"{NUM_EMOJI[i]} <a href=\"{s['url']}\">{name}</a>")
    lines += ["", pick(SET_OUTROS)]
    title = pick(SET_TITLES).format(
        n=n, works=plural(n, "работа", "работы", "работ"))
    return frame(elite_hook(SET_PHRASES), title, "\n".join(lines),
                 "#rust #раст #воркшоп #скин")

# «Лучшее из воркшопа» пачкой: один пост сразу на несколько авторов.
ELITE_BATCH = 3           # авторов в одном посте
TRIO_PHRASES = [
    "подборка свежих работ", "свежий улов из мастерской", "что выкатили авторы",
    "горячая подборка", "новинки, которые цепляют", "новые работы недели",
]
TRIO_ONLY = ["сразу три автора", "тройка новинок", "три автора — три стиля"]
TRIO_TITLES = ["Свежие работы от {n} {a_gen}", "Подборка мастерской: {k} {works}",
               "Новинки от {n} {a_gen} — {k} {works}"]

def build_elite_digest_caption(sets):
    """Один пост на несколько авторов: у каждого — его новые работы."""
    lines = []
    for i, works in enumerate(sets):
        lines.append(f"{NUM_EMOJI[i]} <b>{html.escape(works[0]['author'] or 'автор')}</b>")
        for s in works:
            name = html.escape(translate_to_ru(clean(s["title_raw"], 45)))
            lines.append(f"   ▫️ <a href=\"{s['url']}\">{name}</a>")
    lines += ["", pick(SET_OUTROS)]
    n, k = len(sets), sum(len(w) for w in sets)
    title = pick(TRIO_TITLES).format(
        n=n, a_gen=plural(n, "автора", "авторов", "авторов"),
        k=k, works=plural(k, "работа", "работы", "работ"))
    return frame(elite_hook(TRIO_PHRASES + (TRIO_ONLY if n == 3 else [])), title, "\n".join(lines),
                 "#rust #раст #воркшоп #скин")

# Тихие часы по Киеву: конкурс и «Лучшее из воркшопа» ночью не постим —
# они копятся и выходят утром. Новости и принятые скины — без ограничений.
QUIET_FROM, QUIET_TO = 0, 9

def quiet_now():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo("Europe/Kyiv")).hour
    except Exception:
        hour = (time.gmtime().tm_hour + 3) % 24
    return QUIET_FROM <= hour < QUIET_TO

def plural(n, one, few, many):
    """Русское окончание по числу: 1 работа, 2 работы, 5 работ."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many

ACCEPT_HOOKS = [
    "✅ FACEPUNCH ПРИНЯЛИ НОВЫЕ СКИНЫ В ИГРУ!",
    "🎉 Свежая партия скинов уже в игре",
    "🔥 ПРИНЯТО! Новые скины заехали в Rust",
    "🛒 Магазин Rust пополнился — вот кого приняли",
    "🎊 Facepunch добавили новые скины — кого приняли",
    "🏆 Новые скины в магазине Rust — поздравляем авторов",
    "🛍 Обновление магазина: эти работы теперь в игре",
    "✅ ПРИНЯТО В ИГРУ: свежий список",
    "🥳 Эти авторы попали в магазин Rust",
    "📦 Новая партия скинов уже в магазине",
    "🔥 Свежие скины заехали в магазин Rust",
    "🎉 Из мастерской — в магазин: новые принятые работы",
    "👏 Эти скины теперь официально в игре",
    "💰 Магазин обновился — вот что приняли",
]
ACCEPT_OUTROS = [
    "Поздравляем авторов 👏", "Кто уже присмотрел себе обновку? 👀",
    "Ставь 🔥 за любимый скин", "Что возьмёте первым? 🛒", "Заслуженно 👏",
    "Отличная партия, как вам? 🔥", "Поздравляем всех с принятием 🥳",
    "Есть фаворит в этой партии? 👀", "Магазин стал богаче 💰",
]

def build_accepted_caption(skins, contest_pids=(), limit=None):
    """Пост «кого приняли в игру»: авторы и все их принятые работы. Если
    текст не влезает в limit символов, хвост списка сворачиваем в
    «…и ещё N работ»."""
    by_author = {}
    for s in skins:
        by_author.setdefault(s["author"] or "автор неизвестен", []).append(s)
    blocks = []
    for author, items in by_author.items():
        lines = [f"👤 <b>{html.escape(author)}</b>"]
        lines += [f"   ▫️ <a href=\"{s['url']}\">{html.escape(s['title_ru'])}</a>"
                  for s in items]
        blocks.append("\n".join(lines))
    n, a = len(skins), len(by_author)
    title = (f"{n} {plural(n, 'работа', 'работы', 'работ')} от {a} "
             f"{plural(a, 'автора', 'авторов', 'авторов')}")
    tail = ""
    if any(s["id"] in contest_pids for s in skins):
        tail += ("\n\n🎯 Среди них есть скины из нашего конкурса — "
                 "итоги в воскресенье 🏆")
    tail += "\n\n" + pick(ACCEPT_OUTROS)
    hook = pick(ACCEPT_HOOKS)
    shown = len(blocks)
    while True:
        body = "\n\n".join(blocks[:shown])
        rest = sum(len(v) for v in list(by_author.values())[shown:])
        if rest:
            body += f"\n\n…и ещё {rest} {plural(rest, 'работа', 'работы', 'работ')}"
        text = frame(hook, title, body + tail, "#rust #раст #скины #принято")
        if limit is None or len(text) <= limit or shown == 1:
            return text
        shown -= 1

def post_new_accepts(tg, state, api_key):
    """Пост о свежепринятых в игру скинах. Первый запуск только запоминает
    уже принятые (иначе вывалили бы сотни старых), дальше постим новинки."""
    seen = state.get("accepted_seen")
    if seen is None:
        ids = [s["id"] for s in fetch_recent_accepted(api_key, pages=10)]
        if len(ids) >= 200:
            state["accepted_seen"] = ids[::-1]   # от старых к новым
        return
    known = set(seen)
    fresh = [s for s in fetch_recent_accepted(api_key)
             if s["id"] not in known]
    if not fresh:
        return
    if len(fresh) > 150:   # почти всё окно «новое» — сбой выдачи, не спамим
        print(f"Подозрительно много новых принятых ({len(fresh)}) — пропускаю.")
        state["accepted_seen"] = (seen + [s["id"] for s in fresh[::-1]])[-3000:]
        return
    names = resolve_steam_names(api_key, [s["author_id"] for s in fresh])
    for s in fresh:
        s["author"] = names.get(s["author_id"], "")
        s["title_ru"] = translate_to_ru(clean(s["title_raw"], 70))
    contest = {p for r in state.get("rounds", {}).values()
               for p in r.get("pids", [])}
    text = build_accepted_caption(fresh, contest)
    image = next((s["image"] for s in fresh if s["image"]), "")
    if image and len(text) <= 1024:
        res = tg.send_photo(image, text)
    else:
        res = tg.send_message(build_accepted_caption(fresh, contest, 4000))
    if res.get("ok"):
        state["accepted_seen"] = (seen + [s["id"] for s in fresh[::-1]])[-3000:]

# ---------- онлайн Rust и магазин недели ----------

def kyiv_time():
    """Текущее время по Киеву (летнее/зимнее учитывается)."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Kyiv"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=3)))

def fmt_num(n):
    return f"{n:,}".replace(",", " ")

def fetch_online():
    """Сколько людей прямо сейчас играет в Rust (Steam, ключ не нужен)."""
    url = ("https://api.steampowered.com/ISteamUserStats/"
           f"GetNumberOfCurrentPlayers/v1/?appid={RUST_APPID}")
    return int(http_get_json(url, timeout=15)["response"]["player_count"])

def days_after_wipe(now):
    """Сколько дней прошло после форс-вайпа (первый четверг месяца, UTC);
    отрицательное число — если вайп в этом месяце ещё впереди."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromtimestamp(now, timezone.utc).date()
    first = d.replace(day=1)
    wipe = first + timedelta(days=(3 - first.weekday()) % 7)
    return (d - wipe).days

ONLINE_HOOKS = [
    "📊 ОНЛАЙН RUST ПРЯМО СЕЙЧАС",
    "👥 Сколько людей сейчас на островах Rust",
    "📈 Сводка онлайна Rust за сегодня",
    "🏝 Сколько выживших сейчас на серверах",
    "🔢 Онлайн Rust: свежие цифры",
    "⚡️ Rust сегодня: сколько игроков в сети",
    "🛰 Мониторинг онлайна Rust",
    "🌍 Rust не спит — онлайн на этот вечер",
]
RECORD_HOOKS = [
    "🚀 РЕКОРД ОНЛАЙНА ЗА МЕСЯЦ!",
    "🔥 Rust обновил максимум онлайна за месяц",
    "📈 Новый пик онлайна в Rust",
    "🤯 Столько игроков в Rust не было весь месяц",
    "🏆 Онлайн Rust на месячном максимуме",
]
WIPE_RECORD_HOOKS = [
    "🚀 ВАЙП СДЕЛАЛ СВОЁ: рекорд онлайна за месяц!",
    "🪓 После вайпа сервера ломятся — новый рекорд онлайна",
    "🔥 Вайп! Онлайн Rust на месячном максимуме",
    "📈 Эффект вайпа: столько игроков не было весь месяц",
]
ONLINE_OUTROS = ["А ты сейчас в игре? 🎮", "Сервера не пустуют 💪",
                 "Ставь 🔥, если тоже фармишь прямо сейчас",
                 "Самое время зайти на сервер 😏", "Остров ждёт тебя 🏝", "", ""]
ONLINE_POST_HOUR = 20   # ежедневная сводка онлайна — вечером по Киеву

def online_tick(tg, state, now):
    """Каждый запуск: замер онлайна. Раз в день вечером — сводка, а если
    онлайн выше максимума за прошлые 30 дней — пост о рекорде."""
    n = fetch_online()
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
        wipe = 0 <= days_after_wipe(now) <= 3
        body = (f"👥 Сейчас в игре: <b>{fmt_num(n)}</b>\n"
                f"📊 Прошлый максимум за месяц: {fmt_num(max(prev))}")
        outro = pick(ONLINE_OUTROS)
        if outro:
            body += f"\n\n{outro}"
        hook = pick(WIPE_RECORD_HOOKS if wipe else RECORD_HOOKS)
        res = tg.send_message(frame(hook, "", body, "#rust #раст #онлайн"))
        if res.get("ok"):
            state["online_record_ts"] = int(now)
        return

    # ежедневная сводка — вечером, один раз за день
    kt = kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if kt.hour < ONLINE_POST_HOUR or state.get("online_daily") == today:
        return
    lines = [f"👥 Сейчас в игре: <b>{fmt_num(n)}</b>"]
    ago = min(log, key=lambda x: abs(x[0] - (now - 86400)))
    if abs(ago[0] - (now - 86400)) <= 5400 and ago[1]:
        diff = (n - ago[1]) * 100 / ago[1]
        arrow = "📈" if diff >= 0 else "📉"
        lines.append(f"{arrow} {diff:+.0f}% к этому времени вчера")
    peak = max(c for t, c in log if now - t <= 86400)
    lines.append(f"🏔 Пик за сутки: {fmt_num(peak)}")
    outro = pick(ONLINE_OUTROS)
    if outro:
        lines += ["", outro]
    res = tg.send_message(frame(pick(ONLINE_HOOKS), "", "\n".join(lines),
                                "#rust #раст #онлайн"))
    if res.get("ok"):
        state["online_daily"] = today

STORE_HOOKS = [
    "🛒 МАГАЗИН НЕДЕЛИ: что завезли и почём",
    "💸 Новинки магазина Rust — смотрим цены",
    "🛍 Магазин Rust обновился",
    "🆕 Свежий завоз в магазин Rust",
    "💰 Что продают в Rust на этой неделе",
    "🛒 Обновление магазина — цены внутри",
    "🔥 Новые скины уже в продаже",
    "🏷 Магазин Rust: новинки и ценники",
]
STORE_TITLES = ["{n} {new} в магазине Rust", "Свежий завоз: {n} {items}",
                "В продаже {n} {new}", "На этой неделе — {n} {new}"]
STORE_OUTROS = ["Что берёте? 🛒", "Есть что-то стоящее? 👀", "Кошелёк, держись 💸",
                "Ставь 🔥 за лучший скин недели",
                "Берём сразу или ждём маркет? 🤔", "Какой скин заберёте первым? 🔥"]

def fetch_store(cc):
    """Предметы магазина Rust с ценами в валюте страны cc (us/ru/ua):
    {id: {name, price, image, url}}."""
    import re
    url = (f"https://store.steampowered.com/itemstore/{RUST_APPID}/"
           f"ajaxgetitemdefs/?start=0&count=200&filter=New&l=english&cc={cc}")
    page = http_get_json(url, timeout=20).get("results_html") or ""
    out = {}
    for block in page.split('class="item_def_grid_item')[1:]:
        pid = re.search(r"/detail/(\d+)/", block)
        name = re.search(r"item_def_name[^>]*>\s*<a[^>]*>(.*?)</a>", block, re.S)
        price = re.search(r'item_def_price">(.*?)</div>', block, re.S)
        img = re.search(r'class="item_def_icon" src="([^"]+)"', block)
        if not (pid and name and price):
            continue
        cost = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", price.group(1))).split())
        out[pid.group(1)] = {
            "name": html.unescape(name.group(1).strip()),
            "price": cost.replace(" руб.", "₽"),
            "image": img.group(1).replace("/200fx200f", "/512fx512f") if img else "",
            "url": (f"https://store.steampowered.com/itemstore/{RUST_APPID}"
                    f"/detail/{pid.group(1)}/"),
        }
    return out

def price_value(p):
    import re
    s = re.sub(r"[^\d,.]", "", p).replace(",", ".").strip(".")
    try:
        return float(s)
    except ValueError:
        return None

def store_items(ids, usd, cur):
    """Плитки витрины: название, цена $, цены ₽ и ₴, картинка."""
    return [{"name": usd[i]["name"], "price": usd[i]["price"],
             "sub": " · ".join(cur[cc][i]["price"] for cc in ("ru", "ua")
                               if cur.get(cc, {}).get(i, {}).get("price")),
             "image": usd[i]["image"]} for i in ids]

def send_store_card(tg, ids, usd, cur, sums, text):
    """Новинки магазина одной картинкой-витриной, как в игре."""
    import rust_cards
    card = os.path.join(tempfile.gettempdir(), "rust_store.jpg")
    more = f" · ещё {len(ids) - 9} — в списке" if len(ids) > 9 else ""
    note = ("Всё сразу: " + " · ".join(sums) if sums and len(ids) > 1
            else "Цены — магазин Steam") + more
    try:
        if rust_cards.store_card(card, store_items(ids, usd, cur),
                                 kyiv_time().strftime("%d.%m"), note):
            return tg.send_photo_file(card, text)
    except Exception as e:
        print("Витрина магазина не собралась:", e)
    return {}

def post_store_news(tg, state):
    """Пост о новинках магазина Rust с ценами ($, ₽, ₴). Первый запуск только
    запоминает текущий ассортимент, дальше постим то, чего раньше не было."""
    import re
    usd = fetch_store("us")
    if not usd:
        return
    seen = state.get("store_seen")
    if seen is None:
        state["store_seen"] = sorted(usd)
        return
    known = set(seen)
    fresh = [i for i in usd if i not in known]
    if not fresh:
        return
    if len(fresh) > 30:   # почти весь магазин «новый» — сбой выдачи, не спамим
        print(f"Подозрительно много новинок магазина ({len(fresh)}) — пропускаю.")
        state["store_seen"] = (seen + fresh)[-3000:]
        return
    cur = {"us": usd}
    for cc in ("ru", "ua"):
        try:
            cur[cc] = fetch_store(cc)
        except Exception as e:
            print(f"Цены магазина ({cc}) не загрузились:", e)
            cur[cc] = {}
    lines = []
    for k, i in enumerate(fresh):
        tags = [cur[cc][i]["price"] for cc in ("us", "ru", "ua")
                if cur[cc].get(i, {}).get("price")]
        num = NUM_EMOJI[k] if k < len(NUM_EMOJI) else "▫️"
        lines.append(f"{num} <a href=\"{usd[i]['url']}\">"
                     f"{html.escape(usd[i]['name'])}</a> — {' · '.join(tags)}")

    def total(cc, fmt):
        vals = [price_value(cur[cc].get(i, {}).get("price", "")) for i in fresh]
        return "" if None in vals else fmt(sum(vals))

    sums = [s for s in (total("us", lambda t: f"${t:.2f}"),
                        total("ru", lambda t: f"{fmt_num(round(t))}₽"),
                        total("ua", lambda t: f"{fmt_num(round(t))}₴")) if s]
    body = "\n".join(lines)
    if sums and len(fresh) > 1:
        body += "\n\n💰 Всё сразу: " + " · ".join(sums)
    body += "\n\n" + pick(STORE_OUTROS)
    n = len(fresh)
    title = pick(STORE_TITLES).format(
        n=n, new=plural(n, "новинка", "новинки", "новинок"),
        items=plural(n, "предмет", "предмета", "предметов"))
    text = frame(pick(STORE_HOOKS), title, body, "#rust #раст #магазин #скины")
    visible = len(html.unescape(re.sub(r"<[^>]+>", "", text)))
    images = [usd[i]["image"] for i in fresh if usd[i]["image"]][:10]
    res = {}
    if visible <= 1024:   # витрина в стиле магазина Rust (rust_cards.py)
        res = send_store_card(tg, fresh, usd, cur, sums, text)
    if not res.get("ok") and visible <= 1024 and len(images) >= 2:
        res = tg.send_media_group(images, text)
    elif not res.get("ok") and visible <= 1024 and images:
        res = tg.send_photo(images[0], text)
    if not res.get("ok"):   # картинки не прошли или текст длинный — просто текстом
        res = tg.send_message(text)
    if res.get("ok"):
        state["store_seen"] = (seen + fresh)[-3000:]

# ---------- новости из X (официальный @playrust) ----------
# Читаем через официальный X API: оплата за использование, ~$0.005 за твит,
# для одного аккаунта — центы в месяц. Нужен секрет X_BEARER_TOKEN; без него
# этот источник просто выключен.
X_USER_ID = "1542707718"   # @playrust
X_HOOKS = [
    "🐦 Facepunch написали в X",
    "📢 Свежее из официального X Rust",
    "⚡️ Rust в X: новости от разработчиков",
    "👀 Официальный аккаунт Rust поделился новостью",
    "🗞 Новости из X от Facepunch",
    "📡 Rust пишет в X — переводим",
    "🔔 Свежий пост @playrust",
    "🛠 Facepunch в X: что нового",
]

def fetch_x_posts(token, since_id=None):
    """Собственные посты @playrust (без ответов и ретвитов) с вложениями,
    новые — первыми. since_id — вернуть только то, что новее."""
    params = {"max_results": "5", "exclude": "replies,retweets",
              "tweet.fields": "created_at,entities,attachments",
              "expansions": "attachments.media_keys",
              "media.fields": "type,url,preview_image_url,variants"}
    if since_id:
        params["since_id"] = since_id
    url = (f"https://api.x.com/2/users/{X_USER_ID}/tweets?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
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

def x_media(p):
    """Что приложить к посту: ("photo", url, url) или ("video", mp4, превью)."""
    for m in p["media"]:
        if m.get("type") == "photo" and m.get("url"):
            return "photo", m["url"], m["url"]
        if m.get("type") in ("video", "animated_gif"):
            mp4 = sorted((v for v in m.get("variants", [])
                          if v.get("content_type") == "video/mp4"),
                         key=lambda v: v.get("bit_rate", 0))
            # самое чёткое видео, что влезет в лимит Telegram (20 МБ по ссылке)
            fit = [v for v in mp4 if v.get("bit_rate", 0) <= 2500000]
            best = (fit or mp4[:1] or [{}])[-1].get("url", "")
            return "video", best, m.get("preview_image_url", "")
    return "", "", ""

def build_x_caption(p):
    """Новость из твита: перевод текста, ссылки из твита и оригинал."""
    text, links = p["text"], []
    for u in p["urls"]:
        text = text.replace(u.get("url", ""), "")
        exp = u.get("expanded_url") or ""
        if exp and not u.get("media_key") and "/status/" not in exp:
            links.append(exp)
    text = "\n".join(line.rstrip() for line in text.strip().splitlines())
    body = html.escape(translate_to_ru(text))
    extra = []
    for link in links[:2]:
        href = html.escape(link, quote=True)
        if "store.steampowered.com" in link:
            extra.append(f"🛒 <a href=\"{href}\">Купить в Steam</a>")
        else:
            extra.append(f"🔗 <a href=\"{href}\">Подробнее</a>")
    extra.append(f"🐦 <a href=\"https://x.com/playrust/status/{p['id']}\">"
                 "Оригинал в X</a>")
    body += "\n\n" + "\n".join(extra)
    outro = pick(NEWS_OUTROS)
    if outro:
        body += f"\n\n{outro}"
    return frame(pick(X_HOOKS), "", body, "#rust #раст #новости")

def post_x_news(tg, state):
    """Новые посты @playrust — новостями в канал, по порядку. Первый запуск
    публикует только самый свежий (если ему меньше суток)."""
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return
    last = state.get("x_last_id")
    try:
        posts = fetch_x_posts(token, last)
    except urllib.error.HTTPError as e:
        print("X API ошибка:", e.code, e.read().decode("utf-8", "replace")[:300])
        return
    if not posts:
        return
    if last is None:
        from datetime import datetime, timezone
        newest = posts[0]
        state["x_last_id"] = newest["id"]
        born = datetime.strptime(newest["created"][:19], "%Y-%m-%dT%H:%M:%S")
        age = time.time() - born.replace(tzinfo=timezone.utc).timestamp()
        posts = [newest] if age < 86400 else []
    for p in sorted(posts, key=lambda p: int(p["id"])):   # от старых к новым
        text = build_x_caption(p)
        kind, url, preview = x_media(p)
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

# ---------- маркет Steam: что дорожает и что дешевеет ----------
# Раз в день в обед (по Киеву): как скины из магазина последних 4 недель
# ведут себя на маркете — дороже или дешевле цены магазина, коллекции, хиты
# продаж, новинки недели (данные rust.scmm.app) — пост с картинкой-отчётом.
MARKET_HOUR = 13
MARKET_HOOKS = [
    "📈 РЫНОК СКИНОВ RUST: кто дорожает, кто дешевеет",
    "💹 Маркет Rust — главные движения цен",
    "💰 Что творится с ценами на скины Rust",
    "📊 Биржевая сводка Rust: скины на взлёте и в падении",
    "🔥 Скины, которые взлетели в цене",
    "🧾 Обеденная сводка по маркету Rust",
    "🎢 Качели маркета Rust: итоги",
    "💸 Для инвесторов в скины: сводка цен",
]
MARKET_START_HOOKS = [
    "💎 МАРКЕТ RUST: самые дорогие и самые ходовые скины",
    "🛒 Что сейчас в топе маркета Rust",
]
MARKET_OUTROS = ["Кто успел закупиться? 😏", "Держим или продаём? 🤔",
                 "Ставь 🔥, если следишь за маркетом",
                 "Инвестиции в скины — дело тонкое 💼",
                 "Не финансовый совет 😄", "А у тебя что в инвентаре? 👀"]
SERIES_STOP = {"the", "red", "blue", "black", "white", "green", "pink", "gold",
               "golden", "purple", "old", "big", "little", "dark", "light",
               "small", "large", "new", "mini", "super", "royal", "classic"}

SCMM_API = "https://api.scmm.app/api"   # rust.scmm.app, открытое API

def fetch_store_history(weeks=4):
    """Скины текущей и прошлых ротаций магазина Rust (rust.scmm.app): цена
    в магазине, текущая цена на маркете, коллекция, примерные продажи."""
    stores = [s for s in http_get_json(SCMM_API + "/store", timeout=20)
              if s.get("start")]
    stores.sort(key=lambda s: s["start"], reverse=True)
    out = []
    for n, s in enumerate(stores[:weeks + 1]):
        data = http_get_json(f"{SCMM_API}/store/{s['id']}?currency=USD",
                             timeout=25)
        for it in data.get("items") or []:
            if not it.get("storePrice"):
                continue
            mp = it.get("marketPrice")
            out.append({
                "id": it.get("guid") or it.get("name", ""),
                "name": it.get("name", ""),
                "store": int(it["storePrice"]),
                "price": int(mp) if mp else 0,
                "collection": (it.get("itemCollection") or "").strip(),
                "sold": int(it.get("supplyTotalEstimated") or 0),
                "week": s["start"][8:10] + "." + s["start"][5:7],
                "start": s["start"],
                "current": n == 0,   # текущая неделя — на маркете ещё нет
                "icon": it.get("iconUrl") or "",
                "bg": (it.get("backgroundColour") or "#2b2d33").lstrip("#")})
        time.sleep(1)
    return out, (stores[0]["start"] if stores else "")

def market_url(name):
    return ("https://steamcommunity.com/market/listings/"
            f"{RUST_APPID}/{urllib.parse.quote(name)}")

def money(cents):
    return f"${cents / 100:,.2f}".replace(",", " ")

def pct_text(p):
    return f"{p:+.0f}%".replace("-", "−")

def series_moves(changes):
    """Серии скинов (общее первое слово названия, от 3 предметов) со средним
    изменением цены: самая растущая и самая падающая."""
    groups = {}
    for name, pct in changes.items():
        words = name.split()
        if (len(words) >= 2 and len(words[0]) > 2
                and words[0].lower() not in SERIES_STOP):
            groups.setdefault(words[0], []).append(pct)
    avg = {k: (sum(v) / len(v), len(v)) for k, v in groups.items() if len(v) >= 3}
    if not avg:
        return None, None
    up = max(avg.items(), key=lambda kv: kv[1][0])
    down = min(avg.items(), key=lambda kv: kv[1][0])
    return (up if up[1][0] >= 1 else None), (down if down[1][0] <= -1 else None)

def build_market_card(title, subtitle, sections, out_path):
    """Картинка-отчёт в стиле магазина Rust (rust_cards.py): витрины
    «дороже, чем в магазине» и «дешевле» по три скина.
    sections: [(заголовок, цвет, [(название, предмет, подпись, процент)])]."""
    import rust_cards
    out = []
    for head, color, rows in sections:
        tiles = []
        for name, it, sub, right in rows[:3]:
            src = it.get("icon") or ""
            if src and not src.startswith("http"):
                src = ("https://community.cloudflare.steamstatic.com/economy/"
                       "image/" + src + "/360fx360f")
            tiles.append({"name": name, "image": src,
                          "price": money(it["price"]),
                          "sub": f"в магазине {money(it['store'])}",
                          "value": right.replace("−", "-")})
        out.append((head.replace("▲ ", "").replace("▼ ", ""),
                    color[1] > color[0], tiles))   # зелёный — рост
    return rust_cards.market_card(out_path, subtitle.split(" · ")[0], out)

def market_tick(tg, state, forced=False):
    """Раз в день в обед: как скины из магазина последних недель ведут себя
    на маркете (данные rust.scmm.app) — пост с картинкой-отчётом."""
    import re
    from datetime import datetime, timedelta
    kt = kyiv_time()
    today = kt.strftime("%Y-%m-%d")
    if not forced and (kt.hour < MARKET_HOUR
                       or state.get("market_day") == today):
        return
    allitems, cur_start = fetch_store_history()
    past = [s for s in allitems if not s["current"] and s["price"]]
    cur = [s for s in allitems if s["current"]]
    if len(past) < 10:
        print(f"SCMM ответил не полностью ({len(past)}) — попробую позже.")
        return
    snaps = state.setdefault("market_snaps", {})
    prev = sorted(d for d in snaps if d < today)
    snaps[today] = {s["id"]: s["price"] for s in past}
    for d in sorted(snaps)[:-9]:
        del snaps[d]
    for s in past:
        s["roi"] = (s["price"] - s["store"]) * 100 / s["store"]
    ups = sorted((s for s in past if s["roi"] >= 1),
                 key=lambda s: -s["roi"])[:5]
    downs = sorted((s for s in past if s["roi"] <= -1),
                   key=lambda s: s["roi"])[:5]
    link = lambda s: (f"<a href=\"{market_url(s['name'])}\">"
                      f"{html.escape(s['name'])}</a>")
    line = lambda s: (f"▫️ {link(s)} — {money(s['store'])} → "
                      f"{money(s['price'])} (<b>{pct_text(s['roi'])}</b>)")
    row = lambda s: (s["name"], s, f"магазин {money(s['store'])} → маркет {money(s['price'])}"
                     f"  ·  неделя {s['week']}", pct_text(s["roi"]))
    sections = [x for x in (
        ("▲ ДОРОЖЕ, ЧЕМ В МАГАЗИНЕ", (61, 220, 132), [row(s) for s in ups]),
        ("▼ ДЕШЕВЛЕ, ЧЕМ В МАГАЗИНЕ", (255, 82, 82),
         [row(s) for s in downs])) if x[2]]
    lines = []
    if ups:
        lines += (["📈 <b>Подорожали после магазина</b>"]
                  + [line(s) for s in ups[:3]] + [""])
    if downs:
        lines += (["📉 <b>Дешевле, чем в магазине</b>"]
                  + [line(s) for s in downs[:3]] + [""])
    # дополнительные строки — по важности; если подпись не влезет, лишние
    # отрежем с конца
    extras = []
    if cur:
        top = max(cur, key=lambda s: s["sold"])
        opens = (datetime.fromisoformat(cur_start[:19])
                 + timedelta(days=7)).strftime("%d.%m")
        k = len(cur)
        extras.append(f"🆕 Сейчас в магазине {k} "
                      f"{plural(k, 'новый скин', 'новых скина', 'новых скинов')}"
                      f", на маркете — с {opens}. Лидер продаж: "
                      f"{html.escape(top['name'])} (~{fmt_num(top['sold'])} шт.)")
    cols = {}
    for s in past:
        if s["collection"]:
            cols.setdefault(s["collection"], []).append(s["roi"])
    cols = {k: sum(v) / len(v) for k, v in cols.items() if len(v) >= 2}
    best = max(cols.items(), key=lambda kv: kv[1]) if len(cols) >= 2 else None
    worst = min(cols.items(), key=lambda kv: kv[1]) if len(cols) >= 2 else None
    if best:
        extras.append(f"🧩 Лучшая коллекция: «{html.escape(best[0].title())}»"
                      f" — в среднем {pct_text(best[1])}")
    last_week = max(past, key=lambda s: s["start"])["week"]
    hit = max((s for s in past if s["week"] == last_week),
              key=lambda s: s["sold"])
    if hit["sold"]:
        extras.append(f"🔥 Хит продаж недели {last_week}: {link(hit)} — "
                      f"~{fmt_num(hit['sold'])} шт.")
    if worst:
        extras.append(f"🧊 Слабее всех: «{html.escape(worst[0].title())}» — "
                      f"{pct_text(worst[1])}")
    if prev:
        old = snaps[prev[-1]]
        moves = [(s, (s["price"] - old[s["id"]]) * 100 / old[s["id"]])
                 for s in past if old.get(s["id"])]
        moves = [m for m in moves if abs(m[1]) >= 3]
        if moves:
            s, p = max(moves, key=lambda m: abs(m[1]))
            extras.append(f"⚡ За сутки сильнее всех: {link(s)} {pct_text(p)}")
    date = kt.strftime("%d.%m.%Y")
    period = "магазин → маркет, 4 недели"
    hook, outro = pick(MARKET_HOOKS), pick(MARKET_OUTROS)

    def compose(ex):
        return frame(hook, f"🗓 {date} · {period}",
                     "\n".join(lines + ex + ["", outro]),
                     "#rust #раст #маркет #скины")

    text = compose(extras)
    while extras and len(html.unescape(re.sub(r"<[^>]+>", "", text))) > 1024:
        extras.pop()
        text = compose(extras)
    card = os.path.join(tempfile.gettempdir(), "rust_market.jpg")
    res = {}
    try:
        if build_market_card("РЫНОК СКИНОВ RUST", f"{date} · {period}",
                             sections, card):
            res = tg.send_photo_file(card, text)
    except Exception as e:
        print("Картинка маркета не собралась:", e)
    if not res.get("ok"):
        res = tg.send_message(text)
    if res.get("ok"):
        state["market_day"] = today   # одна сводка в день, даже ручная

# ---------- топ скинов недели из мастерской (micro522.com) ----------
# Раз в ~3 дня вечером (по Киеву) — топ-3 работ недели по оценке Steam с
# micro522.com/WorkshopVotes (страница обновляется ежечасно) + картинка-подиум.
TOP_URL = "https://micro522.com/WorkshopVotes/votePageSubmitted.html"
TOP_EVERY_H = 70          # примерно раз в 3 дня
TOP_HOUR = 17             # вечером по Киеву
TOP_MIN_WORKS = 25        # неделя должна набрать столько работ
TOP_HOOKS = [
    "🏆 ТОП-3 СКИНОВ НЕДЕЛИ В МАСТЕРСКОЙ",
    "🥇 Лучшие работы недели в воркшопе Rust",
    "🔥 Мастерская Rust: тройка лидеров недели",
    "👑 Кто правит воркшопом на этой неделе",
    "📊 Рейтинг мастерской: топ-3 недели",
    "🎨 Самые сильные скины недели по оценке Steam",
]
TOP_OUTROS = ["Кто, по-вашему, попадёт в игру? 🤔", "За кого болеете? Ставь 🔥",
              "Достойный подиум? 👀", "Какой из трёх взяли бы себе? 🛒",
              "Ждём их в магазине? 🤞"]

def fetch_workshop_top():
    """Работы с micro522.com: {(год, неделя): [скины по убыванию оценки]}."""
    import re
    req = urllib.request.Request(TOP_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        page = r.read().decode("utf-8", "replace")

    def text(cell):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split())

    weeks = {}
    for row in page.split("<tr")[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 13:
            continue
        wk = re.match(r"(\d+) Week(\d+)", text(cells[1]))
        link = re.search(r"""href=['"](https://steamcommunity\.com/[^'"]+)['"][^>]*>([^<]*)""",
                         cells[4])
        img = re.search(r"""<img[^>]+src=['"]([^'"]+)['"]""", cells[4])
        if not (wk and link):
            continue
        try:
            score = float(text(cells[3]))
            up, down = int(text(cells[8])), int(text(cells[9]))
        except ValueError:
            continue
        pic = html.unescape(img.group(1)) if img else ""
        pic = re.sub(r"imh=\d+", "imh=1024", re.sub(r"imw=\d+", "imw=1024", pic))
        weeks.setdefault((int(wk.group(1)), int(wk.group(2))), []).append({
            "title": html.unescape(link.group(2)).strip(),
            "url": html.unescape(link.group(1)),
            "author": text(cells[2]), "score": score, "up": up, "down": down,
            "category": text(cells[12]), "image": pic})
    for works in weeks.values():
        works.sort(key=lambda s: -s["score"])
    return weeks

def build_top_card(subtitle, top, out_path):
    """Картинка-подиум 1440×1800: №1 крупно сверху, №2 и №3 рядом снизу.
    Рисуем в 2× и уменьшаем — гладкие края и чёткий текст."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        return False
    S, W, H = 2, 1440, 1800
    p = lambda v: int(v * S)
    card_bg, line_c = (31, 34, 43), (48, 52, 64)
    muted, red = (150, 156, 172), (205, 65, 43)
    medals = [(255, 196, 46), (205, 212, 224), (214, 134, 62)]

    grad = Image.linear_gradient("L").resize((p(W), p(H)))
    img = Image.composite(Image.new("RGB", (p(W), p(H)), (11, 12, 16)),
                          Image.new("RGB", (p(W), p(H)), (27, 29, 37)),
                          grad).convert("RGBA")
    glow = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 8 - 75, -55, W // 8 + 45, 45),
                                 fill=medals[0] + (90,))
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

    def fit(text, fnt, width):
        if draw.textlength(text, font=fnt) <= width:
            return text
        while text and draw.textlength(text + "…", font=fnt) > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def wrap(text, fnt, width, lines=2):
        out, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if cur and draw.textlength(t, font=fnt) > width:
                out.append(cur)
                cur = w
            else:
                cur = t
        out.append(cur)
        if len(out) > lines:
            out = out[:lines - 1] + [" ".join(out[lines - 1:])]
        out[-1] = fit(out[-1], fnt, width)
        return out

    def picture(url, size):
        tile = Image.new("RGBA", (p(size), p(size)), (20, 22, 28, 255))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGBA")
            k = min(p(size) / im.width, p(size) / im.height)   # и увеличиваем тоже
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                           Image.LANCZOS)
            tile.alpha_composite(im, ((tile.width - im.width) // 2,
                                      (tile.height - im.height) // 2))
        except Exception:
            pass
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, tile.width - 1, tile.height - 1), radius=p(24), fill=255)
        tile.putalpha(mask)
        return tile

    def badge(cx, cy, n, r):
        draw.ellipse((cx - p(r), cy - p(r), cx + p(r), cy + p(r)),
                     fill=medals[n], outline=(20, 22, 28), width=p(4))
        draw.text((cx, cy), str(n + 1), font=font(int(r * 1.15), True),
                  fill=(20, 22, 28), anchor="mm")

    def stats(x, y, it, size):
        f = font(size, True)
        for txt, col in ((f"▲ {it['up']}", (61, 220, 132)),
                         (f"▼ {it['down']}", (255, 82, 82)),
                         (f"★ {it['score']:.1f}", (255, 255, 255))):
            draw.text((x, y), txt, font=f, fill=col, anchor="lm")
            x += draw.textlength(txt, font=f) + p(30)

    def pill(x, y, text, size=22):
        f = font(size, True)
        w = draw.textlength(text, font=f) + p(36)
        draw.rounded_rectangle((x, y - p(size), x + w, y + p(size)),
                               radius=p(size), fill=(44, 48, 60))
        draw.text((x + w / 2, y), text, font=f, fill=muted, anchor="mm")

    # шапка
    draw.rectangle((0, 0, p(W), p(12)), fill=red)
    tag, tf = "МАСТЕРСКАЯ STEAM", font(22, True)
    tw = draw.textlength(tag, font=tf)
    draw.rounded_rectangle((p(64), p(52), p(64) + tw + p(40), p(94)),
                           radius=p(21), fill=red)
    draw.text((p(64) + (tw + p(40)) / 2, p(73)), tag, font=tf,
              fill=(255, 255, 255), anchor="mm")
    draw.text((p(62), p(150)), "ТОП-3 СКИНОВ НЕДЕЛИ", font=font(70, True),
              fill=(255, 255, 255), anchor="lm")
    draw.text((p(64), p(214)), subtitle, font=font(30), fill=muted, anchor="lm")

    # №1 — крупно, во всю ширину
    if top:
        it = top[0]
        draw.rounded_rectangle((p(56), p(262), p(W - 56), p(862)), radius=p(32),
                               fill=card_bg, outline=medals[0], width=p(3))
        img.alpha_composite(picture(it["image"], 540), (p(86), p(292)))
        badge(p(110), p(316), 0, 44)
        x, tw1, tf1 = p(668), p(W - 56 - 668 - 36), font(46, True)
        yy = 360
        for ln in wrap(it["title"], tf1, tw1):
            draw.text((x, p(yy)), ln, font=tf1, fill=(255, 255, 255),
                      anchor="lm")
            yy += 58
        draw.text((x, p(yy + 22)), fit("автор: " + it["author"], font(30), tw1),
                  font=font(30), fill=muted, anchor="lm")
        stats(x, p(yy + 92), it, 34)
        if it["category"]:
            pill(x, p(yy + 162), it["category"])
        draw.text((x, p(812)), "1 МЕСТО НЕДЕЛИ", font=font(28, True),
                  fill=medals[0], anchor="lm")

    # №2 и №3 — рядом
    for k, it in enumerate(top[1:3], start=1):
        x0 = 56 if k == 1 else 728
        draw.rounded_rectangle((p(x0), p(892), p(x0 + 656), p(1700)),
                               radius=p(32), fill=card_bg, outline=medals[k],
                               width=p(3))
        img.alpha_composite(picture(it["image"], 420), (p(x0 + 118), p(922)))
        badge(p(x0 + 140), p(944), k, 38)
        tf2 = font(36, True)
        yy = 1384
        for ln in wrap(it["title"], tf2, p(596)):
            draw.text((p(x0 + 30), p(yy)), ln, font=tf2, fill=(255, 255, 255),
                      anchor="lm")
            yy += 46
        draw.text((p(x0 + 30), p(yy + 16)),
                  fit("автор: " + it["author"], font(26), p(596)),
                  font=font(26), fill=muted, anchor="lm")
        stats(p(x0 + 30), p(yy + 70), it, 30)
        if it["category"]:
            pill(p(x0 + 30), p(1660), it["category"], 20)

    # подвал
    draw.line((p(64), p(H - 80), p(W - 64), p(H - 80)), fill=line_c,
              width=p(2))
    draw.text((p(64), p(H - 44)), "по данным micro522.com · Steam Workshop",
              font=font(26), fill=(120, 126, 142), anchor="lm")
    draw.text((p(W - 64), p(H - 44)), CHANNEL_TAG, font=font(28, True),
              fill=red, anchor="rm")
    img = img.convert("RGB").resize((W, H), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=95, subsampling=0)
    return True

def top_tick(tg, state, forced=False):
    """Раз в ~3 дня вечером: топ-3 скинов недели (micro522.com) с картинкой.
    Если подиум тот же, что в прошлый раз, — переносим на завтра."""
    kt = kyiv_time()
    if not forced and (kt.hour < TOP_HOUR or time.time()
                       - state.get("top_ts", 0) < TOP_EVERY_H * 3600):
        return
    weeks = fetch_workshop_top()
    full = [k for k, v in weeks.items() if len(v) >= TOP_MIN_WORKS]
    if not full:
        print("micro522: нет недели с достаточным числом работ.")
        return
    key = max(full)
    works = weeks[key]
    top = works[:3]
    ids = [s["url"] for s in top]
    if not forced and ids == state.get("top_last"):
        state["top_ts"] = int(time.time()) - (TOP_EVERY_H - 24) * 3600
        return
    n = len(works)
    sub = (f"Неделя {key[1]} · {n} {plural(n, 'работа', 'работы', 'работ')}"
           " · оценка Steam")
    lines = []
    for medal, s in zip(("🥇", "🥈", "🥉"), top):
        lines.append(f"{medal} <a href=\"{s['url']}\">"
                     f"{html.escape(s['title'])}</a>")
        lines.append(f"└ 🎨 {html.escape(s['author'])} · 👍 {s['up']} · "
                     f"👎 {s['down']} · ★ {s['score']:.1f}")
    lines += ["", pick(TOP_OUTROS)]
    text = frame(pick(TOP_HOOKS), sub, "\n".join(lines),
                 "#rust #раст #воркшоп #топ")
    card = os.path.join(tempfile.gettempdir(), "rust_top.jpg")
    res = {}
    try:
        if top_store_card(key, n, top, card) or build_top_card(sub, top, card):
            res = tg.send_photo_file(card, text)
    except Exception as e:
        print("Картинка топа не собралась:", e)
    if not res.get("ok"):
        res = tg.send_message(text)
    if res.get("ok"):
        state["top_ts"] = int(time.time())
        state["top_last"] = ids
        # эти скины уже были в канале — «Лучшее из воркшопа» их не повторяет
        state["top_shown"] = (state.get("top_shown", []) + ids)[-30:]

def top_store_card(key, n, top, out_path):
    """Топ-3 недели в стиле магазина Rust (rust_cards.top_card)."""
    try:
        import rust_cards
        return rust_cards.top_card(
            out_path, f"НЕДЕЛЯ {key[1]}", top,
            f"{n} {plural(n, 'работа', 'работы', 'работ')} за неделю"
            " · оценки игроков Steam")
    except Exception as e:
        print("Топ в стиле магазина не собрался:", e)
        return False

def contest_store_card(album, out_path):
    """Конкурс «кого примут в игру» в стиле магазина Rust."""
    try:
        import rust_cards
        works = [{"title": clean(s["title_raw"], 80), "author": s["author"],
                  "image": s["image"]} for s in album]
        return rust_cards.contest_card(
            out_path, kyiv_time().strftime("%d.%m"), works,
            "жми номер под постом и подтверди · итоги в воскресенье")
    except Exception as e:
        print("Конкурс в стиле магазина не собрался:", e)
        return False

def build_collage(image_urls, out_path):
    """Коллаж из 5 скинов с номерами 1-5 в один JPEG. Нужен Pillow; если
    его нет или картинки не скачались — возвращаем False (будет запасной
    путь: обычный альбом + отдельные кнопки)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False
    imgs = []
    for u in image_urls[:5]:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                imgs.append(Image.open(io.BytesIO(r.read())).convert("RGB"))
        except Exception:
            return False
    if len(imgs) < 5:
        return False
    tile, gap, bg = 360, 8, (17, 18, 24)

    def square(im):
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2,
                      (w - s) // 2 + s, (h - s) // 2 + s))
        return im.resize((tile, tile))

    imgs = [square(im) for im in imgs]
    cols = 3
    width = cols * tile + (cols + 1) * gap
    height = 2 * tile + 3 * gap
    canvas = Image.new("RGB", (width, height), bg)
    pos = [(gap + i * (tile + gap), gap) for i in range(3)]
    bottom_w = 2 * tile + gap
    bx = (width - bottom_w) // 2
    pos += [(bx + i * (tile + gap), 2 * gap + tile) for i in range(2)]
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
    except Exception:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    rad = 48
    for i, (im, (x, y)) in enumerate(zip(imgs, pos)):
        canvas.paste(im, (x, y))
        draw.ellipse((x + 12, y + 12, x + 12 + 2 * rad, y + 12 + 2 * rad),
                     fill=(206, 66, 43))
        n = str(i + 1)
        try:
            bb = draw.textbbox((0, 0), n, font=font)
            tx = x + 12 + rad - (bb[2] - bb[0]) / 2 - bb[0]
            ty = y + 12 + rad - (bb[3] - bb[1]) / 2 - bb[1]
        except Exception:
            tx, ty = x + 12 + rad - 24, y + 12 + rad - 40
        draw.text((tx, ty), n, fill=(255, 255, 255), font=font)
    try:
        canvas.save(out_path, "JPEG", quality=85)
        return True
    except Exception:
        return False

# ---------- конкурс "угадай принятый скин" ----------

def iso_week(ts):
    return time.strftime("%G-%V", time.gmtime(ts))

def fetch_worker_votes(state):
    """Голоса берём у Cloudflare-воркера (публичный /export). Индекс
    кнопки переводим в id скина по нашим раундам и кладём в votes."""
    url = (os.environ.get("WORKER_URL")
           or "https://rust-votes.twithgfaw.workers.dev").rstrip("/")
    try:
        data = http_get_json(url + "/export", timeout=15)
    except Exception as e:
        print("Голоса воркера не загрузились:", e)
        return
    rounds = state.get("rounds", {})
    votes = state.get("votes", {})
    for rid, usersd in (data or {}).items():
        pids = (rounds.get(rid, {}) or {}).get("pids", [])
        if not pids:
            continue
        vr = votes.setdefault(rid, {})
        for uid, v in (usersd or {}).items():
            idx = v.get("idx")
            if isinstance(idx, int) and 0 <= idx < len(pids):
                vr[uid] = {"pid": pids[idx], "name": v.get("name") or "Игрок"}
    state["votes"] = votes


def collect_votes(tg, state):
    """Забираем нажатия кнопок (callback_query). Один голос на игрока:
    новое нажатие заменяет прежний прогноз. Кнопка «Подтвердить» просто
    показывает игроку, что его выбор засчитан."""
    offset = state.get("update_offset", 0)
    updates = tg.get_updates(offset)
    if not updates:
        return
    rounds = state.get("rounds", {})
    votes = state.get("votes", {})
    last = offset - 1
    for u in updates:
        last = max(last, u.get("update_id", 0))
        cq = u.get("callback_query")
        if not cq:
            continue
        data = cq.get("data", "")
        user = cq.get("from") or {}
        uid = str(user.get("id"))
        # кнопка «Подтвердить»: показываем игроку его текущий выбор
        if data.startswith("c"):
            crid = data[1:]
            mine = (votes.get(crid, {}) or {}).get(uid)
            if mine:
                pids = (rounds.get(crid, {}) or {}).get("pids", [])
                num = pids.index(mine["pid"]) + 1 if mine["pid"] in pids else 0
                tg.answer_callback(
                    cq.get("id"),
                    f"Готово! Твой голос засчитан: вариант №{num} ✅" if num
                    else "Готово! Твой голос засчитан ✅")
            else:
                tg.answer_callback(cq.get("id"),
                                   "Сначала выбери номер 1–5 👆, потом подтверди")
            continue
        # выбор варианта: формат vРАУНД_ИНДЕКС
        if not data.startswith("v") or "_" not in data:
            continue
        try:
            rid, idx = data[1:].split("_", 1)
            idx = int(idx)
        except ValueError:
            continue
        rnd = rounds.get(rid)
        if not rnd:
            continue
        skins = rnd.get("pids", [])
        if not (0 <= idx < len(skins)):
            continue
        if not uid or uid == "None":
            continue
        name = user.get("username") or user.get("first_name") or "Игрок"
        votes.setdefault(rid, {})
        votes[rid][uid] = {"pid": skins[idx], "name": name}
        tg.answer_callback(cq.get("id"),
                           f"Выбран вариант №{idx + 1}. Нажми «Подтвердить» ✅")
    state["votes"] = votes
    state["update_offset"] = last + 1

def live_counts_line(state, rid):
    """Строка-счётчик голосов по вариантам для раунда rid."""
    rnd = state.get("rounds", {}).get(rid, {})
    pids = rnd.get("pids", [])
    tally = [0] * len(pids)
    for v in state.get("votes", {}).get(rid, {}).values():
        if v.get("pid") in pids:
            tally[pids.index(v["pid"])] += 1
    parts = [f"{NUM_EMOJI[i]} {tally[i]}" for i in range(len(pids))]
    total = sum(tally)
    return f"\U0001f4ca Голоса ({total}): " + "   ".join(parts)

def update_live_counts(tg, state):
    """Обновляем подписи постов-конкурсов этой недели: дописываем счётчик
    голосов. Так всем видно, что голоса реально считаются."""
    wk = iso_week(time.time())
    for rid, rnd in state.get("rounds", {}).items():
        if rnd.get("week") != wk or not rnd.get("msg_id"):
            continue
        base = rnd.get("caption")
        if not base:
            continue
        new_cap = base + "\n\n" + live_counts_line(state, rid)
        if new_cap == rnd.get("last_caption"):
            continue  # ничего не изменилось — не трогаем пост
        res = tg.edit_caption(rnd["msg_id"], new_cap)
        if res.get("ok"):
            rnd["last_caption"] = new_cap

def prune_rounds(state, keep_days=21):
    """Чистим старые раунды и голоса, чтобы файл не рос бесконечно."""
    cutoff = time.time() - keep_days * 86400
    rounds = state.get("rounds", {})
    votes = state.get("votes", {})
    old = [pid for pid, r in rounds.items() if r.get("ts", 0) < cutoff]
    for pid in old:
        rounds.pop(pid, None)
        votes.pop(pid, None)
    state["rounds"] = rounds
    state["votes"] = votes

MEDAL = ["\U0001f947", "\U0001f948", "\U0001f949"]

def build_leaderboard_caption(ranking, accepted_count):
    top = [r for r in ranking if r["score"] > 0][:10]
    if top:
        lines = []
        for i, r in enumerate(top):
            mark = MEDAL[i] if i < 3 else f"{i + 1}."
            lines.append(f"{mark} {html.escape(r['name'])} — "
                         f"{r['score']} ✅")
        body = "\n".join(lines)
    else:
        body = "На этой неделе никто пока не угадал принятых скинов \U0001f937"
    sub = f"Приняли в игру скинов за неделю: {accepted_count}"
    return frame("\U0001f3c6 ИТОГИ НЕДЕЛИ · КТО УГАДАЛ", sub, body,
                 "#rust #раст #конкурс")

def score_week(state, accepted_pids):
    """Считаем очки за текущую неделю: +1 за каждый свой скин, который
    реально приняли в игру."""
    week = iso_week(time.time())
    rounds = state.get("rounds", {})
    votes = state.get("votes", {})
    week_polls = [pid for pid, r in rounds.items()
                  if r.get("week") == week]
    scores, accepted_count = {}, 0
    for pid in week_polls:
        correct = set(rounds[pid].get("pids", [])) & accepted_pids
        accepted_count += len(correct)
        for uid, v in votes.get(pid, {}).items():
            guess = v.get("pid") or (v.get("pids") or [None])[0]
            rec = scores.setdefault(uid, {"name": v["name"], "score": 0})
            rec["name"] = v["name"]
            if guess in correct:
                rec["score"] += 1
    ranking = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return ranking, accepted_count, bool(week_polls)

# ---------- главный сценарий ----------

def demo_cards():
    """Пример новых картинок в лог (base64) — ничего не публикует."""
    import rust_cards
    usd = fetch_store("us")
    cur = {"us": usd}
    for cc in ("ru", "ua"):
        try:
            cur[cc] = fetch_store(cc)
        except Exception as e:
            print(f"Цены магазина ({cc}) не загрузились:", e)
            cur[cc] = {}
    ids = list(usd)[:6]
    total = sum(price_value(usd[i]["price"]) or 0 for i in ids)
    card = os.path.join(tempfile.gettempdir(), "rust_store.jpg")
    if rust_cards.store_card(card, store_items(ids, usd, cur),
                             kyiv_time().strftime("%d.%m"),
                             f"Всё сразу: ${total:.2f}"):
        rust_cards.dump(card)
    past = [s for s in fetch_store_history()[0]
            if not s["current"] and s["price"]]
    for s in past:
        s["roi"] = (s["price"] - s["store"]) * 100 / s["store"]
    ups = sorted((s for s in past if s["roi"] >= 1), key=lambda s: -s["roi"])
    downs = sorted((s for s in past if s["roi"] <= -1), key=lambda s: s["roi"])
    row = lambda s: (s["name"], s, "", pct_text(s["roi"]))
    sections = [x for x in (
        ("▲ ДОРОЖЕ, ЧЕМ В МАГАЗИНЕ", (61, 220, 132), [row(s) for s in ups[:3]]),
        ("▼ ДЕШЕВЛЕ, ЧЕМ В МАГАЗИНЕ", (255, 82, 82),
         [row(s) for s in downs[:3]])) if x[2]]
    card = os.path.join(tempfile.gettempdir(), "rust_market.jpg")
    if build_market_card("", kyiv_time().strftime("%d.%m.%Y"), sections, card):
        rust_cards.dump(card)

def main():
    ap = argparse.ArgumentParser(description="Rust Digest Bot для Telegram")
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--dry-run", action="store_true",
                    help="ничего не постить, только показать в консоли")
    args = ap.parse_args()
    if os.environ.get("EXTRA_POST") == "пример новых картинок":
        demo_cards()
        return
    if os.environ.get("EXTRA_POST") == "пример новых рубрик":
        import rust_formats
        rust_formats.demo()
        return
    if os.environ.get("EXTRA_POST") == "пример: индекс, викторина, вайп, X":
        import rust_formats
        rust_formats.demo_extra()
        return

    # Конфиг читаем из файла, если он есть (локальный запуск на ПК).
    # В облаке (GitHub Actions) файла нет — тогда берём значения из
    # переменных окружения / секретов. Env имеет приоритет над файлом.
    cfg = configparser.ConfigParser()
    if os.path.exists(args.config):
        cfg.read(args.config, encoding="utf-8")

    token = (os.environ.get("BOT_TOKEN")
             or cfg.get("telegram", "bot_token", fallback="")).strip()
    chat = (os.environ.get("CHANNEL")
            or cfg.get("telegram", "channel", fallback="")).strip()
    # подпись канала в футере: если канал публичный (@username) — ставим его
    global CHANNEL_TAG
    if chat.startswith("@"):
        CHANNEL_TAG = chat
    works_count = int(os.environ.get("WORKS_COUNT")
                      or cfg.get("content", "works_count", fallback="3"))
    min_score = int(os.environ.get("MIN_SCORE")
                    or cfg.get("content", "min_score", fallback="300"))
    post_news = (os.environ.get("POST_OFFICIAL_NEWS")
                 or cfg.get("content", "post_official_news",
                            fallback="true")).strip().lower() in ("1", "true", "yes", "on")
    period = (os.environ.get("REDDIT_PERIOD")
              or cfg.get("content", "reddit_period", fallback="day")).strip()
    steam_key = (os.environ.get("STEAM_API_KEY")
                 or cfg.get("content", "steam_api_key", fallback="")).strip()

    if not args.dry_run and ("PASTE_BOT_TOKEN" in token or not token or not chat):
        print("Нет токена/канала. Локально — заполни config.ini; "
              "в GitHub Actions — задай секреты BOT_TOKEN и CHANNEL. "
              "(Или запусти с --dry-run для проверки.)")
        sys.exit(1)

    state = load_state()
    _RECENT[:] = state.get("recent_phrases", [])   # чтобы фразы не повторялись
    posted = set(state.get("posted_ids", []))
    tg = Telegram(token, chat, dry_run=args.dry_run)

    # сначала забираем новые голоса конкурса и обновляем живой счётчик
    if not args.dry_run:
        try:
            fetch_worker_votes(state)
            update_live_counts(tg, state)
        except Exception as e:
            print("Сбор голосов не удался:", e)

    sent_any = False

    # 1) официальные новости (с фирменной шапкой Rust). С ключом Claude
    #    (rust_formats.NEWS_LIVE) — пересказ каждой новости отдельным постом
    try:
        import rust_formats
    except Exception as e:
        print("Новые рубрики не загрузились:", e)
        rust_formats = None
    if post_news and rust_formats and rust_formats.ai_ready():
        rust_formats.post_news(tg, posted, args.dry_run)
    elif post_news:
        news = [n for n in fetch_official_news(5) if n["id"] not in posted][:3]
        if news:
            res = tg.send_photo(NEWS_BANNER, build_news_caption(news))
            if args.dry_run or res.get("ok"):
                for n in news:
                    posted.add(n["id"])
                sent_any = sent_any or not args.dry_run
            else:
                print("Новости НЕ отправлены (см. ошибку выше). "
                      "В историю не записал — повторю при следующем запуске.")
            time.sleep(2)
        else:
            print("Новых официальных новостей нет.")

    # 2) крутые работы
    works = [w for w in fetch_top_works(period, 15, min_score)
             if w["id"] not in posted][:works_count]
    if works:
        for i, w in enumerate(works, 1):
            res = tg.send_photo(w["image"], build_work_caption(w, i))
            if args.dry_run or res.get("ok"):
                posted.add(w["id"])
                sent_any = sent_any or not args.dry_run
            time.sleep(2)
    else:
        print("Новых работ по заданным порогам нет.")

    # 3) лучшие видео дня у блогеров (только про Rust, не больше 2/день)
    yt_max = int(os.environ.get("YT_MAX_PER_DAY") or "2")
    if YT_CHANNELS and yt_max > 0:
        yt_log = state.get("yt_log", [])
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time()))
        yt_today = sum(
            1 for ts in yt_log
            if time.strftime("%Y-%m-%d", time.gmtime(ts)) == today)
        slots = yt_max - yt_today
        # одно видео за запуск, между видео — от 4 часов, ночью не постим
        if slots > 0 and (quiet_now() or (yt_log and time.time()
                                          - yt_log[-1] < 4 * 3600)):
            print("Видео подождёт: недавно уже было или сейчас ночь.")
            slots = 0
        if slots > 0:
            best = [v for v in fetch_youtube(YT_CHANNELS)
                    if v["id"] not in posted][:1]
            if best:
                for v in best:
                    res = tg.send_photo(v["image"], build_video_caption(v))
                    if args.dry_run or res.get("ok"):
                        posted.add(v["id"])
                        if not args.dry_run:
                            yt_log = (yt_log + [int(time.time())])[-30:]
                            state["yt_log"] = yt_log
                        sent_any = True
                    time.sleep(2)
            else:
                print("Новых лучших видео про Rust нет.")
        else:
            print("Лимит видео на сегодня исчерпан.")

    # 4) мастерская Steam: мастера (сразу) + конкурс-коллаж из РАЗНЫХ авторов
    if steam_key:
        now = time.time()
        counts = fetch_accepted_authors(steam_key)   # author_id -> принято
        verified = set(counts)
        elite = {a for a, c in counts.items() if c >= ELITE_MIN}
        newest = fetch_new_submissions(steam_key)

        # «Лучшее из воркшопа» — 3 раза в день по графику ELITE_SLOTS, в посте
        # до ELITE_BATCH авторов, у которых уже есть принятые скины, с их
        # свежими работами. Ручной запуск — сразу.
        slot = elite_slot()
        forced = os.environ.get("EXTRA_POST") == "лучшее из воркшопа"
        quiet = quiet_now() and not forced
        elite_sets = []
        if forced or (slot and state.get("elite_slot") != slot):
            skip = (set(state.get("accepted_seen", []))
                    | set(state.get("top_last", []))
                    | set(state.get("top_shown", [])))
            elite_sets = pick_elite_sets(newest, counts, posted, skip, now)
            if not elite_sets:
                print("Для «лучшего из воркшопа» сейчас нечего постить.")
        for st in elite_sets:
            elite.add(st[0]["author_id"])   # не дублируем в конкурсе
        elite_new = [s for st in elite_sets for s in st]

        # пул авторов альбома сбрасывается раз в неделю
        wk = iso_week(now)
        if state.get("week_authors_wk") != wk:
            state["week_authors"] = []
            state["week_authors_wk"] = wk
        week_authors = set(state.get("week_authors", []))

        # 5 скинов РАЗНЫХ авторов (не мастера, не повтор за неделю)
        ws_albums = state.get("ws_albums", [])
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        today_count = sum(
            1 for ts in ws_albums
            if time.strftime("%Y-%m-%d", time.gmtime(ts)) == today)
        hours_since = (now - max(ws_albums)) / 3600 if ws_albums else 999
        album = []
        if today_count < 2 and hours_since >= 5 and not quiet:
            used = set()
            for s in newest:
                a = s["author_id"]
                if (a not in verified or a in elite or a in used
                        or a in week_authors or s["id"] in posted):
                    continue
                used.add(a)
                album.append(s)
                if len(album) == 5:
                    break
            if len(album) < 5:
                print(f"Разных новых авторов пока {len(album)} (<5) — ждём.")
                album = []

        # имена авторов — только для тех, кого реально постим
        names = resolve_steam_names(
            steam_key, [s["author_id"] for s in elite_new + album])
        for s in elite_new + album:
            s["author"] = names.get(s["author_id"], "")

        # 4a) «Лучшее из воркшопа» — ОДИН пост на пачку авторов (альбомом)
        if elite_sets:
            works = [s for st in elite_sets for s in st]
            if len(works) == 1:
                res = tg.send_photo(works[0]["image"],
                                    build_elite_caption(works[0]))
            elif len(elite_sets) == 1:
                res = tg.send_media_group([s["image"] for s in works],
                                          build_elite_set_caption(works))
            else:
                res = tg.send_media_group([s["image"] for s in works][:10],
                                          build_elite_digest_caption(elite_sets))
            if args.dry_run or res.get("ok"):
                posted.update(s["id"] for s in works)
                if not args.dry_run:
                    state["elite_last_ts"] = int(now)
                    if slot:
                        state["elite_slot"] = slot
                sent_any = sent_any or not args.dry_run

        # 4b) конкурс: коллаж из 5 скинов + кнопки голосования — ОДИН пост
        if len(album) == 5:
            rid = str(state.get("round_seq", 0))
            caption = build_workshop_caption(album)
            markup = json.dumps({"inline_keyboard": [
                [{"text": NUM_EMOJI[i], "callback_data": f"v{rid}_{i}"}
                 for i in range(5)],
                [{"text": "✅ Подтвердить голос",
                  "callback_data": f"c{rid}"}]]}, ensure_ascii=False)
            collage = os.path.join(tempfile.gettempdir(), "rust_collage.jpg")
            if (contest_store_card(album, collage)
                    or build_collage([s["image"] for s in album], collage)):
                res = tg.send_photo_file(collage, caption, markup)
            else:
                # запасной путь: альбом + отдельное сообщение с кнопками
                res = tg.send_media_group([s["image"] for s in album], caption)
                if not args.dry_run and res.get("ok"):
                    tg.send_vote_buttons(
                        "\U0001f3af Жми номер — свой прогноз, потом «Подтвердить»:",
                        [NUM_EMOJI[i] for i in range(5)], rid)
            if args.dry_run or res.get("ok"):
                for s in album:
                    posted.add(s["id"])
                state["round_seq"] = state.get("round_seq", 0) + 1
                if not args.dry_run:
                    mid = (res.get("result") or {}).get("message_id")
                    rounds = state.setdefault("rounds", {})
                    rounds[rid] = {"pids": [s["id"] for s in album],
                                   "week": wk, "ts": int(now),
                                   "msg_id": mid, "caption": caption}
                    state["ws_albums"] = (ws_albums + [int(now)])[-10:]
                    state["week_authors"] = list(
                        week_authors | {s["author_id"] for s in album})
                sent_any = True

    # 4c) новые принятые в игру скины — пост «кого и что приняли»
    if steam_key and not args.dry_run:
        try:
            post_new_accepts(tg, state, steam_key)
        except Exception as e:
            print("Пост о принятых скинах не удался:", e)

    # 4d) магазин Rust: новинки недели с ценами
    if not args.dry_run:
        try:
            post_store_news(tg, state)
        except Exception as e:
            print("Пост о магазине не удался:", e)

    # 4e) онлайн: замер каждый запуск, вечером — сводка, при рекорде — пост
    if not args.dry_run:
        try:
            online_tick(tg, state, time.time())
        except Exception as e:
            print("Онлайн не получен:", e)

    # 4f) новости из официального X (@playrust) — без тихих часов
    if not args.dry_run:
        try:
            post_x_news(tg, state)
        except Exception as e:
            print("Новости из X не получены:", e)

    # 4g) маркет Steam: сводка цен раз в день в обед
    if not args.dry_run:
        try:
            market_tick(tg, state,
                        os.environ.get("EXTRA_POST") == "сводка маркета")
        except Exception as e:
            print("Сводка маркета не удалась:", e)

    # 4h) топ-3 скинов недели (micro522.com) — раз в ~3 дня вечером
    if not args.dry_run:
        try:
            top_tick(tg, state,
                     os.environ.get("EXTRA_POST") == "топ мастерской")
        except Exception as e:
            print("Топ мастерской не удался:", e)

    # 4i) новые рубрики: скин дня и «угадай цену» (rust_formats.py)
    if rust_formats and not args.dry_run:
        try:
            rust_formats.tick(tg, state, os.environ.get("EXTRA_POST")
                              == "новые рубрики — выложить сейчас")
        except Exception as e:
            print("Новые рубрики не удались:", e)
        # 4j) индекс рынка, викторина, вайп-день, сообщество из X
        rust_formats.extras_tick(tg, state, os.environ.get("EXTRA_POST")
                                 == "индекс, викторина, X — выложить сейчас")

    # 5) итоги конкурса — в воскресенье, один раз за неделю
    if steam_key and not args.dry_run:
        wk = iso_week(time.time())
        if time.gmtime().tm_wday == 6 and state.get("last_lb_week") != wk and not quiet_now():
            ranking, acc_count, had_polls = score_week(
                state, fetch_accepted_pids(steam_key))
            if had_polls:
                tg.send_message(build_leaderboard_caption(ranking, acc_count))
            state["last_lb_week"] = wk
        prune_rounds(state)

    # В сухом прогоне историю НЕ трогаем — иначе потом боевой запуск
    # решит, что всё уже постил, и ничего не отправит.
    if args.dry_run:
        print("Готово (dry-run: ничего не отправлено, история не изменена).")
    else:
        state["recent_phrases"] = _RECENT[-500:]
        # по порядку: старые id + новые, чтобы обрезка [-500:] убирала старейшие
        old = state.get("posted_ids", [])
        seen_old = set(old)
        state["posted_ids"] = old + [x for x in posted if x not in seen_old]
        save_state(state)
        print("Готово.")

if __name__ == "__main__":
    main()
