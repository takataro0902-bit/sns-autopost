"""模擬APIで publish.py / cleanup.py / queue_from_postboard.py を確かめる"""
import io, json, os, shutil, subprocess, sys, tempfile, threading, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

KIT = Path(sys.argv[1]).resolve()
STATE = {"calls": [], "existing": [], "media_ok": True, "fail_create": False,
         "guild_channels": [{"id": "C1", "name": "📣お知らせ", "type": 0}, {"id": "C2", "name": "🏆重賞の全頭診断", "type": 0},
                            {"id": "C3", "name": "🎯みんなの予想・的中", "type": 0}, {"id": "C4", "name": "🐎倶楽部コンテンツ", "type": 4},
                            {"id": "C5", "name": "新しい部屋", "type": 0}]}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_HEAD(self):
        self.send_response(200 if STATE["media_ok"] else 404); self.end_headers()
    def do_GET(self):
        u = urlsplit(self.path); q = parse_qs(u.query); STATE["calls"].append(("GET", u.path, q))
        if u.path.startswith("/api/v10/"):  # Discordボット
            STATE["calls"][-1] = ("BOTGET", u.path, self.headers.get("Authorization"))
            if u.path.endswith("/users/@me/guilds"): return self._send(200, [{"id": "G1", "name": "うま太郎倶楽部"}])
            if u.path.endswith("/guilds/G1/channels"): return self._send(200, STATE["guild_channels"])
        if u.path.endswith("/me"): return self._send(200, {"user_id": "IG123", "id": "TH1", "username": "lua"})
        if u.path.endswith("/media") or u.path.endswith("/threads") or u.path.endswith("/replies"): return self._send(200, {"data": STATE["existing"]})
        return self._send(200, {"status_code": "FINISHED", "status": "FINISHED"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n)
        if self.path.startswith("/api/v10/channels/"):  # Discordボット
            STATE["calls"].append(("BOT", self.path, raw, self.headers.get("Authorization")))
            if STATE.get("bot_fail"): return self._send(403, {"message": "Missing Permissions"})
            return self._send(200, {"id": f"B{len(STATE['calls'])}"})
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
hook = {"DISCORD_WEBHOOK_UMATARO_COURSE": "https://discord.com/api/webhooks/123/SECRETTOKEN"}
r = setup(); d = add_post(r, "20261020_1300_umataro_d", account="umataro", type="carousel", media=[f"{i:02d}.jpg" for i in range(1, 13)],
                     caption="今日の予想\n#競馬", platforms=["discord"], discord_mention="everyone", discord_channel="course")
p = run(r, "scripts/publish.py", env=hook)
dc = [c for c in STATE["calls"] if c[0] == "DISCORD"]
first = dc[0][2] if dc else b""
check("Discord：12枚は10枚＋2枚に分けて送り、本文は1通目だけ・ハッシュタグ行を外す・@everyone",
      len(dc) == 2 and result(d)["discord"].get("id") == ",".join(f"M{STATE['calls'].index(c) + 1}" for c in dc)
      and '"content": "@everyone\\n今日の予想"'.encode() in first and "#競馬".encode() not in first and b'"parse": ["everyone"]' in first
      and first.count(b'name="files[') == 10 and dc[1][2].count(b'name="files[') == 2 and b'"content"' not in dc[1][2]
      and dc[0][1] == "/api/webhooks/123/SECRETTOKEN?wait=true" and dc[0][3].startswith("DiscordBot"), (p.stdout, [c[1] for c in dc]))
STATE.update(calls=[])
r = setup(); d = add_post(r, "20261020_1300_umataro_e", account="umataro", type="text", media=[], caption="お知らせ", platforms=["discord"], discord_channel="course")
p = run(r, "scripts/publish.py", env=hook)
dc = [c for c in STATE["calls"] if c[0] == "DISCORD"]
check("Discord：文字だけ・@everyoneなしなら通知を抑える", len(dc) == 1 and result(d)["discord"].get("id") and b'"parse": []' in dc[0][2], (p.stdout, dc))
r = setup(); d = add_post(r, "20261020_1300_umataro_f", account="umataro", type="text", media=[], caption="x", platforms=["discord"], discord_channel="course")
p = run(r, "scripts/publish.py")
err = result(d)["discord"].get("error", "")
check("Discord：URLがなければ名前を知らせ、URLはログに出さない", "DISCORD_WEBHOOK_UMATARO_COURSE" in err and "DISCORD_BOT_TOKEN_UMATARO" in err and "SECRETTOKEN" not in p.stdout + err, err)
r = setup()
subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
subprocess.run(["git", "-C", str(r), "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
p7 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "discord", "--at", "2099-01-03 08:00", "--id", "salon", "--caption", "朝のお知らせ", "--mention-everyone", "--discord-channel", "news", "--discord-thread-name", "質問はこちら")
j7 = json.loads((r / "queue" / "20990103_0800_umataro_salon" / "post.json").read_text())
(src / "tall.png").write_bytes(png(1080, 1920))
p8 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "discord", "--at", "2099-01-03 09:00", "--id", "tall", "--caption", "縦長", "--discord-channel", "course", str(src / "tall.png"))
p10 = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "discord", "--at", "2099-01-03 09:00", "--id", "nochan", "--caption", "x")
p9 = run(r, "tools/add_post.py", "--account", "lua", "--platforms", "discord", "--at", "2099-01-03 09:00", "--id", "x", "--caption", "x")
check("add_post：Discordの文字だけ・縦長画像OK・Discord未設定の事業は断る・チャンネル省略は断る",
      j7["type"] == "text" and j7["platforms"] == ["discord"] and j7["discord_mention"] == "everyone" and p8.returncode == 0 and p9.returncode != 0
      and j7["discord_channel"] == "news" and j7["discord_thread_name"] == "質問はこちら" and p10.returncode != 0 and "news=📣お知らせ" in p10.stderr,
      (p7.stderr, p8.stdout + p8.stderr, p9.stderr))

# 14 Discord（ボット：1つのトークンで全チャンネル）
STATE.update(calls=[], bot_fail=False)
bt = {"DISCORD_BOT_TOKEN_UMATARO": "BOTSECRET", **hook}
r = setup(); d = add_post(r, "20261020_1300_umataro_g", account="umataro", type="carousel", media=["01.jpg"], caption="全頭診断",
                         platforms=["discord"], discord_channel="zento", discord_thread_name="富士S 質問はこちら")
d2 = add_post(r, "20261020_1301_umataro_h", account="umataro", type="text", media=[], caption="当日の最終判断", platforms=["discord"],
              discord_channel="zento", discord_in_thread="20261020_1300_umataro_g")
d3 = add_post(r, "20261020_1302_umataro_i", account="umataro", type="text", media=[], caption="みんな", platforms=["discord"], discord_channel="minna")
p = run(r, "scripts/publish.py", env=bt)
bots = [c for c in STATE["calls"] if c[0] == "BOT"]
gets = [c for c in STATE["calls"] if c[0] == "BOTGET"]
check("Discordボット：名前でチャンネルを探して送り、スレッドを作り、そのスレッドに書く・ウェブフックは使わない",
      [c[1] for c in bots] == ["/api/v10/channels/C2/messages", "/api/v10/channels/C2/messages/" + result(d)["discord"]["id"] + "/threads",
                               "/api/v10/channels/" + result(d)["discord"]["id"] + "/messages", "/api/v10/channels/C3/messages"]
      and all(c[-1] == "Bot BOTSECRET" for c in bots + gets) and len(gets) == 2 and "富士S 質問はこちら".encode() in bots[1][2]
      and result(d2)["discord"].get("id") and result(d3)["discord"].get("id") and not any(c[0] == "DISCORD" for c in STATE["calls"])
      and "BOTSECRET" not in p.stdout, (p.stdout, [c[1] for c in STATE["calls"]]))
STATE.update(calls=[], bot_fail=True)
r = setup(); d = add_post(r, "20261020_1300_umataro_j", account="umataro", type="text", media=[], caption="x", platforms=["discord"], discord_channel="news")
d2 = add_post(r, "20261020_1300_umataro_k", account="umataro", type="text", media=[], caption="x", platforms=["discord"], discord_channel="kaiko")
d3 = add_post(r, "20261020_1300_umataro_l", account="umataro", type="text", media=[], caption="x", platforms=["discord"])
p = run(r, "scripts/publish.py", env=bt)
check("Discordボット：権限なしは理由を出す・サーバーにない部屋は止める・チャンネル省略は止める",
      "権限" in result(d)["discord"].get("error", "") and "☁️レース回顧" in result(d2)["discord"].get("error", "")
      and "discord_channel を指定" in result(d3)["discord"].get("error", ""), (result(d), result(d2), result(d3)))
STATE.update(calls=[], bot_fail=False)
r = setup(); p = run(r, "scripts/check.py", env=bt)
check("設定の確認：ボットでチャンネルIDを出し、configにない部屋も知らせる",
      "「news」📣お知らせ：OK  チャンネルID C1" in p.stdout and "「kaiko」☁️レース回顧：NG" in p.stdout and "新しい部屋（C5）" in p.stdout
      and "倶楽部コンテンツ" not in p.stdout.split("configにない")[-1] and "BOTSECRET" not in p.stdout, p.stdout + p.stderr)

# 16 Threadsの続き（自分の投稿への返信）：親が出てから reply_to_id 付きで出す。親が未投稿なら待つ
STATE.update(calls=[], existing=[], fail_create=False, media_ok=True)
r = setup()
dp = add_post(r, "20261020_1300_umataro_p", account="umataro", type="text", media=[], caption="1本目", platforms=["threads"])
dc = add_post(r, "20261020_1301_umataro_c", account="umataro", type="text", media=[], caption="続き", platforms=["threads"],
              threads_reply_to="20261020_1300_umataro_p", publish_at="2026-10-20T13:01:00+09:00")
p = run(r, "scripts/publish.py", env={"THREADS_TOKEN_UMATARO": "t"})
creates = [c[2] for c in STATE["calls"] if c[0] == "POST" and c[1].endswith("/me/threads")]
pid = result(dp)["threads"].get("id")
check("Threadsの続き：親のあとに reply_to_id 付きで出る", pid and result(dc)["threads"].get("id") and len(creates) == 2
      and "reply_to_id" not in creates[0] and creates[1].get("reply_to_id") == [pid], (p.stdout, creates))
STATE.update(calls=[])
r = setup()
add_post(r, "20261020_1310_umataro_p2", account="umataro", type="text", media=[], caption="1本目 続きは下👇", platforms=["threads"], publish_at="2026-10-20T13:10:00+09:00")
dc2 = add_post(r, "20261020_1301_umataro_c2", account="umataro", type="text", media=[], caption="続き", platforms=["threads"],
               threads_reply_to="20261020_1310_umataro_p2", publish_at="2026-10-20T13:01:00+09:00")
p = run(r, "scripts/publish.py", env={"THREADS_TOKEN_UMATARO": "t"})
rc = result(dc2)["threads"]
check("Threadsの続き：親がまだなら失敗に数えず待つ", not rc.get("id") and not rc.get("attempts") and "まだ" in rc.get("error", "") and p.returncode == 0, (p.stdout, rc))
pa = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "threads", "--at", "2099-01-03 09:00", "--id", "x",
         "--caption", "続き", "--threads-reply-to", "20261020_1310_umataro_p2")
pb = run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "threads", "--at", "2026-10-20 13:05", "--id", "y",
         "--caption", "続き", "--threads-reply-to", "20261020_1310_umataro_p2")
jx = json.loads((r / "queue" / "20990103_0900_umataro_x" / "post.json").read_text()) if pa.returncode == 0 else {}
check("add_post：--threads-reply-to を書く・親より前の時刻は止める", jx.get("threads_reply_to") == "20261020_1310_umataro_p2" and pb.returncode != 0, (pa.stdout + pa.stderr, pb.stderr))

# 17 出す前チェック（rules/umataro_threads.json）：NGは止める・--override で理由付きで入れる・型Bの固定文は通す
r = setup()
add_post(r, "20261021_2000_umataro_q1", account="umataro", type="text", media=[], caption="1行目の書き出し\n\n同じ締め", platforms=["threads"],
         publish_at="2026-10-21T20:00:00+09:00")
add_post(r, "20261021_2001_umataro_q2", account="umataro", type="text", media=[], caption="親だけ", platforms=["threads"],
         publish_at="2026-10-21T20:01:00+09:00")
ap = lambda at, i, cap, *x: run(r, "tools/add_post.py", "--account", "umataro", "--platforms", "threads", "--at", at, "--id", i, "--caption", cap, *x)
p1 = ap("2026-10-22 12:00", "a1", "うま太郎の〇〇")
p2 = ap("2026-10-22 12:01", "a2", "データはnetkeibaで見た")
p3 = ap("2026-10-22 12:02", "a3", "コメントで教えてください")
p4 = ap("2026-10-22 12:03", "a4", "別の書き出し\n\n同じ締め")
p5 = ap("2026-10-22 12:04", "a5", "続きだよ", "--threads-reply-to", "20261021_2001_umataro_q2")
p6 = ap("2026-10-22 12:05", "a6", "別の書き出し\n\n同じ締め", "--override", "テスト")
p7 = ap("2026-10-22 12:06", "a7", "【秋華賞】、迷ってる人は絶対見てください🐎\n\n▲ 1 A\n\n◎と○はこの3頭以外です。\n\n◎と○は無料オプチャに出します。")
p8 = ap("2026-10-22 12:07", "a8", "てか、無敗の1番人気どうだった？")
j6 = json.loads((r / "queue" / "20261022_1205_umataro_a6" / "post.json").read_text()) if p6.returncode == 0 else {}
check("出す前チェック：〇〇・出典・お願い・締めの被り・誘導のない親は止める",
      all(p.returncode != 0 for p in (p1, p2, p3, p4, p5)) and "〇〇" in p1.stdout and "出典" in p2.stdout and "お願い" in p3.stdout
      and "締め" in p4.stdout and "誘導" in p5.stdout, [p.stdout + p.stderr for p in (p1, p2, p3, p4, p5)])
check("出す前チェック：--override は理由を残して入れる・型Bの固定文と普通の投稿は通す",
      j6.get("check_override", {}).get("reason") == "テスト" and p7.returncode == 0 and p8.returncode == 0, (p6.stdout + p6.stderr, p7.stdout + p7.stderr, p8.stdout))
lua = run(r, "tools/add_post.py", "--account", "lua", "--platforms", "threads", "--at", "2026-10-22 12:08", "--id", "l1", "--caption", "見てください")
check("出す前チェック：ルールのないアカウントは今までどおり", lua.returncode == 0, lua.stdout + lua.stderr)

print("\n全部OK" if ok else "\nNGあり"); sys.exit(0 if ok else 1)
