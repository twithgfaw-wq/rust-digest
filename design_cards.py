# -*- coding: utf-8 -*-
"""
Картки каналу @Her_Design «Все про дизайн» у стилі «дошка дизайнера»
(затверджено 10.10): синє поле в клітинку з пунктирною рамкою, аркуш із
блокнота з дірочками, рожевий затискач, жовтий скотч і лінійка, папка,
піксельний курсор, зірочки, внизу таблички з назвою каналу.

Шрифти з Google Fonts, усі з кирилицею: Unbounded для заголовків, Onest для
тексту, Caveat для рукописних позначок. Без інтернету малюємо DejaVu.
Малюємо в 2× і зменшуємо, щоб текст і краї були чіткі.
"""
import io
import os
import re
import tempfile
import urllib.request

S = 2                                    # малюємо в 2× і зменшуємо
W, H = 1280, 720
BLUE = (45, 100, 222)
GRID = (92, 139, 240)
STITCH = (169, 193, 247)
PAPER = (245, 243, 238)
PAPER_GRID = (222, 228, 242)
SHADOW = (31, 77, 184)
INK = (30, 63, 158)
MUTED = (91, 106, 142)
PINK = (238, 91, 169)
PINK_DARK = (214, 63, 143)
YELLOW = (247, 200, 67)
YELLOW_DARK = (227, 174, 34)
WHITE = (255, 255, 255)
PILL = (201, 216, 251)
WIRE = (42, 42, 58)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FONT_CSS = ("https://fonts.googleapis.com/css?family=Unbounded:500,700|"
            "Onest:400,600|Caveat:600&subset=latin,cyrillic,cyrillic-ext")
DEJAVU = "/usr/share/fonts/truetype/dejavu/"
CURSOR = [(0, 0), (0, 30), (8, 23), (13, 34), (19, 31), (14, 21), (24, 21)]
_fonts = {}


def p(v):
    return int(round(v * S))


# ---------- шрифти й картинки ----------

def _font_files():
    """Зі старим User-Agent Google Fonts віддає звичайні TTF."""
    if _fonts:
        return _fonts
    _fonts["tried"] = True
    try:
        req = urllib.request.Request(FONT_CSS,
                                     headers={"User-Agent": "Mozilla/4.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            css = r.read().decode("utf-8", "replace")
        for block in css.split("@font-face")[1:]:
            fam = re.search(r"font-family:\s*'([^']+)'", block)
            w = re.search(r"font-weight:\s*(\d+)", block)
            u = re.search(r"url\((https://[^)]+\.ttf)\)", block)
            if not (fam and w and u):
                continue
            name = fam.group(1).lower()
            path = os.path.join(tempfile.gettempdir(),
                                f"hd_{name}_{w.group(1)}.ttf")
            if not os.path.exists(path):
                with urllib.request.urlopen(u.group(1), timeout=20) as r:
                    data = r.read()
                with open(path, "wb") as f:
                    f.write(data)
            _fonts[(name, int(w.group(1)))] = path
    except Exception as e:
        print("Шрифти Google не скачались, малюємо DejaVu:", e)
    print("Шрифти:", sorted(k for k in _fonts if k != "tried"))
    return _fonts


def font(family, weight, size):
    from PIL import ImageFont
    dejavu = DEJAVU + ("DejaVuSans-Bold.ttf" if weight >= 600
                       else "DejaVuSans.ttf")
    for path in (_font_files().get((family, weight)), dejavu):
        if path:
            try:
                return ImageFont.truetype(path, p(size))
            except Exception:
                pass
    return ImageFont.load_default()


def fetch_image(url):
    """Фото статті (RGB) або None."""
    from PIL import Image
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "image/webp,image/jpeg,image/png,image/*;q=0.8"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        print("Фото не завантажилось:", url[:120], type(e).__name__)
        return None


def cover(im, w, h):
    """Обрізаємо фото під рамку без спотворень (як CSS cover)."""
    from PIL import Image
    k = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * k + 0.5)),
                    max(h, int(im.height * k + 0.5))), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for word in words:
        t = (cur + " " + word).strip()
        if not cur or draw.textlength(t, font=fnt) <= p(maxw):
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_title(draw, text, maxw, max_lines):
    """Найбільший кегль, з яким заголовок влазить у max_lines рядків."""
    for size in (46, 42, 38, 34, 31, 28):
        fnt = font("unbounded", 700, size)
        lines = wrap(draw, text, fnt, maxw)
        if len(lines) <= max_lines:
            return fnt, lines, size
    lines = lines[:max_lines]
    lines[-1] = lines[-1].rstrip(" ,.:;—-") + "…"
    return fnt, lines, size


# ---------- деталі стилю ----------

def dashed_rect(d, box, color, dash=14, gap=10, width=2):
    x0, y0, x1, y1 = box
    for x in range(x0, x1, dash + gap):
        e = min(x + dash, x1)
        d.line((p(x), p(y0), p(e), p(y0)), fill=color, width=p(width))
        d.line((p(x), p(y1), p(e), p(y1)), fill=color, width=p(width))
    for y in range(y0, y1, dash + gap):
        e = min(y + dash, y1)
        d.line((p(x0), p(y), p(x0), p(e)), fill=color, width=p(width))
        d.line((p(x1), p(y), p(x1), p(e)), fill=color, width=p(width))


def board():
    """Синє поле в клітинку, пунктирна рамка, жовта лінійка в куті."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (p(W), p(H)), BLUE + (255,))
    d = ImageDraw.Draw(img)
    for x in range(0, W + 1, 48):
        d.line((p(x), 0, p(x), p(H)), fill=GRID, width=p(1))
    for y in range(0, H + 1, 48):
        d.line((0, p(y), p(W), p(y)), fill=GRID, width=p(1))
    dashed_rect(d, (20, 20, W - 20, H - 20), STITCH)
    d.polygon([(0, 0), (p(184), 0), (0, p(184))], fill=YELLOW)
    d.polygon([(p(28), p(28)), (p(112), p(28)), (p(28), p(112))], fill=BLUE)
    for x in range(124, 176, 12):                # риски лінійки
        d.line((p(x), 0, p(x), p(10)), fill=YELLOW_DARK, width=p(2))
    return img, d


def paper(d, box):
    """Аркуш у клітинку з дірочками зверху і тінню."""
    x0, y0, x1, y1 = box
    d.rounded_rectangle((p(x0 + 16), p(y0 + 16), p(x1 + 16), p(y1 + 16)),
                        radius=p(8), fill=SHADOW)
    d.rounded_rectangle((p(x0), p(y0), p(x1), p(y1)), radius=p(8),
                        fill=PAPER)
    for x in range(x0 + 28, x1 - 4, 28):
        d.line((p(x), p(y0 + 4), p(x), p(y1 - 4)), fill=PAPER_GRID,
               width=p(1))
    for y in range(y0 + 28, y1 - 4, 28):
        d.line((p(x0 + 4), p(y), p(x1 - 4), p(y)), fill=PAPER_GRID,
               width=p(1))
    for x in range(x0 + 36, x1 - 20, 52):
        d.ellipse((p(x - 10), p(y0 + 18), p(x + 10), p(y0 + 38)), fill=BLUE)


def clip(d, x, y):
    """Рожевий затискач для паперу."""
    d.line((p(x + 22), p(y + 30), p(x + 8), p(y)), fill=WIRE, width=p(6))
    d.line((p(x + 90), p(y + 30), p(x + 104), p(y)), fill=WIRE, width=p(6))
    d.rounded_rectangle((p(x), p(y + 24), p(x + 112), p(y + 76)),
                        radius=p(8), fill=PINK)
    d.rounded_rectangle((p(x), p(y + 24), p(x + 112), p(y + 38)),
                        radius=p(6), fill=PINK_DARK)


def cursor(d, x, y, k=2.2):
    pts = [(p(x + a * k), p(y + b * k)) for a, b in CURSOR]
    d.polygon(pts, fill=YELLOW)
    d.line(pts + [pts[0]], fill=INK, width=p(5), joint="curve")


def sparkle(d, x, y, r, color):
    k = 0.22
    pts = [(0, -r), (r * k, -r * k), (r, 0), (r * k, r * k), (0, r),
           (-r * k, r * k), (-r, 0), (-r * k, -r * k)]
    d.polygon([(p(x + a), p(y + b)) for a, b in pts], fill=color)


def folder(d, x, y, k=1.0):
    def q(a, b):
        return (p(x + a * k), p(y + b * k))
    d.polygon([q(0, 16), q(44, 16), q(56, 28), q(112, 28), q(112, 120),
               q(0, 120)], fill=YELLOW_DARK)
    d.rectangle((*q(12, 6), *q(92, 90)), fill=WHITE)
    d.polygon([q(0, 44), q(112, 44), q(112, 120), q(0, 120)], fill=YELLOW)


def tape(img, cx, cy, w, h, angle):
    """Напівпрозорий жовтий скотч."""
    from PIL import Image
    layer = Image.new("RGBA", (p(w), p(h)), YELLOW + (215,))
    layer = layer.rotate(angle, expand=True, resample=Image.BICUBIC)
    img.paste(layer, (p(cx) - layer.width // 2, p(cy) - layer.height // 2),
              layer)


def tilted_text(img, x, y, text, fnt, fill, angle):
    """Рукописна позначка під невеликим кутом."""
    from PIL import Image, ImageDraw
    l, t, r, b = ImageDraw.Draw(img).textbbox((0, 0), text, font=fnt)
    layer = Image.new("RGBA", (r - l + p(24), b - t + p(24)), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((p(12) - l, p(12) - t), text, font=fnt,
                               fill=fill)
    layer = layer.rotate(angle, expand=True, resample=Image.BICUBIC)
    img.paste(layer, (p(x), p(y)), layer)


def polaroid(img, photo, cx, cy, caption, w=340, h=380, angle=-4):
    """Фото статті в білій рамці «полароїд» з тінню, трохи під кутом."""
    from PIL import Image, ImageDraw
    fw, fh, pad = p(w), p(h), p(16)
    frame = Image.new("RGBA", (fw, fh), WHITE + (255,))
    frame.paste(cover(photo, fw - 2 * pad, fh - pad - p(64)), (pad, pad))
    ImageDraw.Draw(frame).text((fw // 2, fh - p(34)), caption,
                               font=font("caveat", 600, 30), fill=MUTED,
                               anchor="mm")
    shadow = Image.new("RGBA", (fw, fh), SHADOW + (150,))
    frame = frame.rotate(angle, expand=True, resample=Image.BICUBIC)
    shadow = shadow.rotate(angle, expand=True, resample=Image.BICUBIC)
    x, y = p(cx) - frame.width // 2, p(cy) - frame.height // 2
    img.paste(shadow, (x + p(14), y + p(14)), shadow)
    img.paste(frame, (x, y), frame)


def pills(d, tag, handle):
    f = font("onest", 400, 22)
    for text, x in (("Все про дизайн", 48), (tag, 515), (handle, 982)):
        d.rounded_rectangle((p(x), p(636), p(x + 250), p(684)), radius=p(24),
                            outline=PILL, width=p(2))
        d.text((p(x + 125), p(660)), text, font=f, fill=WHITE, anchor="mm")


def save(img, path):
    from PIL import Image
    img.convert("RGB").resize((W, H), Image.LANCZOS).save(
        path, "JPEG", quality=92, subsampling=0)


# ---------- картки ----------

def news_card(label, title, meta, photo_url, out_path, tag="#новини",
              handle="@Her_Design", note="деталі — в пості"):
    """Картка новини або дизайнера: мітка рубрики, джерело й дата,
    заголовок, фото статті в рамці. False — якщо не вийшло."""
    try:
        from PIL import ImageDraw
    except Exception as e:
        print("Немає Pillow:", e)
        return False
    try:
        img, d = board()
        photo = fetch_image(photo_url)
        paper(d, (150, 80, 1090, 600))
        maxw = 470 if photo else 820
        if photo:
            polaroid(img, photo, 862, 336, meta.split(" · ")[0])
            tape(img, 862, 156, 130, 34, 8)
        d = ImageDraw.Draw(img)
        clip(d, 268, 38)
        lf = font("unbounded", 700, 24)
        lw = d.textlength(label, font=lf) / S
        d.rounded_rectangle((p(200), p(146), p(240 + lw), p(198)), radius=p(8),
                            fill=BLUE)
        d.text((p(220 + lw / 2), p(172)), label, font=lf, fill=WHITE,
               anchor="mm")
        d.text((p(200), p(226)), meta, font=font("onest", 400, 22),
               fill=MUTED, anchor="lm")
        tf, lines, size = fit_title(d, title, maxw, 4)
        y = 258
        for line in lines:
            d.text((p(200), p(y)), line, font=tf, fill=INK)
            y += size * 1.22
        tilted_text(img, 196, max(y + 14, 470), note,
                    font("caveat", 600, 36), PINK, 3)
        d = ImageDraw.Draw(img)
        cursor(d, 690 if photo else 990, 470 if photo else 500)
        folder(d, 1124, 250, 1.1)
        sparkle(d, 1184, 118, 22, PINK)
        sparkle(d, 84, 380, 18, WHITE)
        sparkle(d, 1200, 560, 16, YELLOW)
        pills(d, tag, handle)
        save(img, out_path)
        return True
    except Exception as e:
        print("Картка не намалювалась:", type(e).__name__, e)
        return False


# ---------- шрифт дня і вікторина ----------

TEXT_DARK = (27, 27, 47)
_gfonts = {}


def tmp_path(kind):
    import time
    return os.path.join(tempfile.gettempdir(),
                        f"hd_{kind}_{int(time.time() * 1000)}.jpg")


def gfont(family, weight=400):
    """TTF конкретного шрифту з Google Fonts (для шрифту дня і вікторини)."""
    if (family, weight) in _gfonts:
        return _gfonts[(family, weight)]
    path = None
    try:
        url = ("https://fonts.googleapis.com/css?family="
               + family.replace(" ", "+") + f":{weight}"
               + "&subset=latin,latin-ext,cyrillic,cyrillic-ext")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/4.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            css = r.read().decode("utf-8", "replace")
        u = re.search(r"url\((https://[^)]+\.ttf)\)", css)
        if u:
            path = os.path.join(tempfile.gettempdir(), "hd_g_"
                                + re.sub(r"\W+", "_", family) + f"_{weight}.ttf")
            if not os.path.exists(path):
                with urllib.request.urlopen(u.group(1), timeout=20) as r:
                    data = r.read()
                with open(path, "wb") as f:
                    f.write(data)
        else:
            print("Google Fonts не дав TTF для", family)
    except Exception as e:
        print("Шрифт", family, "не скачався:", type(e).__name__)
        path = None
    _gfonts[(family, weight)] = path
    return path


def fit_font(draw, path, text, maxw, start, minsize=24):
    """Найбільший кегль шрифту path, з яким text влазить у maxw."""
    from PIL import ImageFont
    size = start
    while size > minsize:
        f = ImageFont.truetype(path, p(size))
        if draw.textlength(text, font=f) <= p(maxw):
            return f, size
        size -= 4
    return ImageFont.truetype(path, p(minsize)), minsize


def hex_rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def sheet(label):
    """Дошка, аркуш, затискач і мітка рубрики — основа карток рубрик."""
    img, d = board()
    paper(d, (150, 80, 1090, 600))
    clip(d, 268, 38)
    lf = font("unbounded", 700, 24)
    lw = d.textlength(label, font=lf) / S
    d.rounded_rectangle((p(200), p(146), p(240 + lw), p(198)), radius=p(8),
                        fill=BLUE)
    d.text((p(220 + lw / 2), p(172)), label, font=lf, fill=WHITE, anchor="mm")
    return img, d


def finish(img, tag, handle, out_path, cur=(1000, 470)):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    cursor(d, *cur)
    folder(d, 1124, 250, 1.1)
    sparkle(d, 1184, 118, 22, PINK)
    sparkle(d, 84, 380, 18, WHITE)
    sparkle(d, 1200, 560, 16, YELLOW)
    pills(d, tag, handle)
    save(img, out_path)


def chips(d, x, y, items):
    f = font("onest", 600, 20)
    for text, fill, color in items:
        w = d.textlength(text, font=f) / S + 36
        d.rounded_rectangle((p(x), p(y), p(x + w), p(y + 40)), radius=p(20),
                            fill=fill)
        d.text((p(x + w / 2), p(y + 20)), text, font=f, fill=color,
               anchor="mm")
        x += w + 12
    return x


def font_card(family, font_path, items, out_path, handle="@Her_Design",
              sample="Аа Бб Ґґ Її Єє", line=None, label="ШРИФТ ДНЯ",
              tag="#шрифт_дня"):
    """Шрифт дня: назва, великий зразок і панграма самим шрифтом, чипи."""
    try:
        from PIL import ImageFont
        img, d = sheet(label)
        d.text((p(200), p(232)), family, font=font("unbounded", 700, 30),
               fill=INK, anchor="lm")
        sf, size = fit_font(d, font_path, sample, 840, 108)
        d.text((p(200), p(262)), sample, font=sf, fill=TEXT_DARK)
        y = 262 + size * 1.35
        if line:
            lf = ImageFont.truetype(font_path, p(32))
            for ln in wrap(d, line, lf, 840)[:2]:
                d.text((p(200), p(y)), ln, font=lf, fill=MUTED)
                y += 46
        chips(d, 200, 530, items)
        finish(img, tag, handle, out_path, cur=(1010, 430))
        return True
    except Exception as e:
        print("Картка шрифту не намалювалась:", type(e).__name__, e)
        return False


def quiz_card(label, question, out_path, colors=None, font_path=None,
              sample=None, line=None, handle="@Her_Design", tag="#вікторина"):
    """Вікторина: питання і або кольори бренду (без кодів), або напис
    загаданим шрифтом."""
    try:
        from PIL import ImageDraw, ImageFont
        img, d = sheet(label)
        d.text((p(200), p(236)), question, font=font("unbounded", 700, 36),
               fill=INK, anchor="lm")
        tilted_text(img, 700, 112, "відповідай в опитуванні",
                    font("caveat", 600, 36), PINK, 4)
        d = ImageDraw.Draw(img)
        if colors:
            n, gap, h = len(colors), 22, 250
            w = min(190, (840 - gap * (n - 1)) / n)
            x = 200 + (840 - n * w - gap * (n - 1)) / 2   # по центру
            for i, c in enumerate(colors):
                d.rectangle((p(x + 8), p(296), p(x + w + 8), p(288 + h + 8)),
                            fill=SHADOW)
                d.rectangle((p(x), p(288), p(x + w), p(288 + h)), fill=WHITE,
                            outline=(214, 219, 232), width=p(2))
                d.rectangle((p(x + 10), p(298), p(x + w - 10), p(288 + h - 56)),
                            fill=hex_rgb(c), outline=(214, 219, 232),
                            width=p(1))
                d.text((p(x + 18), p(288 + h - 28)), str(i + 1),
                       font=font("caveat", 600, 30), fill=MUTED, anchor="lm")
                x += w + gap
        else:
            sf, size = fit_font(d, font_path, sample, 840, 140)
            d.text((p(200), p(282)), sample, font=sf, fill=TEXT_DARK)
            if line:
                lf = ImageFont.truetype(font_path, p(40))
                d.text((p(200), p(282 + size * 1.4)), line, font=lf,
                       fill=MUTED)
        finish(img, tag, handle, out_path, cur=(1030, 500))
        return True
    except Exception as e:
        print("Картка вікторини не намалювалась:", type(e).__name__, e)
        return False


def palette_card(name, colors, out_path, handle="@Her_Design",
                 tag="#палітра"):
    """Палітра дня: назва і 5 кольорів-«свотчів» із HEX і назвою."""
    try:
        img, d = sheet("ПАЛІТРА ДНЯ")
        d.text((p(200), p(236)), name, font=font("unbounded", 700, 34),
               fill=INK, anchor="lm")
        n, gap, h = len(colors), 20, 262
        w = (840 - gap * (n - 1)) / n
        x = 200
        hf, nf = font("onest", 600, 20), font("onest", 400, 16)
        for hx, nm in colors:
            d.rectangle((p(x + 8), p(286), p(x + w + 8), p(278 + h + 8)),
                        fill=SHADOW)
            d.rectangle((p(x), p(278), p(x + w), p(278 + h)), fill=WHITE,
                        outline=(214, 219, 232), width=p(2))
            d.rectangle((p(x + 8), p(286), p(x + w - 8), p(278 + h - 78)),
                        fill=hex_rgb(hx), outline=(214, 219, 232), width=p(1))
            d.text((p(x + 12), p(278 + h - 52)), hx, font=hf, fill=INK,
                   anchor="lm")
            label = nm
            while len(label) > 1 and d.textlength(label, font=nf) > p(w - 22):
                label = label[:-1]
            d.text((p(x + 12), p(278 + h - 24)), label, font=nf, fill=MUTED,
                   anchor="lm")
            x += w + gap
        finish(img, tag, handle, out_path, cur=(1040, 470))
        return True
    except Exception as e:
        print("Картка палітри не намалювалась:", type(e).__name__, e)
        return False
