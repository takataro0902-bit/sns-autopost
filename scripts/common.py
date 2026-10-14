"""共通の部品：設定の読み込み、HTTP、時刻、画像URLの組み立て。外部ライブラリは使わない。"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# テスト時に差し替えられるよう、APIの置き場所は環境変数でも変えられる
IG_HOST = os.environ.get("IG_HOST", "https://graph.instagram.com")
TH_HOST = os.environ.get("TH_HOST", "https://graph.threads.net")
DC_HOST = os.environ.get("DC_HOST", "https://discord.com")


class ApiError(Exception):
    pass


class NotReady(ApiError):
    """画像・動画のURLがまだ開けないなど、待てば直るもの。失敗回数に数えない"""


def log(*args):
    print(*args, flush=True)


def now_utc():
    fake = os.environ.get("FAKE_NOW")  # テスト用
    if fake:
        return datetime.fromisoformat(fake).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def parse_time(s):
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = datetime.fromisoformat(s + CONFIG["timezone_offset"])
    return dt.astimezone(timezone.utc)


def account_of(post):
    acc = post.get("account")
    if acc not in CONFIG["accounts"]:
        raise ApiError(f"config.json の accounts にないアカウントです：{acc}")
    return acc


def platforms_of(post):
    return post.get("platforms") or CONFIG["accounts"][account_of(post)]["platforms"]


URL_RE = re.compile(r"https?://[^\s　）)」』】>]+")


def rule_problems(account, platforms, texts):
    """config の accounts.<アカウント>.post_rules（アフィリエイト用の守り）に合わない所を並べて返す。
    first_line_prefix：本文の1行目がこれで始まること（PR表記を末尾やハッシュタグに埋もれさせない）
    link_domains：本文のURLはこのドメイン（とそのサブドメイン）だけ（ASPのリンク・短縮URLを直接貼らない）
    banned_words：使わない言葉
    platforms：post_rules のあるアカウントは、config の platforms 以外へは出さない"""
    conf = CONFIG["accounts"].get(account, {})
    rules = conf.get("post_rules")
    if not rules:
        return []
    probs = [f"{p} にはこのアカウントから自動投稿しない設定です" for p in platforms if p not in conf["platforms"]]
    prefix = rules.get("first_line_prefix")
    domains = rules.get("link_domains")
    for label, text in texts:
        if not text:
            continue
        first = text.strip().splitlines()[0] if text.strip() else ""
        if prefix and not first.startswith(prefix):
            probs.append(f"{label}の1行目が「{prefix}」で始まっていません")
        if domains is not None:
            for u in URL_RE.findall(text):
                host = (urllib.parse.urlsplit(u).hostname or "").lower()
                if not any(host == d or host.endswith("." + d) for d in domains):
                    probs.append(f"{label}に許可していないリンクがあります：{u}（使えるのは {', '.join(domains)}）")
        for w in rules.get("banned_words", []):
            if w.lower() in text.lower():
                probs.append(f"{label}に使わない言葉「{w}」が入っています")
    return probs


def post_texts(post):
    """投稿に使われうる本文をすべて（ラベル付きで）返す"""
    return [(k, post.get(k)) for k in ("caption", "threads_caption", "discord_caption") if post.get(k)]


def token(platform, account):
    """Secretsの名前は IG_TOKEN_<アカウント> / THREADS_TOKEN_<アカウント>（例：IG_TOKEN_LUA）。
    ワークフローの env に1つずつ書いて渡す（Secrets全体を渡すとGitHubに「怪しい実行」として止められるため）"""
    name = f"{'IG' if platform == 'instagram' else 'THREADS'}_TOKEN_{account.upper()}"
    value = os.environ.get(name)
    if not value:
        raise ApiError(f"Secrets に {name} がありません")
    return value


def discord_channel(post):
    """post.json の discord_channel（省略時は config の discord_channels の最初）を返す"""
    chans = CONFIG["accounts"][account_of(post)].get("discord_channels") or {}
    ch = post.get("discord_channel") or next(iter(chans), None)
    if ch not in chans:
        raise ApiError(f"config.json の accounts.{account_of(post)}.discord_channels にないチャンネルです：{ch}")
    return ch


def discord_webhook(account, channel):
    """Secretsの名前は DISCORD_WEBHOOK_<アカウント>_<チャンネル>（例：DISCORD_WEBHOOK_UMATARO_MAIN）。
    中身はDiscordの「ウェブフックURLをコピー」で取ったURL。テスト用に DC_HOST で行き先を差し替えられる"""
    name = f"DISCORD_WEBHOOK_{account.upper()}_{channel.upper()}"
    value = os.environ.get(name)
    if not value:
        raise ApiError(f"Secrets に {name} がありません")
    parts = urllib.parse.urlsplit(value)
    return DC_HOST.rstrip("/") + parts.path


def media_base_url():
    """画像・動画を公開するURLの土台。既定は GitHub Pages（https://<owner>.github.io/<repo>/）。"""
    base = os.environ.get("MEDIA_BASE_URL")
    if base:
        return base.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        sys.exit("MEDIA_BASE_URL も GITHUB_REPOSITORY もありません")
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def media_url(post_dir, filename):
    rel = post_dir.relative_to(ROOT).as_posix() + "/" + filename
    return media_base_url() + urllib.parse.quote(rel)


def http(method, url, params=None, timeout=60):
    data = None
    if params is not None:
        body = urllib.parse.urlencode(params).encode()
        if method == "GET":
            url = url + ("&" if "?" in url else "?") + body.decode()
        else:
            data = body
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ApiError(f"HTTP {e.code} {redact(url)}: {raw[:500]}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"接続できません {redact(url)}: {e.reason}") from None
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"raw": raw}


def redact(url):
    """ログにトークン（DiscordはURLの最後の部分）が出ないようにする"""
    p = urllib.parse.urlsplit(url)
    if "/webhooks/" in p.path:
        p = p._replace(path=p.path.rsplit("/", 1)[0] + "/***")
    q = [(k, "***" if "token" in k or "secret" in k else v) for k, v in urllib.parse.parse_qsl(p.query)]
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q)))


def url_is_reachable(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def wait_until(check, label, tries=10, interval=30):
    """コンテナの処理完了を待つ（公式の目安：1分おき・最大5分。ここでは30秒おき・最大5分）"""
    for _ in range(tries):
        status = check()
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(f"{label} の処理が失敗しました（{status}）")
        time.sleep(float(os.environ.get("POLL_INTERVAL", interval)))
    raise ApiError(f"{label} の処理が5分以内に終わりませんでした")
