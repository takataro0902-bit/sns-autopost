"""Threadsの数字（インサイト）を読むだけのスクリプト。投稿・変更は一切しない。
投稿ごとの 表示・いいね・返信・再投稿・引用・シェア と、アカウントの日別の表示・フォロワー数を
insights/<アカウント>_<日付>.json と .csv に書き出す。
トークンに threads_manage_insights の権限がないと、数字の部分はエラーとして記録される（止めない）。"""
import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from common import CONFIG, QUEUE, ROOT, TH_HOST, ApiError, http, log, token

POST_METRICS = "views,likes,replies,reposts,quotes,shares"
JST = timezone(timedelta(hours=9))


def _pages(url, params, limit_pages=20):
    out = []
    for _ in range(limit_pages):
        r = http("GET", url, params)
        out += r.get("data", [])
        nxt = (r.get("paging") or {}).get("next")
        if not nxt:
            break
        url, params = nxt, None
    return out


def _metrics(r):
    vals = {}
    for m in r.get("data", []):
        if "values" in m and m["values"]:
            vals[m["name"]] = m["values"][0].get("value")
        elif "total_value" in m:
            vals[m["name"]] = m["total_value"].get("value")
    return vals


def queue_titles(account):
    """ThreadsのID → 予約フォルダ名（どの原稿か分かるように）"""
    out = {}
    for f in QUEUE.glob(f"*_{account}_*/post.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = ((p.get("result") or {}).get("threads") or {}).get("id")
        if tid:
            out[str(tid)] = f.parent.name
    return out


def run(account):
    tk = token("threads", account)
    base = f"{TH_HOST}/{CONFIG['threads_api_version']}"
    report = {"account": account, "fetched_at": datetime.now(JST).isoformat(), "errors": []}
    me = http("GET", f"{base}/me", {"fields": "id,username", "access_token": tk})
    report["user"] = me
    fields = "id,timestamp,text,permalink,media_type,is_quote_post"
    posts = []
    for kind in ("threads", "replies"):
        try:
            items = _pages(f"{base}/me/{kind}", {"fields": fields, "limit": 100, "access_token": tk})
        except ApiError as e:
            report["errors"].append(f"{kind}一覧: {e}")
            items = []
        for it in items:
            it["kind"] = "本体" if kind == "threads" else "返信・続き"
        posts += items
    titles = queue_titles(account)
    for p in posts:
        p["queue"] = titles.get(str(p["id"]), "")
        try:
            p.update(_metrics(http("GET", f"{base}/{p['id']}/insights", {"metric": POST_METRICS, "access_token": tk})))
        except ApiError as e:
            p["insights_error"] = str(e)[:300]
        time.sleep(0.2)
    report["posts"] = sorted(posts, key=lambda x: x.get("timestamp", ""))

    # アカウント全体（日別の表示は最大で過去の一定期間。取れた分だけ）
    until = int(time.time())
    since = until - 60 * 60 * 24 * 30
    for metric in ("views", "likes,replies,reposts,quotes,followers_count"):
        try:
            r = http("GET", f"{base}/me/threads_insights", {"metric": metric, "since": since, "until": until, "access_token": tk})
            report.setdefault("account_insights", []).extend(r.get("data", []))
        except ApiError as e:
            report["errors"].append(f"アカウント {metric}: {e}")

    out_dir = ROOT / "insights"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    (out_dir / f"{account}_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["timestamp", "kind", "queue", "views", "likes", "replies", "reposts", "quotes", "shares", "permalink", "text", "insights_error"]
    with open(out_dir / f"{account}_{stamp}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in report["posts"]:
            row = dict(p)
            ts = p.get("timestamp")
            if ts:
                row["timestamp"] = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(JST).strftime("%Y-%m-%d %H:%M")
            row["text"] = (p.get("text") or "").replace("\n", " / ")[:120]
            w.writerow(row)
    ok = sum(1 for p in posts if "views" in p)
    log(f"{account}: 投稿 {len(posts)} 件、数字が取れたもの {ok} 件、エラー {len(report['errors'])} 件")
    for e in report["errors"]:
        log("  " + e[:300])
    if posts and not ok:
        log("  投稿ごとの数字が1件も取れません。最初のエラー：" + posts[0].get("insights_error", "")[:300])


if __name__ == "__main__":
    accounts = sys.argv[1:] or [a for a, c in CONFIG["accounts"].items() if "threads" in c.get("platforms", [])]
    for a in accounts:
        try:
            run(a)
        except ApiError as e:
            log(f"{a}: {e}")
