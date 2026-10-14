"""模擬APIで publish.py / cleanup.py / queue_from_postboard.py を確かめる"""
import io, json, os, shutil, subprocess, sys, tempfile, threading, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

KIT = Path(sys.argv[1]).resolve()
STATE = {"calls": [], "existing": [], "media_ok": True, "fail_create": False}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_HEAD(self):
        self.send_response(200 if STATE["media_ok"] else 404); self.end_headers()
    def do_GET(self):
        u = urlsplit(self.path); q = parse_qs(u.query); STATE["calls"].append(("GET", u.path, q))
        if u.path.endswith("/me"): return self._send(200, {"user_id": "IG123", "id": "TH1", "username": "lua"})
        if u.path.endswith("/media") or u.path.endswith("/threads"): return self._send(200, {"data": STATE["existing"]})
        return self._send(200, {"status_code": "FINISHED", "status": "FINISHED"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n)
        if "/webhooks/" in self.path:  # Discord（multipart）
            STATE["calls"].append(("DISCORD", self.path, raw, self.headers.get("User-Agent")))
            return self._send(200, {"id": f"M{len(STATE['calls'])}"})
        q = parse_qs(raw.decode())
        u = urlsplit(self.path); STATE["calls"].append(("POST", u.path, q))
        if STATE["fail_create"]: return self._send(400, {"error": {"message": "bad"}})
        return self._send(200, {"id": f"C{len(STATE['calls'])}"})

srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

def setup():
    tmp = Path(tempfile.mkdtemp()); repo = tmp / "repo"; shutil.copytree(KIT, repo, ignore=shutil.ignore_patterns(".git", "media", "__pycache__"))
    for d in (repo / "queue").iterdir():  # 本物の予約はテストに持ち込まない
        if d.is_dir(): shutil.rmtree(d)
    return repo

def run(repo, script, *args, env=None):
    e = dict(os.environ, IG_HOST=base, TH_HOST=base, DC_HOST=base, MEDIA_BASE_URL=base + "/pages/", IG_TOKEN_LUA="tok", THREADS_TOKEN_LUA="t", POLL_INTERVAL="0", FAKE_NOW="2026-10-20T13:05:00+09:00")
    e.update(env or {})
    return subprocess.run([sys.executable, str(repo / script), *args], env=e, capture_output=True, text=True)

def add_post(repo, name="20261020_1300_a", **kw):
    d = repo / "queue" / name; d.mkdir(parents=True, exist_ok=True)
    post = {"publish_at": "2026-10-20T13:00:00+09:00", "type": "carousel", "media": ["01.jpg", "02.jpg"], "caption": "本文です\n#dress", "account": "lua"}
    post.update(kw); (d / "post.json").write_text(json.dumps(post, ensure_ascii=False))
    return d

def result(d): return json.loads((d / "post.json").read_text())["result"]
ok = True
def check(label, cond, extra=""):
    global ok; print(("OK  " if cond else "NG  ") + label, extra if not cond else ""); ok &= bool(cond)

# 1 通常のカルーセル（IG_USER_ID 空でも /me で解決）
STATE.update(calls=[], existing=[], media_ok=True, fail_create=False)
r = setup(); d = add_post(r); p = run(r, "scripts/publish.py")
res = result(d)
check("カルーセル投稿", res["instagram"].get("id") and p.returncode == 0, p.stdout + p.stderr)
check("IGのユーザーIDを /me で取って /IG123/media を使う", any(c[1].endswith("/IG123/media") and c[0] == "POST" for c in STATE["calls"]))

# 2 URLがまだ開けない → 回数に数えない
STATE.update(calls=[], media_ok=False)
r = setup(); d = add_post(r); p = run(r, "scripts/publish.py"); res = result(d)["instagram"]
check("URL待ちは失敗回数に数えない", "attempts" not in res and not res.get("gave_up"), res)

# 3 二重投稿よけ
STATE.update(calls=[], media_ok=True, existing=[{"id": "OLD9", "caption": "本文です\n#dress", "timestamp": "2026-10-20T04:01:00+0000"}])
r = setup(); d = add_post(r); p = run(r, "scripts/publish.py"); res = result(d)["instagram"]
check("すでに出ていれば作らずIDだけ記録", res.get("id") == "OLD9" and not any(c[0] == "POST" for c in STATE["calls"]), res)

# 4 3回失敗で諦めてエラー終了
STATE.update(calls=[], existing=[], fail_create=True)
r = setup(); d = add_post(r)
for _ in range(3): p = run(r, "scripts/publish.py")
res = result(d)["instagram"]
check("3回失敗で諦める・メール用にエラー終了", res.get("gave_up") and res.get("attempts") == 3 and p.returncode == 1, res)

# 5 遅れすぎ
STATE.update(fail_create=False)
r = setup(); d = add_post(r); p = run(r, "scripts/publish.py", env={"FAKE_NOW": "2026-10-20T16:30:00+09:00"})
check("3時間過ぎたら投稿しない", result(d)["instagram"].get("gave_up") and p.returncode == 1)

# 6 Threads（ハッシュタグ行を外す）
STATE.update(calls=[])
r = setup(); d = add_post(r, type="image", media=["01.jpg"], platforms=["threads"])
p = run(r, "scripts/publish.py")
texts = [c[2].get("text", [""])[0] for c in STATE["calls"] if c[0] == "POST" and c[1].endswith("/me/threads")]
check("Threads投稿（本文からハッシュタグ行を除く）", result(d)["threads"].get("id") and texts == ["本文です"], (p.stdout, texts))

# 7 後片付け
r = setup(); m = r / "media" / "queue"
d1 = add_post(r, "20261001_1300_a", publish_at="2026-10-01T13:00:00+09:00"); j = json.loads((d1 / "post.json").read_text()); j["result"] = {"instagram": {"id": "1"}}; (d1 / "post.json").write_text(json.dumps(j))
add_post(r, "20261019_1300_b", publish_at="2026-10-19T13:00:00+09:00")
for n in ("20261001_1300_a", "20261019_1300_b", "20260901_1300_orphan"): (m / n).mkdir(parents=True); (m / n / "01.jpg").write_text("x")
p = run(r, "scripts/cleanup.py", str(r / "media"))
left = sorted(x.name for x in m.iterdir())
check("後片付け：済み・古い・予定なしだけ消す", left == ["20261019_1300_b"], (left, p.stdout, p.stderr))

# 8 投稿表から queue を作る（media ブランチ用フォルダも用意）
r = setup()
subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
subprocess.run(["git", "-C", str(r), "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
src = r.parent / "src"; src.mkdir()
from PIL import Image
def png(w, h):
    b = io.BytesIO(); Image.new("RGBA", (w, h), (200, 0, 0, 255)).save(b, "PNG"); return b.getvalue()
with zipfile.ZipFile(src / "c.zip", "w") as z: z.writestr("1.png", png(1080, 1350)); z.writestr("2.png", png(1080, 1350)); z.writestr("preview.png", png(10, 10))
with zipfile.ZipFile(src / "bad.zip", "w") as z: z.writestr("1.png", png(1080, 1920))
days = [{"date": "2026-10-20", "posts": [
    {"id": "c1", "time": "13:00", "kind": "carousel", "zip": "c.zip", "caption": "本文"},
    {"id": "b1", "time": "19:00", "kind": "carousel", "zip": "bad.zip", "caption": "本文"},
    {"id": "r1", "time": "21:00", "kind": "reel", "zip": "none.zip", "caption": "本文"}]}]
(src / "days.json").write_text(json.dumps(days, ensure_ascii=False))
p = run(r, "tools/queue_from_postboard.py", "--account", "lua", "--from", "2026-10-20", "--to", "2026-10-26", "--days", str(src / "days.json"), "--zips", str(src))
qd = r / "queue" / "20261020_1300_lua_c1"; md = r / "media" / "queue" / "20261020_1300_lua_c1"
check("queue作成：post.jsonはmain・画像はmediaに", (qd / "post.json").exists() and sorted(x.name for x in md.iterdir()) == ["01.jpg", "02.jpg"] and not (qd / "01.jpg").exists(), p.stdout + p.stderr)
check("縦長すぎ・zipなしは入れない", "縦横比" in p.stdout and "zipが見つからない" in p.stdout and not (r / "queue" / "20261020_1900_lua_b1").exists() and not (r / "media" / "queue" / "20261020_1900_lua_b1").exists(), p.stdout)
br = subprocess.run(["git", "-C", str(r / "media"), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
check("media ブランチを用意", br == "media" and (r / "media" / "ok.txt").exists(), br)

# 9 知らないアカウント・トークンなし
STATE.update(calls=[])
r = setup(); d = add_post(r, account="keiba"); p = run(r, "scripts/publish.py")
check("configにないアカウントはエラーで知らせる", p.returncode == 1 and "keiba" in p.stdout, p.stdout)
r = setup(); d = add_post(r); p = run(r, "scripts/publish.py", env={"IG_TOKEN_LUA": ""})
check("トークンがなければ失敗に数える", "IG_TOKEN_LUA" in result(d)["instagram"].get("error", ""), result(d))

# 10 トークン延長（gh は偽物に差し替え）
r = setup(); fake = r.parent / "bin"; fake.mkdir(); (fake / "gh").write_text("#!/bin/sh\necho \"$@\" >> " + str(r.parent / "gh.log") + "\n"); (fake / "gh").chmod(0o755)
H.do_GET_orig = H.do_GET
def g(self):
    if "refresh_access_token" in self.path: return self._send(200, {"access_token": "NEW", "expires_in": 5184000})
    return H.do_GET_orig(self)
H.do_GET = g
p = run(r, "scripts/refresh_tokens.py", env={"PATH": f"{fake}:{os.environ['PATH']}", "IG_TOKEN_LUA": "a", "THREADS_TOKEN_LUA": "", "THREADS_TOKEN_KEIBA": "b", "GH_PAT": "x"})
log = (r.parent / "gh.log").read_text()
check("IG_TOKEN_*・THREADS_TOKEN_* を全部延長", "IG_TOKEN_LUA" in log and "THREADS_TOKEN_KEIBA" in log and "GH_PAT" not in log, (p.stdout, log))
def g2(self):
    if "/access_token" in self.path and "th_exchange_token" in self.path:
        if "SHORT" in self.path: return self._send(200, {"access_token": "LONG", "expires_in": 5184000})
        return self._send(400, {"error": {"message": "not short-lived"}})
    return g(self)
H.do_GET = g2
(r.parent / "gh.log").write_text("")
p = run(r, "scripts/refresh_tokens.py", env={"PATH": f"{fake}:{os.environ['PATH']}", "IG_TOKEN_LUA": "", "THREADS_TOKEN_UMATARO": "SHORT", "THREADS_TOKEN_KEIBA": "b", "THREADS_APP_SECRET": "s", "GH_PAT": "x"})
log = (r.parent / "gh.log").read_text()
check("Threadsの短期トークンは長期に交換・長期のものはふつうに延長", "THREADS_TOKEN_UMATARO --body LONG" in log and "THREADS_TOKEN_KEIBA --body NEW" in log and p.returncode == 0, (p.stdout, log))
H.do_GET = g

# 11 汎用の入口 add_post.py
r = setup()
subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
subprocess.run(["git", "-C", str(r), "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
src = r.parent / "src2"; src.mkdir()
with zipfile.ZipFile(src / "c.zip", "w") as z: z.writestr("b.png", png(1080, 1350)); z.writestr("a.png", png(1080, 1350))
(src / "v.mp4").write_bytes(b"0" * 100)
(src / "cap.txt").write_text("本文\n#a #b", encoding="utf-8")
p1 = run(r, "tools/add_post.py", "--account", "lua", "--at", "2099-01-02 20:00", "--id", "c1", "--caption-file", str(src / "cap.txt"), str(src / "c.zip"))
p2 = run(r, "tools/add_post.py", "--account", "lua", "--at", "2099-01-02 21:00", "--id", "r1", "--caption", "リール", str(src / "v.mp4"))
p3 = run(r, "tools/add_post.py", "--account", "keiba", "--at", "2099-01-02 21:00", "--id", "x", "--caption", "x", str(src / "v.mp4"))
j1 = json.loads((r / "queue" / "20990102_2000_lua_c1" / "post.json").read_text())
j2 = json.loads((r / "queue" / "20990102_2100_lua_r1" / "post.json").read_text())
check("add_post：zip→カルーセル・mp4→リール・知らない事業は断る",
      j1["type"] == "carousel" and j1["media"] == ["01.jpg", "02.jpg"] and j1["caption"] == "本文\n#a #b" and j1["publish_at"] == "2099-01-02T20:00:00+09:00"
      and j2["type"] == "reel" and (r / "media" / "queue" / "20990102_2100_lua_r1" / "01.mp4").exists() and p3.returncode != 0,
      (p1.stdout, p1.stderr, p2.stderr, p3.stderr))
p5 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "threads", "--at", "2099-01-03 09:00", "--id", "yoso", "--caption", "今日の予想")
j5 = json.loads((r / "queue" / "20990103_0900_umataro_yoso" / "post.json").read_text())
p6 = run(r, "tools/add_post.py", "--account", "umataro", "--at", "2099-01-03 10:00", "--id", "x", "--caption", "x")
check("add_post：Threadsの文字だけの投稿・Instagram込みなら画像必須", j5["type"] == "text" and j5["media"] == [] and p6.returncode != 0, (p5.stderr, p6.stderr))
p4 = run(r, "tools/list_queue.py")
check("list_queue：予約が見える", "c1" in p4.stdout and "lua" in p4.stdout, p4.stdout + p4.stderr)

# 12 Threadsの文字だけの投稿を出す
STATE.update(calls=[], existing=[], fail_create=False)
r = setup(); d = add_post(r, "20261020_1300_umataro_t", account="umataro", type="text", media=[], caption="予想です", platforms=["threads"])
p = run(r, "scripts/publish.py", env={"THREADS_TOKEN_UMATARO": "t"})
posts = [c[2] for c in STATE["calls"] if c[0] == "POST" and c[1].endswith("/me/threads")]
check("Threadsの文字だけの投稿", result(d)["threads"].get("id") and posts and posts[0].get("media_type") == ["TEXT"], (p.stdout, posts))

# 13 Discord（ウェブフック）
STATE.update(calls=[], existing=[], fail_create=False, media_ok=True)
hook = {"DISCORD_WEBHOOK_UMATARO_MAIN": "https://discord.com/api/webhooks/123/SECRETTOKEN"}
r = setup(); d = add_post(r, "20261020_1300_umataro_d", account="umataro", type="carousel", media=[f"{i:02d}.jpg" for i in range(1, 13)],
                     caption="今日の予想\n#競馬", platforms=["discord"], discord_mention="everyone")
p = run(r, "scripts/publish.py", env=hook)
dc = [c for c in STATE["calls"] if c[0] == "DISCORD"]
first = dc[0][2] if dc else b""
check("Discord：12枚は10枚＋2枚に分けて送り、本文は1通目だけ・ハッシュタグ行を外す・@everyone",
      len(dc) == 2 and result(d)["discord"].get("id") == ",".join(f"M{STATE['calls'].index(c) + 1}" for c in dc)
      and '"content": "@everyone\\n今日の予想"'.encode() in first and "#競馬".encode() not in first and b'"parse": ["everyone"]' in first
      and first.count(b'name="files[') == 10 and dc[1][2].count(b'name="files[') == 2 and b'"content"' not in dc[1][2]
      and dc[0][1] == "/api/webhooks/123/SECRETTOKEN?wait=true" and dc[0][3].startswith("DiscordBot"), (p.stdout, [c[1] for c in dc]))
STATE.update(calls=[])
r = setup(); d = add_post(r, "20261020_1300_umataro_e", account="umataro", type="text", media=[], caption="お知らせ", platforms=["discord"])
p = run(r, "scripts/publish.py", env=hook)
dc = [c for c in STATE["calls"] if c[0] == "DISCORD"]
check("Discord：文字だけ・@everyoneなしなら通知を抑える", len(dc) == 1 and result(d)["discord"].get("id") and b'"parse": []' in dc[0][2], (p.stdout, dc))
r = setup(); d = add_post(r, "20261020_1300_umataro_f", account="umataro", type="text", media=[], caption="x", platforms=["discord"])
p = run(r, "scripts/publish.py")
err = result(d)["discord"].get("error", "")
check("Discord：URLがなければ名前を知らせ、URLはログに出さない", "DISCORD_WEBHOOK_UMATARO_MAIN" in err and "SECRETTOKEN" not in p.stdout + err, err)
r = setup()
subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
subprocess.run(["git", "-C", str(r), "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
p7 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "discord", "--at", "2099-01-03 08:00", "--id", "salon", "--caption", "朝のお知らせ", "--mention-everyone")
j7 = json.loads((r / "queue" / "20990103_0800_umataro_salon" / "post.json").read_text())
(src / "tall.png").write_bytes(png(1080, 1920))
p8 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "discord", "--at", "2099-01-03 09:00", "--id", "tall", "--caption", "縦長", str(src / "tall.png"))
p9 = run(r, "tools/add_post.py", "--account", "lua", "--platforms", "discord", "--at", "2099-01-03 09:00", "--id", "x", "--caption", "x")
check("add_post：Discordの文字だけ・縦長画像OK・Discord未設定の事業は断る",
      j7["type"] == "text" and j7["platforms"] == ["discord"] and j7["discord_mention"] == "everyone" and p8.returncode == 0 and p9.returncode != 0,
      (p7.stderr, p8.stdout + p8.stderr, p9.stderr))

print("\n全部OK" if ok else "\nNGあり"); sys.exit(0 if ok else 1)
