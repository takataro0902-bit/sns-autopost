"""投稿表（days.json）と各zipから、予約投稿の待ち行列（queue/）を作る。Claudeが1週間分づくりのあとに使う。
どの事業でも、投稿表を同じ形（日付ごとに posts：id・time・kind・zip・caption）で作れば使える。

使い方（例：LUA GINZA）：
  python3 tools/queue_from_postboard.py --account lua --from 2026-10-20 --to 2026-10-26
      --days /mnt/project-files/lua-ginza/posts/_src/postboard/days.json
      --zips /mnt/project-files/lua-ginza [--platforms instagram,threads]

・zipと本文（caption）がそろった投稿だけを入れる。足りないものは「入れなかった」と一覧で出す。
・PNGはJPEGに変換する（InstagramのAPIはJPEGのみ）。ファイル名は 01.jpg… の英数字にする。
・同じ投稿がすでに queue にあれば上書きしない（--force で上書き。投稿済みのものは常に触らない）。
・post.json は main の queue/ に、画像・動画は media ブランチ（./media に取り出す）の queue/ に置く。
  ./media がなければ自動で用意する。終わったら media → main の順に commit・push する。
・動画は95MBまで（GitHubは100MBを超えるファイルをpushできないため）。
"""
import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
MEDIA = ROOT / "media"
TZ = "+09:00"
MAX_VIDEO = 95 * 1024 * 1024


def ensure_media_worktree():
    """media ブランチを ./media に取り出す（なければ空のブランチを作る）"""
    if (MEDIA / ".git").exists():
        return
    git = ["git", "-C", str(ROOT)]
    has_remote = subprocess.run(git + ["fetch", "origin", "media"], capture_output=True).returncode == 0
    if has_remote:
        subprocess.run(git + ["worktree", "add", "-B", "media", str(MEDIA), "origin/media"], check=True)
    else:
        subprocess.run(git + ["worktree", "add", "--orphan", "-b", "media", str(MEDIA)], check=True)
    for name, body in ((".nojekyll", ""), ("ok.txt", "ok\n")):
        if not (MEDIA / name).exists():
            (MEDIA / name).write_text(body)


def to_jpeg(data):
    im = Image.open(io.BytesIO(data))
    if im.mode != "RGB":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.convert("RGBA").split()[-1])
        im = bg
    w, h = im.size
    if not 0.8 <= w / h <= 1.91:  # Instagramの許容は 4:5〜1.91:1
        raise ValueError(f"縦横比が範囲外です（{w}x{h}）")
    if w > 1440:
        im = im.resize((1440, round(h * 1440 / w)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92, optimize=True)
    if out.tell() > 8 * 1024 * 1024:
        raise ValueError("8MBを超えています")
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--account", required=True, help="config.json の accounts の名前（例：lua）")
    ap.add_argument("--days", required=True, help="投稿表 days.json")
    ap.add_argument("--zips", required=True, help="各投稿のzipがあるフォルダ")
    ap.add_argument("--platforms", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    accounts = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["accounts"]
    if args.account not in accounts:
        sys.exit(f"config.json の accounts に {args.account} がありません（先に足してください）")
    ensure_media_worktree()
    days = json.loads(Path(args.days).read_text(encoding="utf-8"))
    added, skipped = [], []
    for day in days:
        if not args.start <= day["date"] <= args.end:
            continue
        for p in day["posts"]:
            label = f"{day['date']} {p.get('time')} {p.get('title', '')}"
            kind = {"carousel": "carousel", "reel": "reel", "image": "image"}.get(p.get("kind"))
            if not kind:
                skipped.append(f"{label}（お休み・素材待ち）")
                continue
            if not (p.get("zip") and p.get("caption") and re.fullmatch(r"\d{1,2}:\d{2}", p.get("time", ""))):
                skipped.append(f"{label}（zip・本文・時刻のどれかがない）")
                continue
            zpath = Path(args.zips) / p["zip"]
            if not zpath.exists():
                skipped.append(f"{label}（zipが見つからない：{p['zip']}）")
                continue

            hh, mm = p["time"].split(":")
            slug = re.sub(r"[^A-Za-z0-9_-]", "", p.get("id", "post"))
            name = f"{day['date'].replace('-', '')}_{int(hh):02d}{mm}_{args.account}_{slug}"
            d = QUEUE / name
            md = MEDIA / "queue" / name
            pj = d / "post.json"
            if pj.exists():
                old = json.loads(pj.read_text(encoding="utf-8"))
                if any(r.get("id") for r in old.get("result", {}).values()):
                    skipped.append(f"{label}（投稿済みなので触らない）")
                    continue
                if not args.force:
                    skipped.append(f"{label}（もう入っている。作り直すなら --force）")
                    continue
                shutil.rmtree(d)
            shutil.rmtree(md, ignore_errors=True)
            md.mkdir(parents=True)

            def give_up(reason):
                skipped.append(f"{label}（{reason}）")
                shutil.rmtree(md)

            media = []
            with zipfile.ZipFile(zpath) as z:
                names = sorted(n for n in z.namelist() if not n.endswith("/"))
                if kind == "reel":
                    vids = [n for n in names if n.lower().endswith(".mp4")]
                    if not vids:
                        give_up("zipに動画がない")
                        continue
                    if z.getinfo(vids[0]).file_size > MAX_VIDEO:
                        give_up("動画が95MBを超えている。書き出し直しが必要")
                        continue
                    (md / "01.mp4").write_bytes(z.read(vids[0]))
                    media = ["01.mp4"]
                else:
                    imgs = [n for n in names if n.lower().endswith((".png", ".jpg", ".jpeg")) and "preview" not in n.lower()]
                    try:
                        for i, n in enumerate(imgs, 1):
                            (md / f"{i:02d}.jpg").write_bytes(to_jpeg(z.read(n)))
                            media.append(f"{i:02d}.jpg")
                    except ValueError as e:
                        give_up(f"画像の問題：{e}")
                        continue
                    if not media:
                        give_up("zipに画像がない")
                        continue
                    if len(media) == 1:
                        kind = "image"
                    if len(media) > 10:
                        give_up(f"画像が{len(media)}枚。Instagramは10枚まで")
                        continue

            post = {
                "publish_at": f"{day['date']}T{int(hh):02d}:{mm}:00{TZ}",
                "account": args.account,
                "type": kind,
                "media": media,
                "caption": p["caption"],
                "title": p.get("title", ""),
            }
            if args.platforms:
                post["platforms"] = args.platforms.split(",")
            d.mkdir(parents=True, exist_ok=True)
            pj.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            added.append(f"{label} → {d.name}（{kind}・{len(media)}点）")

    print("入れたもの：")
    print("\n".join("  " + a for a in added) or "  なし")
    print("入れなかったもの：")
    print("\n".join("  " + s for s in skipped) or "  なし")
    if added:
        print("次に：git -C media add -A && git -C media commit -m 投稿素材 && git -C media push -u origin media"
              " → git add queue && git commit -m 予約 && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
