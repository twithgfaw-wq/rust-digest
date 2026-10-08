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
    if t.get("tag"):
        f = font(18, True)
        tw = draw.textlength(t["tag"], font=f) / S + 16
        draw.rectangle((p(x0 + 10), p(y0 + 12), p(x0 + 10 + tw), p(y0 + 38)),
                       fill=RED)
        draw.text((p(x0 + 10 + tw / 2), p(y0 + 25)), t["tag"], font=f,
                  fill=WHITE, anchor="mm")
    if t.get("number"):
        draw.ellipse((p(x0 + 12), p(y0 + 12), p(x0 + 62), p(y0 + 62)),
                     fill=RED)
        draw.text((p(x0 + 37), p(y0 + 37)), str(t["number"]),
                  font=font(30, True), fill=WHITE, anchor="mm")
    if t.get("price"):
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
