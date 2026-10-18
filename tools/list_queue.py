"""予約の一覧（これからの投稿と、最近の結果）を表示する。

使い方：python3 tools/list_queue.py [--account lua] [--days 7]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from common import CONFIG, QUEUE, parse_time  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=7, help="何日前までの結果を出すか")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    jst = timezone(timedelta(hours=9))
    for d in sorted(p for p in QUEUE.iterdir() if (p / "post.json").exists()):
        post = json.loads((d / "post.json").read_text(encoding="utf-8"))
        if args.account and post.get("account") != args.account:
            continue
        when = parse_time(post["publish_at"])
        if when < now - timedelta(days=args.days):
            continue
        plats = post.get("platforms") or CONFIG["accounts"].get(post.get("account"), {}).get("platforms", [])
        states = []
        for p in plats:
            r = post.get("result", {}).get(p, {})
            states.append(f"{p}:" + ("済" if r.get("id") else "諦め" if r.get("gave_up") else f"失敗{r['attempts']}回" if r.get("attempts") else "待ち"))
        print(f"{when.astimezone(jst):%m/%d %H:%M}  {post.get('account')}  {post['type']}{len(post['media'])}点  "
              f"{' '.join(states)}  {post.get('title', d.name)}"
              + (f"  ↳続き（親 {post['threads_reply_to']}）" if post.get("threads_reply_to") else ""))


if __name__ == "__main__":
    main()
