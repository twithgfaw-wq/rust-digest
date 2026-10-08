# -*- coding: utf-8 -*-
"""
Картинки CS2-канала в светлом «каталожном» стиле — как официальные
постеры кейсов: светло-серый фон с виньеткой, крупные предметы с мягкой
тенью, подписи под ними. Цвет — только там, где он что-то значит:
редкость скина, рост/падение цены, решение «брать или нет».

Шрифт — Roboto Condensed (скачиваем из Google Fonts при запуске), без
интернета — DejaVu. Рисуем в 2× и уменьшаем: текст и края чёткие.
На картинках только простые символы: стрелки и «≈» есть не во всех
шрифтах, поэтому пишем словами.
"""
import io
import os
import re
import tempfile
import urllib.request

import rust_digest_bot as bot

S = 2                                    # рисуем в 2× и уменьшаем
TEXT, MUTED, LINE = (50, 53, 60), (110, 114, 124), (196, 198, 204)
GREEN, AMBER, RED = (34, 148, 82), (204, 134, 0), (206, 62, 62)
WHITE = (255, 255, 255)
VERDICT = {"buy": ("МОЖНО БРАТЬ", GREEN), "watch": ("ПОДОЖДАТЬ", AMBER),
           "avoid": ("НЕ БРАТЬ", RED)}
FONT_CSS = ("https://fonts.googleapis.com/css?family=Roboto+Condensed:400,700"
            "&subset=latin,cyrillic")
DEJAVU = "/usr/share/fonts/truetype/dejavu/"
STEAM_IMG = ("https://community.cloudflare.steamstatic.com/economy/image/"
             "{}/360fx360f")
_fonts = {}


def p(v):
    return int(round(v * S))


# ---------- шрифты, картинки, цвета ----------

def _font_files():
    """Roboto Condensed: со старым User-Agent Google отдаёт обычные TTF."""
    if _fonts:
        return _fonts
    _fonts["tried"] = True
    try:
        req = urllib.request.Request(FONT_CSS,
                                     headers={"User-Agent": "Mozilla/4.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            css = r.read().decode("utf-8", "replace")
        for block in css.split("@font-face")[1:]:
            w = re.search(r"font-weight:\s*(\d+)", block)
            u = re.search(r"url\((https://[^)]+\.ttf)\)", block)
            if not (w and u):
                continue
            path = os.path.join(tempfile.gettempdir(),
                                f"cs2_roboto_{w.group(1)}.ttf")
            if not os.path.exists(path):
                with urllib.request.urlopen(u.group(1), timeout=20) as r:
                    data = r.read()
                with open(path, "wb") as f:
                    f.write(data)
            _fonts[int(w.group(1))] = path
    except Exception as e:
        print("Шрифт Roboto Condensed не скачался, рисуем DejaVu:", e)
    return _fonts


def font(size, bold=False):
    from PIL import ImageFont
    dejavu = DEJAVU + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    for path in (_font_files().get(700 if bold else 400), dejavu):
        if path:
            try:
                return ImageFont.truetype(path, p(size))
            except Exception:
                pass
    return ImageFont.load_default()


def fetch_image(url):
    """Картинка предмета (RGBA) или None."""
    from PIL import Image
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": bot.UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGBA")
    except Exception:
        return None


def readable(hexcolor, default=TEXT):
    """Цвет редкости из Steam; слишком светлый — затемняем, чтобы читался
    на светлом фоне (серый «ширпотреб», золото ножей)."""
    try:
        c = tuple(int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default
    lum = (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255
    if lum > 0.55:
        c = tuple(int(v * 0.55 / lum) for v in c)
    return c


# ---------- основа ----------

def canvas(W, H):
    """Светло-серый фон с мягкой виньеткой."""
    from PIL import Image, ImageDraw
    big = Image.radial_gradient("L").resize((p(W) * 3 // 2, p(H) * 3 // 2),
                                            Image.BICUBIC)
    left, top = (big.width - p(W)) // 2, (big.height - p(H)) // 2
    mask = big.crop((left, top, left + p(W), top + p(H)))
    img = Image.composite(Image.new("RGB", mask.size, (198, 199, 204)),
                          Image.new("RGB", mask.size, (239, 239, 241)),
                          mask).convert("RGBA")
    return img, ImageDraw.Draw(img)


def overlay(img, shape, xy, fill, radius=24):
    """Полупрозрачная фигура поверх картинки. Радиус скругления не больше
    половины высоты — иначе Pillow рисует вместо плашки овал."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if shape == "panel":
        d.rounded_rectangle(xy, radius=p(radius), fill=fill)
    else:
        getattr(d, shape)(xy, fill=fill)
    img.alpha_composite(layer)


def panel(img, x0, y0, x1, y1):
    overlay(img, "panel", (p(x0), p(y0), p(x1), p(y1)), (255, 255, 255, 150))


def header(draw, W, title, subtitle):
    """Знак канала и заголовок по центру, пояснение под ним."""
    tf, mark = font(46), 62
    tw = draw.textlength(title, font=tf) / S
    x0 = (W - (mark + 20 + tw)) / 2
    draw.rounded_rectangle((p(x0), p(32), p(x0 + mark), p(32 + mark)),
                           radius=p(16), fill=TEXT)
    draw.text((p(x0 + mark / 2), p(32 + mark / 2)), "CS2",
              font=font(22, True), fill=(239, 239, 241), anchor="mm")
    draw.text((p(x0 + mark + 20), p(32 + mark / 2)), title, font=tf,
              fill=TEXT, anchor="lm")
    draw.text((p(W / 2), p(124)), subtitle, font=font(24), fill=MUTED,
              anchor="mm")


def footer(draw, W, H, left, tag="@cs2_me"):
    draw.line((p(48), p(H - 54), p(W - 48), p(H - 54)), fill=LINE,
              width=p(2))
    draw.text((p(48), p(H - 28)), left, font=font(20), fill=MUTED,
              anchor="lm")
    draw.text((p(W - 48), p(H - 28)), tag, font=font(24, True), fill=TEXT,
              anchor="rm")


def save(img, W, H, path):
    from PIL import Image
    img.convert("RGB").resize((W, H), Image.LANCZOS).save(
        path, "JPEG", quality=93, subsampling=0)
    return True


def wrap(draw, text, fnt, width, lines=2):
    """Перенос по словам в ширину width (лишнее — «…»)."""
    out, cur = [], ""
    for word in (text or "").split():
        t = f"{cur} {word}".strip()
        if not cur or draw.textlength(t, font=fnt) <= p(width):
            cur = t
        else:
            out.append(cur)
            cur = word
    out.append(cur)
    if len(out) > lines:
        out, last = out[:lines], out[lines - 1]
        while last and draw.textlength(last + "…", font=fnt) > p(width):
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out


def place_item(img, im, cx, cy, bw, bh):
    """Предмет по центру рамки bw×bh и мягкая тень под ним."""
    from PIL import Image, ImageDraw, ImageFilter
    if im is None:
        return
    box = im.getbbox()
    if box:
        im = im.crop(box)
    k = min(p(bw) / im.width, p(bh) / im.height)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                   Image.LANCZOS)
    sw, sh, pad = int(im.width * 0.8), max(p(10), int(im.width * 0.07)), p(26)
    shade = Image.new("RGBA", (sw + 2 * pad, sh + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse((pad, pad, pad + sw, pad + sh),
                                  fill=(0, 0, 0, 80))
    shade = shade.filter(ImageFilter.GaussianBlur(p(9)))
    bottom = p(cy) + im.height // 2
    img.alpha_composite(shade, (max(0, p(cx) - shade.width // 2),
                                max(0, bottom - shade.height // 2 - p(2))))
    img.alpha_composite(im, (max(0, p(cx) - im.width // 2),
                             max(0, p(cy) - im.height // 2)))


def item_name(draw, cx, y, name, rarity, size, width):
    """«AK-47 | Blue Laminate · FN»: оружие серым, скин — цветом редкости,
    как подписи на постерах кейсов. Одна строка по центру."""
    a, b = (name.split(" | ", 1) if " | " in name else (name, ""))
    a = a + " | " if b else a
    f = font(size)
    while draw.textlength(a + b, font=f) > p(width) and size > 17:
        size -= 1
        f = font(size)
    if draw.textlength(a + b, font=f) > p(width):
        if b:
            while b and draw.textlength(a + b + "…", font=f) > p(width):
                b = b[:-1]
            b = b.rstrip() + "…"
        else:
            a = wrap(draw, a, f, width, 1)[0]
    x = p(cx) - draw.textlength(a + b, font=f) / 2
    draw.text((x, p(y)), a, font=f, fill=MUTED if b else TEXT, anchor="lm")
    if b:
        draw.text((x + draw.textlength(a, font=f), p(y)), b, font=f,
                  fill=readable(rarity), anchor="lm")


def tag(draw, xy, text, fnt, fill, anchor):
    """Подпись на белой плашке — читается поверх линии графика."""
    x0, y0, x1, y1 = draw.textbbox(xy, text, font=fnt, anchor=anchor)
    draw.rounded_rectangle((x0 - p(6), y0 - p(4), x1 + p(6), y1 + p(4)),
                           radius=p(6), fill=WHITE)
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def pill(draw, cx, cy, text, color, size=22):
    f = font(size, True)
    w = draw.textlength(text, font=f) / S + 34
    draw.rounded_rectangle((p(cx - w / 2), p(cy - 20), p(cx + w / 2),
                            p(cy + 20)), radius=p(19), fill=color)
    draw.text((p(cx), p(cy)), text, font=f, fill=WHITE, anchor="mm")


# ---------- маркет: что дорожает и что дешевеет ----------

def market_card(title, subtitle, sections, source, out_path):
    """sections: [(заголовок, цвет, [плитки])], плитка — dict: name, icon,
    rarity, prices, pct, why. До трёх плиток в ряду, как на постере кейса."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W = 1200
    H = 160 + 520 * len(sections) + 70
    img, draw = canvas(W, H)
    header(draw, W, title, subtitle)
    cw, y = (W - 96) / 3, 160
    for label, color, tiles in sections:
        lf = font(26, True)
        draw.text((p(48), p(y + 20)), label, font=lf, fill=color, anchor="lm")
        lw = draw.textlength(label, font=lf) / S
        draw.line((p(48 + lw + 18), p(y + 20), p(W - 48), p(y + 20)),
                  fill=LINE, width=p(2))
        ty = y + 50
        for i, t in enumerate(tiles[:3]):
            cx = 48 + cw * i + cw / 2
            place_item(img, fetch_image(t["icon"]), cx, ty + 120, cw - 70, 190)
            item_name(draw, cx, ty + 262, t["name"], t.get("rarity", ""), 24,
                      cw - 24)
            draw.text((p(cx), p(ty + 298)), t["prices"], font=font(23),
                      fill=TEXT, anchor="mm")
            draw.text((p(cx), p(ty + 346)), t["pct"], font=font(46, True),
                      fill=color, anchor="mm")
            for k, line in enumerate(wrap(draw, t.get("why", ""), font(21),
                                          cw - 40, 2)):
                draw.text((p(cx), p(ty + 394 + 28 * k)), line, font=font(21),
                          fill=MUTED, anchor="mm")
        y += 520
    footer(draw, W, H, source)
    return save(img, W, H, out_path)


# ---------- инвестиции: обзор ТОП-5 и карточка предмета ----------

def top5_card(title, subtitle, items, out_path):
    """Обзор: пять предметов сеткой 3×2 и шестая клетка — «как читать».
    item — dict: name, icon, verdict, price, hint."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, H = 1200, 1250
    img, draw = canvas(W, H)
    header(draw, W, title, subtitle)
    cw, ch = (W - 96) / 3, 510
    for i, it in enumerate(items[:5]):
        x0, ty = 48 + cw * (i % 3), 160 + ch * (i // 3)
        cx = x0 + cw / 2
        draw.text((p(x0 + 18), p(ty + 24)), str(i + 1), font=font(34, True),
                  fill=MUTED, anchor="lm")
        place_item(img, fetch_image(it["icon"]), cx, ty + 150, cw - 120, 220)
        for k, line in enumerate(wrap(draw, it["name"], font(26), cw - 30)):
            draw.text((p(cx), p(ty + 300 + 32 * k)), line, font=font(26),
                      fill=TEXT, anchor="mm")
        label, color = VERDICT[it["verdict"]]
        draw.text((p(cx), p(ty + 388)), it["price"], font=font(38, True),
                  fill=TEXT, anchor="mm")
        pill(draw, cx, ty + 438, label, color)
        draw.text((p(cx), p(ty + 482)), it["hint"], font=font(21),
                  fill=MUTED, anchor="mm")
    # шестая клетка — как читать карточки
    x0, ty = 48 + cw * 2, 160 + ch
    cx = x0 + cw / 2
    panel(img, x0 + 14, ty + 30, x0 + cw - 14, ty + ch - 20)
    draw.text((p(cx), p(ty + 80)), "Как читать", font=font(30, True),
              fill=TEXT, anchor="mm")
    for k, (v, hint) in enumerate((("buy", "цена уже выгодная"),
                                   ("watch", "дороговато — ждём скидку"),
                                   ("avoid", "цена падает"))):
        label, color = VERDICT[v]
        pill(draw, cx, ty + 150 + 96 * k, label, color)
        draw.text((p(cx), p(ty + 192 + 96 * k)), hint, font=font(21),
                  fill=MUTED, anchor="mm")
    draw.text((p(cx), p(ty + 446)), "листай: карточка каждого",
              font=font(22, True), fill=TEXT, anchor="mm")
    footer(draw, W, H, "цены: продажи на CSFloat · не финансовый совет")
    return save(img, W, H, out_path)


def chart(img, draw, sp, days, box, color, zone, zone_label, money):
    """График цены по неделям: линия цветом решения, зелёная выгодная зона,
    пик и точка «сейчас», годы снизу."""
    x0, y0, x1, y1 = box
    if len(sp) < 2:
        return
    lo, hi = min(sp + ([zone] if zone else [])), max(sp)
    span = (hi - lo) or hi or 1
    lo, hi = max(0.0, lo - span * 0.08), hi + span * 0.2
    X = lambda i: x0 + (x1 - x0) * i / (len(sp) - 1)
    Y = lambda v: y1 - (y1 - y0) * (v - lo) / (hi - lo)
    for v in (min(sp), (min(sp) + max(sp)) / 2, max(sp)):
        draw.line((p(x0), p(Y(v)), p(x1), p(Y(v))), fill=LINE, width=p(1))
        draw.text((p(x0 - 10), p(Y(v))), money(v), font=font(18),
                  fill=MUTED, anchor="rm")
    if zone:
        zy = Y(zone)
        overlay(img, "rectangle", (p(x0), p(zy), p(x1), p(y1)),
                GREEN + (40,))
        for x in range(int(x0), int(x1), 18):
            draw.line((p(x), p(zy), p(min(x + 10, x1)), p(zy)), fill=GREEN,
                      width=p(2))
        tag(draw, (p(x0 + 12), p(zy - 10)), zone_label, font(19, True),
            GREEN, "ls")
    pts = [(p(X(i)), p(Y(v))) for i, v in enumerate(sp)]
    overlay(img, "polygon", pts + [(p(x1), p(y1)), (p(x0), p(y1))],
            color + (40,))
    draw.line(pts, fill=color, width=p(4), joint="curve")
    top = max(range(len(sp)), key=lambda i: sp[i])
    if X(len(sp) - 1) - X(top) > 90:      # пик не там же, где «сейчас»
        draw.ellipse((pts[top][0] - p(6), pts[top][1] - p(6),
                      pts[top][0] + p(6), pts[top][1] + p(6)), fill=TEXT)
        tag(draw, (p(min(max(X(top), x0 + 70), x1 - 70)), p(Y(sp[top]) - 14)),
            f"пик {money(sp[top])}", font(19, True), TEXT, "mb")
    nx, ny = pts[-1]
    draw.ellipse((nx - p(10), ny - p(10), nx + p(10), ny + p(10)), fill=WHITE)
    draw.ellipse((nx - p(7), ny - p(7), nx + p(7), ny + p(7)), fill=color)
    tag(draw, (nx - p(18), ny - p(16)), "сейчас", font(19, True), TEXT, "rb")
    last = -999
    for i, d in enumerate(days[:len(sp)]):
        if (i == 0 or d[:4] != days[i - 1][:4]) and X(i) - last >= 70:
            draw.text((p(X(i)), p(y1 + 24)), d[:4], font=font(18),
                      fill=MUTED, anchor="lm" if i == 0 else "mm")
            last = X(i)


def item_card(out_path, rank, total, name, kind, icon, price, net, verdict,
              sub, why, spark, spark_days, zone, zone_label, scenarios, pills,
              money):
    """Карточка одного предмета: картинка, цена, большое решение, причина,
    график с выгодной зоной, три варианта «что дальше» и две подсказки.
    scenarios: [(подпись, цена, процент, цвет)]."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    W, H = 1080, 1440
    img, draw = canvas(W, H)
    label, color = VERDICT[verdict]
    draw.text((p(48), p(52)), f"#{rank} из {total}", font=font(26, True),
              fill=MUTED, anchor="lm")
    draw.text((p(W / 2), p(52)), "ИНВЕСТИЦИИ CS2", font=font(26, True),
              fill=TEXT, anchor="mm")
    draw.text((p(W - 48), p(52)), "@cs2_me", font=font(26, True),
              fill=MUTED, anchor="rm")

    place_item(img, fetch_image(icon), W / 2, 280, 440, 320)
    y = 500
    for line in wrap(draw, name, font(40, True), W - 120):
        draw.text((p(W / 2), p(y)), line, font=font(40, True), fill=TEXT,
                  anchor="mm")
        y += 46
    draw.text((p(W / 2), p(y)), kind, font=font(24), fill=MUTED, anchor="mm")
    draw.text((p(W / 2), p(y + 62)), price, font=font(72, True), fill=TEXT,
              anchor="mm")
    draw.text((p(W / 2), p(y + 116)),
              f"стоит сейчас · на руки после продажи: {net}", font=font(22),
              fill=MUTED, anchor="mm")

    draw.rounded_rectangle((p(48), p(750), p(W - 48), p(860)), radius=p(28),
                           fill=color)
    draw.text((p(W / 2), p(790)), label, font=font(46, True), fill=WHITE,
              anchor="mm")
    draw.text((p(W / 2), p(834)), sub, font=font(26), fill=WHITE, anchor="mm")
    for k, line in enumerate(wrap(draw, why, font(28), W - 120)):
        draw.text((p(W / 2), p(898 + 36 * k)), line, font=font(28),
                  fill=TEXT, anchor="mm")

    panel(img, 48, 960, W - 48, 1196)
    draw.text((p(72), p(986)), "Как менялась цена", font=font(22, True),
              fill=MUTED, anchor="lm")
    chart(img, draw, spark, spark_days, (150, 1012, W - 72, 1150), color,
          zone, zone_label, money)

    draw.text((p(48), p(1226)), "Что может быть дальше", font=font(26, True),
              fill=TEXT, anchor="lm")
    draw.text((p(W - 48), p(1226)), "по ценам за последний год",
              font=font(20), fill=MUTED, anchor="rm")
    tw = (W - 96 - 32) / 3
    for i, (title, val, change, c) in enumerate(scenarios):
        x0 = 48 + i * (tw + 16)
        panel(img, x0, 1246, x0 + tw, 1350)
        cx = x0 + tw / 2
        draw.text((p(cx), p(1272)), title, font=font(22), fill=MUTED,
                  anchor="mm")
        draw.text((p(cx), p(1308)), val, font=font(36, True), fill=TEXT,
                  anchor="mm")
        draw.text((p(cx), p(1336)), change, font=font(22, True), fill=c,
                  anchor="mm")
    pf = font(22, True)
    for i, text in enumerate(pills):
        w = draw.textlength(text, font=pf) / S + 36
        x0 = 48 if i == 0 else W - 48 - w
        overlay(img, "panel", (p(x0), p(1368), p(x0 + w), p(1408)),
                (255, 255, 255, 170), radius=18)
        draw.text((p(x0 + w / 2), p(1388)), text, font=pf, fill=TEXT,
                  anchor="mm")
    draw.text((p(W / 2), p(1426)), "цены: продажи на CSFloat · не финансовый"
              " совет", font=font(17), fill=MUTED, anchor="mm")
    return save(img, W, H, out_path)
