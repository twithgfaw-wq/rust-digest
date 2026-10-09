# -*- coding: utf-8 -*-
"""
📣 Ручной пост: публикует в канал то, что лежит в manual_post.json —
например, анонс нового видео автора канала.
  text    — подпись (HTML Telegram);
  photo   — ссылка на картинку: пост с фото (подпись до 1024 знаков);
  photos  — список ссылок: альбом до 10 фото, подпись на первом (без кнопки);
  video   — ссылка: Telegram покажет над текстом большое превью
            с плеером (YouTube смотрят прямо в канале);
  button  — [надпись, ссылка] — кнопка под постом;
  poll    — {question, options} — опрос сразу после поста;
  ws_id / ws_ids — работа(ы) мастерской CS2: отметим как выложенные, чтобы рубрика
            «Мастерская CS2» не повторила её (cs2_state.json → ws_posted);
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
    msg = {"chat_id": post["channel"], "parse_mode": "HTML"}
    if post.get("photos"):   # альбом: подпись на первом фото, кнопок нет
        method = "sendMediaGroup"
        msg = {"chat_id": post["channel"], "media": [
            dict({"type": "photo", "media": u},
                 **({"caption": post["text"], "parse_mode": "HTML"}
                    if k == 0 else {}))
            for k, u in enumerate(post["photos"][:10])]}
    elif post.get("photo"):
        method = "sendPhoto"
        msg.update(photo=post["photo"], caption=post["text"])
    else:
        method = "sendMessage"
        msg["text"] = post["text"]
        if post.get("video"):
            msg["link_preview_options"] = {"url": post["video"],
                                           "prefer_large_media": True,
                                           "show_above_text": True}
        else:
            msg["link_preview_options"] = {"is_disabled": True}
    if post.get("button") and method != "sendMediaGroup":
        msg["reply_markup"] = {"inline_keyboard": [[
            {"text": post["button"][0], "url": post["button"][1]}]]}
    res = api(token, method, msg)
    first = res.get("result") or {}
    if isinstance(first, list):
        first = first[0] if first else {}
    print("Пост:", res.get("ok"), first.get("message_id"))
    if not res.get("ok"):
        return
    sent.append(post["id"])
    with open(SENT, "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False, indent=2)
    ws = post.get("ws_ids") or ([post["ws_id"]] if post.get("ws_id") else [])
    if ws:
        state = load("cs2_state.json", None)
        if state is not None:
            state.setdefault("ws_posted", []).extend(ws)
            with open("cs2_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    if post.get("poll"):
        p = post["poll"]
        res = api(token, "sendPoll", {
            "chat_id": post["channel"], "question": p["question"],
            "options": [{"text": o} for o in p["options"]],
            "is_anonymous": True})
        print("Опрос:", res.get("ok"))


if __name__ == "__main__":
    main()
