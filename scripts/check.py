"""設定の確認用。アカウントごとにトークンが使えるか、アカウント名、24時間の投稿枠を表示する（投稿はしない）。"""
import json
import os
import subprocess
import urllib.request

from common import (CONFIG, IG_HOST, TH_HOST, ApiError, discord_bot_token, discord_webhook, http, log, media_base_url, token,
                    url_is_reachable)
from platforms import DISCORD_UA, _norm, discord_channel_id, discord_guild_channels


def main():
    base_url = media_base_url()
    ok = url_is_reachable(base_url + "ok.txt")
    log(f"画像・動画の公開URL：{base_url}  {'OK' if ok else 'NG（Pagesの設定か media ブランチを確認）'}")
    if not os.environ.get("GH_TOKEN"):
        log("GH_PAT（トークン自動延長用）：未設定")
    else:
        r = subprocess.run(["gh", "secret", "list"], capture_output=True, text=True)
        log("GH_PAT（トークン自動延長用）：OK" if r.returncode == 0 else f"GH_PAT：NG（権限を確認）{r.stderr.strip()[:200]}")
        if r.returncode == 0:  # 名前だけ（中身は出ない）
            names = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
            log("Secretsの名前：" + "、".join(names))
    for acc, conf in CONFIG["accounts"].items():
        label = f"[{acc}] {conf.get('name', '')}"
        for platform in conf["platforms"]:
            try:
                tok = token(platform, acc)
                if platform == "instagram":
                    base = f"{IG_HOST}/{CONFIG['instagram_api_version']}"
                    me = http("GET", f"{base}/me", {"fields": "user_id,username,account_type", "access_token": tok})
                    lim = http("GET", f"{base}/{me.get('user_id')}/content_publishing_limit",
                               {"fields": "config,quota_usage", "access_token": tok})
                    log(f"{label} Instagram：OK  @{me.get('username')}（{me.get('account_type')}）  24時間の投稿枠 {lim}")
                else:
                    base = f"{TH_HOST}/{CONFIG['threads_api_version']}"
                    me = http("GET", f"{base}/me", {"fields": "id,username", "access_token": tok})
                    lim = http("GET", f"{base}/{me.get('id')}/threads_publishing_limit",
                               {"fields": "config,quota_usage", "access_token": tok})
                    log(f"{label} Threads：OK  @{me.get('username')}  24時間の投稿枠 {lim}")
            except ApiError as e:
                log(f"{label} {platform}：NG {e}")
        chans = conf.get("discord_channels") or {}
        bot = discord_bot_token(acc)
        if chans and bot:
            try:
                found = discord_guild_channels(bot)
                log(f"{label} Discordボット：OK  入っているサーバー：{'、'.join(sorted({g for g, _, _ in found})) or 'なし（招待がまだ）'}")
                for ch, name in chans.items():
                    try:
                        log(f"{label} Discord「{ch}」{name}：OK  チャンネルID {discord_channel_id(acc, ch, bot)}")
                    except ApiError as e:
                        log(f"{label} Discord「{ch}」{name}：NG {e}")
                known = {_norm(n) for n in chans.values()}
                extra = [f"{n}（{cid}）" for _, n, cid in found if _norm(n) not in known]
                if extra:
                    log(f"{label} Discord：config にないチャンネル：{'、'.join(extra)}")
            except ApiError as e:
                log(f"{label} Discordボット：NG {e}")
            continue
        for ch, name in chans.items():
            try:
                url = discord_webhook(acc, ch)
            except ApiError:
                log(f"{label} Discord「{ch}」{name}：未設定（DISCORD_WEBHOOK_{acc.upper()}_{ch.upper()}）")
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": DISCORD_UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    w = json.loads(r.read().decode())
                log(f"{label} Discord「{ch}」{name}（ウェブフック）：OK  ウェブフック名「{w.get('name')}」チャンネルID {w.get('channel_id')}")
            except Exception as e:
                log(f"{label} Discord「{ch}」：NG URLが使えません（消された・コピー違いなど）{type(e).__name__}")
        if chans and not bot:
            log(f"{label} Discordボット：未設定（DISCORD_BOT_TOKEN_{acc.upper()}）")

if __name__ == "__main__":
    main()
