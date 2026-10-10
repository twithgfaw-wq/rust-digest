# -*- coding: utf-8 -*-
"""
Аватарки @Her_Design — варіанти 9 («папка з роботами») і 10 («клавіша Д»),
які обрали 10.10. SVG малюємо в PNG 1024×1024 через Chrome на GitHub;
шрифти Unbounded і Playfair Display вбудовуємо з Google Fonts, щоб усе
було як на макеті. PNG кладемо в папку avatars/ репозиторію.

Режими (DESIGN_AVATAR): show — намалювати обидві й показати в лозі;
9 або 10 — поставити цю аватарку на канал (setChatPhoto; бот має бути
адміном із правом змінювати профіль каналу).
"""
import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import rust_digest_bot as bot

FONT_CSS = ("https://fonts.googleapis.com/css?family=Unbounded:700,900|"
            "Playfair+Display:700&subset=latin,cyrillic")
OUT_DIR = "avatars"

BG = """<defs><pattern id="g" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" fill="none" stroke="#5C8BF0" stroke-width="1.2"/></pattern><pattern id="p" width="15" height="15" patternUnits="userSpaceOnUse"><path d="M15 0H0V15" fill="none" stroke="#DCE3F2" stroke-width="1"/></pattern></defs><rect width="400" height="400" fill="#2D64DE"/><rect width="400" height="400" fill="url(#g)"/>"""
STAR = "M0 -10 C2 -2 2 -2 10 0 C2 2 2 2 0 10 C-2 2 -2 2 -10 0 C-2 -2 -2 -2 0 -10Z"
CURSOR = """<path d="M2 2 L2 32 L10 25 L15 36 L21 33 L16 23 L26 23 Z" fill="#1E3F9E"/><path d="M0 0 L0 30 L8 23 L13 34 L19 31 L14 21 L24 21 Z" fill="#F7C843" stroke="#1E3F9E" stroke-width="2.2" stroke-linejoin="round"/><path d="M3 6 L3 18" stroke="#FFF3C4" stroke-width="2" stroke-linecap="round"/>"""
FOLDER = "M66 132 Q66 118 80 118 H150 Q160 118 166 126 L176 140 H322 Q336 140 336 154 V316 Q336 330 322 330 H80 Q66 330 66 316 Z"


def star(x, y, r, color):
    return (f'<path transform="translate({x},{y}) scale({r / 10})" d="{STAR}" '
            f'fill="{color}" stroke="#1E3F9E" stroke-width="{12 / r:.3f}"/>')


SVG = {
    "9": BG + f"""<path d="{FOLDER}" fill="#1E3F9E" transform="translate(10,10)"/>
<path d="{FOLDER}" fill="#D9A21B" stroke="#1E3F9E" stroke-width="4"/>
<g transform="rotate(8 250 170)"><rect x="176" y="84" width="128" height="150" rx="5" fill="#EE5BA9" stroke="#1E3F9E" stroke-width="3"/><circle cx="240" cy="140" r="30" fill="#F7C843" stroke="#1E3F9E" stroke-width="3"/><rect x="198" y="182" width="84" height="10" rx="5" fill="#fff"/></g>
<g transform="rotate(-7 160 170)"><rect x="92" y="76" width="140" height="160" rx="5" fill="#F5F3EE" stroke="#1E3F9E" stroke-width="3"/><rect x="92" y="76" width="140" height="160" rx="5" fill="url(#p)"/><text x="162" y="160" text-anchor="middle" font-family="Playfair Display" font-weight="700" font-size="66" fill="#1E3F9E">Aa</text><rect x="110" y="178" width="100" height="8" rx="4" fill="#2D64DE"/><rect x="110" y="194" width="70" height="8" rx="4" fill="#9DB4F2"/></g>
<g transform="translate(120,46) scale(0.85)"><path d="M16 22 C10 8 6 4 8 0 M58 22 C64 8 68 4 66 0" stroke="#3A3A4A" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M16 22 C12 10 9 6 10 2" stroke="#9AA3B5" stroke-width="2" fill="none"/><rect x="2" y="20" width="74" height="40" rx="7" fill="#D63F8F"/><rect y="16" width="74" height="40" rx="7" fill="#EE5BA9" stroke="#1E3F9E" stroke-width="2.5"/><rect x="8" y="21" width="58" height="8" rx="4" fill="#F7A3CF"/></g>
<path d="M58 196 Q56 182 70 182 H330 Q344 182 342 196 L330 318 Q328 332 314 332 H86 Q72 332 70 318 Z" fill="#F7C843" stroke="#1E3F9E" stroke-width="4"/>
<path d="M74 194 H326" stroke="#FFE08A" stroke-width="7" stroke-linecap="round"/>
<rect x="104" y="226" width="192" height="76" rx="10" fill="#fff" stroke="#1E3F9E" stroke-width="3"/>
<text x="200" y="257" text-anchor="middle" font-family="Unbounded" font-weight="700" font-size="20" fill="#1E3F9E">ВСЕ ПРО</text><text x="200" y="289" text-anchor="middle" font-family="Unbounded" font-weight="900" font-size="25" fill="#EE5BA9">ДИЗАЙН</text>
<g transform="translate(292,284) scale(1.8)">{CURSOR}</g>
{star(338, 92, 16, "#fff")}{star(66, 92, 12, "#F7C843")}{star(60, 350, 10, "#EE5BA9")}""",
    "10": BG + f"""<circle cx="200" cy="200" r="172" fill="none" stroke="#A9C1F7" stroke-width="3" stroke-dasharray="12 9"/>
<rect x="102.8" y="111.44" width="216" height="216" rx="34.56" fill="#1F4DB8"/>
<rect x="92" y="92" width="216" height="216" rx="34.56" fill="#BFD0F7" stroke="#1E3F9E" stroke-width="5.4"/>
<rect x="113.6" y="101.72" width="172.8" height="166.32" rx="27.65" fill="#F5F3EE" stroke="#1E3F9E" stroke-width="3.24"/>
<path d="M137.79 114.68 H262.21" stroke="#fff" stroke-opacity="0.75" stroke-width="6.48" stroke-linecap="round"/>
<text x="200" y="234.56" text-anchor="middle" font-family="Unbounded" font-weight="900" font-size="108" fill="#1E3F9E">Д</text>
<text x="128.72" y="144.92" font-family="Unbounded" font-weight="700" font-size="28.08" fill="#5B6A8E">L</text>
{star(326, 96, 20, "#EE5BA9")}{star(78, 306, 13, "#F7C843")}{star(334, 300, 10, "#fff")}
<g transform="translate(262,250) scale(2.3)">{CURSOR}</g>""",
}


def font_faces():
    """Шрифти вбудовуємо прямо в сторінку — Chrome не чекає мережі."""
    req = urllib.request.Request(FONT_CSS, headers={"User-Agent": "Mozilla/4.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        css = r.read().decode("utf-8", "replace")
    faces = []
    for block in css.split("@font-face")[1:]:
        fam = re.search(r"font-family:\s*'([^']+)'", block)
        w = re.search(r"font-weight:\s*(\d+)", block)
        u = re.search(r"url\((https://[^)]+\.ttf)\)", block)
        if fam and w and u:
            with urllib.request.urlopen(u.group(1), timeout=20) as r:
                data = base64.b64encode(r.read()).decode()
            faces.append(f"@font-face{{font-family:'{fam.group(1)}';"
                         f"font-weight:{w.group(1)};src:url(data:font/ttf;"
                         f"base64,{data}) format('truetype');}}")
    print("Шрифти для аватарок:", len(faces))
    return "\n".join(faces)


def render(key, faces):
    chrome = (shutil.which("google-chrome") or shutil.which("chromium-browser")
              or shutil.which("chromium"))
    if not chrome:
        print("Chrome не знайдено")
        return None
    tmp = tempfile.mkdtemp()
    page = os.path.join(tmp, f"a{key}.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html><head><meta charset="utf-8"><style>'
                + faces + "html,body{margin:0;background:#2D64DE}"
                "svg{display:block}</style></head><body>"
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"'
                ' width="1024" height="1024">' + SVG[key] + "</svg></body></html>")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.abspath(os.path.join(OUT_DIR, f"her_design_{key}.png"))
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--window-size=1024,1024", "--virtual-time-budget=5000",
                    f"--screenshot={out}", "file://" + page],
                   check=True, timeout=120, capture_output=True)
    print(f"Аватарка {key}: {out} ({os.path.getsize(out) // 1024} КБ)")
    return out


def dump(path):
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((720, 720), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    print("CARD_B64:" + base64.b64encode(buf.getvalue()).decode())


def set_photo(token, chat, path):
    """Ставимо аватарку на канал, якщо в бота є право змінювати профіль."""
    base = f"https://api.telegram.org/bot{token}"
    me = bot.http_get_json(f"{base}/getMe")["result"]
    q = urllib.parse.urlencode({"chat_id": chat, "user_id": me["id"]})
    m = bot.http_get_json(f"{base}/getChatMember?{q}")["result"]
    print("Право змінювати профіль каналу:", m.get("can_change_info"))
    if not m.get("can_change_info"):
        print("Немає права — аватарку не ставлю.")
        return False
    with open(path, "rb") as f:
        img = f.read()
    boundary = "----HerDesign" + str(int(time.time() * 1000))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"chat_id\"\r\n\r\n{chat}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
            f"filename=\"avatar.png\"\r\nContent-Type: image/png\r\n\r\n"
            ).encode("utf-8") + img + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{base}/setChatPhoto", data=body,
        headers={"User-Agent": bot.UA,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = r.read().decode("utf-8", "replace")
        print("Telegram:", res[:200])
        return '"ok":true' in res
    except urllib.error.HTTPError as e:
        print("Telegram відповів", e.code, e.read().decode("utf-8", "replace")[:200])
        return False


def run(token, chat, mode):
    faces = font_faces()
    keys = ["9", "10"] if mode == "show" else [mode]
    for key in keys:
        if key not in SVG:
            print("Немає аватарки", key)
            continue
        path = render(key, faces)
        if not path:
            continue
        dump(path)
        if mode != "show":
            set_photo(token, chat, path)
