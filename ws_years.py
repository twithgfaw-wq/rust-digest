# -*- coding: utf-8 -*-
"""
Разовый отчёт для сюжета о мастерской CS (28.10.2026): сколько работ по годам
загружали авторы, у которых есть хотя бы одна принятая Valve работа.
Только официальный Steam Web API (STEAM_API_KEY), один запуск, ничего не
публикует — печатает таблицы в лог.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

KEY = os.environ.get("STEAM_API_KEY", "").strip()
API = "https://api.steampowered.com/IPublishedFileService/"
SKIN_TAGS = {"Weapon Finish", "Sticker", "Charm", "Gloves", "Knife", "Agent",
             "Patch", "Graffiti", "Music Kit", "Keychain"}
CS2 = datetime(2023, 9, 27, tzinfo=timezone.utc).timestamp()   # релиз CS2


def call(method, params):
    url = API + method + "/v1/?" + urllib.parse.urlencode(dict(params, key=KEY))
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "replace")).get(
                    "response", {})
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, method, flush=True)
            time.sleep(20 * (k + 1))
        except Exception as e:
            print("  ", type(e).__name__, method, flush=True)
            time.sleep(10)
    return None


def year(t):
    return datetime.fromtimestamp(t, timezone.utc).year


def accepted():
    items, cursor = {}, "*"
    while True:
        r = call("QueryFiles", {"appid": 730, "query_type": 2,
                                "numperpage": 100, "cursor": cursor,
                                "return_tags": "true"})
        if r is None:
            break
        res = r.get("publishedfiledetails") or []
        for it in res:
            items[it["publishedfileid"]] = (it.get("creator"),
                                            it.get("time_created", 0))
        cursor = r.get("next_cursor") or ""
        if not res or not cursor:
            break
        time.sleep(0.3)
    return items


def user_files(sid):
    out, page = [], 1
    while True:
        r = call("GetUserFiles", {"steamid": sid, "appid": 730, "page": page,
                                  "numperpage": 100, "type": "myfiles",
                                  "return_tags": "true"})
        if r is None:
            return None
        res = r.get("publishedfiledetails") or []
        for it in res:
            tags = {t.get("tag") for t in it.get("tags") or []}
            out.append((it.get("time_created", 0), bool(tags & SKIN_TAGS)))
        if not res or len(out) >= int(r.get("total", 0) or 0):
            return out
        page += 1
        time.sleep(0.3)


def main():
    if not KEY:
        print("Нет STEAM_API_KEY")
        return
    acc = accepted()
    by_author = defaultdict(list)
    for creator, created in acc.values():
        if creator:
            by_author[creator].append(created)
    print(f"принятых работ (API): {len(acc)}; авторов: {len(by_author)}",
          flush=True)
    vet = {a for a, c in by_author.items() if any(t < CS2 for t in c)}
    files, missing = {}, []
    for n, sid in enumerate(sorted(by_author), 1):
        f = user_files(sid)
        if f is None:
            missing.append(sid)
        else:
            files[sid] = f
        if n % 50 == 0:
            print(f"авторы {n}/{len(by_author)}", flush=True)
        time.sleep(0.3)
    print(f"собрано авторов: {len(files)}, не ответило: {len(missing)}; "
          f"всего их работ в мастерской CS: {sum(len(f) for f in files.values())}"
          f" (скины/стикеры/брелоки: "
          f"{sum(1 for f in files.values() for t, s in f if s)})")

    print("\nГОД | работ (скины/стикеры/брелоки) у авторов с принятыми | "
          "из них ветераны CS:GO | активных авторов (≥1 работа) | из них "
          "ветераны | работ на активного автора")
    for y in range(2013, 2027):
        w = [(a, t) for a, f in files.items() for t, s in f if s and year(t) == y]
        act = {a for a, _ in w}
        wv = sum(1 for a, _ in w if a in vet)
        print(f"{y} | {len(w)} | {wv} | {len(act)} | {len(act & vet)} | "
              f"{len(w) / max(1, len(act)):.1f}")

    print("\nПоследняя загрузка скина/стикера/брелока (на 28.10.2026):")
    now = datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp()
    b = Counter()
    for a, f in files.items():
        last = max([t for t, s in f if s] + by_author[a])
        d = (now - last) / 86400
        b["≤3 мес" if d <= 92 else "3–12 мес" if d <= 365 else "1–2 года"
          if d <= 730 else "2–4 года" if d <= 1461 else ">4 лет"] += 1
    print({k: b[k] for k in ["≤3 мес", "3–12 мес", "1–2 года", "2–4 года",
                             ">4 лет"]})
    vb = Counter()
    for a in vet & set(files):
        last = max([t for t, s in files[a] if s] + by_author[a])
        vb["загружали после выхода CS2" if last >= CS2 else
           "ничего после выхода CS2"] += 1
    print("ветераны CS:GO:", dict(vb), "из", len(vet & set(files)))


if __name__ == "__main__":
    main()
