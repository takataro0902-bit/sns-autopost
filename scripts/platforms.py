"""InstagramとThreadsへの投稿（公式API（Meta）の「コンテナを作る→処理完了を待つ→公開する」の流れ）と、
Discordのチャンネルへの投稿（ウェブフック）。"""
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta

from common import (CONFIG, IG_HOST, discord_channel, discord_webhook, redact, TH_HOST, ApiError, NotReady, account_of, http, log, media_url, parse_time,
                    token as get_token, url_is_reachable, wait_until)


def _check_urls(urls):
    for u in urls:
        if not url_is_reachable(u):
            # GitHub Pagesの反映待ちなど。失敗回数には数えず、次の回にやり直す
            raise NotReady(f"画像・動画のURLがまだ開けません：{u}")


def _already_posted(list_url, token, text_field, text, publish_at):
    """前の回で投稿はできたのに記録が残らなかった（通信切れ・pushの失敗など）ときの二重投稿よけ。
    最近の投稿に、同じ本文で予定時刻以降のものがあればそのIDを返す。確かめられないときは None。"""
    try:
        res = http("GET", list_url, {"fields": f"id,{text_field},timestamp", "limit": 10, "access_token": token})
    except ApiError as e:
        log(f"  （二重投稿の確認ができませんでした。そのまま進めます：{e}）")
        return None
    since = parse_time(publish_at) - timedelta(minutes=30)
    for m in res.get("data", []):
        try:
            ts = datetime.strptime(m.get("timestamp", ""), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        if ts >= since and (m.get(text_field) or "").strip()[:200] == text.strip()[:200]:
            return m["id"]
    return None


# ---------- Instagram（Instagramログイン版API。Facebookページ不要） ----------

def post_instagram(post_dir, post):
    token = get_token("instagram", account_of(post))
    base = f"{IG_HOST}/{CONFIG['instagram_api_version']}"
    user = http("GET", f"{base}/me", {"fields": "user_id", "access_token": token})["user_id"]
    caption = post["caption"]
    kind = post["type"]
    if kind == "text":
        raise ApiError("Instagramは文字だけの投稿ができません（画像か動画が必要）")
    files = post["media"]
    urls = [media_url(post_dir, f) for f in files]
    _check_urls(urls)
    done = _already_posted(f"{base}/{user}/media", token, "caption", caption, post["publish_at"])
    if done:
        log(f"  すでに投稿されていました（ID {done}）。記録だけ直します")
        return done

    def create(params):
        params = dict(params, access_token=token)
        return http("POST", f"{base}/{user}/media", params)["id"]

    def wait(cid, label):
        wait_until(lambda: http("GET", f"{base}/{cid}", {"fields": "status_code", "access_token": token}).get("status_code"), label)

    if kind == "carousel":
        if not 2 <= len(urls) <= 10:
            raise ApiError(f"Instagramのカルーセルは2〜10枚です（今は{len(urls)}枚）")
        children = []
        for i, u in enumerate(urls, 1):
            params = {"is_carousel_item": "true"}
            if u.lower().endswith((".mp4", ".mov")):
                params.update(media_type="VIDEO", video_url=u)
            else:
                params["image_url"] = u
            cid = create(params)
            wait(cid, f"Instagram {i}枚目")
            children.append(cid)
        container = create({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    elif kind == "image":
        container = create({"image_url": urls[0], "caption": caption})
    elif kind == "reel":
        params = {"media_type": "REELS", "video_url": urls[0], "caption": caption, "share_to_feed": "true"}
        if post.get("cover"):
            params["cover_url"] = media_url(post_dir, post["cover"])
        container = create(params)
    else:
        raise ApiError(f"知らない投稿の種類です：{kind}")

    wait(container, "Instagramの投稿")
    res = http("POST", f"{base}/{user}/media_publish", {"creation_id": container, "access_token": token})
    return res["id"]


# ---------- Threads ----------

def threads_text(post):
    """Threadsは文字数が少ない（既定500字）。ハッシュタグだけの行は外し、長ければ末尾を切る。"""
    text = post.get("threads_caption")
    if not text:
        lines = [l for l in post["caption"].splitlines() if not re.fullmatch(r"\s*(#\S+\s*)+", l)]
        text = "\n".join(lines).strip()
    limit = CONFIG["threads_max_chars"]
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def post_threads(post_dir, post):
    token = get_token("threads", account_of(post))
    user = "me"
    base = f"{TH_HOST}/{CONFIG['threads_api_version']}"
    text = threads_text(post)
    kind = post["type"]
    urls = [media_url(post_dir, f) for f in post["media"]]
    _check_urls(urls)
    done = _already_posted(f"{base}/{user}/threads", token, "text", text, post["publish_at"])
    if done:
        log(f"  すでに投稿されていました（ID {done}）。記録だけ直します")
        return done

    def create(params):
        params = dict(params, access_token=token)
        return http("POST", f"{base}/{user}/threads", params)["id"]

    def wait(cid, label):
        wait_until(lambda: http("GET", f"{base}/{cid}", {"fields": "status,error_message", "access_token": token}).get("status"), label)

    def item(u, carousel):
        p = {"is_carousel_item": "true"} if carousel else {"text": text}
        if u.lower().endswith((".mp4", ".mov")):
            p.update(media_type="VIDEO", video_url=u)
        else:
            p.update(media_type="IMAGE", image_url=u)
        return p

    if kind == "text":
        container = create({"media_type": "TEXT", "text": text})
    elif kind == "carousel":
        urls = urls[:20]  # Threadsのカルーセルは2〜20枚
        children = []
        for i, u in enumerate(urls, 1):
            cid = create(item(u, True))
            wait(cid, f"Threads {i}枚目")
            children.append(cid)
        container = create({"media_type": "CAROUSEL", "children": ",".join(children), "text": text})
    elif kind in ("image", "reel"):
        container = create(item(urls[0], False))
    else:
        raise ApiError(f"知らない投稿の種類です：{kind}")

    wait(container, "Threadsの投稿")
    res = http("POST", f"{base}/{user}/threads_publish", {"creation_id": container, "access_token": token})
    return res["id"]


# ---------- Discord（ウェブフック。ボット不要・無料） ----------
# 公式：https://docs.discord.com/developers/resources/webhook （Execute Webhook）
#   本文2000字まで。画像は multipart の files[n] で直接アップロード（1ファイル既定20MiBまで：同 reference「Uploading Files」）
# 1メッセージの添付は10点ずつに分ける（公式ページに上限の記載が見当たらないため、広く知られた10点で安全側に）

DISCORD_MAX_FILES = 10
DISCORD_UA = "DiscordBot (https://github.com/takataro0902-bit/sns-autopost, 1.0)"


def discord_text(post):
    text = post.get("discord_caption")
    if not text:
        lines = [l for l in post["caption"].splitlines() if not re.fullmatch(r"\s*(#\S+\s*)+", l)]
        text = "\n".join(lines).strip()
    if post.get("discord_mention") == "everyone":
        text = "@everyone\n" + text
    if len(text) > 2000:
        raise ApiError(f"Discordの本文は2000字までです（今は{len(text)}字）。discord_caption で短くしてください")
    return text


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": DISCORD_UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except Exception as e:
        raise NotReady(f"画像・動画をまだ取りに行けません：{url}（{e}）") from None


def _discord_send(url, payload, files):
    """files: [(ファイル名, 中身)]。429（混雑）は言われた秒数だけ待って3回までやり直す"""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             f'Content-Type: application/json\r\n\r\n'.encode() + json.dumps(payload, ensure_ascii=False).encode() + b"\r\n"]
    for i, (name, data) in enumerate(files):
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": DISCORD_UA}
    for _ in range(3):
        req = urllib.request.Request(url + "?wait=true", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429:
                try:
                    wait = float(json.loads(raw).get("retry_after", 5))
                except (ValueError, AttributeError):
                    wait = 5
                time.sleep(min(wait, 60))
                continue
            raise ApiError(f"HTTP {e.code} {redact(url)}: {raw[:500]}") from None
        except urllib.error.URLError as e:
            raise ApiError(f"接続できません {redact(url)}: {e.reason}") from None
    raise ApiError("Discordが混んでいて送れませんでした（429が続いた）")


def post_discord(post_dir, post):
    account = account_of(post)
    url = discord_webhook(account, discord_channel(post))
    text = discord_text(post)
    files = [(f, _download(media_url(post_dir, f))) for f in post["media"]]
    if not text and not files:
        raise ApiError("本文も画像もありません")
    mentions = {"parse": ["everyone"] if post.get("discord_mention") == "everyone" else []}
    ids = []
    chunks = [files[i:i + DISCORD_MAX_FILES] for i in range(0, len(files), DISCORD_MAX_FILES)] or [[]]
    for n, chunk in enumerate(chunks):
        payload = {"allowed_mentions": mentions}
        if n == 0 and text:
            payload["content"] = text
        if post.get("discord_username"):
            payload["username"] = post["discord_username"]
        payload["attachments"] = [{"id": i, "filename": name} for i, (name, _) in enumerate(chunk)]
        ids.append(_discord_send(url, payload, chunk)["id"])
    return ",".join(ids)


PLATFORMS = {"instagram": post_instagram, "threads": post_threads, "discord": post_discord}
