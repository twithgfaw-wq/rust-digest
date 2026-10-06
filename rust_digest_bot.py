#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust Digest Bot — автоматическая сводка новостей по игре Rust в Telegram.

Что делает за один прогон:
  1. Берёт свежие ОФИЦИАЛЬНЫЕ новости Rust из Steam News API.
  2. Берёт топ "крутых работ" из r/playrust (базы, билды, арт, моменты).
  3. Берёт новые видео YouTube-блогеров по Rust (hedgesn и др.).
  4. Берёт свежие работы из мастерской Steam от ПРОВЕРЕННЫХ авторов
     (тех, чьи скины уже принимали в игру) — альбом из 5 штук.
  5. Публикует всё это в твой Telegram-канал с картинками и ссылками.

Английские заголовки автоматически переводятся на русский.

Только стандартная библиотека Python 3 — ставить ничего не надо.
"""

import argparse
import configparser
import datetime
import html
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

RUST_APPID = 252490
UA = "RustDigestBot/1.0 (personal Telegram digest)"
STATE_FILE = "posted_state.json"   # чтобы не постить одно и то же дважды

# YouTube-блогеры по Rust: (отображаемое имя, channel_id).
# Новые видео этих каналов автоматически улетают в канал.
# Чтобы добавить блогера — пришли ссылку на его канал, впишу сюда ID.
YT_CHANNELS = [
    ("Hedge", "UCftwbY3DWqa5QWxZtA_BuvQ"),
]


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


def fetch_youtube(channels, max_age_days=4):
    """Новые видео YouTube-блогеров через их RSS-ленты (без ключей).
    Берём только свежие (за последние max_age_days дней), чтобы при
    первом включении не вывалить весь архив."""
    atom = "{http://www.w3.org/2005/Atom}"
    ytns = "{http://www.youtube.com/xml/schemas/2015}"
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
            vid = vid_el.text
            pub = pub_el.text if pub_el is not None else ""
            try:
                dt = datetime.datetime.fromisoformat(
                    pub.replace("Z", "+00:00"))
                if (now - dt.timestamp()) / 86400 > max_age_days:
                    continue
            except Exception:
                pass
            out.append({
                "id": "yt_" + vid,
                "title": translate_to_ru(clean(title_el.text, 200)),
                "author": name,
                "url": "https://www.youtube.com/watch?v=" + vid,
                "image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "published": pub,
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    return out


def resolve_steam_names(api_key, steamids):
    """SteamID -> ник автора (одним запросом на всех)."""
    ids = ",".join(sorted({str(s) for s in steamids if s}))
    if not ids:
        return {}
    url = ("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
           f"?key={api_key}&steamids={ids}")
    try:
        data = http_get_json(url, timeout=15)
        players = data.get("response", {}).get("players", [])
        return {p.get("steamid"): p.get("personaname", "") for p in players}
    except Exception:
        return {}


def _query_files(api_key, query_type, per, cursor):
    url = ("https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
           f"?key={api_key}&appid={RUST_APPID}&query_type={query_type}"
           f"&numperpage={per}&cursor={urllib.parse.quote(cursor)}"
           "&return_previews=true&return_metadata=true&requiredtags%5B0%5D=Skin")
    return http_get_json(url, timeout=20).get("response", {})


def fetch_accepted_author_ids(api_key, pages=8, per=100):
    """SteamID проверенных авторов — тех, чьи скины УЖЕ приняли в игру
    (query_type=2 = accepted-for-game). Листаем несколько страниц."""
    ids, cursor = set(), "*"
    for _ in range(pages):
        try:
            resp = _query_files(api_key, 2, per, cursor)
        except Exception as e:
            print("Список проверенных авторов не загрузился:", e)
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            c = it.get("creator")
            if c:
                ids.add(str(c))
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    return ids


def fetch_new_from_verified(api_key, verified_ids, want=5, scan_pages=5,
                            per=50, max_age_days=14):
    """Свежие НОВЫЕ заявки (query_type=1, по дате публикации), но только
    от проверенных авторов из verified_ids."""
    picked, steamids, cursor = [], [], "*"
    now = time.time()
    seen = set()
    for _ in range(scan_pages):
        try:
            resp = _query_files(api_key, 1, per, cursor)
        except Exception as e:
            print("Новые работы не загрузились:", e)
            break
        items = resp.get("publishedfiledetails", [])
        for it in items:
            creator = str(it.get("creator") or "")
            if creator not in verified_ids:
                continue
            pid = it.get("publishedfileid")
            preview = it.get("preview_url")
            title = it.get("title")
            if not pid or not preview or not title or pid in seen:
                continue
            tc = it.get("time_created", 0) or 0
            if tc and (now - tc) / 86400 > max_age_days:
                continue
            seen.add(pid)
            picked.append({
                "id": "ws_" + str(pid),
                "title_raw": title,
                "author_id": creator,
                "author": "",
                "image": preview,
                "created": tc,
                "url": ("https://steamcommunity.com/sharedfiles/filedetails/"
                        "?id=" + str(pid)),
            })
            steamids.append(creator)
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items or len(picked) >= want * 3:
            break
    picked.sort(key=lambda x: x["created"], reverse=True)
    names = resolve_steam_names(api_key, steamids)
    for s in picked:
        s["author"] = names.get(s["author_id"], "")
    return picked


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


# ---------- сборка постов ----------

def today_str():
    return time.strftime("%d.%m.%Y")


def build_news_text(news):
    lines = [f"📰 <b>RUST — сводка новостей</b> · {today_str()}", ""]
    for n in news:
        lines.append(f"🔹 <a href=\"{n['url']}\">{html.escape(n['title'])}</a>")
    lines.append("")
    lines.append("#rust #раст #новости")
    return "\n".join(lines)


FLAIR_EMOJI = {
    "Base Design": "🏰", "Image": "🖼", "Video": "🎬",
    "Work in Progress": "🔨", "Art": "🎨", "Discussion": "💬",
}

def build_work_caption(w, index):
    emoji = FLAIR_EMOJI.get(w["flair"], "🔥")
    tag = f" · {html.escape(w['flair'])}" if w["flair"] else ""
    return (f"{emoji} <b>Работа дня #{index}</b>{tag}\n"
            f"{html.escape(w['title'])}\n\n"
            f"👤 u/{html.escape(w['author'])} · ⬆️ {w['score']}\n"
            f"🔗 <a href=\"{w['url']}\">обсуждение на r/playrust</a>\n\n"
            f"#rust #раст #работы")


def build_video_caption(v):
    return (f"🎬 <b>{html.escape(v['author'])}</b> — новое видео\n"
            f"{html.escape(v['title'])}\n\n"
            f"▶️ <a href=\"{v['url']}\">смотреть на YouTube</a>\n\n"
            f"#rust #раст #видео")


NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣",
             "5️⃣", "6️⃣", "7️⃣", "8️⃣",
             "9️⃣", "\U0001f51f"]


def build_workshop_caption(skins):
    lines = ["\U0001f3a8 <b>Мастерская Rust — новинки</b>",
             "Свежие работы авторов, чьи скины уже в игре:", ""]
    for i, s in enumerate(skins):
        title = translate_to_ru(clean(s["title_raw"], 90))
        author = s["author"] or "автор неизвестен"
        lines.append(f"{NUM_EMOJI[i]} <b>{html.escape(title)}</b> — "
                     f"{html.escape(author)}")
    lines.append("")
    lines.append("#rust #раст #скины #мастерская")
    return "\n".join(lines)


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
    works_count = int(os.environ.get("WORKS_COUNT")
                      or cfg.get("content", "works_count", fallback="3"))
    min_score = int(os.environ.get("MIN_SCORE")
                    or cfg.get("content", "min_score", fallback="300"))
    post_news = (os.environ.get("POST_OFFICIAL_NEWS")
                 or cfg.get("content", "post_official_news",
                            fallback="true")).strip().lower() in ("1", "true", "yes", "on")
    period = (os.environ.get("REDDIT_PERIOD")
              or cfg.get("content", "reddit_period", fallback="day")).strip()

    if not args.dry_run and ("PASTE_BOT_TOKEN" in token or not token or not chat):
        print("Нет токена/канала. Локально — заполни config.ini; "
              "в GitHub Actions — задай секреты BOT_TOKEN и CHANNEL. "
              "(Или запусти с --dry-run для проверки.)")
        sys.exit(1)

    state = load_state()
    posted = set(state.get("posted_ids", []))
    tg = Telegram(token, chat, dry_run=args.dry_run)

    sent_any = False

    # 1) официальные новости
    if post_news:
        news = [n for n in fetch_official_news(5) if n["id"] not in posted][:3]
        if news:
            res = tg.send_message(build_news_text(news))
            # В историю пишем ТОЛЬКО если Telegram принял отправку —
            # иначе при ошибке (бот не админ и т.п.) попробуем снова.
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

    # 3) новые видео блогеров (YouTube)
    yt_count = int(os.environ.get("YT_COUNT") or "2")
    if YT_CHANNELS and yt_count > 0:
        videos = [v for v in fetch_youtube(YT_CHANNELS)
                  if v["id"] not in posted][:yt_count]
        if videos:
            for v in videos:
                res = tg.send_photo(v["image"], build_video_caption(v))
                if args.dry_run or res.get("ok"):
                    posted.add(v["id"])
                    sent_any = sent_any or not args.dry_run
                time.sleep(2)
        else:
            print("Новых видео блогеров нет.")

    # 4) мастерская Steam — альбом из 5 новинок проверенных авторов, до 2/день
    steam_key = (os.environ.get("STEAM_API_KEY")
                 or cfg.get("content", "steam_api_key", fallback="")).strip()
    if steam_key:
        ws_albums = state.get("ws_albums", [])
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        today_count = sum(
            1 for ts in ws_albums
            if time.strftime("%Y-%m-%d", time.gmtime(ts)) == today)
        hours_since = (now - max(ws_albums)) / 3600 if ws_albums else 999
        if today_count < 2 and hours_since >= 5:
            verified = fetch_accepted_author_ids(steam_key)
            cand = [s for s in fetch_new_from_verified(steam_key, verified)
                    if s["id"] not in posted]
            fresh = cand[:5]
            if len(fresh) >= 5:
                res = tg.send_media_group([s["image"] for s in fresh],
                                          build_workshop_caption(fresh))
                if args.dry_run or res.get("ok"):
                    for s in fresh:
                        posted.add(s["id"])
                    if not args.dry_run:
                        state["ws_albums"] = (ws_albums + [int(now)])[-10:]
                    sent_any = True
            else:
                print(f"Новых работ от проверенных авторов пока "
                      f"{len(fresh)} (<5) — ждём накопления.")

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
