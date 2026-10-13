# SNS自動投稿（自作版Buffer）

決めた時間に、画像・動画と本文をSNSへ自動で投稿する仕組みです。月額0円で動きます。
事業（アカウント）ごとに分けて使えます。今はLUA GINZAのInstagramだけ登録してあり、ほかの事業はあとから足せます。

## しくみ（ひとことで）

1. Claudeが1週間分の投稿（画像・本文・時間・どの事業か）を `queue/` に入れる
2. GitHubが15分おきに「時間が来た投稿はあるか」を見て、Meta公式のAPIで投稿する
3. 投稿できたかどうかは各投稿の `post.json` に書き戻す。失敗したらGitHubからメールが届く

本人の毎週の作業は「画像を送る」だけになります（予約の手作業がなくなる）。

## 費用と制限（2026-10-13に公式ページで確認し直し）

| 項目 | 内容 | 出典 |
|---|---|---|
| GitHub Actions | 公開リポジトリなら無料（非公開は月2,000分まで無料） | docs.github.com「GitHub Actions billing」 |
| GitHub の定期実行 | 混雑時は遅れる・まれに飛ばされる。公開リポジトリは60日間動きがないと止まる（毎週の予約pushで防げる見込み） | docs.github.com「Events that trigger workflows」 |
| GitHub のファイル | 100MiBを超えるファイルはpushできない（このため動画は95MBまで） | docs.github.com「About large files on GitHub」 |
| Instagram API | 無料。自分が持つ・管理するアカウントだけなら審査不要（Standard Access） | developers.facebook.com「Instagram Platform overview」「App Review」 |
| Instagram 投稿上限 | 24時間で100件（同じページ内に50件の記載もあり。どちらでも1日4本には十分） | 同「Content publishing」 |
| Instagram 形式 | 画像はJPEGのみ・8MB・縦横比4:5〜1.91:1・幅320〜1440。カルーセル10点まで。リール3秒〜15分・300MB | 同「Content publishing」「IG User Media」 |
| Instagram トークン | 60日有効。作って24時間以上たてば延長できる（この仕組みが毎週月曜に自動で延長） | 同「Business Login」「Get started」 |
| Threads API | 24時間で250件。カルーセル2〜20点。本文500字まで。リンク5個まで | developers.facebook.com/docs/threads |
| X API | 月額なしの従量制。1投稿0.015ドル、URL入りは0.20ドル。カード登録で20ドル分のクレジット | docs.x.com「Pricing」 |

注意：GitHubの定期実行は混雑時に数分〜十数分遅れることがあります。13:00の予約は、だいたい13:00〜13:30の間に出ます。

## 本人の初回設定（1回だけ）

画面の名前は日本語訳＋（英語の原名）で書いています。翻訳で表記が少し違うことがあります。

### 1. GitHub
1. 新しいリポジトリを作る：https://github.com/new
   - リポジトリ名（Repository name）：`sns-autopost`（事業の名前を入れない汎用名にする）
   - 公開（Public）を選ぶ
   - READMEの追加などのチェックは入れず、「リポジトリを作成（Create repository）」
2. Claudeアプリの許可（https://github.com/apps/claude/installations/select_target ）を「選択したリポジトリのみ（Only select repositories）」にしている場合は、`sns-autopost` を追加して保存
3. ここで一度Claudeに「作った」と伝える → Claudeが中身を入れる
4. リポジトリの「設定（Settings）」→ 左メニュー「ページ（Pages）」→「ソース（Source）」を「GitHub Actions」に切り替える（選んだ時点で保存される）

※公開リポジトリなので、予約中の画像と本文は投稿前でもURLを知っている人は見られます（検索で見つかる可能性は低い）。画像は投稿後おおむね1週間以内に消えます。

### 2. Instagramのトークン（Meta開発者）※事業ごとに1回
1. そのInstagramがプロアカウント（ビジネス or クリエイター）で、公開アカウントになっているか確かめる
2. https://developers.facebook.com/ にFacebookアカウントでログインし、開発者登録をする
3. アプリを作成（Create app）→ 用途で「Manage messaging and content on Instagram」を選ぶ（出てこなければ「その他（Other）」→ 種類「ビジネス（Business）」）
   - アプリは1つで、複数の事業のInstagramを足せます
4. 左メニュー「API setup with Instagram Login」→ 権限に `instagram_business_basic` と `instagram_business_content_publish` があるか確かめる
5. 「Generate access tokens」の「Add account」→ そのInstagramでログイン →「Generate token」で出たトークンをコピー（60日有効。以後は自動で延長）
   - **トークンはチャットに貼らないでください**（次の3でGitHubに直接入れます）

### 3. GitHubにトークンを入れる
リポジトリの「設定（Settings）」→「シークレットと変数（Secrets and variables）」→「アクション（Actions）」→「新しいリポジトリシークレット（New repository secret）」

| 名前 | 中身 |
|---|---|
| `IG_TOKEN_LUA` | LUA GINZAのInstagramのトークン（2でコピーしたもの） |
| `GH_PAT` | トークン自動延長用（下の作り方）。全事業で1つ |

名前のきまり：`IG_TOKEN_<事業の略>`（Instagram）、`THREADS_TOKEN_<事業の略>`（Threads）。略は `config.json` の accounts の名前を大文字にしたもの（例：lua → LUA）。

`GH_PAT` の作り方：右上のアイコン →「設定（Settings）」→「開発者設定（Developer settings）」→「個人用アクセストークン（Personal access tokens）」→「きめ細かいトークン（Fine-grained tokens）」→「新しいトークンを生成（Generate new token）」
- リポジトリへのアクセス（Repository access）：`sns-autopost` だけ
- 権限（Permissions）：リポジトリ権限の「シークレット（Secrets）」を「読み取りと書き込み（Read and write）」に（ほかは触らない）
- 有効期限（Expiration）：無期限（No expiration）が選べればそれ。選べなければ最長にして期限をカレンダーに入れる（切れると延長が止まり、メールが届く）

ここまで終わったら、Claudeに「設定できた」と伝えてください。Claudeが「設定の確認」を動かして、つながったか確かめます（投稿はしません）。

### 4. 最初のテスト投稿（Claudeが本人に確認してから）
Claudeがテスト用の投稿を1本用意し、本人の了解を取ってから「予約投稿」を `only` 指定で動かします。Metaのアプリが「開発中」のままで一般に見える投稿になるかは公式ページに記載がなく、このテストで確かめます。

## 事業やSNSを足すとき
- **事業を足す**：`config.json` の `accounts` に1行足す（例：`"keiba": {"name": "競馬予想", "platforms": ["instagram"]}`）→ 本人が2・3の手順でトークンを作り `IG_TOKEN_KEIBA` を入れる。Claudeが3つのワークフロー（予約投稿・設定の確認・トークン延長）にそのトークンの行を足す
- **Threadsを足す**：Metaのアプリに「Threads APIにアクセス」の用途を追加 → トークンを `THREADS_TOKEN_<事業の略>` で入れる → その事業の `platforms` に `threads` を足す
- **X**：未対応（従量課金。料金は上の表）

## Claudeの毎週の手順

1. その事業の投稿表（days.json：日付ごとに posts の id・time・kind・zip・caption）と各zipを作る
2. `python3 tools/queue_from_postboard.py --account <事業> --from <月曜> --to <日曜> --days <days.json> --zips <zipのフォルダ>` で `queue/` に入れる（PNG→JPEG変換・枚数・動画の大きさチェック込み）
3. 「入れなかったもの」を確認し、**media ブランチ（./media）→ main の順に** コミットしてpush（mainへのpushで「画像の公開」が動く）
4. 必要なら Actions の「予約投稿」を `dry_run` で動かし、予定どおりか確かめる

## ファイル

- `config.json`：事業（accounts）ごとの投稿先、遅れの許容、APIの版など
- `queue/<日付_時刻_事業_ID>/post.json`（main）：1投稿の中身と結果（書き方は `scripts/publish.py` の先頭）
- `queue/<日付_時刻_事業_ID>/01.jpg など`（media ブランチ）：画像・動画。GitHub Pagesで公開し、APIが取りに来る
- `scripts/publish.py`：時間が来た投稿を公開する（3回失敗、または予定から3時間過ぎたら諦めてメール。画像URLの準備待ちは失敗に数えない。投稿済みなのに記録が残らなかったときは二重に出さない）
- `scripts/platforms.py`：Instagram・Threadsへの投稿処理
- `scripts/refresh_tokens.py`：毎週月曜に、Secretsの `IG_TOKEN_*`・`THREADS_TOKEN_*` をすべて延長
- `scripts/cleanup.py`：毎週日曜3時に、済んだ投稿の画像・動画を media ブランチから消し、ブランチを1コミットに作り直す
- `scripts/check.py`：設定の確認（投稿はしない）
- `tools/queue_from_postboard.py`：投稿表から `queue/` を作る
- `tests/mock_test.py`：模擬APIでのテスト（`python3 tests/mock_test.py .`）
