# Python構成と編集ガイド

更新: 2026-11-12。処理分割後の構成。計算・配置・出力仕様は維持。

## 起動

FusionSheetLayout.py の run → commands.start → mdfExport.entry.start。
停止時はボタンとイベント参照を解放する。

## commands/mdfExport の役割

| ファイル | 担当 |
|---|---|
| entry.py | Fusion UI、イベント、警告確認、保存先選択、ログ保存の通知 |
| settings.py | 設定初期値、検証、settings.jsonの読み書き |
| service.py | 抽出→配置の組み立て、形式別出力と検証保存 |
| fusion_adapter.py | Fusionのボディ列挙、板形状判定、2D輪郭抽出 |
| geometry.py | Curve / Loop / Part、mm単位の形状計算・輪郭検証 |
| layout.py | 向き補正を適用し、外接矩形で棚配置 |
| results.py | ExtractionResult / AnalysisResult の名前付き結果 |
| reporting.py | 結果文章、変更検出用のsignature |
| dxf_writer.py | DXF生成・検証。同じフォルダーのdxf_template.txtを使う |
| svg_writer.py | SVG生成・検証 |
| file_io.py | 一時ファイル、既存出力バックアップ、保存確定 |
| core.py | 旧import用の互換窓口。新規処理は追加しない |

## データと処理

Curveは直線・円弧・円、Loopは外周または穴、Partは部品。
長さはmm、角度はラジアン。Fusionの参照は持たない。

entry → service.analyze → fusion_adapter.extract_parts → ExtractionResult。
service.arrange が layout を呼び、AnalysisResultを返す。
画面側は result.parts / warnings / size / hidden_count で参照する。
service.export_file が形式別writerとvalidatorを選び、file_io.safe_writeで保存する。
モデル変更検出の再解析、警告確認、既存出力の上書き確認は維持。

settingsの読み込みエラー通知はentryからコールバックで渡す。
計算・配置・設定・出力はadskをimportしない。serviceは解析時のみFusionアダプターを読み込む。

## 編集方針

- 配置変更: layout.py。形状自体の移動・回転演算はgeometry.py。
- 対象形状追加: fusion_adapter.py。形状検証を緩める場合は対応範囲と試験を追加する。
- 設定追加: settings.py、entry.pyの入力と検証、利用する処理、reporting.pyを合わせて変更する。
- 形式追加: writerを追加しservice.export_fileとUIの形式選択を更新する。
- 計算とFusion APIを混ぜない。UIが不要な処理は通常のPythonで確認する。
- 構成整理と機能変更は分け、代表形状の出力を比較する。

commandDialogは旧UIの削除とアイコン参照に使用中。paletteShow/paletteSendは未登録。
この整理ではこれらの削除やアイコン移動は行っていない。
lib/fusionAddInUtilsはイベント保持・ログの補助。通常は編集不要。

## 現在の仕様

板厚2.5mm、許容誤差初期値±0.05mm。幅600mm、間隔3mm。
初期形式SVG、非表示除外、曖昧な板厚方向は警告付き出力ON。
保存済みsettings.jsonが優先。直線・円・円弧を保持する。
最長直線（穴も含む）を近い水平/垂直へ回転し、45度は垂直。
幅超過部品は除外。高さ上限、複数枚分割、追加の回転探索なし。
元モデルを変更しない。警告の構造化や配置位置の独立管理は将来の変更候補。

## 確認

通常Pythonで `python -m unittest discover -s tests -v`。
Fusionでの確認: アドイン停止→実行、設定画面、SVG/DXF保存、警告時の取消、再起動後の設定復元。
過去のSPEC.mdは履歴を含むため、構成の参照先は本書とする。
