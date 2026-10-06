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
ELITE_MIN = 6
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
            title = title_el.text or ""
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
        собрался). Кнопки в один ряд."""
        kb = {"inline_keyboard": [
            [{"text": lbl, "callback_data": f"v{rid}_{i}"}
             for i, lbl in enumerate(labels)]]}
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


# ---------- сборка постов ----------

def today_str():
    return time.strftime("%d.%m.%Y")


def frame(kicker, title, body, hashtags):
    """Единый каркас поста: метка-бейдж, жирный заголовок, тело,
    разделитель и подпись канала. body — уже готовый HTML (не экранируем)."""
    parts = [f"{BRAND} <b>{kicker}</b>"]
    if title:
        parts.append(html.escape(title))
    parts += ["", body, "", DIVIDER,
              f"\U0001f4e2 {CHANNEL_TAG}   {hashtags}"]
    return "\n".join(parts)


def build_news_caption(news):
    body = "\n".join(
        f"🔹 <a href=\"{n['url']}\">{html.escape(n['title'])}</a>"
        for n in news)
    return frame(f"НОВОСТИ RUST · {today_str()}", "Свежие обновления",
                 body, "#rust #раст #новости")


FLAIR_EMOJI = {
    "Base Design": "🏰", "Image": "🖼", "Video": "🎬",
    "Work in Progress": "🔨", "Art": "🎨", "Discussion": "💬",
}


def build_work_caption(w, index):
    emoji = FLAIR_EMOJI.get(w["flair"], "🔥")
    kicker = f"{emoji} РАБОТА ДНЯ"
    if w["flair"]:
        kicker += f" · {html.escape(w['flair'])}"
    body = (f"👤 u/{html.escape(w['author'])}   ⬆️ {w['score']}\n"
            f"🔗 <a href=\"{w['url']}\">Обсуждение на r/playrust</a>")
    return frame(kicker, w["title"], body, "#rust #раст #работы")


def fmt_views(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n // 1000}K"
    return str(n)


def build_video_caption(v):
    kicker = f"🎬 {html.escape(v['author'])} · ВИДЕО ДНЯ"
    views = f"   👁 {fmt_views(v['views'])}" if v.get("views") else ""
    body = f"▶️ <a href=\"{v['url']}\">Смотреть на YouTube</a>{views}"
    return frame(kicker, v["title"], body, "#rust #раст #видео")


NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣",
             "5️⃣", "6️⃣", "7️⃣", "8️⃣",
             "9️⃣", "\U0001f51f"]


def build_workshop_caption(skins):
    lines = []
    for i, s in enumerate(skins):
        title = html.escape(translate_to_ru(clean(s["title_raw"], 80)))
        author = html.escape(s["author"] or "автор неизвестен")
        lines.append(f"{NUM_EMOJI[i]} <b>{title}</b> — {author}")
    lines.append("")
    lines.append("\U0001f3af Какой из них примут в игру? Жми ОДИН номер "
                 "под постом. Итоги — в конце недели \U0001f3c6")
    return frame("\U0001f3a8 КОНКУРС · УГАДАЙ ПРИНЯТЫЙ СКИН",
                 "5 новых работ — у каждого свой автор",
                 "\n".join(lines), "#rust #раст #скины #конкурс")


def build_elite_caption(s):
    title = translate_to_ru(clean(s["title_raw"], 90))
    body = (f""
            f""
            f"\U0001f464 <b>{html.escape(s['author'] or 'автор')}</b>\n"
            f"\U0001f517 <a href=\"{s['url']}\">Открыть в мастерской</a>")
    return frame("\U0001f525 ЛУЧШЕЕ ИЗ ВОРКШОПА", title, body,
                 "#rust #раст #воркшоп #скин")


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


def collect_votes(tg, state):
    """Забираем нажатия кнопок (callback_query). Один голос на игрока:
    новое нажатие заменяет прежний прогноз."""
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
        user = cq.get("from") or {}
        uid = str(user.get("id"))
        if not uid or uid == "None":
            continue
        name = user.get("username") or user.get("first_name") or "Игрок"
        votes.setdefault(rid, {})
        votes[rid][uid] = {"pid": skins[idx], "name": name}
    state["votes"] = votes
    state["update_offset"] = last + 1


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

def main():
    ap = argparse.ArgumentParser(description="Rust Digest Bot для Telegram")
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--dry-run", action="store_true",
                    help="ничего не постить, только показать в консоли")
    args = ap.parse_args()

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
    posted = set(state.get("posted_ids", []))
    tg = Telegram(token, chat, dry_run=args.dry_run)

    # сначала забираем новые голоса конкурса
    if not args.dry_run:
        try:
            collect_votes(tg, state)
        except Exception as e:
            print("Сбор голосов не удался:", e)

    sent_any = False

    # 1) официальные новости (с фирменной шапкой Rust)
    if post_news:
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
        if slots > 0:
            best = [v for v in fetch_youtube(YT_CHANNELS)
                    if v["id"] not in posted][:slots]
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

        # мастера: их новые работы постим СРАЗУ, отдельными постами
        elite_new = [s for s in newest
                     if s["author_id"] in elite and s["id"] not in posted
                     ][:ELITE_MAX_PER_RUN]

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
        if today_count < 2 and hours_since >= 5:
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

        # 4a) посты мастеров — сразу, отдельно
        for s in elite_new:
            res = tg.send_photo(s["image"], build_elite_caption(s))
            if args.dry_run or res.get("ok"):
                posted.add(s["id"])
                sent_any = sent_any or not args.dry_run
            time.sleep(2)

        # 4b) конкурс: коллаж из 5 скинов + кнопки голосования — ОДИН пост
        if len(album) == 5:
            rid = str(state.get("round_seq", 0))
            caption = build_workshop_caption(album)
            markup = json.dumps({"inline_keyboard": [[
                {"text": NUM_EMOJI[i], "callback_data": f"v{rid}_{i}"}
                for i in range(5)]]}, ensure_ascii=False)
            collage = os.path.join(tempfile.gettempdir(), "rust_collage.jpg")
            if build_collage([s["image"] for s in album], collage):
                res = tg.send_photo_file(collage, caption, markup)
            else:
                # запасной путь: альбом + отдельное сообщение с кнопками
                res = tg.send_media_group([s["image"] for s in album], caption)
                if not args.dry_run and res.get("ok"):
                    tg.send_vote_buttons(
                        "\U0001f3af Жми ОДИН номер — свой прогноз:",
                        [NUM_EMOJI[i] for i in range(5)], rid)
            if args.dry_run or res.get("ok"):
                for s in album:
                    posted.add(s["id"])
                state["round_seq"] = state.get("round_seq", 0) + 1
                if not args.dry_run:
                    rounds = state.setdefault("rounds", {})
                    rounds[rid] = {"pids": [s["id"] for s in album],
                                   "week": wk, "ts": int(now)}
                    state["ws_albums"] = (ws_albums + [int(now)])[-10:]
                    state["week_authors"] = list(
                        week_authors | {s["author_id"] for s in album})
                sent_any = True

    # 5) итоги конкурса — в воскресенье, один раз за неделю
    if steam_key and not args.dry_run:
        wk = iso_week(time.time())
        if time.gmtime().tm_wday == 6 and state.get("last_lb_week") != wk:
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
        state["posted_ids"] = list(posted)
        save_state(state)
        print("Готово.")


if __name__ == "__main__":
    main()
