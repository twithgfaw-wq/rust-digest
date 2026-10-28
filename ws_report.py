# -*- coding: utf-8 -*-
"""
Разовый отчёт по мастерской CS (для сюжета о мастерской, 28.10.2026):
все соавторы принятых Valve работ (блок «Created by») и последняя активность
соавторов, которые сами принятые работы не загружали.
Запуск: python ws_report.py SHARD SHARDS — каждая часть берёт свою долю работ.
Ничего не публикует: печатает в лог строку REPORT_JSON:{...}.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/126 Safari/537.36")
BASE = 76561197960265728
SKIN_TAGS = {"Weapon Finish", "Sticker", "Charm", "Gloves", "Knife", "Agent",
             "Patch", "Graffiti", "Music Kit", "Weapon", "Keychain"}


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
    items = {}
    for extra in ("", "&requiredflags[]=incompatible"):
        p = 1
        while True:
            d = browse("https://steamcommunity.com/workshop/browse/?appid=730"
                       f"&browsesort=accepted&section=mtxitems&p={p}{extra}")
            res = d.get("results") or []
            for r in res:
                items[r["publishedfileid"]] = r["creator"]
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
            people.append({"sid": str(BASE + int(m.group(1))),
                           "name": nm.group(1).strip() if nm else ""})
    return people


def activity(sid):
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
    return {"page_ok": bool(ids),
            "last_any": max((d.get("time_created", 0) for d in det), default=0),
            "last_skin": max((d.get("time_created", 0) for d in skins), default=0)}


def main():
    shard, shards = int(sys.argv[1]), int(sys.argv[2])
    acc = accepted()
    mine = [i for i in sorted(acc) if int(i) % shards == shard]
    print(f"принятых: {len(acc)}, моя часть: {len(mine)}", flush=True)
    collab, missing = {}, []
    for n, iid in enumerate(mine, 1):
        c = contributors(iid)
        if c is None:
            missing.append(iid)
        else:
            collab[iid] = c
        if n % 25 == 0:
            print(f"{n}/{len(mine)}", flush=True)
        time.sleep(0.8)
    uploaders = set(acc.values())
    check = {p["sid"] for c in collab.values() for p in c} - uploaders
    if shard == 0:
        check |= {s for s in os.environ.get("RECHECK", "").split(",") if s}
    act = {}
    for sid in sorted(check):
        a = activity(sid)
        if a is not None:
            act[sid] = a
        time.sleep(0.8)
    print("REPORT_JSON:" + json.dumps({"shard": shard, "accepted_total": len(acc),
                                       "collab": collab, "missing": missing,
                                       "activity": act}, ensure_ascii=False))


if __name__ == "__main__":
    main()
