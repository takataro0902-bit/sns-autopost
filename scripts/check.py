"""設定の確認用。アカウントごとにトークンが使えるか、アカウント名、24時間の投稿枠を表示する（投稿はしない）。"""
from common import CONFIG, IG_HOST, TH_HOST, ApiError, http, log, media_base_url, token, url_is_reachable


def main():
    base_url = media_base_url()
    ok = url_is_reachable(base_url + "ok.txt")
    log(f"画像・動画の公開URL：{base_url}  {'OK' if ok else 'NG（Pagesの設定か media ブランチを確認）'}")
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
                    log(f"{label} Threads：OK  @{me.get('username')}")
            except ApiError as e:
                log(f"{label} {platform}：NG {e}")


if __name__ == "__main__":
    main()
