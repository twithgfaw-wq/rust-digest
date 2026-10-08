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


# ---------- инвест-разбор недельного выпуска ----------

def arrow(draw, x, cy, up, color, size=16):
    """Треугольник ▲/▼, а при up=None — ► «около нуля» (в Roboto таких
    знаков нет)."""
    h = size * 0.9
    if up is None:
        pts = [(x, cy - size / 2), (x, cy + size / 2), (x + h, cy)]
    elif up:
        pts = [(x, cy + h / 2), (x + size, cy + h / 2), (x + size / 2, cy - h / 2)]
    else:
        pts = [(x, cy - h / 2), (x + size, cy - h / 2), (x + size / 2, cy + h / 2)]
    draw.polygon([(p(a), p(b)) for a, b in pts], fill=color)


def dots(draw, x, cy, n, color, rest=None, r=8, step=22):
    """10 кружков «шанс N из 10»: n закрашено, остальные пустые или rest."""
    for i in range(10):
        cx = x + r + i * step
        box = (p(cx - r), p(cy - r), p(cx + r), p(cy + r))
        if i < n:
            draw.ellipse(box, fill=color)
        elif rest:
            draw.ellipse(box, fill=rest)
        else:
            draw.ellipse(box, outline=(110, 104, 96), width=p(2))


def invest_card(out_path, badge, subtitle, sections, example, note,
                foot="rust.scmm.app · история недельных скинов"):
    """Инвест-разбор списком — крупно, чтобы читалось с телефона: разделы
    «можно брать / подумать / не стоит», в строке — скин, цена в магазине,
    прибыль после комиссии и «шанс N из 10». sections: [(заголовок, цвет,
    строки dict: name, image, price, net, up (None — около нуля), n10,
    note, ncolor)]; example: net, back, n10 — для блока «как читать»."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, RH, SH = 1200, 132, 62
    n = sum(len(rows) for _, _, rows in sections)
    top = 120
    y = top + 150
    H = y + len(sections) * (SH + 8) + n * RH + 24 + 196 + 64 + 6 + 70
    img, draw = canvas(W, H)
    nav(draw, W, "ИНВЕСТИЦИИ")
    y1 = H - 70
    panel(img, draw, (48, top, W - 48, y1), "ИНВЕСТ-РАЗБОР", badge)
    draw.text((p(76), p(top + 112)), subtitle.upper(), font=font(21),
              fill=MUTED, anchor="lm")
    for head, color, rows in sections:
        draw.rectangle((p(76), p(y), p(W - 76), p(y + SH)),
                       fill=tuple(int(c * 0.22 + 20) for c in color))
        draw.rectangle((p(76), p(y), p(84), p(y + SH)), fill=color)
        draw.text((p(104), p(y + SH / 2)), head.upper(), font=font(30, True),
                  fill=color, anchor="lm")
        cnt = f"{len(rows)}"
        draw.text((p(W - 100), p(y + SH / 2)), cnt, font=font(30, True),
                  fill=color, anchor="rm")
        y += SH + 8
        for r in rows:
            img.paste(gradient(p(112), p(112), *RED_TILE), (p(76), p(y + 6)))
            base.place_item(img, fetch_image(r.get("image")), 132, y + 62, 96,
                            96)
            x, w = 208, 560
            name = wrap(draw, r["name"].upper(), font(32, True), w, 1)[0]
            draw.text((p(x), p(y + 36)), name, font=font(32, True), fill=WHITE,
                      anchor="lm")
            draw.text((p(x), p(y + 76)), f"в магазине {r['price']}".upper(),
                      font=font(22), fill=MUTED, anchor="lm")
            if r.get("note"):
                draw.text((p(x), p(y + 108)),
                          wrap(draw, r["note"], font(21, True), w, 1)[0],
                          font=font(21, True),
                          fill=tuple(r.get("ncolor") or MUTED),
                          anchor="lm")
            rx = 800
            arrow(draw, rx, y + 42, r.get("up", True), color, 26)
            draw.text((p(rx + 38), p(y + 42)), r["net"], font=font(56, True),
                      fill=color, anchor="lm")
            dots(draw, rx, y + 98, r["n10"], color)
            draw.text((p(rx + 228), p(y + 98)), f"шанс {r['n10']}/10",
                      font=font(22, True), fill=color, anchor="lm")
            draw.line((p(76), p(y + RH - 1), p(W - 76), p(y + RH - 1)),
                      fill=(66, 56, 38), width=p(1))
            y += RH
    # как читать
    y += 24
    half = (W - 152 - 24) / 2
    good, bad = (61, 220, 132), (255, 82, 82)
    for i in range(2):
        bx = 76 + i * (half + 24)
        base.overlay(img, "rectangle", (p(bx), p(y), p(bx + half), p(y + 180)),
                     (0, 0, 0, 90))
    tx = 100
    draw.text((p(tx), p(y + 36)), f"{example['net']} — ЭТО", font=font(28, True),
              fill=WHITE, anchor="lm")
    draw.text((p(tx), p(y + 76)), "купил в магазине, продал через 7 дней,",
              font=font(22), fill=MUTED, anchor="lm")
    draw.text((p(tx), p(y + 104)), "комиссия Steam уже вычтена:", font=font(22),
              fill=MUTED, anchor="lm")
    ok = example["back"] >= 100
    draw.text((p(tx), p(y + 146)), "ВЛОЖИЛ 100", font=font(26, True),
              fill=WHITE, anchor="lm")
    vx = tx + draw.textlength("ВЛОЖИЛ 100", font=font(26, True)) / S + 18
    arrow(draw, vx, y + 146, None, MUTED, 18)
    vx += 36
    draw.text((p(vx), p(y + 146)), f"ВЕРНУЛОСЬ {example['back']}",
              font=font(26, True), fill=good if ok else bad, anchor="lm")
    rx = 76 + half + 24 + 24
    n10 = example["n10"]
    draw.text((p(rx), p(y + 36)), f"ШАНС {n10} ИЗ 10 — ЭТО", font=font(28, True),
              fill=WHITE, anchor="lm")
    draw.text((p(rx), p(y + 76)), "из 10 похожих скинов прошлых недель",
              font=font(22), fill=MUTED, anchor="lm")
    draw.text((p(rx), p(y + 104)), f"{n10} продались в плюс, {10 - n10} — в минус",
              font=font(22), fill=MUTED, anchor="lm")
    dots(draw, rx, y + 146, n10, good, rest=bad, r=10, step=27)
    bar(draw, (51, y1 - 67, W - 51, y1 - 3), note)
    footer(draw, W, H, foot)
    return save(img, W, H, out_path)


# ---------- мастерская: топ недели и конкурс ----------

def safe_text(text):
    """Без эмодзи и значков: в Roboto их нет — были бы квадратики."""
    import unicodedata
    out = "".join(ch for ch in (text or "") if ord(ch) <= 0xFFFF
                  and unicodedata.category(ch) not in ("So", "Cs", "Co", "Cn")
                  and not 0xFE00 <= ord(ch) <= 0xFE0F and ch != "\u200d")
    return " ".join(out.split())


def trim(im):
    """Обрезаем чёрные/однотонные поля вокруг картинки (letterbox)."""
    from PIL import Image, ImageChops
    rgb = im.convert("RGB")
    corner = rgb.getpixel((0, 0))
    if sum(corner) > 90:
        return im
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, corner))
    box = diff.convert("L").point(lambda v: 255 if v > 14 else 0).getbbox()
    if box and (box[2] - box[0]) * (box[3] - box[1]) < 0.92 * im.width * im.height:
        return im.crop(box)
    return im


def photo(img, url, box):
    """Картинка работы из мастерской — во всю рамку, лишнее обрезаем."""
    from PIL import Image
    x0, y0, x1, y1 = box
    w, h = p(x1 - x0), p(y1 - y0)
    bg = Image.new("RGBA", (w, h), (24, 22, 20, 255))
    im = fetch_image(url)
    if im is not None:
        im = trim(im)
        k = max(w / im.width, h / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                       Image.LANCZOS)
        left, up = (im.width - w) // 2, (im.height - h) // 2
        bg.alpha_composite(im.crop((left, up, left + w, up + h)))
    img.paste(bg, (p(x0), p(y0)))


def shade(img, box, strength=200):
    """Затемнение снизу вверх — чтобы текст поверх картинки читался."""
    from PIL import Image
    x0, y0, x1, y1 = box
    mask = Image.linear_gradient("L").resize((p(x1 - x0), p(y1 - y0)))
    mask = mask.point(lambda v: v * strength // 255)
    layer = Image.new("RGBA", mask.size, (12, 10, 9, 255))
    layer.putalpha(mask)
    img.alpha_composite(layer, (p(x0), p(y0)))


def medal(draw, cx, cy, n, r=30):
    """Кружок с местом: 0–2 — золото, серебро, бронза; дальше — красный
    кружок с номером n − 2 (номера конкурса 1–5)."""
    colors = [(232, 186, 62), (200, 205, 214), (205, 128, 62)]
    c = colors[n] if n < 3 else RED
    draw.ellipse((p(cx - r), p(cy - r), p(cx + r), p(cy + r)), fill=c,
                 outline=(16, 12, 10), width=p(3))
    draw.text((p(cx), p(cy)), str(n + 1 if n < 3 else n - 2),
              font=font(int(r * 1.2), True), fill=INK if n < 3 else WHITE,
              anchor="mm")


def votes(draw, x, y, up, down, size=26):
    """▲ 1 234  ▼ 56  · 96% лайков."""
    f = font(size, True)
    arrow(draw, x, y, True, (98, 200, 80), size * 0.7)
    x += size * 0.7 + 10
    t = f"{up:,}".replace(",", " ")
    draw.text((p(x), p(y)), t, font=f, fill=WHITE, anchor="lm")
    x += draw.textlength(t, font=f) / S + 24
    arrow(draw, x, y, False, (230, 80, 64), size * 0.7)
    x += size * 0.7 + 10
    t = f"{down:,}".replace(",", " ")
    draw.text((p(x), p(y)), t, font=f, fill=WHITE, anchor="lm")
    x += draw.textlength(t, font=f) / S + 24
    if up + down:
        draw.text((p(x), p(y)), f"{round(100 * up / (up + down))}% ЗА",
                  font=font(size - 4, True), fill=GOLD, anchor="lm")


def top_card(out_path, badge, works, bar_text):
    """Топ-3 недели в мастерской: №1 крупно (картинка + цифры справа),
    №2 и №3 рядом снизу. works — dict: title, author, image, up, down,
    category."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, top = 1200, 120
    H = top + 108 + 560 + 24 + 512 + 24 + 64 + 6 + 70
    img, draw = canvas(W, H)
    nav(draw, W, "МАСТЕРСКАЯ")
    y1 = H - 70
    panel(img, draw, (48, top, W - 48, y1), "ТОП-3 НЕДЕЛИ", badge)
    if works:
        it, y = works[0], top + 108
        photo(img, it["image"], (76, y, 636, y + 560))
        draw.rectangle((p(76), p(y), p(636), p(y + 560)), outline=GOLD,
                       width=p(3))
        medal(draw, 120, y + 44, 0, 34)
        x, w = 664, W - 76 - 664
        draw.text((p(x), p(y + 24)), "1 МЕСТО НЕДЕЛИ", font=font(24, True),
                  fill=GOLD, anchor="lt")
        yy = y + 70
        for line in wrap(draw, safe_text(it["title"]).upper(), font(44, True),
                         w, 3):
            draw.text((p(x), p(yy)), line, font=font(44, True), fill=WHITE,
                      anchor="lt")
            yy += 52
        draw.text((p(x), p(yy + 14)),
                  wrap(draw, "автор: " + (safe_text(it["author"]) or "—"),
                       font(26), w, 1)[0],
                  font=font(26), fill=MUTED, anchor="lt")
        yy += 80
        draw.text((p(x), p(yy)), "ОЦЕНКИ ИГРОКОВ STEAM", font=font(19),
                  fill=MUTED, anchor="lt")
        votes(draw, x, yy + 48, it["up"], it["down"], 30)
        total = it["up"] + it["down"]
        if total:
            by = yy + 90
            share = it["up"] / total
            draw.rectangle((p(x), p(by), p(x + w), p(by + 14)),
                           fill=(150, 54, 42))
            draw.rectangle((p(x), p(by), p(x + w * share), p(by + 14)),
                           fill=(98, 200, 80))
            draw.text((p(x), p(by + 40)),
                      f"{round(share * 10)} из 10 игроков — «за»".upper(),
                      font=font(22, True), fill=WHITE, anchor="lm")
        if it.get("category"):
            f = font(20, True)
            cw = draw.textlength(it["category"].upper(), font=f) / S + 28
            draw.rectangle((p(x), p(y + 500), p(x + cw), p(y + 536)),
                           fill=(116, 32, 25))
            draw.text((p(x + cw / 2), p(y + 518)), it["category"].upper(),
                      font=f, fill=WHITE, anchor="mm")
    tw = (W - 152 - 24) / 2
    for k, it in enumerate(works[1:3], start=1):
        x0, y0 = 76 + (k - 1) * (tw + 24), top + 108 + 560 + 24
        photo(img, it["image"], (x0, y0, x0 + tw, y0 + 512))
        shade(img, (x0, y0 + 260, x0 + tw, y0 + 512), 245)
        draw.rectangle((p(x0), p(y0), p(x0 + tw), p(y0 + 512)),
                       outline=(16, 12, 10), width=p(2))
        medal(draw, x0 + 40, y0 + 40, k, 28)
        names = wrap(draw, safe_text(it["title"]).upper(), font(32, True),
                     tw - 40, 2)
        ny = y0 + 512 - 106 - 38 * (len(names) - 1)
        for line in names:
            draw.text((p(x0 + 20), p(ny)), line, font=font(32, True),
                      fill=WHITE, anchor="ls")
            ny += 38
        draw.text((p(x0 + 20), p(y0 + 512 - 66)),
                  wrap(draw, "автор: " + (safe_text(it["author"]) or "—"),
                       font(21), tw - 40, 1)[0],
                  font=font(21), fill=MUTED, anchor="ls")
        votes(draw, x0 + 20, y0 + 512 - 32, it["up"], it["down"], 24)
    bar(draw, (51, y1 - 67, W - 51, y1 - 3), bar_text)
    footer(draw, W, H, "оценки Steam · micro522.com")
    return save(img, W, H, out_path)


def contest_card(out_path, badge, works, bar_text):
    """Конкурс «угадай, кого примут»: 5 работ с номерами 1–5 (3 + 2).
    works — dict: title, author, image."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, top, gap = 1200, 120, 16
    tw = (W - 152 - 2 * gap) / 3
    H = top + 108 + 2 * tw + gap + 16 + 64 + 6 + 70
    img, draw = canvas(W, H)
    nav(draw, W, "МАСТЕРСКАЯ")
    y1 = H - 70
    panel(img, draw, (48, top, W - 48, y1), "КОГО ПРИМУТ В ИГРУ?", badge)
    for i, it in enumerate(works[:5]):
        row, col = divmod(i, 3)
        in_row = 3 if row == 0 else len(works[3:5])
        x0 = 76 + (3 - in_row) * (tw + gap) / 2 + col * (tw + gap)
        y0 = top + 108 + row * (tw + gap)
        photo(img, it["image"], (x0, y0, x0 + tw, y0 + tw))
        shade(img, (x0, y0 + tw * 0.62, x0 + tw, y0 + tw), 230)
        draw.rectangle((p(x0), p(y0), p(x0 + tw), p(y0 + tw)),
                       outline=(16, 12, 10), width=p(2))
        medal(draw, x0 + 38, y0 + 38, i + 3, 28)
        draw.text((p(x0 + 16), p(y0 + tw - 46)),
                  wrap(draw, safe_text(it["title"]).upper(), font(24, True),
                       tw - 32, 1)[0],
                  font=font(24, True), fill=WHITE, anchor="ls")
        if safe_text(it.get("author")):
            draw.text((p(x0 + 16), p(y0 + tw - 16)),
                      wrap(draw, safe_text(it["author"]), font(19), tw - 32,
                           1)[0],
                      font=font(19), fill=MUTED, anchor="ls")
    bar(draw, (51, y1 - 67, W - 51, y1 - 3), bar_text)
    footer(draw, W, H, "работы из мастерской Steam")
    return save(img, W, H, out_path)
