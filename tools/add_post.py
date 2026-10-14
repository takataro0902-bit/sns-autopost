"""1本の投稿を予約に入れる。どの事業のプロジェクトからでも使える汎用の入口。

使い方（例）：
  python3 tools/add_post.py --account lua --at "2026-10-20 20:00" --id futomomo3 \
      --caption-file caption.txt  01.png 02.png 03.png
  python3 tools/add_post.py --account lua --at "2026-10-20 21:00" --id reel5 --caption "本文" reel.mp4
  python3 tools/add_post.py --account lua --at "2026-10-21 13:00" --id post23 --caption-file c.txt post23.zip

・画像（PNG/JPEG）は並べた順に投稿する。zip を渡すと中の画像を名前順に使う（preview を含む名前は除く）
・画像1枚なら image、2〜10枚なら carousel、mp4 ならリール
・画像なしで --platforms threads にすると、Threadsの文字だけの投稿（500字まで）
  例：python3 tools/add_post.py --account umataro --platforms threads --at "2026-10-18 09:00" --id yoso1018 --caption-file yoso.txt
・--platforms discord でDiscordのチャンネルへ（画像あり・文字だけどちらも可。本文2000字まで）
  チャンネルは --discord-channel（config の discord_channels の名前。省略時は最初のもの）。@everyone で知らせるなら --mention-everyone
  例：python3 tools/add_post.py --account umataro --platforms discord --at "2026-10-18 08:00" --id salon1018 --caption-file s.txt 01.png
・日時は日本時間。post.json は ./queue に、画像・動画は ./media（media ブランチ）に置く
・終わったら media → main の順に commit・push する（最後に表示されるコマンド）
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from queue_from_postboard import MAX_VIDEO, MEDIA, QUEUE, ROOT, TZ, ensure_media_worktree, to_jpeg  # noqa: E402

IMG = (".png", ".jpg", ".jpeg")


def collect(paths):
    """(名前, 中身) の並びにする。zip は展開して名前順"""
    items = []
    for p in map(Path, paths):
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                names = sorted(n for n in z.namelist()
                               if n.lower().endswith(IMG + (".mp4",)) and "preview" not in n.lower() and not n.endswith("/"))
                items += [(n, z.read(n)) for n in names]
        else:
            items.append((p.name, p.read_bytes()))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True, help="config.json の accounts の名前（例：lua）")
    ap.add_argument("--at", required=True, help='日本時間 "YYYY-MM-DD HH:MM"')
    ap.add_argument("--id", required=True, help="英数字の短い名前（フォルダ名に使う）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--caption")
    g.add_argument("--caption-file")
    ap.add_argument("--platforms", default="", help="例：instagram,threads（省略時は config の設定）")
    ap.add_argument("--discord-channel", default="", help="Discordの投稿先（config の discord_channels の名前）")
    ap.add_argument("--mention-everyone", action="store_true", help="Discordで @everyone を付けて通知する")
    ap.add_argument("--force", action="store_true", help="同じ予約があれば作り直す（投稿済みは触らない）")
    ap.add_argument("files", nargs="*", help="画像・動画・zip（Threadsの文字だけの投稿なら不要）")
    args = ap.parse_args()

    accounts = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["accounts"]
    if args.account not in accounts:
        sys.exit(f"config.json の accounts に {args.account} がありません")
    when = datetime.strptime(args.at, "%Y-%m-%d %H:%M")
    if when <= datetime.now():
        print("注意：過去の日時です。3時間以内なら次の回ですぐ投稿され、それより前なら投稿されません")
    caption = args.caption if args.caption is not None else Path(args.caption_file).read_text(encoding="utf-8").strip()
    platforms = args.platforms.split(",") if args.platforms else accounts[args.account]["platforms"]
    ig = "instagram" in platforms
    if ig and len(caption) > 2200:
        sys.exit(f"本文が{len(caption)}字です。Instagramは2,200字まで")
    if ig and len(re.findall(r"#\S+", caption)) > 30:
        sys.exit("ハッシュタグが30個を超えています（Instagramは30個まで）")
    extra = {}
    if "discord" in platforms:
        chans = accounts[args.account].get("discord_channels") or {}
        if not chans:
            sys.exit(f"config.json の accounts.{args.account} に discord_channels がありません")
        if args.discord_channel and args.discord_channel not in chans:
            sys.exit(f"discord_channels にないチャンネルです：{args.discord_channel}（あるもの：{', '.join(chans)}）")
        if len(caption) + (10 if args.mention_everyone else 0) > 2000:
            sys.exit(f"本文が{len(caption)}字です。Discordは2000字まで")
        if args.discord_channel:
            extra["discord_channel"] = args.discord_channel
        if args.mention_everyone:
            extra["discord_mention"] = "everyone"

    slug = re.sub(r"[^A-Za-z0-9_-]", "", args.id) or "post"
    name = f"{when:%Y%m%d_%H%M}_{args.account}_{slug}"
    d, md = QUEUE / name, MEDIA / "queue" / name
    pj = d / "post.json"
    if pj.exists():
        old = json.loads(pj.read_text(encoding="utf-8"))
        if any(r.get("id") for r in old.get("result", {}).values()):
            sys.exit(f"{name} は投稿済みなので触りません")
        if not args.force:
            sys.exit(f"{name} はもう入っています。作り直すなら --force")

    if not args.files:
        if not set(platforms) <= {"threads", "discord"}:
            sys.exit("画像・動画がありません（文字だけの投稿は --platforms threads / discord のときだけ）")
        if "threads" in platforms and len(caption) > 500:
            sys.exit(f"本文が{len(caption)}字です。Threadsは500字まで")
        post = {"publish_at": f"{when:%Y-%m-%dT%H:%M:00}{TZ}", "account": args.account, "type": "text",
                "media": [], "caption": caption, "title": args.id, "platforms": platforms, **extra}
        d.mkdir(parents=True, exist_ok=True)
        pj.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"入れました：{name}（{'・'.join(platforms)}の文字だけ・{len(caption)}字）")
        print("次に：git add queue && git commit -m 予約 && git push")
        return

    ensure_media_worktree()
    items = collect(args.files)
    vids = [x for x in items if x[0].lower().endswith(".mp4")]
    imgs = [x for x in items if x[0].lower().endswith(IMG)]
    if vids and imgs or len(vids) > 1:
        sys.exit("動画（リール）は1本だけで、画像と混ぜられません")
    if not items:
        sys.exit("画像・動画が見つかりません")

    shutil.rmtree(md, ignore_errors=True)
    md.mkdir(parents=True)
    try:
        if vids:
            if len(vids[0][1]) > MAX_VIDEO:
                raise ValueError("動画が95MBを超えています。書き出し直しが必要です")
            (md / "01.mp4").write_bytes(vids[0][1])
            media, kind = ["01.mp4"], "reel"
        else:
            if ig and len(imgs) > 10:
                raise ValueError(f"画像が{len(imgs)}枚あります。Instagramは10枚まで")
            media = []
            for i, (_, data) in enumerate(imgs, 1):
                (md / f"{i:02d}.jpg").write_bytes(to_jpeg(data, check_ratio=ig))
                media.append(f"{i:02d}.jpg")
            kind = "image" if len(media) == 1 else "carousel"
    except ValueError as e:
        shutil.rmtree(md)
        sys.exit(f"入れられません：{e}")

    post = {"publish_at": f"{when:%Y-%m-%dT%H:%M:00}{TZ}", "account": args.account, "type": kind,
            "media": media, "caption": caption, "title": args.id, **extra}
    if args.platforms:
        post["platforms"] = args.platforms.split(",")
    d.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"入れました：{name}（{kind}・{len(media)}点・本文{len(caption)}字）")
    print("次に：git -C media add -A && git -C media commit -m 投稿素材 && git -C media push origin media"
          " → git add queue && git commit -m 予約 && git push")


if __name__ == "__main__":
    main()
