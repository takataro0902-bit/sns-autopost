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
  チャンネルは --discord-channel（config の discord_channels のキー。例 news・yoso・zento・course。チャンネルが1つの事業だけ省略可）。
  @everyone で知らせるなら --mention-everyone。投稿にスレッドを付けるなら --discord-thread-name "富士S 質問はこちら"（ボットのみ）。
  前に出した投稿のスレッドに書くなら --discord-in-thread <そのフォルダ名>
  例：python3 tools/add_post.py --account umataro --platforms discord --discord-channel news --at "2026-10-18 08:00" --id salon1018 --caption-file s.txt 01.png
・--threads-reply-to <親のフォルダ名> で、Threadsの「続き」（自分の投稿への返信）として出す。親より1〜2分後の時刻にする
  例：python3 tools/add_post.py --account umataro --platforms threads --at "2026-10-20 20:01" --id kiku-c1 \
        --threads-reply-to 20261020_2000_umataro_kiku --caption-file c1.txt
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
    ap.add_argument("--discord-channel", default="", help="Discordの投稿先（config の discord_channels のキー）")
    ap.add_argument("--discord-thread-name", default="", help="Discordで、この投稿にスレッドを作る（その名前）")
    ap.add_argument("--discord-in-thread", default="", help="Discordで、前に出した投稿（フォルダ名）のスレッドに書く")
    ap.add_argument("--mention-everyone", action="store_true", help="Discordで @everyone を付けて通知する")
    ap.add_argument("--threads-reply-to", default="", help="Threadsで、前に予約した投稿（フォルダ名）の続き＝自分の返信として出す。親より後の時刻にする")
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
        if not args.discord_channel and len(chans) > 1:
            sys.exit("--discord-channel を指定してください：" + "、".join(f"{k}={v}" for k, v in chans.items()))
        if args.discord_in_thread and not (QUEUE / args.discord_in_thread / "post.json").exists():
            sys.exit(f"--discord-in-thread のフォルダがありません：{args.discord_in_thread}")
        if len(caption) + (10 if args.mention_everyone else 0) > 2000:
            sys.exit(f"本文が{len(caption)}字です。Discordは2000字まで")
        if args.discord_channel:
            extra["discord_channel"] = args.discord_channel
        if args.mention_everyone:
            extra["discord_mention"] = "everyone"
        if args.discord_thread_name:
            extra["discord_thread_name"] = args.discord_thread_name
        if args.discord_in_thread:
            extra["discord_in_thread"] = args.discord_in_thread

    if args.threads_reply_to:
        if platforms != ["threads"]:
            sys.exit("--threads-reply-to は --platforms threads のときだけ使えます")
        ppj = QUEUE / args.threads_reply_to / "post.json"
        if not ppj.exists():
            sys.exit(f"--threads-reply-to のフォルダがありません：{args.threads_reply_to}")
        parent_at = datetime.strptime(json.loads(ppj.read_text(encoding="utf-8"))["publish_at"][:16], "%Y-%m-%dT%H:%M")
        if when <= parent_at:
            sys.exit(f"続きは親（{parent_at:%m/%d %H:%M}）より後の時刻にしてください（1〜2分後がおすすめ）")
        extra["threads_reply_to"] = args.threads_reply_to

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
