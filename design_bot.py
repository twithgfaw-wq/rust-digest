#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Her Design Bot — канал @Her_Design «Все про дизайн».

Що робить за один прогін (GitHub Actions раз на 30 хв, а також миттєвий
запуск від Cloudflare Worker, щойно в джерелах з'являється нове):
  ⚡ Новини дизайну і 👤 дизайнери — свіжі статті з дизайнерських медіа
     (Dezeen, designboom, Creative Boom, Abduzeedo, Creative Bloq,
     Wallpaper*, Fast Company, Figma, Awwwards). Claude оцінює кожну
     від 1 до 10, і одразу виходять лише 8+. Текст українською, тільки
     факти зі статті, і перед публікацією окремий фактчек звіряє кожне
     твердження зі статтею. Картка у фірмовому стилі з фото джерела, автор
     роботи й посилання на оригінал.

Бот той самий, що в @rust_news_Pro і @cs2_me (BOT_TOKEN).

Запуск: python design_bot.py
  DESIGN_DRY=1      — нічого не надсилати, тільки лог;
  DESIGN_DEMO=1     — приклади постів у лог (картки як CARD_B64) і перевірка
                      прав бота в каналі. Нічого не надсилає;
  DESIGN_BEST_NOW=1 — опублікувати найкращу новину за добу зараз.
"""
import email.utils
import html
import io
import json
import os
import random
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import cs2_ai as ai
import design_cards as cards
import rust_digest_bot as bot

STATE_FILE = "design_state.json"
CHANNEL_TAG = "@Her_Design"          # підпис у футері (оновлюється в main)
UA = cards.UA

FEEDS = [
    ("Dezeen", "https://www.dezeen.com/feed/"),
    ("designboom", "https://www.designboom.com/feed/"),
    ("Creative Boom", "https://www.creativeboom.com/feed/"),
    ("Abduzeedo", "https://abduzeedo.com/rss.xml"),
    ("Creative Bloq", "https://www.creativebloq.com/feeds.xml"),
    ("Wallpaper*", "https://www.wallpaper.com/feeds.xml"),
    ("Fast Company", "https://www.fastcompany.com/co-design/rss"),
    ("Figma", "https://www.figma.com/blog/feed/atom.xml"),
    ("Awwwards", "https://www.awwwards.com/blog/feed/"),
]
LIVE = False           # увімкнемо після схвалення прикладів
MIN_SCORE = 8          # одразу публікуємо лише 8+ з 10
MAX_PER_RUN = 2        # за один прогін — не більше двох новин
MAX_PER_DAY = 10
MAX_AGE_H = 36         # старіші статті не беремо
QUEUE_H = 24           # відібрані, але ще не опубліковані — чекають добу
QUIET = (0, 8)         # вночі за Києвом не постимо; зранку — найкраще за ніч

# рубрика → (шапка поста, мітка на картці, табличка на картці, хештеги)
RUBRICS = {
    "news": ("⚡ НОВИНИ ДИЗАЙНУ", "НОВИНА", "#новини", "#дизайн #новини"),
    "designer": ("👤 ДИЗАЙНЕР", "ДИЗАЙНЕР", "#дизайнер", "#дизайн #дизайнер"),
}
FOOTERS = [
    "💙 Все про дизайн — {tag}",
    "✏️ {tag} — все про дизайн",
    "📌 Більше дизайну — {tag}",
]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]

STYLE = """Ти — редактор українського Telegram-каналу @Her_Design «Все про
дизайн»: графічний дизайн, брендинг, шрифти, UI/UX, ілюстрація, моушн,
упаковка, предметний дизайн. Пишеш як досвідчений дизайнер для колег і тих,
хто вчиться: жива природна українська мова, конкретика, короткі речення.
Без води і шаблонних фраз («у світі дизайну», «давайте розберемося», «не
секрет, що», «варто зазначити», «друзі»), без канцеляриту й захоплених
вигуків.

Правила:
- Тільки факти зі статті. Нічого не вигадуй: ні імен, ні цифр, ні дат, ні
  причин. Чого немає в тексті — про те не пиши.
- Імена людей, студій, брендів і назви шрифтів пиши як в оригіналі
  (латиницею).
- Формат — Telegram HTML: лише <b> та <i>. Без Markdown і без посилань —
  посилання бот додасть сам.
"""


# ---------- допоміжне ----------

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": ("application/rss+xml, application/atom+xml, "
                   "application/xml, text/xml, text/html;q=0.9, */*;q=0.8")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def key(link):
    """Посилання без #якоря та utm-міток — щоб не постити одне двічі."""
    link = (link or "").strip().split("#")[0]
    if "?" in link:
        base, qs = link.split("?", 1)
        keep = [x for x in qs.split("&")
                if x and not x.lower().startswith("utm_")]
        link = base + ("?" + "&".join(keep) if keep else "")
    return link.rstrip("/")


def strip_html(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def kdate(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Kyiv"))
    except Exception:
        return datetime.fromtimestamp(ts + 3 * 3600, timezone.utc)


def date_ua(ts):
    d = kdate(ts)
    return f"{d.day} {MONTHS[d.month - 1]}"


def visible_len(text):
    """Довжина підпису так, як її рахує Telegram (без тегів, UTF-16)."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def safe_html(s):
    """Лишаємо тільки <b> та <i>, решту екрануємо."""
    s = html.escape(html.unescape(s or ""), quote=False)
    for t in ("b", "i"):
        s = s.replace(f"&lt;{t}&gt;", f"<{t}>").replace(f"&lt;/{t}&gt;",
                                                        f"</{t}>")
    return s.strip()


# ---------- стан ----------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    if "seen" in state:
        state["seen"] = state["seen"][-2000:]
    state["posted"] = state.get("posted", [])[-300:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- джерела (RSS і Atom) ----------

def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child(el, *names):
    for c in el:
        if local(c.tag) in names:
            return c
    return None


IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def item_image(el, raw):
    for c in el.iter():
        n, url = local(c.tag), c.get("url")
        if not url:
            continue
        if n in ("content", "thumbnail") and (
                "image" in (c.get("type") or "image")
                or c.get("medium") == "image"):
            return url
        if n == "enclosure" and (c.get("type") or "").startswith("image"):
            return url
    m = IMG_RE.search(raw or "")
    return html.unescape(m.group(1)) if m else ""


def parse_feed(name, data):
    root = ET.fromstring(data.lstrip(b"\xef\xbb\xbf \t\r\n"))
    out = []
    for e in [x for x in root.iter() if local(x.tag) in ("item", "entry")][:40]:
        title = strip_html("".join(child(e, "title").itertext())
                           if child(e, "title") is not None else "")
        link = ""
        for c in e:
            if local(c.tag) != "link":
                continue
            if (c.text or "").strip():
                link = c.text.strip()
                break
            if c.get("href") and c.get("rel", "alternate") == "alternate":
                link = c.get("href")
                break
        raw = max(("".join(c.itertext()) for c in e if local(c.tag) in
                   ("encoded", "content", "description", "summary")),
                  key=len, default="")
        ts = None
        for nm in ("pubdate", "published", "updated", "date"):
            c = child(e, nm)
            if c is not None and (c.text or "").strip():
                ts = parse_date(c.text)
                if ts:
                    break
        if title and link:
            out.append({"src": name, "title": title, "link": link,
                        "ts": ts or 0, "text": strip_html(raw)[:6000],
                        "image": item_image(e, raw)})
    return out


def fetch_all():
    items, report = [], []
    for name, url in FEEDS:
        try:
            got = parse_feed(name, http_get(url))
            items += got
            report.append(f"{name} {len(got)}")
        except Exception as e:
            report.append(f"{name} ✖ {type(e).__name__}")
            print(f"{name}: не вдалося прочитати ({type(e).__name__}: "
                  f"{str(e)[:120]})")
    print("Джерела:", ", ".join(report))
    return items


def article_text(item):
    """Якщо в RSS лише анонс або немає фото — беремо зі сторінки статті
    абзаци тексту й og:image."""
    if len(item.get("text", "")) >= 1500 and item.get("image"):
        return
    try:
        page = http_get(item["link"]).decode("utf-8", "replace")
    except Exception as e:
        print("Сторінка статті не відкрилась:", type(e).__name__)
        return
    if not item.get("image"):
        m = (re.search(r"<meta[^>]+property=[\"']og:image[\"'][^>]+"
                       r"content=[\"']([^\"']+)", page, re.I)
             or re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+"
                          r"property=[\"']og:image", page, re.I))
        if m:
            item["image"] = html.unescape(m.group(1))
    if len(item.get("text", "")) < 1500:
        paras = [strip_html(x) for x in
                 re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)]
        body = "\n".join(x for x in paras if len(x) > 60)
        if len(body) > len(item.get("text", "")):
            item["text"] = body[:9000]


# ---------- Claude: відбір і текст ----------

SCORE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "idx": {"type": "integer"},
            "score": {"type": "integer"},
            "kind": {"type": "string", "enum": ["news", "designer", "skip"]},
            "duplicate": {"type": "boolean"},
        },
        "required": ["idx", "score", "kind", "duplicate"],
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "duplicate": {"type": "boolean"},
        "headline": {"type": "string"},
        "card_title": {"type": "string"},
        "body": {"type": "string"},
        "credit": {"type": "string"},
    },
    "required": ["duplicate", "headline", "card_title", "body", "credit"],
    "additionalProperties": False,
}


def earlier_block(earlier):
    if not earlier:
        return ""
    return ("\n\nУже вийшло в каналі за останні 2 доби:\n"
            + "\n".join("— " + t for t in earlier))


def score_items(items, earlier):
    """Оцінки Claude: {idx: {score, kind, duplicate}} або None."""
    lines = "\n".join(
        f"[{i}] {it['src']} | {it['title']} | "
        + it["text"][:350].replace("\n", " ")
        for i, it in enumerate(items))
    prompt = f"""Ось свіжі статті з дизайнерських медіа. Оціни кожну для каналу
«Все про дизайн» — для дизайнерів і тих, хто вчиться: графічний дизайн,
брендинг і айдентика, шрифти й типографіка, UI/UX і продуктовий дизайн,
ілюстрація, моушн, упаковка, предметний дизайн, дизайн-інструменти
(Figma, Adobe тощо).

score від 1 до 10 — наскільки це круто і важливо саме для цієї аудиторії:
- 9–10: про це говоритиме вся індустрія — ребрендинг відомого бренду,
  великий запуск або зміна у Figma, Adobe, Apple, вражаюча робота топ-студії
  чи відомого дизайнера, гучна подія або скандал довкола дизайну;
- 7–8: сильний гарний проєкт, цікава айдентика, свіжий погляд, яскрава
  історія дизайнера;
- 1–6: рядове, локальне, рекламне, огляди товарів і знижки, добірки
  подарунків, нерухомість, звичайна архітектура чи інтер'єр без дизайнерської
  родзинки, корпоративні новини без візуальної цікавинки.
Архітектуру та інтер'єри оцінюй на 8+ лише якщо це справді вражає.

kind: «designer» — якщо стаття насамперед про конкретного дизайнера чи
студію (інтерв'ю, портрет, творчий шлях, огляд їхніх робіт); «news» — усе
інше, що підходить каналу; «skip» — не для каналу.
duplicate: true — якщо це та сама подія, що вже вийшла в каналі (список
нижче), або якщо інша стаття в цьому списку розповідає про те саме і
цікавіша; інакше false.

Поверни оцінку для кожної статті за її номером idx.{earlier_block(earlier)}

Статті:
{lines}"""
    res = ai.ask(prompt, SCORE_SCHEMA, effort="low", max_tokens=8000,
                 system=STYLE)
    if not res:
        return None
    return {r["idx"]: r for r in res.get("items", [])
            if 0 <= r.get("idx", -1) < len(items)}


def write_post(item, kind, earlier):
    """Пост українською: {duplicate, headline, card_title, body, credit}."""
    rubric = ("👤 ДИЗАЙНЕР — історія про конкретного дизайнера чи студію: хто "
              "це, чим цікаві, що зробили" if kind == "designer" else
              "⚡ НОВИНИ ДИЗАЙНУ — що сталося і чому це цікаво дизайнерам")
    prompt = f"""Перед тобою стаття з {item['src']}. Напиши пост для каналу своїми
словами — не перекладай дослівно.

Рубрика: {rubric}.

Що потрібно:
- headline: короткий чіпкий заголовок українською, до 80 знаків, без емодзі.
- card_title: заголовок для картинки — до 60 знаків, простіший і коротший.
- body: 2–3 короткі абзаци, разом до 550 знаків: суть, найцікавіші деталі
  і чому це варто побачити. Telegram HTML, лише <b> та <i>, без посилань.
- credit: хто автор роботи (студія чи дизайнер, як в оригіналі), якщо це
  прямо сказано в статті; інакше порожній рядок.
- duplicate: true, якщо це та сама подія, що вже вийшла в каналі (список
  нижче); інакше false.

Тільки факти зі статті, і точно: не узагальнюй («усе», «завжди», «перший»),
якщо в тексті сказано обережніше, і не переплутуй деталі.{earlier_block(earlier)}

Заголовок статті: {item['title']}
Посилання: {item['link']}

Текст статті:
{item.get('text', '')[:9000]}"""
    return ai.ask(prompt, POST_SCHEMA, effort="medium", max_tokens=8000,
                  system=STYLE)


CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "fixes": {"type": "array", "items": {"type": "string"}},
        "headline": {"type": "string"},
        "card_title": {"type": "string"},
        "body": {"type": "string"},
        "credit": {"type": "string"},
    },
    "required": ["fixes", "headline", "card_title", "body", "credit"],
    "additionalProperties": False,
}


def verify_post(item, post):
    """Звіряємо чернетку з текстом статті й виправляємо неточності.
    Повертає виправлений пост (fixes — що змінено) або None."""
    draft = json.dumps({k: post[k] for k in
                        ("headline", "card_title", "body", "credit")},
                       ensure_ascii=False, indent=1)
    prompt = f"""Ти — фактчекер. Звір кожне твердження чернетки поста з текстом
статті: імена, назви, числа, дати, хто що зробив, які деталі є в проєкті.
Виправ усе, що текст не підтверджує або що сказано неточно: перебільшення
(«усе», «завжди», «перший»), переплутані деталі, приписані не тим людям роботи.
Непідтверджене — прибери. Стиль і довжину не змінюй, нічого нового не додавай.
Якщо все точно — поверни чернетку без змін і порожній fixes. fixes — коротко,
що саме виправлено.

Чернетка (JSON):
{draft}

Стаття «{item['title']}» ({item['src']}):
{item.get('text', '')[:9000]}"""
    res = ai.ask(prompt, CHECK_SCHEMA, effort="medium", max_tokens=8000,
                 system=STYLE)
    if not res:
        return None
    if res["fixes"]:
        print("Фактчек виправив:", "; ".join(res["fixes"])[:500])
    return dict(post, **{k: res[k] for k in
                         ("headline", "card_title", "body", "credit")})


# ---------- пост ----------

def caption(kind, post, item):
    kicker, _, _, tags = RUBRICS[kind]
    foot = random.choice(FOOTERS).format(tag=CHANNEL_TAG)
    headline = html.escape(post["headline"].strip(), quote=False)

    def build(body, credit):
        parts = [f"<b>{kicker}</b>", f"<b>{headline}</b>", "", body, ""]
        if credit:
            parts.append("🎨 Автор: " + html.escape(credit, quote=False))
        parts.append(f'🔗 <a href="{html.escape(item["link"])}">Джерело: '
                     f'{html.escape(item["src"], quote=False)}</a>')
        parts += ["", foot, tags]
        return "\n".join(parts)

    body = safe_html(post["body"])
    credit = (post.get("credit") or "").strip()
    text = build(body, credit)
    if visible_len(text) > 1024:
        text = build(body, "")
    while visible_len(text) > 1024 and "\n\n" in body:
        body = body.rsplit("\n\n", 1)[0]
        text = build(body, "")
    if visible_len(text) > 1024:
        plain = html.escape(html.unescape(re.sub(r"<[^>]+>", "", body)),
                            quote=False)
        text = build(plain[:500].rsplit(" ", 1)[0] + "…", "")
    return text


def make_card(kind, post, item):
    _, label, tag, _ = RUBRICS[kind]
    meta = item["src"] + (" · " + date_ua(item["ts"]) if item["ts"] else "")
    path = os.path.join(tempfile.gettempdir(),
                        f"hd_card_{int(time.time() * 1000)}.jpg")
    ok = cards.news_card(label, post.get("card_title") or post["headline"],
                         meta, item.get("image"), path, tag=tag,
                         handle=CHANNEL_TAG)
    return path if ok else None


def send_post(tg, card, image_url, text):
    res = tg.send_photo_file(card, text) if card else {}
    if not res.get("ok") and image_url:
        res = tg.send_photo(image_url, text)
    if not res.get("ok"):
        res = tg.send_message(text[:4096])
    return res


def earlier_titles(state, now, hours=48):
    return [x["title"] for x in state.get("posted", [])
            if now - x.get("t", 0) < hours * 3600][-30:]


def publish(tg, state, q, now):
    """posted — вийшло; skip — дубль, викидаємо; retry — спробуємо ще."""
    article_text(q)
    post = write_post(q, q["kind"], earlier_titles(state, now))
    if not post:
        return "retry"
    if post.get("duplicate"):
        print("Дубль — пропускаю:", q["title"][:90])
        return "skip"
    post = verify_post(q, post)
    if not post:                 # без фактчеку не публікуємо
        return "retry"
    text = caption(q["kind"], post, q)
    card = make_card(q["kind"], post, q)
    res = send_post(tg, card, q.get("image"), text)
    if not res.get("ok"):
        return "retry"
    state.setdefault("posted", []).append({
        "t": now, "title": post["headline"], "link": key(q["link"]),
        "src": q["src"]})
    print("Опубліковано:", post["headline"])
    return "posted"


# ---------- новини ----------

def news_tick(tg, state, now, kt, best_now=False):
    items = fetch_all()
    if not items:
        print("Жодне джерело не відповіло.")
        return
    first = "seen" not in state
    if first and not best_now:
        state["seen"] = [key(i["link"]) for i in items]
        print(f"Перший запуск: запам'ятав {len(items)} статей, "
              "нічого не публікую.")
        return
    if not best_now and QUIET[0] <= kt.hour < QUIET[1]:
        print("Ніч за Києвом — новини чекають ранку.")
        return
    seen_list = state.setdefault("seen", [])
    seen = set(seen_list)
    posted = {x["link"] for x in state.get("posted", [])}
    skip = posted if best_now else seen
    max_age = (24 if best_now else MAX_AGE_H) * 3600
    uniq = {}
    for i in items:
        k = key(i["link"])
        if k not in skip and (not i["ts"] or now - i["ts"] < max_age):
            uniq.setdefault(k, i)
    new = sorted(uniq.values(), key=lambda i: -(i["ts"] or now))[:60]
    queue = [q for q in state.get("queue", [])
             if now - q.get("found", now) < QUEUE_H * 3600]
    best = []          # для «найкраща новина зараз»: усе пристойне (5+)
    if new:
        print(f"Нових статей: {len(new)}")
        scores = score_items(new, earlier_titles(state, now))
        if scores is None:
            print("Claude не оцінив статті — спробуємо наступного прогону.")
            state["queue"] = queue
            return
        for idx, it in enumerate(new):
            k = key(it["link"])
            unseen = k not in seen
            if unseen:
                seen_list.append(k)
                seen.add(k)
            r = scores.get(idx)
            if not r:
                continue
            print(f"  {r['score']:>2} {r['kind']:<8}"
                  f"{' дубль' if r['duplicate'] else ''} | "
                  f"{it['src']}: {it['title'][:90]}")
            if r["kind"] == "skip" or r["duplicate"]:
                continue
            q = dict(it, text=it["text"][:3000], score=r["score"],
                     kind=r["kind"], found=now)
            if (unseen and r["score"] >= MIN_SCORE
                    and k not in {key(x["link"]) for x in queue}):
                queue.append(q)
            if best_now and r["score"] >= 5:
                best.append(q)
    if first:          # усе, що зараз у джерелах, далі вважаємо баченим
        for i in items:
            k = key(i["link"])
            if k not in seen:
                seen_list.append(k)
                seen.add(k)
    today = kt.strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"], state["day_count"] = today, 0
    if best_now:
        best.sort(key=lambda q: (-q["score"], -(q["ts"] or 0)))
        for q in best[:3]:          # якщо перша виявиться дублем — наступна
            res = publish(tg, state, q, now)
            if res == "posted":
                state["day_count"] += 1
                queue = [x for x in queue if key(x["link"]) != key(q["link"])]
                break
        else:
            print("Найкращу новину не вдалося опублікувати.")
        state["queue"] = queue
        return
    queue.sort(key=lambda q: (-q["score"], -(q["ts"] or 0)))
    budget = min(MAX_PER_RUN, MAX_PER_DAY - state["day_count"])
    sent, rest = 0, []
    for q in queue:
        if sent >= budget:
            rest.append(q)
            continue
        res = publish(tg, state, q, now)
        if res == "posted":
            sent += 1
            state["day_count"] += 1
        elif res == "retry":
            q["tries"] = q.get("tries", 0) + 1
            if q["tries"] < 3:
                rest.append(q)
    state["queue"] = rest
    if queue:
        print(f"Опубліковано {sent}, у черзі {len(rest)}.")


# ---------- перевірка і приклади ----------

def check_rights(token, chat):
    """Чи може бот публікувати в каналі (лише читання, нічого не шле)."""
    base = f"https://api.telegram.org/bot{token}"
    try:
        me = bot.http_get_json(f"{base}/getMe")["result"]
        q = urllib.parse.urlencode({"chat_id": chat, "user_id": me["id"]})
        m = bot.http_get_json(f"{base}/getChatMember?{q}")["result"]
        print(f"Бот @{me.get('username')} в {chat}: статус {m.get('status')},"
              f" може публікувати: {m.get('can_post_messages')}")
    except urllib.error.HTTPError as e:
        print("Перевірка прав: Telegram відповів", e.code,
              e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("Перевірка прав не вдалася:", type(e).__name__)


def dump_card(path):
    """Для тесту: зменшена картка в лог (base64), щоб її подивитися."""
    import base64
    try:
        from PIL import Image
        im = Image.open(path)
        im = im.resize((720, im.height * 720 // im.width), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        print("CARD_B64:" + base64.b64encode(buf.getvalue()).decode())
    except Exception as e:
        print("Не вдалося вивести картинку:", e)


def demo(token, chat):
    """Приклади постів у лог — показати до запуску. Нічого не надсилає."""
    check_rights(token, chat)
    now = time.time()
    fresh = [i for i in fetch_all()
             if not i["ts"] or now - i["ts"] < 48 * 3600]
    uniq = {}
    for i in fresh:
        uniq.setdefault(key(i["link"]), i)
    fresh = sorted(uniq.values(), key=lambda i: -(i["ts"] or now))[:60]
    print(f"\nСвіжих статей за 2 доби: {len(fresh)}")
    scores = score_items(fresh, [])
    if not scores:
        print("Claude не відповів.")
        return
    ranked = sorted(((scores[i], it) for i, it in enumerate(fresh)
                     if i in scores), key=lambda x: -x[0]["score"])
    print("\nОцінки (вгорі — найкрутіше):")
    for r, it in ranked:
        print(f"  {r['score']:>2} {r['kind']:<8}"
              f"{' дубль' if r['duplicate'] else ''} | "
              f"{it['src']}: {it['title'][:90]}")
    good = [x for x in ranked if x[0]["kind"] != "skip"
            and not x[0]["duplicate"]]
    chosen = ([x for x in good if x[0]["kind"] == "news"][:2]
              + [x for x in good if x[0]["kind"] == "designer"][:2])
    for r, it in chosen:
        article_text(it)
        post = write_post(it, r["kind"], [])
        post = post and verify_post(it, post)
        if not post:
            continue
        text = caption(r["kind"], post, it)
        card = make_card(r["kind"], post, it)
        print(f"\n===== ПРИКЛАД ({r['kind']}, оцінка {r['score']}, "
              f"довжина {visible_len(text)}, фото: "
              f"{it.get('image') or 'немає'}) =====\n{text}")
        if card:
            dump_card(card)


def main():
    global CHANNEL_TAG
    now = time.time()
    token = os.environ.get("BOT_TOKEN", "").strip()
    channel = os.environ.get("CHANNEL", "").strip() or CHANNEL_TAG
    if channel.startswith("@"):
        CHANNEL_TAG = channel
    if os.environ.get("DESIGN_DEMO") == "1":
        demo(token, channel)
        return
    dry = os.environ.get("DESIGN_DRY") == "1"
    best_now = os.environ.get("DESIGN_BEST_NOW") == "1"
    if not (LIVE or dry or best_now):
        print("Канал ще не запущено (LIVE = False) — чекаємо схвалення.")
        return
    state = load_state()
    tg = bot.Telegram(token, channel, dry_run=dry)
    try:
        news_tick(tg, state, now, bot.kyiv_time(), best_now=best_now)
    except Exception as e:
        print("Новини не вийшли:", type(e).__name__, e)
    if not dry:
        save_state(state)


if __name__ == "__main__":
    main()
