# -*- coding: utf-8 -*-
"""
Отчёт для ручного выбора: популярные за неделю и свежие скины мастерской
CS2, отсортированные по числу принятых Valve работ автора. Ничего не
публикует — только лог. Нужен STEAM_API_KEY.
"""
import os
import time

import cs2_workshop as ws


def main():
    key = os.environ.get("STEAM_API_KEY", "").strip()
    authors = ws.accepted_authors(key, pages=10)
    print("Авторов с принятыми работами:", len(authors))
    now = time.time()
    found = {}
    for qtype, days in ((3, 7), (1, None)):
        try:
            items = ws.query(key, qtype, 100, days=days).get(
                "publishedfiledetails") or []
        except Exception as e:
            print("Не загрузилось:", qtype, e)
            continue
        for it in items:
            w = ws.work(it)
            if ws.is_skin(w) and now - w["created"] < 21 * 86400:
                found.setdefault(w["id"], w)
    rows = sorted(found.values(),
                  key=lambda w: (authors.get(w["creator"], {}).get("n", 0),
                                 w["up"] - w["down"]), reverse=True)[:20]
    nick = ws.names(key, [w["creator"] for w in rows])
    for w in rows:
        a = authors.get(w["creator"], {})
        print(f"\n[{a.get('n', 0)} принято] {w['title']} · "
              f"{nick.get(w['creator'], w['creator'])} · 👍{w['up']} 👎{w['down']}"
              f" · ⭐{w['favs']} · {w['url']}")
        print("   теги:", ", ".join(w["tags"]))
        print("   принятые:", "; ".join(a.get("titles", [])[:4]))
        print("   картинки:", " ".join(w["images"][:3]))


if __name__ == "__main__":
    main()
