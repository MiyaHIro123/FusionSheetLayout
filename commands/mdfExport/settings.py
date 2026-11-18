"""設定値の検証とJSON永続化。画面への通知は呼び出し側が担当する。"""
from math import isfinite
from pathlib import Path
import json
import os
import tempfile

ADDIN_DIR = Path(__file__).resolve().parents[2]
SETTINGS_FILE = ADDIN_DIR/'settings.json'
DEFAULT_SETTINGS = {'hidden': False, 'tolerance': 0.05, 'gap': 3.,
                    'width': 600., 'format': 'SVG', 'allow_ambiguous': True}
SETTINGS = dict(DEFAULT_SETTINGS)


def valid_settings(v):
    try:
        return (
            all(type(v[k]) is bool for k in ('hidden', 'allow_ambiguous'))
            and v['format'] in ('DXF', 'SVG')
            and all(type(v[k]) in (int, float) and isfinite(v[k])
                    for k in ('tolerance', 'gap', 'width'))
            and 0 < v['tolerance'] <= .25 and v['gap'] >= 0 and v['width'] > 0
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def save_settings(values):
    if not valid_settings(values):
        raise ValueError('設定値が不正です')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=str(SETTINGS_FILE.parent),
                                         prefix='settings_', suffix='.tmp',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(values, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(SETTINGS_FILE))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_settings(on_error=None):
    notify = on_error if on_error is not None else (lambda message: None)
    SETTINGS.clear()
    SETTINGS.update(DEFAULT_SETTINGS)
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding='utf-8-sig'))
        if not isinstance(raw, dict):
            raise ValueError('設定ファイルはJSONオブジェクトである必要があります')
        values = dict(DEFAULT_SETTINGS)
        values.update({k: raw[k] for k in DEFAULT_SETTINGS if k in raw})
        if not valid_settings(values):
            raise ValueError('設定ファイルに不正な値があります')
        SETTINGS.update(values)
    except FileNotFoundError:
        try:
            save_settings(SETTINGS)
        except Exception as exc:
            notify('初期設定ファイルを保存できませんでした。\n' + str(exc))
    except Exception as exc:
        notify('設定ファイルを読み込めないため、今回は初期値を使用します。\n'
             '既存の設定ファイルは上書きしていません。\n' + str(exc))

