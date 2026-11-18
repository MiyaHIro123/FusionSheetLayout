"""検証付き保存と既存ファイルのバックアップ。"""
from pathlib import Path
import os
import shutil
import uuid


# 保存先と同じフォルダに一時ファイルを作り、検証後に本来の名前へ置き換える。
# 途中で失敗した場合は既存の出力を維持し、自分の一時ファイルだけを片付ける。
# 現実装の出力バックアップ名は「(バックアップ)」方式。今回のコメント追加では動作を変更しない。
def safe_write(path, text, validator=None):
    path = Path(path)
    if not path.parent.is_dir():
        raise OSError('保存先フォルダがありません')
    # Windows tempfile may retry permission failures many times. Fail immediately
    # on access errors while retaining exclusive creation and same-volume replace.
    tmp = str(path.parent/('.mdf_'+uuid.uuid4().hex+'.tmp'))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if validator:
            validator(Path(tmp).read_text(encoding='utf-8'))
        if path.exists():
            backup = path.with_name(path.stem+'(バックアップ)'+path.suffix)
            shutil.copy2(path, backup)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
