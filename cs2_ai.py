# -*- coding: utf-8 -*-
"""
Мозг CS2-бота: Claude Opus 5.5 пишет посты для @cs2_me.

Модель получает только проверенные данные (новость Steam, цены, работы
мастерской, посты из X) и пишет по-человечески: без воды, без шаблонных
фраз и без выдуманных цифр. Если ключа ANTHROPIC_API_KEY нет или модель не
ответила — функции возвращают None, и бот работает по старым шаблонам.
"""
import json
import os

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

STYLE = """Ты — редактор русскоязычного Telegram-канала @cs2_me о Counter-Strike 2.
Пишешь как опытный игрок и трейдер, который давно в CS: живой естественный
русский, конкретика, короткие предложения. Без воды и без шаблонных фраз
(«в мире CS2», «давайте разберёмся», «итак», «не секрет, что», «стоит
отметить», «друзья»), без канцелярита и без восторженных восклицаний.

Правила:
- Используй только факты и числа из входных данных. Ничего не придумывай:
  ни цифр, ни дат, ни причин. Если данных нет — не пиши об этом.
- Отделяй факты от предположений. Прогноз — словами «возможно», «если…, то…».
  Слухи и утечки помечай «⚠️ не подтверждено».
- Названия предметов, карт, режимов и команд оставляй как в игре (по-английски).
- Не обещай доходность и не говори «точно вырастет». Это не финансовый совет,
  но так не пиши — просто будь честным в формулировках.
- Формат — Telegram HTML: можно только <b>, <i>, <a href="…">. Без Markdown,
  без заголовков #, без списков со звёздочками.
"""


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def ask(prompt, schema=None, effort="medium", images=(), max_tokens=16000):
    """Один запрос к Claude. schema — JSON-схема ответа (тогда вернём dict),
    images — ссылки на картинки (для оценки скинов). None — если не вышло."""
    if not available():
        return None
    try:
        import anthropic
    except Exception as e:
        print("Нет пакета anthropic:", e)
        return None
    content = [{"type": "image", "source": {"type": "url", "url": u}}
               for u in images]
    content.append({"type": "text", "text": prompt})
    config = {"effort": effort}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    try:
        r = anthropic.Anthropic().beta.messages.create(
            model=MODEL, max_tokens=max_tokens, system=STYLE,
            betas=[FALLBACK_BETA], fallbacks="default",
            output_config=config,
            messages=[{"role": "user", "content": content}])
    except Exception as e:
        print("Claude не ответил:", type(e).__name__, str(e)[:300])
        return None
    if r.stop_reason == "refusal":
        print("Claude отказался:", getattr(r, "stop_details", None))
        return None
    text = "".join(b.text for b in r.content if b.type == "text").strip()
    u = r.usage
    print(f"Claude: {u.input_tokens} вход / {u.output_tokens} выход токенов")
    if not schema:
        return text or None
    try:
        return json.loads(text)
    except Exception:
        print("Claude вернул не JSON:", text[:300])
        return None


# ---------- новости ----------

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "important": {"type": "boolean"},
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "market": {"type": "string"},
    },
    "required": ["important", "headline", "body", "market"],
    "additionalProperties": False,
}


def news_post(kind, title, text, link, earlier=""):
    """Новость Valve (патч или анонс) — пересказ своими словами.
    earlier — что уже вышло в канале за сутки (чтобы не повторяться).
    Вернёт {important, headline, body, market} или None."""
    seen = (f"\n\nУже опубликовано в канале за последние сутки:\n{earlier}\n"
            "Если эта публикация о том же и не добавляет заметного нового — "
            "important=false. Если добавляет — начни с нового и не повторяй "
            "уже рассказанное." if earlier else "")
    prompt = f"""Перед тобой официальная публикация Valve о CS2 ({kind}).
Перескажи её для подписчиков канала своими словами — не переводи дословно.

Что нужно:
- headline: короткий цепляющий заголовок по сути (до 70 знаков, без эмодзи).
- body: главное для игроков. Для патча — 3–7 самых заметных изменений,
  каждое отдельной строкой, начинай строку с «▫️ », объясняй простыми
  словами, что это значит в игре. Мелкие технические правки объединяй
  («плюс мелкие фиксы карт»). Для анонса — 2–4 коротких абзаца по сути.
  Не длиннее 650 знаков. Telegram HTML.
- market: если публикация влияет на рынок скинов, кейсов, капсул или
  коллекций (новые кейсы/коллекции/терминалы, изменения дропа, trade-up,
  торговли, Armory, стикеров) — 1–2 предложения, что это может значить
  для цен и почему; без обещаний. Иначе пустая строка.
- important: false, если это совсем мелкий технический патч, который
  игроки не заметят (только фиксы крашей/шейдеров/локализации). Иначе true.{seen}

Заголовок публикации: {title}
Ссылка: {link}

Текст публикации:
{text[:12000]}"""
    return ask(prompt, NEWS_SCHEMA, effort="medium")
