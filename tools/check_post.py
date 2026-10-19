"""Threadsの出す前チェック（アカウントごとのルールは rules/*.json、config の threads_check で指定）

add_post.py が予約の前に自動で呼ぶ。原稿だけ先に確かめるときは：
  python3 tools/check_post.py --account umataro --at "2026-10-20 12:00" --caption-file c.txt
  python3 tools/check_post.py --account umataro --at "2026-10-20 20:01" --caption-file c1.txt --threads-reply-to <親のフォルダ名>
止める（NG）と、気をつける（注意）の2段。NGは --override "理由" を付けないと予約できない
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"


def load_rules(account):
    acc = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["accounts"].get(account, {})
    p = acc.get("threads_check")
    return json.loads((ROOT / p).read_text(encoding="utf-8")) if p else None


def _norm(line):
    return re.sub(r"[\s、。！？!?🐎👇🔥🎯🏇🏆]", "", line)


def _lines(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def check(account, caption, when, reply_to="", self_name="", queue=QUEUE):
    """(NGの並び, 注意の並び) を返す。ルールのないアカウントは何もしない"""
    rules = load_rules(account)
    if not rules:
        return [], []
    ng, warn = [], []
    fixed = bool(rules.get("fixed_form_re") and re.search(rules["fixed_form_re"], caption))
    if len(caption) > rules.get("max_len", 500):
        ng.append(f"{len(caption)}字（{rules['max_len']}字まで）")
    for r in rules.get("ng", []):
        if fixed and r.get("skip_in_fixed"):
            continue
        m = re.search(r["re"], caption)
        if m:
            ng.append(f"「{m.group(0)}」：{r['why']}")
    for r in rules.get("warn", []):
        if fixed and r.get("skip_in_fixed"):
            continue
        m = re.search(r["re"], caption)
        if m:
            warn.append(f"「{m.group(0)}」：{r['why']}")
    n = caption.count("！") + caption.count("!")
    if n > rules.get("max_exclaim", 3):
        warn.append(f"「！」が{n}か所（目安は{rules['max_exclaim']}か所まで）")

    lines = _lines(caption)
    if reply_to:
        pj = queue / reply_to / "post.json"
        if pj.exists():
            parent = json.loads(pj.read_text(encoding="utf-8")).get("caption", "")
            if not re.search(rules.get("parent_lead_re", "👇"), parent):
                ng.append(f"親の投稿が続きへ誘導していない：{rules.get('parent_lead_why', '')}")
    elif lines:
        # 直近の同じアカウントのThreadsと、書き出し・締めが被っていないか
        days = rules.get("dup_days", 7)
        first, last = _norm(lines[0]), _norm(lines[-1])
        for pj in sorted(queue.glob(f"*_{account}_*/post.json")):
            if pj.parent.name == self_name:
                continue
            try:
                p = json.loads(pj.read_text(encoding="utf-8"))
                at = datetime.strptime(p["publish_at"][:16], "%Y-%m-%dT%H:%M")
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            if "threads" not in p.get("platforms", ["threads"]) or p.get("threads_reply_to"):
                continue
            if abs(at - when) > timedelta(days=days):
                continue
            pl = _lines(p.get("caption", ""))
            if not pl:
                continue
            if _norm(pl[0]) == first:
                ng.append(f"書き出しが {pj.parent.name} と同じ（直近{days}日は使わない）")
            elif _norm(pl[0])[:8] == first[:8] and len(first) >= 8:
                warn.append(f"書き出しの頭8字が {pj.parent.name} と同じ")
            if _norm(pl[-1]) == last and len(lines) > 1 and not fixed:
                ng.append(f"締めが {pj.parent.name} と同じ（直近{days}日は使わない）")
    return ng, warn


def report(ng, warn):
    for w in warn:
        print(f"  注意  {w}")
    for e in ng:
        print(f"  NG    {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--at", required=True, help='日本時間 "YYYY-MM-DD HH:MM"')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--caption")
    g.add_argument("--caption-file")
    ap.add_argument("--threads-reply-to", default="")
    ap.add_argument("--self", default="", help="予約済みの投稿を確かめ直すときは、そのフォルダ名（自分とは比べない）")
    args = ap.parse_args()
    caption = args.caption if args.caption is not None else Path(args.caption_file).read_text(encoding="utf-8").strip()
    ng, warn = check(args.account, caption, datetime.strptime(args.at, "%Y-%m-%d %H:%M"), args.threads_reply_to, args.self)
    report(ng, warn)
    print("NGあり" if ng else ("OK（注意あり）" if warn else "OK"))
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
