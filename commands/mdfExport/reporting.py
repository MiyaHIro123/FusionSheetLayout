"""解析結果の表示文章と、モデル変更検出用の比較表現。"""
from dataclasses import asdict
import json


# 採用部品、警告、設定、配置寸法を、画面表示と結果ログ用の文章へまとめる。
def report(result, settings):
    parts, warnings, size, hidden = result.parts, result.warnings, result.size, result.hidden_count
    lines = [f'出力形式: {settings.get("format", "SVG")}', f'出力対象: {len(parts)}部品 / 警告: {len(warnings)}件 / 非表示除外: {hidden}件',
             f'配置全体: {size[0]:.3f} × {size[1]:.3f} mm',
             f'板厚: 2.5±{settings["tolerance"]:g} mm / 間隔: {settings["gap"]:g} mm / 配置幅: {settings["width"]:g} mm',
             f'板厚方向の複数候補を警告付きで出力: {"ON" if settings.get("allow_ambiguous", False) else "OFF"}',
             '', '【警告・スキップ】']
    lines.extend(warnings or ['なし'])
    lines += ['', '【出力部品】']
    for p in parts:
        x0, y0, x1, y1 = p.bounds()
        lines.append(f'{p.id} {p.name} | 厚さ{p.thickness:.4f}mm | {x1-x0:.3f}×{y1-y0:.3f}mm | 穴{sum(not l.outer for l in p.loops)}')
    return '\n'.join(lines)


# 解析結果を比較できる文字列にし、確認中にモデルが変わった場合の出力を防ぐ。
def signature(result):
    return json.dumps(([asdict(p) for p in result.parts], (result.warnings, result.size, result.hidden_count)), sort_keys=True, ensure_ascii=False)


