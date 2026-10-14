"""長期トークン（60日有効）を延長する。週1回、GitHub Actionsが動かし、新しいトークンを Secrets に保存し直す。
ワークフローが渡す IG_TOKEN_* / THREADS_TOKEN_* をすべて延長する。
Threadsは画面で作れるトークンが1時間しかもたない短期のものなので、THREADS_APP_SECRET があれば
先に長期（60日）への交換を試す。交換できない（すでに長期）ときは、ふつうの延長に回す。"""
import os
import subprocess
import sys

from common import IG_HOST, TH_HOST, ApiError, http, log

KINDS = {
    "IG_TOKEN_": (f"{IG_HOST}/refresh_access_token", "ig_refresh_token"),
    "THREADS_TOKEN_": (f"{TH_HOST}/refresh_access_token", "th_refresh_token"),
}


def exchange_threads(token):
    secret = os.environ.get("THREADS_APP_SECRET")
    if not secret:
        return None
    try:
        return http("GET", f"{TH_HOST}/access_token",
                    {"grant_type": "th_exchange_token", "client_secret": secret, "access_token": token})
    except ApiError:
        return None


def main():
    failed = False
    found = 0
    for name, token in sorted(os.environ.items()):
        kind = next((k for k in KINDS if name.startswith(k)), None)
        if not kind or not token:
            continue
        found += 1
        url, grant = KINDS[kind]
        try:
            res = exchange_threads(token) if kind == "THREADS_TOKEN_" else None
            if res:
                log(f"{name}：短期トークンを長期に交換しました")
            else:
                res = http("GET", url, {"grant_type": grant, "access_token": token})
            new = res["access_token"]
            days = int(res.get("expires_in", 0)) // 86400
            subprocess.run(["gh", "secret", "set", name, "--body", new], check=True)
            log(f"{name}：延長しました（あと約{days}日有効）")
        except (ApiError, KeyError, subprocess.CalledProcessError) as e:
            failed = True
            log(f"{name}：延長できませんでした：{e}")
    if not found:
        log("延長するトークンがありません（IG_TOKEN_* / THREADS_TOKEN_*）")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
