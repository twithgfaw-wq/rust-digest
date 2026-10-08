# -*- coding: utf-8 -*-
"""
🧠 Викторины — опрос-квиз Telegram: вопрос, 4 варианта, правильный ответ
и пояснение (видно после ответа). Вопросы собираются из данных, а не
придумываются: CS2 — кейсы ByMykel/CSGO-API и цены Skinport; Rust —
магазин и маркет rust.scmm.app. Три раза в неделю в каждом канале.
"""
import json
import random
import time

LIVE = False                    # по расписанию — после одобрения примеров
HOUR = 18                       # по Киеву
CS2_DAYS = (1, 4, 6)            # вт, пт, вс
RUST_DAYS = (0, 2, 5)           # пн, ср, сб


def money(v):
    return f"${v:,.2f}".replace(",", " ")


def send(tg, q):
    return tg._post("sendPoll", {
        "chat_id": tg.chat, "question": q["question"][:300],
        "options": json.dumps([{"text": o[:100]} for o in q["options"]],
                              ensure_ascii=False),
        "type": "quiz", "correct_option_id": str(q["correct"]),
        "explanation": q["explain"][:200], "is_anonymous": "true"})


def shuffle(right, wrong, rnd):
    opts = [right] + wrong[:3]
    rnd.shuffle(opts)
    return opts, opts.index(right)


def nice(p):
    """Красивая «круглая» цена для вариантов ответа."""
    if p < 1:
        return round(p, 2)
    if p < 10:
        return round(p * 2) / 2
    if p < 100:
        return float(round(p))
    return float(round(p, -1))


# ---------- CS2 ----------

def cs2_case(sp, rnd):
    import cs2_formats as fmt
    vol = {i["market_hash_name"]: (i.get("last_30_days") or {}).get("volume")
           or 0 for i in sp}
    crates = [c for c in fmt.api("crates") if c.get("type") == "Case"
              and c.get("contains")]
    crates.sort(key=lambda c: -vol.get(c.get("market_hash_name") or c["name"], 0))
    pool = crates[:25]
    case = rnd.choice(pool)
    reds = [i for i in case["contains"]
            if (i.get("rarity") or {}).get("id") in ("rarity_ancient_weapon",
                                                    "rarity_legendary_weapon")]
    if not reds:
        return None
    skin = rnd.choice(reds)
    others = [c["name"] for c in pool if c is not case and not any(
        i["name"] == skin["name"] for i in c["contains"])]
    rnd.shuffle(others)
    opts, right = shuffle(case["name"], others, rnd)
    color = ("красный (Covert), шанс 0,64%"
             if skin["rarity"]["id"] == "rarity_ancient_weapon"
             else "розовый (Classified), шанс 3,2%")
    return {"question": f"🧠 Из какого кейса выпадает {skin['name']}?",
            "options": opts, "correct": right,
            "explain": f"{skin['name']} — в «{case['name']}»: {color} "
                       "за одно открытие."}


def cs2_items(sp, n=4, lo=2.0, hi=400.0, vol=60):
    out = []
    for i in sp:
        w = i.get("last_7_days") or {}
        name = i["market_hash_name"]
        if (w.get("median") and lo <= w["median"] <= hi
                and (w.get("volume") or 0) >= vol and " | " in name
                and "Sticker" not in name and "★" not in name):
            out.append((name, w["median"]))
    return out


def cs2_pricier(sp, rnd):
    pool = cs2_items(sp)
    rnd.shuffle(pool)
    pick = []
    for name, p in pool:
        if all(max(p, q) / min(p, q) >= 1.4 for _, q in pick):
            pick.append((name, p))
        if len(pick) == 4:
            break
    if len(pick) < 4:
        return None
    best = max(pick, key=lambda x: x[1])
    opts = [n for n, _ in pick]
    return {"question": "🧠 Какой из этих скинов сейчас дороже всех?",
            "options": opts, "correct": opts.index(best[0]),
            "explain": " · ".join(f"{n.split(' | ')[-1]} {money(p)}"
                                  for n, p in sorted(pick, key=lambda x: -x[1]))}


def cs2_guess(sp, rnd):
    pool = cs2_items(sp, lo=5, hi=300, vol=100)
    if not pool:
        return None
    name, p = rnd.choice(pool)
    right = money(nice(p))
    wrong = [money(nice(p * k)) for k in (0.35, 2.5, 6)]
    opts, idx = shuffle(right, wrong, rnd)
    return {"question": f"🧠 Сколько примерно стоит {name} сейчас?",
            "options": opts, "correct": idx,
            "explain": f"Медиана продаж за неделю на Skinport — {money(p)}."}


# ---------- Rust ----------

def rust_store_price(items, rnd):
    pool = [s for s in items if s["store"]]
    s = rnd.choice(pool)
    prices = sorted({x["store"] for x in pool if x["store"] != s["store"]})
    rnd.shuffle(prices)
    m = lambda c: money(c / 100)
    opts, idx = shuffle(m(s["store"]), [m(c) for c in prices], rnd)
    tail = (f" Сейчас на маркете — {m(s['price'])}." if s["price"] else "")
    return {"question": f"🧠 Сколько стоил {s['name']} в магазине Rust?",
            "options": opts, "correct": idx,
            "explain": f"В магазине — {m(s['store'])} (неделя {s['week']})."
                       + tail}


def rust_pricier(items, rnd):
    pool = [s for s in items if s["price"] and not s["current"]]
    rnd.shuffle(pool)
    pick = []
    for s in pool:
        if all(max(s["price"], q["price"]) / min(s["price"], q["price"]) >= 1.4
               for q in pick):
            pick.append(s)
        if len(pick) == 4:
            break
    if len(pick) < 4:
        return None
    best = max(pick, key=lambda s: s["price"])
    opts = [s["name"] for s in pick]
    return {"question": "🧠 Какой из этих скинов Rust сейчас дороже всех на "
                        "маркете?",
            "options": opts, "correct": opts.index(best["name"]),
            "explain": " · ".join(f"{s['name']} {money(s['price'] / 100)}"
                                  for s in sorted(pick, key=lambda s: -s["price"]))}


def rust_roi(items, rnd):
    pool = [s for s in items if s["price"] and not s["current"]]
    rnd.shuffle(pool)
    pick = []
    for s in pool:
        r = s["price"] / s["store"]
        if all(abs(r - q["price"] / q["store"]) >= 0.25 for q in pick):
            pick.append(s)
        if len(pick) == 4:
            break
    if len(pick) < 4:
        return None
    roi = lambda s: (s["price"] / s["store"] - 1) * 100
    best = max(pick, key=roi)
    opts = [s["name"] for s in pick]
    return {"question": "🧠 Какой скин сильнее всего подорожал после магазина?",
            "options": opts, "correct": opts.index(best["name"]),
            "explain": " · ".join(f"{s['name']} {roi(s):+.0f}%".replace("-", "−")
                                  for s in sorted(pick, key=lambda s: -roi(s)))}


def rust_sold(items, rnd):
    pool = [s for s in items if s["sold"] >= 1000]
    if not pool:
        return None
    s = rnd.choice(pool)
    f = lambda n: "~" + f"{int(round(n, -2)):,}".replace(",", " ")
    opts, idx = shuffle(f(s["sold"]), [f(s["sold"] * k) for k in (0.25, 3, 8)],
                        rnd)
    return {"question": f"🧠 Сколько примерно штук {s['name']} продали в "
                        "магазине Rust?",
            "options": opts, "correct": idx,
            "explain": f"По оценке rust.scmm.app — {f(s['sold'])} шт. "
                       f"(цена в магазине {money(s['store'] / 100)})."}


CS2_KINDS = [cs2_case, cs2_pricier, cs2_guess]
RUST_KINDS = [rust_store_price, rust_pricier, rust_roi, rust_sold]


def make(kind, data, state, seed):
    """Вопрос по очереди типов; если не собрался — следующий тип."""
    kinds = CS2_KINDS if kind == "cs2" else RUST_KINDS
    n = state.get(f"{kind}_quiz_n", 0)
    rnd = random.Random(seed)
    for k in range(len(kinds)):
        try:
            q = kinds[(n + k) % len(kinds)](data, rnd)
        except Exception as e:
            print("Викторина не собралась:", e)
            q = None
        if q and len(set(q["options"])) == 4:
            state[f"{kind}_quiz_n"] = n + k + 1
            return q
    return None


def tick(tg, state, kind, get_data, forced=False):
    import rust_digest_bot as bot
    kt = bot.kyiv_time()
    days = CS2_DAYS if kind == "cs2" else RUST_DAYS
    today, key = kt.strftime("%Y-%m-%d"), f"{kind}_quiz_day"
    if not forced and not (LIVE and kt.weekday() in days and kt.hour >= HOUR
                           and state.get(key) != today):
        return
    q = make(kind, get_data(), state, f"{kind}-{today}-{time.time() // 3600}")
    if q and send(tg, q).get("ok"):
        state[key] = today


def demo(kind, data, n=3):
    state = {}
    for i in range(n):
        q = make(kind, data, state, f"demo-{kind}-{i}")
        if q:
            marks = ["✅" if j == q["correct"] else "▫️"
                     for j in range(len(q["options"]))]
            print(f"\n===== ПРИМЕР (викторина {kind}) =====\n{q['question']}\n"
                  + "\n".join(f"{m} {o}" for m, o in zip(marks, q["options"]))
                  + f"\n💡 {q['explain']}")
