# -*- coding: utf-8 -*-
"""
📣 Ручной пост: публикует в канал то, что лежит в manual_post.json —
например, анонс нового видео автора канала.
  text    — подпись (HTML Telegram);
  video   — ссылка: Telegram покажет над текстом большое превью
            с плеером (YouTube смотрят прямо в канале);
  button  — [надпись, ссылка] — кнопка под постом;
  poll    — {question, options} — опрос сразу после поста;
  id      — один и тот же пост дважды не уйдёт (manual_post_sent.json).
Запуск: python manual_post.py (MANUAL_DRY=1 — только показать в логе).
"""
import json
import os
import urllib.error
import urllib.request

SRC = "manual_post.json"
SENT = "manual_post_sent.json"


def api(token, method, params):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        print("Telegram HTTP ошибка:", e.code,
              e.read().decode("utf-8", "replace"))
        return {"ok": False}


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    post = load(SRC, None)
    if not post:
        print("Нет", SRC)
        return
    sent = load(SENT, [])
    print("Канал:", post["channel"], "· id:", post["id"])
    print(post["text"])
    if post.get("poll"):
        print("Опрос:", post["poll"]["question"], post["poll"]["options"])
    if os.environ.get("MANUAL_DRY") == "1":
        print("Тест: ничего не отправлено.")
        return
    if post["id"] in sent:
        print("Этот пост уже опубликован — пропускаю.")
        return
    token = os.environ.get("BOT_TOKEN", "")
    msg = {"chat_id": post["channel"], "text": post["text"],
           "parse_mode": "HTML"}
    if post.get("video"):
        msg["link_preview_options"] = {"url": post["video"],
                                       "prefer_large_media": True,
                                       "show_above_text": True}
    else:
        msg["link_preview_options"] = {"is_disabled": True}
    if post.get("button"):
        msg["reply_markup"] = {"inline_keyboard": [[
            {"text": post["button"][0], "url": post["button"][1]}]]}
    res = api(token, "sendMessage", msg)
    print("Пост:", res.get("ok"), (res.get("result") or {}).get("message_id"))
    if not res.get("ok"):
        return
    sent.append(post["id"])
    with open(SENT, "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False, indent=2)
    if post.get("poll"):
        p = post["poll"]
        res = api(token, "sendPoll", {
            "chat_id": post["channel"], "question": p["question"],
            "options": [{"text": o} for o in p["options"]],
            "is_anonymous": True})
        print("Опрос:", res.get("ok"))


if __name__ == "__main__":
    main()
