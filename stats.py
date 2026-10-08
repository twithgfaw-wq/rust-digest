# -*- coding: utf-8 -*-
"""
Статистика каналов: просмотры и реакции каждого поста из публичного превью
t.me/s/<канал> (Bot API просмотров не отдаёт). Сохраняет stats.json и
печатает сводку по рубрикам: средние просмотры, реакции, лучшие посты,
лучшее время. Запуск: python stats.py [канал ...]
"""
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"
CHANNELS = ["rust_news_Pro", "cs2_me"]
STATS_FILE = "stats.json"
GENERIC = {"rust", "раст", "cs2", "кс2", "cs", "csgo", "counterstrike",
           "скины", "скин"}
# рубрика по хэштегу (первый совпавший) или по первой строке
RUBRICS = [
    ("скин_дня", "🎨 Скин дня"), ("угадай_цену", "🗳 Угадай цену"),
    ("итоги", "📒 Что вышло"), ("инвест", "💼 Инвест"),
    ("маркет", "📊 Маркет"), ("цены", "📊 Маркет"),
    ("магазин", "🛒 Магазин"), ("кейс", "📦 Кейс"),
    ("воркшоп", "🎨 Мастерская"), ("мастерская", "🎨 Мастерская"),
    ("workshop", "🎨 Мастерская"), ("конкурс", "🏆 Конкурс"),
    ("топ", "🏆 Топ мастерской"), ("видео", "🎬 Видео"),
    ("youtube", "🎬 Видео"), ("онлайн", "👥 Онлайн"), ("x", "🐦 X"),
    ("twitter", "🐦 X"), ("сообщество", "💬 Сообщество"),
    ("патч", "📰 Новости"), ("обновление", "📰 Новости"),
    ("новости", "📰 Новости"),
]


def kyiv(dt):
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Europe/Kyiv"))
    except Exception:
        return dt + timedelta(hours=3)


def fetch(channel, before=None):
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def num(s):
    s = s.strip().upper().replace(",", ".")
    mult = 1000 if s.endswith("K") else 1000000 if s.endswith("M") else 1
    try:
        return int(float(s.rstrip("KM")) * mult)
    except ValueError:
        return 0


def text_of(block):
    m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                  block, re.S)
    if not m:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", m.group(1))
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def rubric(text, poll):
    if poll:
        return "🗳 Опрос"
    tags = [t.lower() for t in re.findall(r"#([\w]+)", text)]
    for key, name in RUBRICS:
        if key in tags:
            return name
    first = text.split("\n", 1)[0].lower()
    for key, name in RUBRICS:
        if key in first:
            return name
    rest = [t for t in tags if t not in GENERIC]
    return ("#" + rest[0]) if rest else "без рубрики"


def parse(page, channel):
    out = []
    for block in page.split('<div class="tgme_widget_message_wrap')[1:]:
        m = re.search(r'data-post="' + re.escape(channel) + r'/(\d+)"', block,
                      re.I)
        d = re.search(r'<time datetime="([^"]+)"', block)
        if not m or not d:
            continue
        v = re.search(r'tgme_widget_message_views">([^<]+)<', block)
        reacts = {}
        for e, n in re.findall(r'<span class="tgme_reaction[^"]*">.*?<b>([^<]+)'
                               r'</b></i>([^<]+)</span>', block, re.S):
            reacts[e] = reacts.get(e, 0) + num(n)
        poll = re.search(r'tgme_widget_message_poll_question">([^<]+)<', block)
        text = text_of(block) or (html.unescape(poll.group(1)) if poll else "")
        voters = re.search(r'tgme_widget_message_poll_votes">([^<]+)<', block)
        out.append({
            "id": int(m.group(1)), "date": d.group(1),
            "views": num(v.group(1)) if v else 0,
            "reactions": reacts, "react_total": sum(reacts.values()),
            "media": ("photo" if "tgme_widget_message_photo" in block else
                      "video" if "tgme_widget_message_video" in block else
                      "poll" if poll else "text"),
            "voters": num(voters.group(1).split()[0]) if voters else None,
            "rubric": rubric(text, bool(poll)),
            "head": text.split("\n", 1)[0][:90],
        })
    return out


def collect(channel, limit=400):
    posts, before = {}, None
    while len(posts) < limit:
        try:
            page = fetch(channel, before)
        except Exception as e:
            print(f"{channel}: t.me не ответил:", e)
            break
        got = parse(page, channel)
        new = [p for p in got if p["id"] not in posts]
        if not new:
            break
        for p in new:
            posts[p["id"]] = p
        before = min(p["id"] for p in got)
        if before <= 1:
            break
        time.sleep(1)
    return sorted(posts.values(), key=lambda p: p["id"])


def report(channel, posts, days=14):
    now = datetime.now(timezone.utc)
    recent = [p for p in posts
              if now - datetime.fromisoformat(p["date"]) <= timedelta(days=days)
              and now - datetime.fromisoformat(p["date"]) >= timedelta(hours=12)]
    print(f"\n===== @{channel}: {len(posts)} постов, за {days} дней "
          f"(старше 12 ч): {len(recent)} =====")
    if not recent:
        return
    groups = {}
    for p in recent:
        groups.setdefault(p["rubric"], []).append(p)
    print(f"{'рубрика':<20}{'постов':>7}{'просм.':>8}{'реакц.':>8}{'ER%':>7}")
    rows = []
    for name, ps in groups.items():
        v = statistics.mean(p["views"] for p in ps)
        r = statistics.mean(p["react_total"] for p in ps)
        rows.append((v, name, len(ps), r))
    for v, name, n, r in sorted(rows, reverse=True):
        print(f"{name:<20}{n:>7}{v:>8.1f}{r:>8.2f}{(100 * r / v if v else 0):>7.1f}")
    hours = {}
    for p in recent:
        h = kyiv(datetime.fromisoformat(p["date"])).hour
        hours.setdefault(h // 3 * 3, []).append(p["views"])
    print("Просмотры по времени (Киев):",
          ", ".join(f"{h:02d}–{h + 3:02d}: {statistics.mean(v):.1f} ({len(v)})"
                    for h, v in sorted(hours.items())))
    top = sorted(recent, key=lambda p: (-p["react_total"], -p["views"]))[:5]
    print("Лучшие по реакциям:")
    for p in top:
        print(f"  #{p['id']} {p['views']} просм., {p['react_total']} реакц."
              f" [{p['rubric']}] {p['head']}")
    print("Посты в день:",
          f"{len(recent) / days:.1f}", "· подписчики видят в среднем",
          f"{statistics.mean(p['views'] for p in recent):.1f}")


def main():
    channels = sys.argv[1:] or CHANNELS
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    for ch in channels:
        posts = collect(ch)
        if posts:
            old = {p["id"]: p for p in data.get(ch, {}).get("posts", [])}
            old.update({p["id"]: p for p in posts})
            data[ch] = {"updated": datetime.now(timezone.utc).isoformat(),
                        "posts": sorted(old.values(), key=lambda p: p["id"])}
        report(ch, data.get(ch, {}).get("posts", []))
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
