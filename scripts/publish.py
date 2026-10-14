"""予約の時間が来た投稿を公開する。GitHub Actionsが15分おきに動かす。

queue/<フォルダ>/post.json の例：
{
  "publish_at": "2026-10-20T13:00:00+09:00",
  "type": "carousel",            # carousel / image / reel
  "media": ["01.jpg", "02.jpg"],  # 並び順どおりに投稿
  "account": "lua",               # config.json の accounts の名前（事業ごと）
  "caption": "本文",
  "platforms": ["instagram"],     # 省略時は config.json の accounts.<アカウント>.platforms
  "threads_caption": "（任意）Threads用の短い本文"
}
結果は同じ post.json の "result" に書き戻す。
画像・動画そのものは main ではなく media ブランチ（GitHub Pagesで公開）の同じ場所に置く。
"""
import argparse
import json
import sys
import traceback
from datetime import timedelta

from common import CONFIG, QUEUE, ApiError, NotReady, log, media_url, now_utc, parse_time, platforms_of, post_texts, rule_problems, url_is_reachable
from platforms import PLATFORMS


def load_posts():
    for d in sorted(p for p in QUEUE.iterdir() if p.is_dir()):
        f = d / "post.json"
        if f.exists():
            yield d, json.loads(f.read_text(encoding="utf-8"))


def save(d, post):
    (d / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="投稿せず、何をするかだけ表示")
    ap.add_argument("--only", help="このフォルダだけ、時間に関係なく今すぐ投稿（テスト用）")
    args = ap.parse_args()

    now = now_utc()
    max_late = timedelta(minutes=CONFIG["max_late_minutes"])
    alerts = []

    for d, post in load_posts():
        if args.only and d.name != args.only:
            continue
        result = post.setdefault("result", {})
        when = parse_time(post["publish_at"])
        due = args.only or when <= now
        if not due:
            continue
        try:
            targets = platforms_of(post)
        except ApiError as e:
            alerts.append(f"{d.name}: {e}")
            continue
        probs = rule_problems(post["account"], targets, post_texts(post))
        if probs:
            # 投稿のルール（PR表記など）に合わないものは出さない。直して予約し直すまで止める
            msg = "投稿のルールに合わないので出しません：" + " / ".join(probs)
            for platform in targets:
                r = result.setdefault(platform, {})
                if r.get("id") or r.get("gave_up"):
                    continue
                if args.dry_run:
                    log(f"[お試し] {d.name} / {platform}：{msg}")
                    continue
                r.update(gave_up=True, error=msg[:500])
                alerts.append(f"{d.name} / {platform}: {msg}")
            if not args.dry_run:
                save(d, post)
            continue
        for platform in targets:
            r = result.setdefault(platform, {})
            if r.get("id") or r.get("gave_up"):
                continue
            if not args.only and now - when > max_late:
                if args.dry_run:
                    log(f"[お試し] {d.name} / {platform}：予定から時間が過ぎすぎているので投稿しません")
                    continue
                r.update(gave_up=True, error=f"予定から{CONFIG['max_late_minutes']}分以上過ぎたので投稿しませんでした")
                alerts.append(f"{d.name} / {platform}: {r['error']}")
                save(d, post)
                continue
            if args.dry_run:
                ng = [f for f in post["media"] if not url_is_reachable(media_url(d, f))]
                state = "画像URLはすべて開けます" if not ng else f"開けない画像URLあり：{', '.join(ng)}"
                log(f"[お試し] {d.name} を {platform} に投稿します（{post['type']}・{len(post['media'])}点・{state}）")
                continue
            log(f"投稿します：{d.name} → {platform}")
            try:
                media_id = PLATFORMS[platform](d, post)
                r.clear()
                r.update(id=media_id, at=now_utc().isoformat())
                log(f"  できました（ID {media_id}）")
            except NotReady as e:
                r["error"] = str(e)[:500]
                log(f"  待ちます（失敗には数えません）：{r['error']}")
            except Exception as e:
                r["attempts"] = r.get("attempts", 0) + 1
                r["error"] = (str(e) if isinstance(e, (ApiError, KeyError)) else traceback.format_exc())[-500:]
                log(f"  失敗（{r['attempts']}回目）：{r['error']}")
                if r["attempts"] >= CONFIG["max_attempts"]:
                    r["gave_up"] = True
                    alerts.append(f"{d.name} / {platform}: {r['error']}")
            save(d, post)

    if alerts:
        # 失敗で止まると、GitHubから本人へメールが届く
        log("\n投稿できなかったもの：\n" + "\n".join(alerts))
        sys.exit(1)


if __name__ == "__main__":
    main()
