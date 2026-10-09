# -*- coding: utf-8 -*-
"""
Рубрика «🎨 Мастерская CS2» — сильные новые работы из Steam Workshop.

1. База авторов: все, чьи работы Valve уже принимала в игру (Steam API,
   QueryFiles query_type=2), и сколько принятых работ у каждого.
2. Кандидаты: свежие работы этих авторов (query_type=1) и работы, которые
   набирают голоса за неделю (query_type=3) — так находим перспективных.
3. Claude Opus 5.5 смотрит картинки и данные (голоса, подписки, принятые
   работы автора) и ставит оценку 1–10. Публикуем только от PASS_SCORE,
   не больше трёх в день. Оценку запоминаем, чтобы не платить дважды.
Нужен STEAM_API_KEY.
"""
import html
import os
import time
import urllib.parse

import cs2_ai as ai
import rust_digest_bot as bot

QF = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
FILE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"
RUBRIC = "🎨 МАСТЕРСКАЯ CS2"
SKIN_TAGS = {"Weapon Finish", "Sticker", "Charm", "Gloves", "Knife",
             "Agent", "Patch", "Graffiti", "Music Kit"}
PASS_SCORE = 7          # минимальная оценка для публикации
FRESH_DAYS = 10         # «свежая» работа проверенного автора (с 4 — сильные
                        # работы с оценкой 7+ выпадали, не дождавшись слота)
JUDGE_PER_RUN = 4       # сколько новых работ оцениваем за один запуск


# ---------- Steam API ----------

def query(key, qtype, per=100, cursor="*", days=None):
    params = {"key": key, "appid": 730, "query_type": qtype,
              "numperpage": per, "cursor": cursor,
              "return_previews": "true", "return_tags": "true",
              "return_vote_data": "true", "return_short_description": "true"}
    if days:
        params["days"] = days
    url = QF + "?" + urllib.parse.urlencode(params)
    return bot.http_get_json(url, timeout=30).get("response", {})


def work(it):
    """Работа из ответа QueryFiles → удобный словарь."""
    pid = str(it.get("publishedfileid") or "")
    previews = [p.get("url") for p in it.get("previews") or []
                if p.get("preview_type") == 0 and p.get("url")]
    imgs = [u for u in [it.get("preview_url")] + previews if u]
    vote = it.get("vote_data") or {}
    return {"id": pid, "title": it.get("title") or "",
            "creator": str(it.get("creator") or ""),
            "created": int(it.get("time_created") or 0),
            "images": list(dict.fromkeys(imgs))[:4],
            "tags": [t.get("tag") for t in it.get("tags") or []
                     if t.get("tag")],
            "up": int(vote.get("votes_up") or 0),
            "down": int(vote.get("votes_down") or 0),
            "subs": int(it.get("subscriptions") or 0),
            "favs": int(it.get("favorited") or 0),
            "views": int(it.get("views") or 0),
            "desc": (it.get("short_description") or "")[:600],
            "url": FILE_URL.format(pid)}


def is_skin(w):
    return bool(SKIN_TAGS & set(w["tags"])) and w["images"] and w["title"]


def accepted_authors(key, pages=6):
    """Автор (SteamID) → {"n": принятых работ, "titles": [названия]}."""
    out, cursor = {}, "*"
    for _ in range(pages):
        try:
            resp = query(key, 2, 100, cursor)
        except Exception as e:
            print("Список принятых не загрузился:", e)
            break
        items = resp.get("publishedfiledetails") or []
        for it in items:
            w = work(it)
            if w["creator"]:
                a = out.setdefault(w["creator"], {"n": 0, "titles": []})
                a["n"] += 1
                if len(a["titles"]) < 6:
                    a["titles"].append(w["title"])
        cursor = resp.get("next_cursor") or ""
        if not cursor or not items:
            break
    return out


def candidates(key, authors, seen, now):
    """Свежие работы проверенных авторов + набирающие голоса за неделю."""
    out = {}
    try:
        fresh = [work(i) for i in query(key, 1, 100).get(
            "publishedfiledetails") or []]
    except Exception as e:
        print("Новые работы не загрузились:", e)
        fresh = []
    for w in fresh:
        if (is_skin(w) and w["creator"] in authors and w["id"] not in seen
                and now - w["created"] < FRESH_DAYS * 86400):
            w["why"] = "проверенный автор"
            out[w["id"]] = w
    try:
        trend = [work(i) for i in query(key, 3, 50, days=7).get(
            "publishedfiledetails") or []]
    except Exception as e:
        print("Тренды недели не загрузились:", e)
        trend = []
    trend = [w for w in trend if is_skin(w) and w["id"] not in seen
             and now - w["created"] < 10 * 86400]
    trend.sort(key=lambda w: w["up"] - w["down"], reverse=True)
    for w in trend[:6]:
        w.setdefault("why", "проверенный автор" if w["creator"] in authors
                     else "набирает голоса")
        out.setdefault(w["id"], w)
    return list(out.values())


def names(key, ids):
    """SteamID → ник автора."""
    if not ids:
        return {}
    return bot.resolve_steam_names(key, ids)


# ---------- оценка (Claude) ----------

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "title_ru": {"type": "string"},
        "text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["score", "title_ru", "text", "reason"],
    "additionalProperties": False,
}


def judge(w, author, author_info):
    """Оценка работы Claude по картинкам и данным. dict или None."""
    acc = author_info or {}
    prompt = f"""Ты оцениваешь работу из Steam Workshop CS2 для рубрики «Мастерская CS2».
Публикуем только действительно сильные работы — качество важнее количества.

Работа: «{w['title']}» · теги: {', '.join(w['tags'])}
Автор: {author or 'неизвестен'} · принятых Valve работ: {acc.get('n', 0)}
{('Принятые работы автора: ' + '; '.join(acc.get('titles', []))) if acc.get('titles') else 'Принятых работ нет — новый или перспективный автор.'}
Реакция сообщества: 👍 {w['up']} / 👎 {w['down']}, подписок {w['subs']},
в избранном {w['favs']}, просмотров {w['views']}.
Описание автора: {w['desc'] or '—'}

Оцени по картинкам: качество текстур и материалов, оригинальность идеи,
как это будет выглядеть в игре, соответствие стилю CS2, уровень по сравнению
с принятыми работами автора, реакцию сообщества. Не утверждай, что Valve
примет работу — можно только «шансы выглядят неплохо / есть вопросы».

Верни:
- score: 1–10 (7+ = достойно поста; 9–10 — редкий уровень).
- title_ru: короткое название по-русски для поста (оружие + суть, до 50 знаков).
- text: пост до 450 знаков, Telegram HTML, живым языком: что за работа,
  чем цепляет, что можно улучшить, 1 строка про автора (если есть принятые
  работы — назови число). Без воды и без шаблонных восторгов.
- reason: одна строка — почему такая оценка (для журнала)."""
    return ai.ask(prompt, JUDGE_SCHEMA, effort="medium", images=w["images"][:3])


def compose(w, author, author_info, res):
    """Подпись к альбому работы."""
    n = (author_info or {}).get("n", 0)
    badge = (f"✅ {n} {bot.plural(n, 'принятая работа', 'принятые работы', 'принятых работ')}"
             if n else "🌱 перспективный автор")
    lines = [f"<b>{RUBRIC}</b>", f"<b>{html.escape(res['title_ru'])}</b>",
             f"👤 {html.escape(author or 'автор')} · {badge}", "",
             res["text"].strip(), "",
             (f"👍 {bot.fmt_num(w['up'])} · " if w["up"] else "")
             + f"⭐ {bot.fmt_num(w['favs'])} в избранном · "
             f"👁 {bot.fmt_num(w['views'])} "
             f"{bot.plural(w['views'], 'просмотр', 'просмотра', 'просмотров')}",
             f"🔗 <a href=\"{w['url']}\">Работа в мастерской</a>", "",
             "#cs2 #мастерская_cs2"]
    return "\n".join(lines)


def pick(key, state, now, judge_limit=JUDGE_PER_RUN):
    """Лучшая неопубликованная работа с оценкой от PASS_SCORE:
    (работа, автор, данные автора, оценка) или None. Оценки — в state."""
    authors = accepted_authors(key)
    print(f"Мастерская: {len(authors)} авторов с принятыми работами")
    posted = set(state.get("ws_posted", []))
    scores = state.setdefault("ws_scores", {})
    cands = candidates(key, authors, posted, now)
    nick = names(key, [w["creator"] for w in cands])
    # сначала проверенные авторы и работы с лучшей реакцией
    cands.sort(key=lambda w: (w["creator"] in authors,
                              authors.get(w["creator"], {}).get("n", 0),
                              w["up"] - w["down"]), reverse=True)
    best = None
    judged = 0
    for w in cands:
        res = scores.get(w["id"])
        if res is None:
            if judged >= judge_limit:
                continue
            res = judge(w, nick.get(w["creator"]), authors.get(w["creator"]))
            judged += 1
            if not res:
                continue
            scores[w["id"]] = res
            print(f"Оценка {res['score']}/10 · {w['title']} · {res['reason']}")
        if res["score"] >= PASS_SCORE and (best is None
                                           or res["score"] > best[3]["score"]):
            best = (w, nick.get(w["creator"]), authors.get(w["creator"]), res)
    for k in list(scores)[:-300]:
        del scores[k]
    return best
