# -*- coding: utf-8 -*-
"""
Разовый отчёт по мастерской CS (для сюжета о мастерской, 28.10.2026).
  python ws_report.py shard N M — часть N из M: соавторы принятых работ
      (блок «Created by») и последняя активность авторов → report_N.json;
  python ws_report.py merge DIR — сводка по всем частям в лог.
Ничего не публикует.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/126 Safari/537.36")
BASE = 76561197960265728
SKIN_TAGS = {"Weapon Finish", "Sticker", "Charm", "Gloves", "Knife", "Agent",
             "Patch", "Graffiti", "Music Kit", "Weapon", "Keychain"}
CS2 = datetime(2023, 9, 27, tzinfo=timezone.utc).timestamp()   # релиз CS2


def fetch(url, data=None):
    for _ in range(6):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": UA, "Accept-Language": "en"})
            return urllib.request.urlopen(req, timeout=40).read().decode(
                "utf-8", "replace")
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, flush=True)
            time.sleep(60 if e.code == 429 else 8)
        except Exception as e:
            print("  ", type(e).__name__, flush=True)
            time.sleep(10)
    return None


def browse(url):
    s = fetch(url) or ""
    start = s.index('"queryData":"') + len('"queryData":"')
    i = start
    while True:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            break
        i += 1
    qd = json.loads(json.loads('"' + s[start:i] + '"'))
    for q in qd["queries"]:
        if (q.get("queryKey") or [""])[0] == "workshop_browse":
            return q["state"]["data"]
    return {}


def accepted():
    """id → [автор-загрузчик, время создания, старая (CS:GO) работа]."""
    items = {}
    for extra in ("", "&requiredflags[]=incompatible"):
        p = 1
        while True:
            d = browse("https://steamcommunity.com/workshop/browse/?appid=730"
                       f"&browsesort=accepted&section=mtxitems&p={p}{extra}")
            res = d.get("results") or []
            for r in res:
                items[r["publishedfileid"]] = [r["creator"],
                                               r.get("time_created", 0),
                                               bool(extra)]
            if not res or p >= d.get("total_pages", 1):
                break
            p += 1
            time.sleep(1.0)
    return items


def contributors(iid):
    html = fetch(f"https://steamcommunity.com/sharedfiles/filedetails/?id={iid}")
    if html is None:
        return None
    i = html.find('class="creatorsBlock"')
    people = []
    if i >= 0:
        j = html.find("rightSectionTopTitle", i)
        chunk = html[i:j if j > 0 else i + 30000]
        for m in re.finditer(r'data-miniprofile="(\d+)"', chunk):
            nm = re.search(r'friendBlockContent">\s*([^<\r\n]+)',
                           chunk[m.end():m.end() + 3000])
            people.append([str(BASE + int(m.group(1))),
                           nm.group(1).strip() if nm else ""])
    return people


def activity(sid):
    """Последняя загрузка автора в мастерскую CS: [страница открылась,
    любая работа, скин/стикер/брелок] (unix-время, 0 — нет)."""
    html = fetch(f"https://steamcommunity.com/profiles/{sid}/myworkshopfiles/"
                 "?appid=730&browsesort=mostrecent&numperpage=30")
    if html is None:
        return None
    ids = list(dict.fromkeys(re.findall(r"filedetails/\?id=(\d+)", html)))[:30]
    det = []
    if ids:
        body = {"itemcount": len(ids)}
        for j, x in enumerate(ids):
            body[f"publishedfileids[{j}]"] = x
        txt = fetch("https://api.steampowered.com/ISteamRemoteStorage/"
                    "GetPublishedFileDetails/v1/",
                    urllib.parse.urlencode(body).encode()) or "{}"
        try:
            det = json.loads(txt)["response"]["publishedfiledetails"]
        except Exception:
            det = []
    skins = [d for d in det if d.get("consumer_app_id") == 730
             and {t.get("tag") for t in d.get("tags") or []} & SKIN_TAGS]
    return [bool(ids), max((d.get("time_created", 0) for d in det), default=0),
            max((d.get("time_created", 0) for d in skins), default=0)]


def shard(n, m):
    acc = accepted()
    mine = [i for i in sorted(acc) if int(i) % m == n]
    print(f"принятых: {len(acc)}, моя часть: {len(mine)}", flush=True)
    collab, missing = {}, []
    for k, iid in enumerate(mine, 1):
        c = contributors(iid)
        if c is None:
            missing.append(iid)
        else:
            collab[iid] = c
        if k % 25 == 0:
            print(f"работы {k}/{len(mine)}", flush=True)
        time.sleep(0.8)
    uploaders = {v[0] for v in acc.values()}
    check = {s for s in uploaders if int(s) % m == n}
    check |= {p[0] for c in collab.values() for p in c} - uploaders
    act = {}
    for k, sid in enumerate(sorted(check), 1):
        a = activity(sid)
        if a is not None:
            act[sid] = a
        if k % 25 == 0:
            print(f"авторы {k}/{len(check)}", flush=True)
        time.sleep(0.8)
    json.dump({"accepted": acc, "collab": collab, "missing": missing,
               "activity": act}, open(f"report_{n}.json", "w",
                                      encoding="utf-8"), ensure_ascii=False)
    print("готово: работ", len(collab), "пропущено", len(missing),
          "авторов", len(act))


def merge(folder):
    parts = [json.load(open(f, encoding="utf-8"))
             for f in glob.glob(os.path.join(folder, "**", "report_*.json"),
                                recursive=True)]
    print("частей:", len(parts))
    acc = max((p["accepted"] for p in parts), key=len)
    collab, act, missing = {}, {}, []
    for p in parts:
        collab.update(p["collab"])
        act.update(p["activity"])
        missing += p["missing"]
    now = time.time()
    people, names, multi = defaultdict(list), {}, 0
    for iid, (creator, created, old) in acc.items():
        ppl = collab.get(iid) or [[creator, ""]]
        if len(ppl) > 1:
            multi += 1
        for sid, name in ppl:
            people[sid].append((iid, created, old))
            if name:
                names[sid] = name
    uploaders = {v[0] for v in acc.values()}
    print(f"принятых работ: {len(acc)} (старых из CS:GO: "
          f"{sum(v[2] for v in acc.values())}); страниц не загрузилось: "
          f"{len(missing)}; без блока авторов: "
          f"{sum(1 for i in acc if i in collab and not collab[i])}")
    print(f"работ в коллабе (2+ автора): {multi} ({multi / len(acc):.0%})")
    print(f"ЛЮДЕЙ С ПРИНЯТЫМИ РАБОТАМИ: {len(people)} (загружали сами: "
          f"{len(uploaders)}, только соавторы: {len(set(people) - uploaders)})")
    yc = Counter(datetime.fromtimestamp(c, timezone.utc).year
                 for _, c, _ in acc.values() if c)
    print("принятые по году создания:", dict(sorted(yc.items())))
    old = {s for s, ws in people.items() if any(c < CS2 for _, c, _ in ws)}
    new = {s for s, ws in people.items() if any(c >= CS2 for _, c, _ in ws)}
    print(f"с принятыми работами эпохи CS:GO: {len(old)}; эпохи CS2: "
          f"{len(new)}; и там и там: {len(old & new)}; новички CS2: "
          f"{len(new - old)}; ветераны без принятых в CS2: {len(old - new)} "
          f"({len(old - new) / max(1, len(old)):.0%})")
    cnt = sorted((len(w) for w in people.values()), reverse=True)
    k = max(1, len(cnt) // 10)
    print(f"топ-10% ({k} чел.): {sum(cnt[:k])} из {sum(cnt)} участий "
          f"({sum(cnt[:k]) / sum(cnt):.0%}); с одной принятой работой: "
          f"{sum(1 for c in cnt if c == 1)}")
    new_items = [i for i, v in acc.items() if v[1] >= CS2]
    vet = sum(1 for i in new_items if any(
        s in old for s, _ in (collab.get(i) or [[acc[i][0], ""]])))
    print(f"принятые работы эпохи CS2: {len(new_items)}, с участием ветеранов "
          f"CS:GO: {vet} ({vet / max(1, len(new_items)):.0%})")

    def bucket(t):
        d = (now - t) / 86400
        return ("≤3 мес" if d <= 92 else "3–12 мес" if d <= 365 else
                "1–2 года" if d <= 730 else "2–4 года" if d <= 1461 else
                ">4 лет")
    order = ["≤3 мес", "3–12 мес", "1–2 года", "2–4 года", ">4 лет"]
    b, closed, nodata = Counter(), 0, 0
    vet_b = Counter()
    for s, ws in people.items():
        a = act.get(s)
        last_acc = max(c for _, c, _ in ws)
        if a is None:
            nodata += 1
            continue
        if not a[0]:
            closed += 1
            continue
        last = max(a[2], last_acc)
        b[bucket(last)] += 1
        if s in old:
            vet_b["загружали после выхода CS2" if last >= CS2
                  else "ничего после выхода CS2"] += 1
    known = sum(b.values())
    print("последняя загрузка скина/стикера/брелока (или принятой работы):",
          {o: b[o] for o in order}, f"| закрытый профиль/пусто: {closed}",
          f"| нет ответа: {nodata}")
    print(f"активны за последний год: {b[order[0]] + b[order[1]]} из {known} "
          f"({(b[order[0]] + b[order[1]]) / max(1, known):.0%}); молчат больше "
          f"2 лет: {b[order[3]] + b[order[4]]} "
          f"({(b[order[3]] + b[order[4]]) / max(1, known):.0%})")
    print("ветераны CS:GO (открытый профиль):", dict(vet_b))
    print("\nТОП-25 по принятым работам (с соавторством):")
    for s, ws in sorted(people.items(), key=lambda kv: -len(kv[1]))[:25]:
        a = act.get(s) or [False, 0, 0]
        last_acc = max(c for _, c, _ in ws)
        last = max(a[2], last_acc)
        day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")
        print(f"  {names.get(s, s)} | принято {len(ws)} | последняя принятая "
              f"создана {day(last_acc)} | последняя загрузка "
              f"{day(last) if a[0] else 'профиль закрыт'} | "
              f"{'принят в CS2' if s in new else 'в CS2 не принят'}")


if __name__ == "__main__":
    if sys.argv[1] == "shard":
        shard(int(sys.argv[2]), int(sys.argv[3]))
    else:
        merge(sys.argv[2])
