# -*- coding: utf-8 -*-
"""
Картинки Rust-канала в стиле внутриигрового магазина Rust: тёмный фон,
бордовые плитки предметов, золотая витрина (как «WEEKLY SKINS»), жирные
заглавные подписи, ценник с тележкой в углу плитки и верхнее меню, где
подсвечен раздел поста — как активная вкладка STORE в игре.
Шрифт (Roboto Condensed), загрузка картинок и перенос строк — из
cs2_cards: рисуем так же в 2× и уменьшаем.
"""
import cs2_cards as base
from cs2_cards import S, p, font, fetch_image, wrap

GOLD = (205, 165, 72)
INK = (32, 25, 12)                       # тёмный текст на золоте
GOLD_BG = ((70, 57, 28), (38, 31, 17))
GREY_BG = ((46, 45, 43), (30, 29, 28))
RED_TILE = ((114, 31, 25), (50, 15, 12))
GREY_TILE = ((64, 62, 60), (36, 35, 34))
WHITE, MUTED, DIM = (238, 234, 228), (170, 162, 150), (112, 106, 98)
RED, GREEN = (206, 60, 42), (98, 158, 50)
TABS = ["НОВОСТИ", "МАГАЗИН", "МАРКЕТ", "МАСТЕРСКАЯ", "ИНВЕСТИЦИИ"]
TAG = "@rust_news_Pro"


def gradient(w, h, top, bottom):
    """Вертикальный градиент w×h (в пикселях холста)."""
    from PIL import Image
    w, h = max(1, int(w)), max(1, int(h))
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), bottom),
                           Image.new("RGB", (w, h), top), mask)


def canvas(W, H):
    """Тёмный фон с мягким светом по центру."""
    from PIL import Image, ImageDraw
    big = Image.radial_gradient("L").resize((p(W) * 3 // 2, p(H) * 3 // 2),
                                            Image.BICUBIC)
    left, top = (big.width - p(W)) // 2, (big.height - p(H)) // 2
    mask = big.crop((left, top, left + p(W), top + p(H)))
    img = Image.composite(Image.new("RGB", mask.size, (12, 12, 12)),
                          Image.new("RGB", mask.size, (38, 37, 35)),
                          mask).convert("RGBA")
    return img, ImageDraw.Draw(img)


def nav(draw, W, active):
    """Верхнее меню как в игре: знак канала, разделы, активный — красный."""
    draw.rectangle((0, 0, p(W), p(84)), fill=(23, 23, 23))
    draw.line((0, p(84), p(W), p(84)), fill=(52, 50, 46), width=p(2))
    draw.rectangle((p(40), p(14), p(96), p(70)), fill=RED)
    draw.text((p(68), p(42)), "R", font=font(38, True), fill=WHITE,
              anchor="mm")
    f, x = font(23, True), 124
    for t in TABS:
        w = draw.textlength(t, font=f) / S + 40
        if t == active:
            draw.rectangle((p(x), 0, p(x + w), p(84)), fill=(116, 32, 25))
            draw.rectangle((p(x), p(79), p(x + w), p(84)), fill=RED)
        draw.text((p(x + w / 2), p(42)), t, font=f,
                  fill=WHITE if t == active else MUTED, anchor="mm")
        x += w
    draw.text((p(W - 40), p(42)), TAG, font=font(22, True), fill=MUTED,
              anchor="rm")


def panel(img, draw, box, title, badge=None, gold=True):
    """Витрина: градиент, рамка, крупный заголовок, плашка справа."""
    x0, y0, x1, y1 = box
    img.paste(gradient(p(x1 - x0), p(y1 - y0), *(GOLD_BG if gold else GREY_BG)),
              (p(x0), p(y0)))
    line = GOLD if gold else (78, 75, 70)
    draw.rectangle((p(x0), p(y0), p(x1), p(y1)), outline=line, width=p(3))
    draw.text((p(x0 + 28), p(y0 + 54)), title, font=font(50, True),
              fill=GOLD if gold else WHITE, anchor="lm")
    if badge:
        f = font(22, True)
        w = draw.textlength(badge, font=f) / S + 36
        draw.rectangle((p(x1 - 28 - w), p(y0 + 32), p(x1 - 28), p(y0 + 76)),
                       fill=line)
        draw.text((p(x1 - 28 - w / 2), p(y0 + 54)), badge, font=f,
                  fill=INK if gold else WHITE, anchor="mm")


def bar(draw, box, text, gold=True):
    """Полоса внизу витрины (как «VIEW ALL THIS WEEKS LIMITED SKINS»)."""
    x0, y0, x1, y1 = box
    draw.rectangle((p(x0), p(y0), p(x1), p(y1)),
                   fill=GOLD if gold else (78, 75, 70))
    draw.text((p((x0 + x1) / 2), p((y0 + y1) / 2)), text.upper(),
              font=font(24, True), fill=INK if gold else WHITE, anchor="mm")


def cart(draw, x, y, color):
    """Значок тележки ~22×18."""
    draw.line([(p(x), p(y)), (p(x + 4), p(y)), (p(x + 7), p(y + 12)),
               (p(x + 19), p(y + 12))], fill=color, width=p(2))
    draw.polygon([(p(x + 5), p(y + 3)), (p(x + 22), p(y + 3)),
                  (p(x + 19), p(y + 10)), (p(x + 7), p(y + 10))], fill=color)
    for cx in (x + 9, x + 17):
        draw.ellipse((p(cx - 2), p(y + 14), p(cx + 2), p(y + 18)), fill=color)


def tile(img, draw, box, t):
    """Плитка предмета. t: image, name, sub, price, tag, number, value,
    value_up, hot (бордовая; иначе серая)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    img.paste(gradient(p(w), p(h), *(RED_TILE if t.get("hot", True)
                                     else GREY_TILE)), (p(x0), p(y0)))
    draw.rectangle((p(x0), p(y0), p(x1), p(y1)), outline=(16, 12, 10),
                   width=p(2))
    base.place_item(img, fetch_image(t.get("image")), x0 + w / 2,
                    y0 + h * 0.42, w * 0.70, h * 0.44)
    if t.get("number"):
        draw.ellipse((p(x0 + 12), p(y0 + 12), p(x0 + 62), p(y0 + 62)),
                     fill=RED)
        draw.text((p(x0 + 37), p(y0 + 37)), str(t["number"]),
                  font=font(30, True), fill=WHITE, anchor="mm")
    if t.get("tag"):
        f, tc = font(18, True), t.get("tag_color", RED)
        tx = x0 + (64 if t.get("number") else 10)
        tw = draw.textlength(t["tag"], font=f) / S + 16
        draw.rectangle((p(tx), p(y0 + 12), p(tx + tw), p(y0 + 38)), fill=tc)
        draw.text((p(tx + tw / 2), p(y0 + 25)), t["tag"], font=f,
                  fill=INK if sum(tc) > 450 else WHITE, anchor="mm")
    if t.get("mark") is not None:
        mark(draw, x1 - 30, y0 + 30, t["mark"])
    elif t.get("price"):
        f = font(22, True)
        bw = draw.textlength(t["price"], font=f) / S + 50
        bx = x1 - 10 - bw
        base.overlay(img, "rectangle", (p(bx), p(y0 + 12), p(x1 - 10),
                                        p(y0 + 46)), (0, 0, 0, 120))
        cart(draw, bx + 10, y0 + 20, WHITE)
        draw.text((p(bx + 40), p(y0 + 29)), t["price"], font=f, fill=WHITE,
                  anchor="lm")
    y = y1 - 18
    if t.get("sub"):
        draw.text((p(x0 + 14), p(y)), wrap(draw, t["sub"].upper(), font(17),
                                           w - 28, 1)[0],
                  font=font(17), fill=MUTED, anchor="ls")
        y -= 26
    names = wrap(draw, t["name"].upper(), font(26, True), w - 28, 2)
    for k, line in enumerate(reversed(names)):
        draw.text((p(x0 + 14), p(y - 30 * k)), line, font=font(26, True),
                  fill=WHITE, anchor="ls")
    y -= 30 * len(names) + 4
    if t.get("value"):
        f = font(22, True)
        vw = draw.textlength(t["value"], font=f) / S + 18
        draw.rectangle((p(x0 + 14), p(y - 26), p(x0 + 14 + vw), p(y + 2)),
                       fill=GREEN if t.get("value_up", True) else RED)
        draw.text((p(x0 + 14 + vw / 2), p(y - 12)), t["value"], font=f,
                  fill=WHITE, anchor="mm")


def mark(draw, cx, cy, good):
    """Галочка в зелёном круге или крестик в красном."""
    r = 18
    draw.ellipse((p(cx - r), p(cy - r), p(cx + r), p(cy + r)),
                 fill=GREEN if good else RED)
    if good:
        draw.line([(p(cx - 8), p(cy + 1)), (p(cx - 2), p(cy + 7)),
                   (p(cx + 9), p(cy - 7))], fill=WHITE, width=p(4),
                  joint="curve")
    else:
        for a, b in (((-7, -7), (7, 7)), ((-7, 7), (7, -7))):
            draw.line((p(cx + a[0]), p(cy + a[1]), p(cx + b[0]),
                       p(cy + b[1])), fill=WHITE, width=p(4))


def footer(draw, W, H, left):
    draw.text((p(48), p(H - 26)), left.upper(), font=font(18), fill=DIM,
              anchor="lm")
    draw.text((p(W - 48), p(H - 26)), TAG, font=font(22, True), fill=MUTED,
              anchor="rm")


def save(img, W, H, path):
    return base.save(img, int(round(W)), int(round(H)), path)


def dump(path):
    """Для проверки: уменьшенная картинка в лог (base64)."""
    import base64
    import io
    from PIL import Image
    im = Image.open(path)
    im = im.resize((720, im.height * 720 // im.width), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=80)
    print("CARD_B64:" + base64.b64encode(buf.getvalue()).decode())


def grid(n):
    """Сколько колонок: 1–3 в ряд, 4 — квадратом, дальше по три."""
    return {1: 1, 2: 2, 3: 3, 4: 2}.get(n, 3)


# ---------- магазин: новинки недели ----------

def store_card(out_path, items, badge, bar_text):
    """Новинки магазина: золотая витрина с бордовыми плитками, как в игре.
    items — dict: name, sub, price, image (до 9 штук)."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    items = items[:9]
    n, W = len(items), 1200
    cols = grid(n)
    rows = -(-n // cols)
    tw = (W - 96 - 56 - (cols - 1) * 16) / cols
    th = min(tw * 1.2, 500)
    top = 120
    y1 = top + 108 + rows * (th + 16) + 6 + 64
    H = y1 + 70
    img, draw = canvas(W, H)
    nav(draw, W, "МАГАЗИН")
    panel(img, draw, (48, top, W - 48, y1), "НОВИНКИ НЕДЕЛИ", badge)
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        x0 = 76 + (cols - in_row) * (tw + 16) / 2 + c * (tw + 16)
        yy = top + 108 + r * (th + 16)
        tile(img, draw, (x0, yy, x0 + tw, yy + th),
             dict(it, hot=True, tag="НОВИНКА"))
    bar(draw, (51, y1 - 67, W - 51, y1 - 3), bar_text)
    footer(draw, W, H, "цены: магазин Steam")
    return save(img, W, H, out_path)


# ---------- маркет: что стало со скинами после магазина ----------

def market_card(out_path, badge, sections):
    """Две витрины по три плитки: «дороже, чем в магазине» (золотая,
    бордовые плитки) и «дешевле» (серая). sections: [(заголовок, рост?,
    плитки dict: name, image, price, sub, value)]."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W = 1200
    tw = (W - 96 - 56 - 32) / 3
    th = tw * 1.18
    ph = 108 + th + 28
    top = 120
    H = top + len(sections) * (ph + 24) + 46
    img, draw = canvas(W, H)
    nav(draw, W, "МАРКЕТ")
    for k, (head, up, tiles) in enumerate(sections):
        y0 = top + k * (ph + 24)
        panel(img, draw, (48, y0, W - 48, y0 + ph), head,
              badge if k == 0 else None, gold=up)
        n = min(len(tiles), 3)
        for i, t in enumerate(tiles[:3]):
            x0 = 76 + (3 - n) * (tw + 16) / 2 + i * (tw + 16)
            tile(img, draw, (x0, y0 + 108, x0 + tw, y0 + 108 + th),
                 dict(t, hot=up, value_up=up))
    footer(draw, W, H, "цены: маркет Steam · rust.scmm.app")
    return save(img, W, H, out_path)


# ---------- новые рубрики ----------

def chart(img, draw, sp, days, box, money, store=None):
    """График цены на тёмном фоне: красная линия, золотой пунктир — цена
    в магазине, пик и точка «сейчас», годы снизу."""
    x0, y0, x1, y1 = box
    if len(sp) < 2:
        return
    lo, hi = min(sp + ([store] if store else [])), max(sp + ([store] if store
                                                               else []))
    span = (hi - lo) or hi or 1
    lo, hi = max(0.0, lo - span * 0.08), hi + span * 0.2
    X = lambda i: x0 + (x1 - x0) * i / (len(sp) - 1)
    Y = lambda v: y1 - (y1 - y0) * (v - lo) / (hi - lo)
    for v in (min(sp), max(sp)):
        draw.line((p(x0), p(Y(v)), p(x1), p(Y(v))), fill=(58, 55, 51),
                  width=p(1))
        draw.text((p(x0 - 10), p(Y(v))), money(v), font=font(18),
                  fill=MUTED, anchor="rm")
    if store:
        zy = Y(store)
        for x in range(int(x0), int(x1), 18):
            draw.line((p(x), p(zy), p(min(x + 10, x1)), p(zy)), fill=GOLD,
                      width=p(2))
        draw.text((p(x1), p(zy - 8)), f"в магазине {money(store)}",
                  font=font(18, True), fill=GOLD, anchor="rs")
    pts = [(p(X(i)), p(Y(v))) for i, v in enumerate(sp)]
    base.overlay(img, "polygon", pts + [(p(x1), p(y1)), (p(x0), p(y1))],
                 RED + (60,))
    draw.line(pts, fill=(232, 92, 70), width=p(4), joint="curve")
    top = max(range(len(sp)), key=lambda i: sp[i])
    if X(len(sp) - 1) - X(top) > 90:
        draw.ellipse((pts[top][0] - p(6), pts[top][1] - p(6),
                      pts[top][0] + p(6), pts[top][1] + p(6)), fill=WHITE)
        label = f"пик {money(sp[top])}"
        if store and abs(Y(store) - (Y(sp[top]) - 24)) < 20:
            # над точкой — линия цены магазина: пишем сбоку от точки
            draw.text((p(X(top) + 16), p(Y(sp[top]) + 4)), label,
                      font=font(19, True), fill=WHITE, anchor="lm")
        else:
            draw.text((p(min(max(X(top), x0 + 60), x1 - 60)),
                       p(Y(sp[top]) - 14)), label, font=font(19, True),
                      fill=WHITE, anchor="mb")
    nx, ny = pts[-1]
    draw.ellipse((nx - p(9), ny - p(9), nx + p(9), ny + p(9)), fill=WHITE)
    draw.ellipse((nx - p(6), ny - p(6), nx + p(6), ny + p(6)), fill=RED)
    from datetime import date
    days = days[:len(sp)]
    span = ((date.fromisoformat(days[-1][:10])
             - date.fromisoformat(days[0][:10])).days if days else 0)
    if span < 400:
        # чуть больше года и меньше — даты: начало, середина, «сейчас»
        for i, anchor in ((0, "lm"), (len(days) // 2, "mm")):
            if 0 <= i < len(days) - 1:
                draw.text((p(X(i)), p(y1 + 22)),
                          f"{days[i][8:10]}.{days[i][5:7]}", font=font(18),
                          fill=MUTED, anchor=anchor)
        draw.text((p(x1), p(y1 + 22)), "сейчас", font=font(18), fill=MUTED,
                  anchor="rm")
        return
    last = -999
    for i, d in enumerate(days):
        if (i == 0 or d[:4] != days[i - 1][:4]) and X(i) - last >= 70:
            draw.text((p(X(i)), p(y1 + 22)), d[:4], font=font(18),
                      fill=MUTED, anchor="lm" if i == 0 else "mm")
            last = X(i)


def stat(draw, x, y, w, label, value, extra=None, extra_up=True):
    """Строка «подпись — крупное значение» с тонкой линией снизу."""
    draw.text((p(x), p(y)), label.upper(), font=font(19), fill=MUTED,
              anchor="lm")
    draw.text((p(x), p(y + 36)), value, font=font(36, True), fill=WHITE,
              anchor="lm")
    if extra:
        f = font(22, True)
        vx = x + draw.textlength(value, font=font(36, True)) / S + 14
        vw = draw.textlength(extra, font=f) / S + 18
        draw.rectangle((p(vx), p(y + 22), p(vx + vw), p(y + 50)),
                       fill=GREEN if extra_up else RED)
        draw.text((p(vx + vw / 2), p(y + 36)), extra, font=f, fill=WHITE,
                  anchor="mm")
    draw.line((p(x), p(y + 64), p(x + w), p(y + 64)), fill=(70, 60, 40),
              width=p(1))


def skin_card(out_path, date, s, money):
    """«Скин дня»: витрина с большой плиткой, цифры справа, график цены
    с линией цены магазина и факт внизу. s — dict: name, image, coll,
    store, store_note, market, roi, roi_up, sold, fact, spark, days,
    store_cents."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W = 1200
    from PIL import Image, ImageDraw
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    facts = wrap(probe, s.get("fact") or "", font(26), W - 152, 2)
    facts = [f for f in facts if f.strip()]
    H = 1160 if facts else 1060
    img, draw = canvas(W, H)
    nav(draw, W, "МАРКЕТ")
    panel(img, draw, (48, 120, W - 48, H - 74), "СКИН ДНЯ", date)
    img.paste(gradient(p(440), p(440), *RED_TILE), (p(76), p(228)))
    draw.rectangle((p(76), p(228), p(516), p(668)), outline=(16, 12, 10),
                   width=p(2))
    base.place_item(img, fetch_image(s.get("image")), 296, 440, 360, 330)
    x, w = 548, W - 76 - 548
    y = 252
    for line in wrap(draw, s["name"].upper(), font(40, True), w, 2):
        draw.text((p(x), p(y)), line, font=font(40, True), fill=WHITE,
                  anchor="lm")
        y += 46
    if s.get("coll"):
        draw.text((p(x), p(y + 2)), wrap(draw, s["coll"].upper(), font(22, True),
                                         w, 1)[0],
                  font=font(22, True), fill=GOLD, anchor="lm")
    y = max(y + 48, 372)
    stat(draw, x, y, w, "в магазине" + (f" · {s['store_note']}"
                                        if s.get("store_note") else ""),
         s["store"])
    stat(draw, x, y + 92, w, "на маркете сейчас", s["market"], s.get("roi"),
         s.get("roi_up", True))
    stat(draw, x, y + 184, w, "продано в магазине", s["sold"])
    base.overlay(img, "rectangle", (p(76), p(692), p(W - 76), p(950)),
                 (0, 0, 0, 70))
    draw.text((p(96), p(716)), "ЦЕНА НА МАРКЕТЕ ЗА ВСЁ ВРЕМЯ", font=font(20,
                                                                         True),
              fill=MUTED, anchor="lm")
    chart(img, draw, s.get("spark") or [], s.get("days") or [],
          (170, 748, W - 100, 906), money, s.get("store_cents"))
    fy = 984
    for line in facts:
        draw.text((p(76), p(fy)), line, font=font(26), fill=WHITE,
                  anchor="lm")
        fy += 36
    footer(draw, W, H, "цены: маркет Steam · rust.scmm.app")
    return save(img, W, H, out_path)


def duel_card(out_path, badge, sides, question, note, winner=None):
    """«Угадай цену»: две большие плитки A и B. sides — dict: name,
    image, price, sub, value, value_up."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, H = 1200, 900
    img, draw = canvas(W, H)
    nav(draw, W, "МАРКЕТ")
    panel(img, draw, (48, 120, W - 48, 830), "УГАДАЙ ЦЕНУ", badge)
    tw = (W - 152 - 24) / 2
    for i, s in enumerate(sides):
        x0 = 76 + i * (tw + 24)
        t = dict(s, number="AB"[i], hot=True)
        if winner == i:
            t.update(tag="ПОБЕДИТЕЛЬ", tag_color=GREEN)
        tile(img, draw, (x0, 228, x0 + tw, 228 + 480), t)
    bar(draw, (51, 732, W - 51, 796), question)
    draw.text((p(W / 2), p(812)), note.upper(), font=font(18), fill=MUTED,
              anchor="mm")
    footer(draw, W, H, "цены: маркет Steam · rust.scmm.app")
    return save(img, W, H, out_path)


def report_card(out_path, badge, rows, summary):
    """«Мы советовали — что вышло»: плитки по три — совет (цвет), прогноз
    и что вышло, галочка или крестик. rows — dict: name, image, tag,
    tag_color, value, value_up, sub, mark."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    rows = rows[:9]
    n, W = len(rows), 1200
    cols = grid(n)
    nrows = -(-n // cols)
    tw = (W - 96 - 56 - (cols - 1) * 16) / cols
    th = min(tw * 1.2, 500)
    top = 120
    y1 = top + 108 + nrows * (th + 16) + 6 + 64
    H = y1 + 70
    img, draw = canvas(W, H)
    nav(draw, W, "ИНВЕСТИЦИИ")
    panel(img, draw, (48, top, W - 48, y1), "МЫ СОВЕТОВАЛИ — ЧТО ВЫШЛО", badge)
    for i, r in enumerate(rows):
        rr, c = divmod(i, cols)
        in_row = min(cols, n - rr * cols)
        x0 = 76 + (cols - in_row) * (tw + 16) / 2 + c * (tw + 16)
        yy = top + 108 + rr * (th + 16)
        tile(img, draw, (x0, yy, x0 + tw, yy + th), dict(r, hot=True))
    bar(draw, (51, y1 - 67, W - 51, y1 - 3), summary)
    footer(draw, W, H, "цены: маркет Steam · rust.scmm.app")
    return save(img, W, H, out_path)
