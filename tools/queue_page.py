"""予約の一覧をスマホで見られる1枚のHTMLにする（本文・画像・続き・出た/待ち）。

使い方：python3 tools/queue_page.py --account umataro --platform threads --days 2 --out page.html
画像は media/queue/<フォルダ>/ から埋め込む（先に git -C media pull）
"""
import argparse
import base64
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE, MEDIA = ROOT / "queue", ROOT / "media" / "queue"
JST = timezone(timedelta(hours=9))
WD = "月火水木金土日"

CSS = """
<title>うま太郎 予約中の投稿</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@700;900&family=Noto+Sans+JP:wght@400;700&display=swap">
<style>
/* 紙×墨のブランドに合わせた、スマホ1列の予約フィード。日ごとに区切り、続きは親の下に字下げ */
:root{--bg:#f4efe4;--card:#fffdf8;--ink:#151310;--sub:#6b6458;--line:#d9d0bd;--red:#b2221e;--ok:#2f6b3a;--wait:#8a6d2b;
--disp:"Zen Old Mincho","Hiragino Mincho ProN",serif;--body:"Noto Sans JP","Hiragino Sans",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171512;--card:#211e1a;--ink:#efe8da;--sub:#a59c8c;--line:#3a352d;--red:#e0605a;--ok:#7cc48a;--wait:#d8b56a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#171512;--card:#211e1a;--ink:#efe8da;--sub:#a59c8c;--line:#3a352d;--red:#e0605a;--ok:#7cc48a;--wait:#d8b56a;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--body);line-height:1.7}
.wrap{max-width:560px;margin:0 auto;padding-block:20px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:18px}
h1{font-family:var(--disp);font-weight:900;font-size:1.6rem;margin:0;text-wrap:balance}
.meta{color:var(--sub);font-size:.8rem;margin-top:2px}
h2{font-family:var(--disp);font-size:1.15rem;margin:14px 0 0;padding-bottom:6px;border-bottom:2px solid var(--ink)}
.post{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:.82rem}
.time{font-weight:700;font-variant-numeric:tabular-nums;font-size:1rem}
.pill{border:1px solid currentColor;border-radius:99px;padding:0 9px;font-size:.75rem;font-weight:700}
.st-done{color:var(--ok)}.st-wait{color:var(--wait)}.st-fail{color:var(--red)}
.id{color:var(--sub);font-size:.72rem;margin-left:auto;word-break:break-all}
.cap{white-space:pre-wrap;word-break:break-word;font-size:.95rem;min-width:0}
.post img{width:100%;border-radius:6px;border:1px solid var(--line)}
.replies{display:flex;flex-direction:column;gap:10px;margin-left:14px;padding-left:12px;border-left:2px solid var(--line)}
.reply .top{font-size:.78rem}.reply .cap{font-size:.9rem}
.lab{font-size:.72rem;color:var(--sub);letter-spacing:.08em}
.empty{color:var(--sub)}
</style>
"""


def esc(s):
    return html.escape(s or "")


def status(post, plat):
    r = post.get("result", {}).get(plat, {})
    if r.get("id"):
        return "st-done", "出た"
    if r.get("gave_up") or r.get("attempts"):
        return "st-fail", "失敗" if r.get("gave_up") else "やり直し中"
    return "st-wait", "待ち"


def img_tags(name, post):
    out = []
    for m in post.get("media", []):
        f = MEDIA / name / m
        if f.exists() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            mime = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
            out.append(f'<img alt="投稿の画像" src="data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}">')
    return "".join(out)


def card(name, post, plat, cls="post"):
    when = datetime.fromisoformat(post["publish_at"]).astimezone(JST)
    sc, st = status(post, plat)
    return (f'<div class="{cls}"><div class="top"><span class="time">{when:%H:%M}</span>'
            f'<span class="pill {sc}">{st}</span><span class="id">{esc(post.get("title"))}</span></div>'
            f'<div class="cap">{esc(post.get("caption"))}</div>{img_tags(name, post)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--platform", default="threads")
    ap.add_argument("--days", type=int, default=1, help="何日前の分から出すか")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    since = (datetime.now(JST) - timedelta(days=a.days)).replace(hour=0, minute=0)
    posts = {}
    for pj in sorted(QUEUE.glob(f"*_{a.account}_*/post.json")):
        p = json.loads(pj.read_text(encoding="utf-8"))
        if a.platform in (p.get("platforms") or [a.platform]) and datetime.fromisoformat(p["publish_at"]) >= since:
            posts[pj.parent.name] = p
    kids = {}
    for n, p in posts.items():
        if p.get("threads_reply_to") in posts:
            kids.setdefault(p["threads_reply_to"], []).append(n)
    body, day = [], None
    for n, p in posts.items():
        if p.get("threads_reply_to") in posts:
            continue
        d = datetime.fromisoformat(p["publish_at"]).astimezone(JST)
        if d.date() != day:
            day = d.date()
            body.append(f"<h2>{d.month}/{d.day}（{WD[d.weekday()]}）</h2>")
        html_ = card(n, p, a.platform)
        if kids.get(n):
            html_ += '<div class="lab">続き（コメント欄に自分で返信）</div><div class="replies">' + "".join(
                card(k, posts[k], a.platform, "reply") + "</div>" for k in sorted(kids[n])) + "</div>"
        body.append(html_ + "</div>")
    now = datetime.now(JST)
    page = (CSS + f'<div class="wrap"><div><h1>予約中の投稿</h1><div class="meta">{a.platform.capitalize()}・'
            f'{since:%m/%d}から・{now:%m/%d %H:%M}時点。「待ち」は予約済みでまだ出ていない投稿</div></div>'
            + ("".join(body) or '<p class="empty">この期間の予約はありません</p>') + "</div>")
    Path(a.out).write_text(page, encoding="utf-8")
    print(f"{len(posts)}本 → {a.out}")


if __name__ == "__main__":
    sys.exit(main())
