"""抽出・配置・形式別出力を組み立てる。UIを扱わない。"""
from .layout import layout
from .results import AnalysisResult
from .dxf_writer import dxf_text, validate_dxf
from .svg_writer import svg_text, validate_svg
from .file_io import safe_write


def analyze(design, settings):
    # Fusion外でも配置・出力を使えるようAPI依存をここに限定する。
    from .fusion_adapter import extract_parts
    return arrange(extract_parts(design, settings), settings)


def arrange(extracted, settings):
    parts, warnings, size = layout(extracted.parts, settings['width'], settings['gap'])
    return AnalysisResult(parts, extracted.warnings + warnings, size, extracted.hidden_count)


def export_file(path, parts, output_format):
    writers = {'SVG': (svg_text, validate_svg), 'DXF': (dxf_text, validate_dxf)}
    if output_format not in writers:
        raise ValueError('出力形式が不正です')
    writer, validator = writers[output_format]
    safe_write(path, writer(parts), lambda data: validator(data, parts))
