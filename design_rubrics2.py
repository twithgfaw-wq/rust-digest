# -*- coding: utf-8 -*-
"""
Вечірні рубрики @Her_Design — о 17:00 за Києвом, по днях тижня:
  пн, нд 🧩 Плагін Figma — з перевіреного списку популярних плагінів Figma
         Community (назва, автор, ціна й кількість користувачів — як на
         сторінках Figma Community станом на 11.10.2026);
  ср     🧩 Фішка Figma — нова функція з офіційних Figma Release Notes
         (текст проходить фактчек);
  вт     🤖 Промпт: фото рекламного продукту;
  чт     🤖 Промпт: відео рекламного продукту;
  пт     🎬 Фільм про дизайн, сб 🎮 Гра для дизайнера — з перевіреного
         списку (рік і автори звірені).
І шрифт дня з Fontshare (кожен третій день, замість Google Fonts):
безкоштовний для особистого й комерційного використання (ITF FFL).
"""
import base64
import html
import json
import random
import re
import time
import urllib.request

import cs2_ai as ai
import design_cards as cards
import design_rubrics as rub

LIVE = False                     # увімкнемо після схвалення прикладів
EVENING_HOUR = 17
WINDOW_H = 4
EVENING = {0: "plugin", 1: "prompt_photo", 2: "figma_tip", 3: "prompt_video",
           4: "film", 5: "game", 6: "plugin"}
FIGMA = "https://www.figma.com/community/plugin/"
FS_API = "https://api.fontshare.com/v2/fonts"
FIGMA_NOTES = "https://www.figma.com/release-notes/feed/atom.xml"

# Плагіни: (id/slug, назва, автор, ціна в Figma Community, користувачів,
# офіційний опис зі сторінки, тема). Дані зібрані 11.10.2026.
PLUGINS = [
    ("735098390272716381/iconify", "Iconify", "Vjacheslav Trushkin", "free",
     "4,67 млн", "All popular open source icon sets in one plugin. Emojis too.",
     "іконки"),
    ("738454987945972471/unsplash", "Unsplash", "Unsplash", "free", "3,77 млн",
     "Insert beautiful images from Unsplash into your designs.", "фото"),
    ("842128343887142055/figma-to-code-html-tailwind-flutter-swiftui",
     "Figma to Code (HTML, Tailwind, Flutter, SwiftUI)", "Bernardo Ferrari",
     "free", "2,38 млн", "Code Conversion Made Easy: Figma to Web & Apps",
     "код"),
    ("997643096679511216/icons8-background-remover", "Icons8 Background Remover",
     "Icons8 Team", "free", "1,34 млн",
     "Remove background from one or many images at once!", "фото"),
    ("736000994034548392/lorem-ipsum-by-divriots", "Lorem Ipsum", "divRIOTS",
     "free", "1,21 млн", "Fill your designs with placeholders in a click: "
     "text, images and even data!", "контент"),
    ("731627216655469013/content-reel", "Content Reel", "Eugene Gavriloff",
     "free", "1,12 млн", "Design layouts more efficiently by pulling text "
     "strings, images, and icons.", "контент"),
    ("744047966581015514/feather-icons", "Feather Icons", "Cole Bemis", "free",
     "1,04 млн", "Quick access to Feather icons in Figma", "іконки"),
    ("809860933081065308/lottiefiles-discover-create-export-lottie-animations",
     "LottieFiles", "LottieFiles", "free", "1,02 млн",
     "Animate Your Designs with Lottie Animations", "анімація"),
    ("1183568094858533791/iconoir-icon-library-by-iconduck",
     "Iconoir Icon Library", "Iconduck", "free", "660 тис.",
     "Iconoir Icon Set is an open source library of 1,188 icons. Free to use "
     "in all your designs!", "іконки"),
    ("819335598581469537/clay-mockups-3d", "Clay Mockups 3D", "Hamish", "free",
     "626 тис.", "Create mockups with 3D clay-style device models. Customize "
     "the color, camera angle, and device model.", "мокапи"),
    ("732603254453395948/stark-contrast-accessibility-ai-checker",
     "Stark — Contrast & Accessibility Checker", "Stark", "free", "599 тис.",
     "Fix Color Contrast and Typography issues and add WCAG annotations.",
     "доступність"),
    ("731451122947612104/charts", "Charts", "Sam Mason de Caires", "free",
     "592 тис.", "Charts allows you to generate charts that can be added and "
     "edited within your Figma document.", "діаграми"),
    ("748533339900865323/contrast", "Contrast", "WillowTree", "free",
     "528 тис.", "Quickly check and scan for contrast issues on gradients, "
     "images, blends, and fills.", "доступність"),
    ("740832935938649295/color-palettes-colorsinspo-color-accessibility-tools",
     "Color Palettes (Colorsinspo)", "Hexorial Studio", "free", "451 тис.",
     "A free suite of integrated Color & Accessibility tools.", "колір"),
    ("1286792998372727741/color-wheel-palette-generator",
     "Color wheel palette generator", "Figma Community", "free", "407 тис.",
     "Generate color palettes", "колір"),
    ("1009780509659307229/3d-transformer", "3D Transformer", "Jim Raptis",
     "free", "357 тис.", "Turn a frame into a beautiful 3D mockup", "мокапи"),
    ("898620911119764089/phosphor-icons", "Phosphor Icons", "Phosphor Icons",
     "free", "325 тис.", "A flexible icon family for interfaces, diagrams, "
     "presentations — whatever, really.", "іконки"),
    ("733159460536249875/a11y-color-contrast-checker",
     "A11y — Color Contrast Checker", "Kelly Gorr", "free", "323 тис.",
     "Text color accessibility", "доступність"),
    ("739825414752646970/typescales", "Typescales", "Marvin Bruns", "free",
     "316 тис.", "Quickly generate a simple typescale/modular scale.",
     "типографіка"),
    ("1024452006068794933/foundation-color-generator",
     "Foundation: Color Generator", "Jorge Fernandes", "free", "269 тис.",
     "Create Color Palettes based on great Design Systems like: Material, "
     "Atlassian, Orbit and Ant Design.", "колір"),
    ("939567362549682242/lucide-icons", "Lucide Icons", "Eric Fennis", "free",
     "259 тис.", "Beautiful & consistent icons made by the Lucide community.",
     "іконки"),
    ("820660579767995949/styler", "Styler", "Andrei Iancu", "free", "237 тис.",
     "Bulk management of styles based on layer properties.", "порядок у файлі"),
    ("731271836271143349/rename-it", "Rename It", "Rodrigo Soares", "free",
     "200 тис.", "Keep your Figma files organized, batch rename layers and "
     "frames.", "порядок у файлі"),
    ("967802396210455992/typescale", "Typescale", "Sam Smith", "free",
     "119 тис.", "Harmonious typographic scales", "типографіка"),
    ("965313760136371738/typography-style-guide", "Typography Style Guide",
     "hiloki", "free", "116 тис.", "Create the Typography Style Guide page in "
     "one shot.", "типографіка"),
    ("759472336242530542/text-styles-generator", "Text Styles Generator",
     "Vadim Pleshkov", "free", "111 тис.",
     "Generate local text styles out of text layers", "типографіка"),
    ("853905984020840743/tailwind-color-palettes-tailwindcss-import-export",
     "Tailwind Color Palettes", "Varun", "free", "65,5 тис.",
     "Add TailwindCSS colors to your figma file in few clicks", "колір"),
    ("1057630145566901048/renamed", "Renamed", "Pecherin Maxim", "free",
     "52,7 тис.", "Rename, transform and organize layer names of the entire "
     "page, a selection, or a certain layer type.", "порядок у файлі"),
    ("1134018716847999330/auto-documentation", "Auto Documentation",
     "Eddy Salzmann", "free", "47,4 тис.",
     "Automatically document your colors, fonts and variables", "дизайн-система"),
    ("1321082150993038377/font-collections-google-fonts-variable-fonts-pairing",
     "Font Collections", "grisha", "free", "42,8 тис.",
     "Font Management, Font Pairs and Typography", "типографіка"),
    ("1464228451812548879/bender-bend-your-text-into-an-arc", "Bender",
     "Jeongsu Cha", "free", "24,2 тис.", "Bend Your Text into an Arc!",
     "типографіка"),
    ("1247165533022224611/image-to-color-palette", "Image to Color Palette",
     "Wilson Hou", "free", "18,8 тис.", "Transform your favorite images into "
     "design-ready palettes with a single click.", "колір"),
    ("1159123024924461424/html-to-design-by-divriots-import-websites-to-figma-designs-web-html-css",
     "html.to.design", "divRIOTS", "paid", "2,67 млн",
     "Convert any website into editable Figma designs.", "імпорт"),
    ("738992712906748191/remove-bg", "Remove BG", "Aaron Iker", "paid",
     "1,72 млн", "Remove the background of images automatically with just a "
     "single click.", "фото"),
    ("817043359134136295/mockup-plugin-devices-mockups-print-mockups-branding-mockups",
     "Mockup Plugin", "ls.graphics", "paid", "1,58 млн",
     "Devices mockups, print mockups, branding mockups.", "мокапи"),
    ("762070688792833472/arc-bend-your-type", "ARC — Bend your type!", "Unfold",
     "paid", "1,1 млн", "Curve your text upward, downward or into a circle",
     "типографіка"),
    ("733902567457592893/autoflow", "Autoflow", "David Zhao", "paid",
     "1,07 млн", "Automagically draw flow arrows! Create user flows and "
     "diagrams in a hand-drawn or minimalist style.", "UX"),
    ("767379019764649932/clean-document", "Clean Document", "Yuan Qing Lim",
     "paid", "126 тис.", "Automagically organize and clean up your Figma "
     "document", "порядок у файлі"),
]

# Фільми й серіали про дизайн: (назва, рік, хто, формат, опис).
FILMS = [
    ("Helvetica", "2007", "реж. Gary Hustwit", "документальний фільм",
     "Про найвідоміший шрифт XX століття: звідки взялася Helvetica і чому вона "
     "всюди — від вивісок до логотипів. Говорять і ті дизайнери, які її "
     "люблять, і ті, хто її критикує."),
    ("Objectified", "2009", "реж. Gary Hustwit", "документальний фільм",
     "Про промисловий дизайн і речі, якими ми користуємося щодня, — розмови з "
     "дизайнерами, серед яких Dieter Rams і Jonathan Ive."),
    ("Urbanized", "2011", "реж. Gary Hustwit", "документальний фільм",
     "Про дизайн міст: як вулиці, транспорт і публічні простори впливають на "
     "життя людей."),
    ("Rams", "2018", "реж. Gary Hustwit", "документальний фільм",
     "Портрет Dieter Rams — дизайнера Braun і автора «десяти принципів "
     "хорошого дизайну». Музику написав Brian Eno."),
    ("Abstract: The Art of Design", "2017–2019", "Netflix",
     "документальний серіал",
     "Кожна серія — про одного дизайнера: серед героїв графічна дизайнерка "
     "Paula Scher, ілюстратор Christoph Niemann і дизайнер взуття Tinker "
     "Hatfield. Два сезони."),
    ("Eames: The Architect and the Painter", "2011",
     "реж. Jason Cohn і Bill Jersey", "документальний фільм",
     "Історія Charles і Ray Eames — подружжя, яке створило знамениті крісла, "
     "фільми й виставки середини XX століття."),
    ("Linotype: The Film", "2012", "реж. Douglas Wilson",
     "документальний фільм",
     "Про лінотип — машину, що відливала цілі рядки металевого шрифту і "
     "змінила друк газет і книжок."),
    ("Graphic Means", "2017", "реж. Briar Levit", "документальний фільм",
     "Як робили графічний дизайн до комп'ютерів: фотонабір, ручна верстка, "
     "перебивні літери й світлові столи."),
    ("Milton Glaser: To Inform and Delight", "2008", "реж. Wendy Keys",
     "документальний фільм",
     "Портрет Milton Glaser — автора логотипа I ❤ NY і знаменитого постера з "
     "Bob Dylan."),
    ("Design Canada", "2018", "реж. Greg Durrell", "документальний фільм",
     "Про те, як у 1960–70-х Канада створила свою візуальну мову — від "
     "прапора з кленовим листком до айдентики державних компаній."),
    ("Art & Copy", "2009", "реж. Doug Pray", "документальний фільм",
     "Про людей, які придумали найвідоміші рекламні кампанії, — зокрема "
     "слоган Nike «Just Do It»."),
    ("Typeface", "2009", "реж. Justine Nagan", "документальний фільм",
     "Про музей дерев'яного шрифту Hamilton у Вісконсині й людей, які досі "
     "друкують дерев'яними літерами."),
    ("Sign Painters", "2013", "реж. Faythe Levine і Sam Macon",
     "документальний фільм",
     "Про майстрів, які малюють вивіски вручну, — ремесло, що повертається на "
     "вулиці міст."),
    ("The Genius of Design", "2010", "BBC Two", "документальний серіал",
     "П'ять серій про історію дизайну речей — від промислової революції до "
     "наших днів."),
]

# Ігри, корисні дизайнеру: (назва, рік, студія, опис).
GAMES = [
    ("Type:Rider", "2013", "Cosmografik і ARTE",
     "Платформер, де ти — двокрапка, що подорожує історією шрифтів: від "
     "готичного письма до піксельних шрифтів."),
    ("Typoman", "2015", "Brainseed Factory",
     "Головоломка-платформер: герой складений з літер, а слова змінюють світ "
     "навколо."),
    ("Mini Metro", "2015", "Dinosaur Polo Club",
     "Мінімалістична гра про побудову схеми метро — інформаційний дизайн у "
     "русі."),
    ("Monument Valley", "2014", "ustwo games",
     "Головоломка з неможливою архітектурою в дусі Ешера й дуже вивіреною "
     "палітрою."),
    ("Townscaper", "2020", "Oskar Stålberg",
     "Іграшка-конструктор: клацаєш — і виростає барвисте приморське містечко. "
     "Чиста радість форми й кольору."),
    ("Unpacking", "2021", "Witch Beam",
     "Розпаковуєш речі людини в нових квартирах і з того, що й де лежить, "
     "відчитуєш історію її життя."),
    ("Gris", "2018", "Nomada Studio",
     "Платформер-акварель: у світ поступово повертаються кольори, а з ними — "
     "нові можливості."),
    ("Hue", "2016", "Fiddlesticks",
     "Головоломка, де ти змінюєш колір фону — і предмети того самого кольору "
     "зникають."),
    ("Chants of Sennaar", "2023", "Rundisc",
     "Розшифровуєш мови й знаки різних народів — гра про системи символів і "
     "піктограми."),
    ("Behind the Frame: The Finest Scenery", "2021", "Silver Lining Studio",
     "Коротка історія про художницю, яка готує картину до виставки; виглядає "
     "як мальований анімаційний фільм."),
    ("Assemble with Care", "2019", "ustwo games",
     "Ремонтуєш старі речі — програвачі, годинники, камери — і через них "
     "дізнаєшся історії людей."),
    ("Florence", "2018", "Mountains",
     "Інтерактивна історія кохання, де кожна механіка — частина візуальної "
     "розповіді."),
    ("Old Man's Journey", "2017", "Broken Rules",
     "Подорож мальованими пейзажами, які ти зсуваєш шарами, щоб прокласти "
     "шлях."),
    ("shapez", "2020", "Tobias Springer",
     "Будуєш фабрику, яка ріже, фарбує й складає геометричні фігури, — гра "
     "про системи й форму."),
    ("Pentiment", "2022", "Obsidian Entertainment",
     "Детектив у стилі середньовічних рукописів: шрифт реплік залежить від "
     "того, хто говорить."),
]

PRODUCTS = ["флакон парфумів", "кросівки", "бездротові навушники",
            "банка холодної кави", "крем для обличчя", "наручний годинник",
            "пляшка крафтового соку", "плитка шоколаду", "свічка в склі",
            "шкіряний гаманець", "сонцезахисні окуляри", "баночка меду",
            "помада", "пляшка вина", "пачка зернової кави", "рюкзак"]
EN_LANGS = {"English": "англійська", "German": "німецька",
            "French": "французька", "Spanish": "іспанська",
            "Polish": "польська", "Czech": "чеська", "Turkish": "турецька",
            "Italian": "італійська", "Ukrainian": "українська"}


def text_schema(*keys):
    return {"type": "object",
            "properties": {k: {"type": "string"} for k in keys},
            "required": list(keys), "additionalProperties": False}


def caption(lines, foot, tags):
    return "\n".join(lines + ["", foot, tags])


# ---------- 🧩 плагін Figma ----------

def make_plugin(state, rnd, handle, foot, style):
    done = set(state.get("plugins_posted", []))
    pool = [p for p in PLUGINS if p[0] not in done] or PLUGINS
    free = [p for p in pool if p[3] == "free"]
    pid, name, author, price, users, desc, topic = rnd.choice(
        free if free and rnd.random() < 0.8 else pool)
    res = ai.ask(f"""Плагін Figma «{name}» (автор — {author}, тема — {topic}).
Офіційний опис зі сторінки Figma Community: «{desc}»

- card_title: що робить плагін, українською, до 50 знаків;
- body: 2–3 короткі речення українською: що він робить і в яких задачах
  дизайнеру знадобиться. Тільки те, що випливає з опису; не вигадуй функцій,
  цін чи обмежень. Telegram HTML, лише <b> та <i>.""",
                 text_schema("card_title", "body"), effort="low",
                 max_tokens=2000, system=style)
    if not res:
        return None
    path = cards.tmp_path("plugin")
    price_uk = "Безкоштовний" if price == "free" else "Платний"
    ok = cards.text_card(
        "ПЛАГІН FIGMA", name, path, meta=f"Figma Community · {author}",
        sub=res["card_title"],
        chip_items=[(price_uk, cards.YELLOW, rub.YELLOW_INK),
                    (f"{users} користувачів", rub.BLUE_LIGHT, cards.INK),
                    (topic, rub.PINK_LIGHT, rub.PINK_INK)],
        handle=handle, tag="#figma")
    lines = ["<b>🧩 ПЛАГІН FIGMA</b>",
             f"<b>{html.escape(name, quote=False)}</b> — "
             f"{html.escape(res['card_title'], quote=False)}", "",
             rub.clean_html(res["body"]), "",
             f"▫️ Автор: {html.escape(author, quote=False)}",
             f"▫️ Ціна в Figma Community: "
             f"{'безкоштовно' if price == 'free' else 'платний'}",
             f"▫️ Користувачів: {users} (жовтень 2026)",
             f'🔗 <a href="{FIGMA}{pid}">Відкрити в Figma Community</a>']
    return ok and {"card": path, "key": pid,
                   "text": caption(lines, foot, "#figma #плагіни")}


# ---------- 🧩 фішка Figma (Release Notes) ----------

def make_figma_tip(state, rnd, handle, foot, style):
    import design_bot as db
    try:
        items = db.parse_feed("Figma Release Notes", db.http_get(FIGMA_NOTES))
    except Exception as e:
        print("Figma Release Notes не прочиталися:", type(e).__name__)
        return None
    done = set(state.get("figma_tips", []))
    now = time.time()
    fresh = [i for i in items if db.key(i["link"]) not in done
             and (not i["ts"] or now - i["ts"] < 60 * 86400)]
    if not fresh:
        return None
    it = fresh[0]
    post = ai.ask(f"""Ось запис з офіційних Figma Release Notes. Зроби з нього пост «Фішка
Figma» для дизайнерів українською.
- headline: що нового, до 70 знаків;
- card_title: те саме коротко, до 50 знаків;
- body: 2–4 короткі речення: що з'явилося і як цим скористатися (кроки,
  якщо вони є в тексті). Тільки факти з тексту. Telegram HTML, лише <b>, <i>.

Заголовок: {it['title']}
Текст:
{it['text'][:6000]}""", text_schema("headline", "card_title", "body"),
                  effort="medium", max_tokens=3000, system=style)
    if not post:
        return None
    post = db.verify_post({"title": it["title"], "src": "Figma Release Notes",
                           "text": it["text"]}, dict(post, credit=""))
    if not post:
        return None
    path = cards.tmp_path("figmatip")
    date = db.date_ua(it["ts"]) if it["ts"] else ""
    ok = cards.text_card("ФІШКА FIGMA", post["card_title"], path,
                         meta=f"Figma Release Notes · {date}".strip(" ·"),
                         note="як це працює — в пості", handle=handle,
                         tag="#figma")
    lines = ["<b>🧩 ФІШКА FIGMA</b>",
             f"<b>{html.escape(post['headline'], quote=False)}</b>", "",
             rub.clean_html(post["body"]), "",
             f'🔗 <a href="{html.escape(it["link"])}">Офіційний опис у Figma '
             f'Release Notes</a>']
    return ok and {"card": path, "key": db.key(it["link"]),
                   "text": caption(lines, foot, "#figma #фішки")}


# ---------- 🤖 промпт дня ----------

def make_prompt(state, rnd, handle, foot, style, video=False):
    recent = state.get("prompts", [])[-8:]
    product = rnd.choice([x for x in PRODUCTS if x not in recent] or PRODUCTS)
    what = ("відео (5–8 секунд) для реклами" if video
            else "рекламного фото")
    tools = ("Veo, Kling, Runway чи Sora" if video
             else "Midjourney, Flux, GPT Image чи Gemini")
    res = ai.ask(f"""Склади промпт для генерації {what} продукту: {product}.
Без брендів і логотипів. Промпт — англійською, бо так моделі розуміють
найкраще: предмет і матеріали, фон і сцена, світло, оптика й ракурс,
{'рух камери й продукту, темп, ' if video else ''}настрій і кольори.
До 600 знаків, одним абзацом, без параметрів конкретних моделей.

- title: коротка назва українською, до 40 знаків (наприклад «Парфуми на
  мокрому камені»);
- prompt: сам промпт англійською;
- tips: 2–3 речення українською: які частини промпту за що відповідають і як
  підставити свій продукт; можна згадати, що формат 4:5 зручний для соцмереж.""",
                 text_schema("title", "prompt", "tips"), effort="low",
                 max_tokens=2500, system=style)
    if not res:
        return None
    label = "ПРОМПТ: ВІДЕО" if video else "ПРОМПТ: ФОТО"
    path = cards.tmp_path("prompt")
    ok = cards.text_card(
        label, res["title"], path, code=res["prompt"],
        chip_items=[("Відео" if video else "Фото", cards.YELLOW, rub.YELLOW_INK),
                    (product, rub.PINK_LIGHT, rub.PINK_INK),
                    ("промпт у пості — копіюй", rub.BLUE_LIGHT, cards.INK)],
        handle=handle, tag="#промпт")
    lines = [f"<b>🤖 ПРОМПТ ДНЯ · {'ВІДЕО' if video else 'ФОТО'}</b>",
             f"<b>{html.escape(res['title'], quote=False)}</b>", "",
             f"<pre>{html.escape(res['prompt'], quote=False)}</pre>", "",
             rub.clean_html(res["tips"]), "",
             f"▫️ Підійде для {tools}"]
    return ok and {"card": path, "key": product,
                   "text": caption(lines, foot, "#промпт #ai")}


# ---------- 🎬 фільм і 🎮 гра ----------

def make_film(state, rnd, handle, foot, style):
    done = set(state.get("films_posted", []))
    title, year, who, kind, desc = rnd.choice(
        [f for f in FILMS if f[0] not in done] or FILMS)
    path = cards.tmp_path("film")
    ok = cards.text_card("ЩО ПОДИВИТИСЯ", title, path,
                         meta=f"{kind} · {year}", sub=desc,
                         chip_items=[(year, cards.YELLOW, rub.YELLOW_INK),
                                     (who, rub.BLUE_LIGHT, cards.INK)],
                         handle=handle, tag="#кіно")
    lines = ["<b>🎬 ЩО ПОДИВИТИСЯ ПРО ДИЗАЙН</b>",
             f"<b>{html.escape(title, quote=False)}</b> ({year})", "",
             html.escape(desc, quote=False), "",
             f"▫️ {kind[:1].upper() + kind[1:]}, {html.escape(who, quote=False)}"]
    return ok and {"card": path, "key": title,
                   "text": caption(lines, foot, "#кіно #дизайн")}


def make_game(state, rnd, handle, foot, style):
    done = set(state.get("games_posted", []))
    title, year, studio, desc = rnd.choice(
        [g for g in GAMES if g[0] not in done] or GAMES)
    path = cards.tmp_path("game")
    ok = cards.text_card("У ЩО ПОГРАТИ", title, path, meta=f"гра · {year}",
                         sub=desc,
                         chip_items=[(year, cards.YELLOW, rub.YELLOW_INK),
                                     (studio, rub.BLUE_LIGHT, cards.INK)],
                         handle=handle, tag="#ігри")
    lines = ["<b>🎮 У ЩО ПОГРАТИ ДИЗАЙНЕРУ</b>",
             f"<b>{html.escape(title, quote=False)}</b> ({year})", "",
             html.escape(desc, quote=False), "",
             f"▫️ Студія: {html.escape(studio, quote=False)}"]
    return ok and {"card": path, "key": title,
                   "text": caption(lines, foot, "#ігри #дизайн")}


# ---------- 🔤 шрифт дня з Fontshare ----------

def fs_designers(f):
    names = []
    for d in f.get("designers") or []:
        names.append(d.get("name", "") if isinstance(d, dict) else str(d))
    return ", ".join(n for n in names if n)


def fs_font_file(slug):
    """TTF/WOFF шрифту з Fontshare (звичайне накреслення)."""
    import os
    import tempfile
    for weight in (400, 500, 300, 700):
        try:
            u = (f"https://api.fontshare.com/v2/css?f[]={slug}@{weight}"
                 "&display=swap")
            req = urllib.request.Request(u, headers={"User-Agent": cards.UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                css = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        for ext in ("ttf", "woff"):
            m = re.search(r"url\(['\"]?((?:https?:)?//[^'\")]+\." + ext
                          + r")['\"]?\)", css)
            if not m:
                continue
            url = m.group(1)
            url = "https:" + url if url.startswith("//") else url
            path = os.path.join(tempfile.gettempdir(),
                                f"hd_fs_{slug}_{weight}.{ext}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": cards.UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                with open(path, "wb") as fh:
                    fh.write(data)
                from PIL import ImageFont
                ImageFont.truetype(path, 20)
                return path
            except Exception as e:
                print("Fontshare-шрифт не підійшов:", slug, type(e).__name__)
    return None


def describe_specimen(name, facts, sample, card_path, style):
    if not ai.available():
        return None
    prompt = f"""На картинці — картка «Шрифт дня» для шрифту {name}. Великий рядок
«{sample}» і рядок під ним набрані саме цим шрифтом; назва, мітки й таблички —
фірмовим шрифтом каналу, їх не оцінюй. Дані: {facts}.

Напиши 2–3 короткі речення українською: характер шрифту (що видно на зразку:
форма літер, контраст, ширина, засічки, настрій) і де він доречний. Не
вигадуй історії, років і фактів про авторів. Telegram HTML: лише <b>, <i>."""
    try:
        import anthropic
        with open(card_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        r = anthropic.Anthropic().beta.messages.create(
            model=ai.MODEL, max_tokens=3000, system=style,
            betas=[ai.FALLBACK_BETA], fallbacks="default",
            output_config={"effort": "medium", "format": {
                "type": "json_schema", "schema": text_schema("text")}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg",
                                             "data": b64}},
                {"type": "text", "text": prompt}]}])
        text = "".join(b.text for b in r.content if b.type == "text")
        return json.loads(text)["text"].strip()
    except Exception as e:
        print("Опис шрифту не вийшов:", type(e).__name__, str(e)[:200])
        return None


def make_fontshare_post(state, rnd, handle, foot, style):
    """Шрифт дня з Fontshare: (dict з «family», шлях до картки, текст)."""
    try:
        req = urllib.request.Request(FS_API, headers={"User-Agent": cards.UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            fonts = json.loads(r.read().decode("utf-8", "replace")).get("fonts", [])
    except Exception as e:
        print("Fontshare не відповів:", type(e).__name__)
        return None
    done = set(state.get("fonts_posted", []))
    pool = [f for f in fonts if f.get("license_type") == "itf_ffl"
            and f.get("name") not in done]
    rnd.shuffle(pool)
    for f in pool[:5]:
        path_font = fs_font_file(f.get("slug", ""))
        if not path_font:
            continue
        langs = [x.strip() for x in (f.get("languages") or "").split(",")
                 if x.strip()]
        script = (f.get("script") or "latin").lower()
        cyr = "cyril" in script or "Ukrainian" in langs
        sample = rub.SAMPLE if cyr else rub.SAMPLE_LAT
        line = rub.PANGRAM if cyr else rub.PANGRAM_LAT
        cat = f.get("category") or "Font"
        path = cards.tmp_path("fsfont")
        chips = [("Безкоштовний", cards.YELLOW, rub.YELLOW_INK),
                 (f"Кирилиця: {'так' if cyr else 'ні'}", rub.PINK_LIGHT,
                  rub.PINK_INK),
                 (cat, rub.BLUE_LIGHT, cards.INK),
                 ("Fontshare", rub.BLUE_LIGHT, cards.INK)]
        if not cards.font_card(f["name"], path_font, chips, path,
                               handle=handle, sample=sample, line=line):
            continue
        who = fs_designers(f)
        known = [EN_LANGS[x] for x in langs if x in EN_LANGS][:5]
        lang_text = (("кирилиця й латиниця" if cyr else "латиниця")
                     + (f" — {len(langs)} мов" if langs else "")
                     + (f" (серед них {', '.join(known)})" if known else "")
                     + ("" if cyr else "; кирилиці немає"))
        facts = f"тип — {cat}; мови — {lang_text}; автори — {who or 'не вказані'}"
        desc = describe_specimen(f["name"], facts, sample, path, style)
        lines = ["<b>🔤 ШРИФТ ДНЯ</b>",
                 f"<b>{html.escape(f['name'], quote=False)}</b>", ""]
        if desc:
            lines += [desc, ""]
        lines += [f"▫️ Тип: {html.escape(cat, quote=False)}",
                  f"▫️ Мови: {lang_text}"]
        if who:
            lines.append(f"▫️ Автор: {html.escape(who, quote=False)}")
        lines += ["▫️ Ліцензія: безкоштовний для особистого й комерційного "
                  "використання (ITF Free Font License)",
                  f'🔗 <a href="https://www.fontshare.com/fonts/'
                  f'{f.get("slug", "")}">Завантажити на Fontshare</a>',
                  "", foot, "#шрифт_дня #шрифти"]
        return {"family": f["name"]}, path, "\n".join(lines)
    return None


# ---------- розклад ----------

MAKERS = {"plugin": make_plugin, "figma_tip": make_figma_tip,
          "prompt_photo": make_prompt,
          "prompt_video": lambda *a: make_prompt(*a, video=True),
          "film": make_film, "game": make_game}
STATE_KEYS = {"plugin": "plugins_posted", "figma_tip": "figma_tips",
              "prompt_photo": "prompts", "prompt_video": "prompts",
              "film": "films_posted", "game": "games_posted"}


def tick(tg, state, kt, handle, foot, style, now=""):
    """now: «today» — опублікувати сьогоднішню рубрику зараз, або назва
    рубрики (plugin, figma_tip, prompt_photo, prompt_video, film, game)."""
    today = kt.strftime("%Y-%m-%d")
    kind = EVENING[kt.weekday()] if now == "today" else now
    if not kind and LIVE and EVENING_HOUR <= kt.hour < EVENING_HOUR + WINDOW_H \
            and state.get("evening_day") != today:
        kind = EVENING[kt.weekday()]
    if kind not in MAKERS:
        return
    rnd = random.Random(f"{today}-{kind}-{time.time() // 3600}")
    out = MAKERS[kind](state, rnd, handle, foot, style)
    if kind == "figma_tip" and not out:          # нових фішок немає — плагін
        kind, out = "plugin", make_plugin(state, rnd, handle, foot, style)
    if out and tg.send_photo_file(out["card"], out["text"]).get("ok"):
        state["evening_day"] = today
        key = STATE_KEYS[kind]
        state.setdefault(key, []).append(out["key"])
        state[key] = state[key][-200:]
        print("Вечірня рубрика:", kind, out["key"])


def demo(dump, handle, foot, style):
    """Приклади всіх вечірніх рубрик і шрифту з Fontshare у лог."""
    rnd = random.Random()
    state = {}
    for kind, make in MAKERS.items():
        try:
            out = make(state, rnd, handle, foot, style)
        except Exception as e:
            print(f"{kind}: помилка {type(e).__name__}: {e}")
            continue
        if not out:
            print(f"\n===== {kind}: не вийшло =====")
            continue
        print(f"\n===== ПРИКЛАД ({kind}) =====\n{out['text']}")
        dump(out["card"])
    out = make_fontshare_post(state, rnd, handle, foot, style)
    if out:
        print(f"\n===== ПРИКЛАД (шрифт дня з Fontshare: {out[0]['family']}) "
              f"=====\n{out[2]}")
        dump(out[1])
