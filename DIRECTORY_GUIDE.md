# アドインのディレクトリ説明書

更新日: 2026-10-22

この文書は、どのファイルが何を担当し、処理がどの順に進むかを説明します。
設置先は `C:\Users\**ユーザー名**\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\FusionSheetLayout` です。

## フォルダとファイル

```text
FusionSheetLayout/
├─ FusionSheetLayout.py            Fusionが呼ぶ起動・停止の入口
├─ FusionSheetLayout.manifest      Fusionへの登録情報
├─ config.py                   アドイン名・デバッグ等の共通設定
├─ AddInIcon.svg               アドインのアイコン
├─ README.md                   利用者向けの起動・操作手順
├─ DIRECTORY_GUIDE.md           この説明書
├─ SPEC.md                     入力条件・判定・出力の仕様
├─ IMPLEMENTATION_PLAN.md      実装計画と進捗の記録
├─ TEST_RESULTS.md             自動試験と未確認事項
├─ commands/
│  ├─ __init__.py              登録するコマンドを集め、起動・停止する
│  ├─ mdfExport/               MDF出力機能の本体
│  │  ├─ __init__.py           Pythonパッケージの入口
│  │  ├─ entry.py              ボタン、設定画面、警告確認、保存操作
│  │  ├─ fusion_adapter.py     Fusionモデルの取得・板形状判定・平面化
│  │  ├─ core.py               2D形状、輪郭検査、配置、DXF、安全保存
│  │  ├─ svg_writer.py         SVG生成と読み戻し検査
│  │  ├─ dxf_template.txt      DXFの管理情報を含むひな形
│  │  └─ buckup/              このフォルダで編集するファイルの直前版
│  ├─ commandDialog/          既存のサンプルダイアログ
│  ├─ paletteShow/            既存のパレット表示サンプル
│  └─ paletteSend/            既存のパレット連携サンプル
├─ lib/fusionAddInUtils/      イベント接続やエラー処理の共通補助
├─ logs/                     出力結果・警告一覧のテキスト
├─ .vscode/                  エディターのデバッグ設定
├─ __pycache__/              Pythonが自動生成する実行用キャッシュ
└─ buckup/                   ルートのファイルを編集する場合の直前版
```

`buckup`は指定された名前です。編集する各フォルダに必要時に作成します。
`__pycache__`は各Pythonフォルダにも作られることがあります。通常は編集しません。
サンプルコマンドはMDF出力の本体ではありませんが、登録ファイルの設定に従って動作します。

## 処理の流れ

1. Fusionが`FusionSheetLayout.py`の`run()`を呼び、`commands/__init__.py`から機能を起動します。
2. `entry.py`が「MDFレーザーカット出力」と「MDF出力設定」を登録します。
3. 実行ボタンから`fusion_adapter.py`の`analyze()`を呼びます。表示対象を列挙し、`extract()`で板厚方向を探し、`prove_prism()`で一様な板形状か検査します。
4. 端面の辺を`core.py`の`Curve`へ変換します。長さはmm、角度はラジアンです。`Loop`が外周・穴、`Part`が1部品を表します。
5. `core.py`で輪郭を検査し、`layout()`で外接矩形を使って重ならない棚配置を行います。
6. 警告がある場合、`entry.py`が一覧を表示します。「無視」は出力候補を保存する操作です。設定で許可した板厚方向の複数候補を含み、形状不適合などで除外した部品は含みません。
7. 保存直前にも解析結果が変わっていないか確認し、DXFなら`core.py`、SVGなら`svg_writer.py`で文字列を生成します。
8. `safe_write()`が一時ファイルへ保存して検証し、問題がなければ確定します。結果ログは`logs/`へ記録します。

元モデルの移動・編集・保存は行いません。DXF/SVGはユーザーが選んだ保存先へ出力します。デスクトップへの自動保存は行いません。

## コアプログラムの読み方

`core.py`はFusionなしでも利用できる共通処理です。上から順に読むと、データ型→輪郭の組み立て→交差・妥当性検査→配置→DXF生成・検証→保存、という構成です。

| 調べたい内容 | 主な場所 |
|---|---|
| ボタン・設定項目・警告文 | `entry.py`の`start()`、`settings_created()`、`export_created()` |
| 板厚、段差、複数候補の判定 | `fusion_adapter.py`の`extract()`、`prove_prism()` |
| 円弧や穴の取り出し | `fusion_adapter.py`の`edge_curve()`、`cap_loops()` |
| 間隔・並び順・配置幅 | `core.py`の`layout()` |
| 外接矩形と円弧の極値 | `core.py`の`Curve.bounds()` |
| 輪郭の欠落・自己交差 | `core.py`の`ordered_loop()`、`validate_part()` |
| DXF読み込み互換性 | `core.py`の`dxf_text()`と`dxf_template.txt` |
| SVGの実寸・向き・線の表示 | `svg_writer.py` |
| 保存時のバックアップ・一時ファイル | `core.py`の`safe_write()` |

DXFテンプレートのモデル空間ハンドル`17`と、`core.py`の所有者参照は対応しています。片方だけを変更すると読み込みに影響するため、両方を確認します。

## 編集とバックアップ

今後コードや文書を上書きする前に、そのファイルのあるフォルダ内の`buckup/`へ元と同じ名前でコピーします。例：`commands/mdfExport/core.py`の直前版は`commands/mdfExport/buckup/core.py`です。保持するのは直前の1世代です。バックアップ内のPythonファイルは実行用として登録しません。

注意：アドインが既存DXF/SVGを上書きするときの`safe_write()`は、現時点では従来の`名前(バックアップ).拡張子`方式です。今回の作業は説明文書とコメントの追加に限定し、この実行時動作は変更していません。

## 試験と確認範囲

実装検証用のPythonテストは、このインストール先ではなく今回の開発作業フォルダの`work/mdf_build/`にあります。アドインの実行に必要なものではありません。検証用ライブラリもアドインへ組み込んでいません。

今回のコメント追加ではPythonの構文木を変更前後で比較し、実行処理が変わっていないことを確認します。Fusion内の操作や加工ソフトへの読み込み確認とは区別します。


## 移行後の補足（2026-10-22）

正本はFusionSheetLayoutです。`.git/`はGit履歴、`.gitignore`はログ・キャッシュ・バックアップ等の除外設定、`.gitattributes`は改行設定、`LICENSE`は共有時のライセンスです。これらのGit管理情報は不用意に削除しないでください。移行時にはlogs・buckup・.vscode・__pycache__をコピーしていません。必要なフォルダは実行・編集時に作成されます。
