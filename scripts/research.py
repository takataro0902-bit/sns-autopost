"""他アカウントの公開投稿を検索して読むだけ（投稿しない）。キーワード検索とプロフィール検索が使えるかを試し、取れたものを research/ に書く。
使う権限：threads_keyword_search / threads_profile_discovery（トークンに無ければエラーとして記録）"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from common import CONFIG, ROOT, TH_HOST, ApiError, http, log, token

JST = timezone(timedelta(hours=9))
FIELDS = "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,like_count,reply_count,repost_count,quote_count,views"
FIELDS_MIN = "id,text,media_type,permalink,timestamp,username,has_replies"


def get(url, params):
    try:
        return http("GET", url, params)
    except ApiError as e:
        return {"error": str(e)[:400]}


def run(account, queries, users):
    tk = token("threads", account)
    base = f"{TH_HOST}/{CONFIG['threads_api_version']}"
    out = {"fetched_at": datetime.now(JST).isoformat(), "search": {}, "profiles": {}}
    for q in queries:
        for st in ("TOP", "RECENT"):
            r = get(f"{base}/keyword_search", {"q": q, "search_type": st, "fields": FIELDS, "limit": 50, "access_token": tk})
            if "error" in r:
                r2 = get(f"{base}/keyword_search", {"q": q, "search_type": st, "fields": FIELDS_MIN, "limit": 50, "access_token": tk})
                r2["first_error"] = r["error"]
                r = r2
            out["search"][f"{q}|{st}"] = r
            time.sleep(0.5)
    for u in users:
        prof = get(f"{base}/profile_lookup", {"username": u, "access_token": tk})
        posts = get(f"{base}/profile_posts", {"username": u, "fields": FIELDS, "limit": 50, "access_token": tk})
        out["profiles"][u] = {"profile": prof, "posts": posts}
        time.sleep(0.5)
    d = ROOT / "research"
    d.mkdir(exist_ok=True)
    f = d / f"{account}_{datetime.now(JST).strftime('%Y%m%d_%H%M%S')}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in out["search"].items():
        log(k, len(v.get("data", [])), v.get("error", "")[:200], v.get("first_error", "")[:200])
    for k, v in out["profiles"].items():
        log(k, str(v["profile"])[:200], len(v["posts"].get("data", [])) if isinstance(v["posts"], dict) else "")


if __name__ == "__main__":
    req = json.loads((ROOT / ".research-request.json").read_text(encoding="utf-8"))
    run("umataro", req.get("queries", []), req.get("users", []))
