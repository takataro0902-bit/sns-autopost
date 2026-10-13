"""後片付け：投稿が済んで数日たった投稿の画像・動画を media ブランチから消す。週1回、GitHub Actionsが動かす。
消したあと media ブランチは「今ある画像だけの1コミット」に作り直す（リポジトリが動画で膨らまないように）。

使い方：python3 scripts/cleanup.py <mediaブランチを取り出したフォルダ>
"""
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

from common import CONFIG, QUEUE, ApiError, log, now_utc, parse_time, platforms_of


def main():
    media_root = Path(sys.argv[1]) / "queue"
    if not media_root.exists():
        log("media ブランチに queue がありません。何もしません")
        return
    keep = timedelta(days=CONFIG["prune_media_after_days"])
    now = now_utc()
    for d in sorted(p for p in media_root.iterdir() if p.is_dir()):
        pj = QUEUE / d.name / "post.json"
        if not pj.exists():
            # main 側に予定がない（消された・名前が変わった）画像は、念のため2週間で消す
            age = now - parse_time(f"{d.name[:4]}-{d.name[4:6]}-{d.name[6:8]}T00:00:00")
            if age > timedelta(days=14):
                shutil.rmtree(d)
                log(f"消しました（予定なし）：{d.name}")
            continue
        post = json.loads(pj.read_text(encoding="utf-8"))
        res = post.get("result", {})
        try:
            platforms = platforms_of(post)
        except ApiError:
            continue
        finished = all(res.get(p, {}).get("id") or res.get(p, {}).get("gave_up") for p in platforms)
        if finished and now - parse_time(post["publish_at"]) > keep:
            shutil.rmtree(d)
            log(f"消しました：{d.name}")


if __name__ == "__main__":
    main()
