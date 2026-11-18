"""Fusion buttons: click -> analyze -> Ignore/Cancel warnings -> save DXF."""
from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path
import re
import traceback
import adsk.core
import adsk.fusion
from ...lib import fusionAddInUtils as futil
from .service import analyze, export_file
from .file_io import safe_write
from .settings import SETTINGS, valid_settings, save_settings, load_settings
from .reporting import report, signature

COMMAND_ID = 'MiyaHiro_MDFLaser_Export_v01'
SETTINGS_ID = 'MiyaHiro_MDFLaser_Settings_v01'
MENU_ID = 'MiyaHiro_MDFLaser_Menu_v01'
PROCESSING_ID = 'MiyaHiro_MDFLaser_Processing_v01'
TAB_ID = 'ToolsTab'
PANEL_ID = 'FusionSheetLayoutPanel'
PANEL_NAME = 'SHEET LAYOUT'
LEGACY_PANEL_ID = 'SolidScriptsAddinsPanel'
WORKSPACE_ID = 'FusionSolidEnvironment'
ADDIN_DIR = Path(__file__).resolve().parents[2]
# 既存のツールバー用アイコンを実行ボタンに使用する。
ICON_FOLDER = str(ADDIN_DIR/'commands'/'commandDialog'/'resources')
LOG_DIR = ADDIN_DIR/'logs'
_handlers = []
_commands = []
_processing_active = False


def ui():
    return adsk.core.Application.get().userInterface


def fail(message):
    ui().messageBox(message, 'MDFレーザーカット出力')


# 固定メッセージを表示し、完了・例外時に閉じる。保存先選択中は表示しない。
@contextmanager
def processing(document, design):
    global _processing_active
    if _processing_active:
        raise ValueError('処理中...')
    _processing_active = True
    progress = None
    try:
        try:
            progress = ui().createProgressDialog()
            progress.isCancelButtonShown = False
            progress.isBackgroundTranslucent = False
            progress.show('Sheet Layout', '処理中...', 0, 1, 0)
            adsk.doEvents()
        except Exception:
            # 表示機能の失敗で本来の解析・保存を中止しない。
            futil.log('処理中表示を開始できませんでした: ' + traceback.format_exc())
        if adsk.core.Application.get().activeDocument != document or not design.isValid:
            raise ValueError('対象のドキュメントが変わりました。もう一度実行してください。')
        yield
    finally:
        try:
            if progress:
                try:
                    progress.hide()
                except Exception:
                    futil.log('処理中表示を閉じられませんでした: ' + traceback.format_exc())
        finally:
            _processing_active = False


def text_input(command, name, text, rows=20):
    box = command.commandInputs.addTextBoxCommandInput(name, '', escape(text).replace('\n', '<br>'), rows, True)
    box.isFullWidth = True
    return box


# イベントハンドラーを保持し、コマンド破棄時に参照を解放する。
def keep_command(command):
    handlers = []
    _commands.append(handlers)
    def destroy(args):
        for i, group in enumerate(_commands):
            if group is handlers:
                _commands.pop(i)
                break
        handlers.clear()
    futil.add_handler(command.destroy, destroy, local_handlers=handlers)
    return handlers


# 実行ボタンから解析を開始する。警告があれば無視／キャンセルを表示する。
# 無視の実行時にも再解析し、保存先選択、形式別生成、検証保存、logsへの記録へ進む。
def export_created(args):
    command = args.command
    command.isExecutedWhenPreEmpted = False
    handlers = keep_command(command)
    try:
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise ValueError('デザインのモデルを開いてから実行してください。')
        if adsk.fusion.Sketch.cast(app.activeEditObject):
            raise ValueError('スケッチ編集を終了してから実行してください。')
        document = app.activeDocument
        settings = dict(SETTINGS)
        output_format = settings.get('format', 'SVG')
        if output_format not in ('DXF', 'SVG'):
            raise ValueError('出力形式が不正です')
        extension = '.'+output_format.lower()
        with processing(document, design):
            result = analyze(design, settings)
            summary = report(result, settings)
        if not result.parts:
            text_input(command, 'mdf_result', '出力できる部品がありません。\n\n'+summary)
            command.isOKButtonVisible = False
            return
        if result.warnings:
            command.setDialogInitialSize(740, 580)
            text_input(command, 'mdf_warnings',
                       '警告を確認してください。\n「無視」: 下の出力部品を保存します。設定で許可した板厚方向の複数候補も含みます。\n'
                       '対象外形状・配置幅超過などで除外された部品は出力しません。\n'
                       '「キャンセル」: ファイルを作成せず終了します。\n\n'+summary, 24)
            command.okButtonText = '無視'
        # With no command inputs Fusion automatically executes the command.
        command.isAutoExecute = True
        snapshot = signature(result)

        def execute(event_args):
            try:
                if app.activeDocument != document or not design.isValid:
                    raise ValueError('対象のドキュメントが変わりました。もう一度ボタンを押してください。')
                current = analyze(design, settings)
                current_signature = signature(current)
                if current_signature != snapshot:
                    raise ValueError('解析後にモデルまたは表示状態が変わりました。もう一度解析してください。')
                dialog = ui().createFileDialog()
                dialog.title = 'MDFレーザーカット'+output_format+'の保存'
                dialog.filter = f'{output_format} (*{extension})'
                dialog.initialDirectory = str(ADDIN_DIR)
                base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', document.name).strip(' .') or 'Design'
                dialog.initialFilename = base+'_MDF_'+datetime.now().strftime('%Y%m%d_%H%M%S')+extension
                if dialog.showSave() != adsk.core.DialogResults.DialogOK:
                    return
                path = Path(dialog.filename)
                if path.suffix.lower() != extension:
                    path = path.with_suffix(extension) if path.suffix.lower() in ('.svg', '.dxf') else path.with_name(path.name+extension)
                if path.exists():
                    answer = ui().messageBox(f'既存{output_format}をバックアップして上書きしますか？\n'+str(path),
                                             '出力先の確認', adsk.core.MessageBoxButtonTypes.OKCancelButtonType)
                    if answer != adsk.core.DialogResults.DialogOK:
                        return
                # File dialogs are modal, but recheck after them as well to guard invalid references.
                if app.activeDocument != document or not design.isValid:
                    raise ValueError('ドキュメントが変わったため出力を中止しました。')
                latest = analyze(design, settings)
                if signature(latest) != snapshot:
                    raise ValueError('モデルが変わったため出力を中止しました。もう一度解析してください。')
                parts = latest.parts
                export_file(path, parts, output_format)
                report_note = ''
                try:
                    details = f'作成日時: {datetime.now().isoformat(timespec="seconds")}\nFusion: {app.version}\n{output_format}: {path}\n\n'+summary
                    LOG_DIR.mkdir(parents=True, exist_ok=True)
                    report_path = LOG_DIR/(path.stem+'_結果_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.txt')
                    safe_write(report_path, details)
                    report_note = '\n結果一覧: '+str(report_path)
                except Exception as exc:
                    report_note = f'\n{output_format}は保存済みですが、結果一覧の保存に失敗しました: '+str(exc)
                fail(f'{output_format}を保存しました。\n{len(parts)}部品 / {latest.size[0]:.3f} × {latest.size[1]:.3f} mm\n{path}'+report_note)
            except Exception:
                fail('処理を完了できませんでした。\n元モデルは変更していません。\n\n'+traceback.format_exc())
        futil.add_handler(command.execute, execute, local_handlers=handlers)
    except Exception:
        text_input(command, 'mdf_error', '解析を開始できませんでした。\n\n'+traceback.format_exc())
        command.isOKButtonVisible = False


# 形式、表示対象、板厚候補の扱い、許容誤差、間隔、配置幅の設定画面を作る。
def settings_created(args):
    command = args.command
    command.isExecutedWhenPreEmpted = False
    command.okButtonText = '設定を保存'
    handlers = keep_command(command)
    inputs = command.commandInputs
    text_input(command, 'mdf_help', '設定はsettings.jsonに保存し、Fusion再起動後も保持します。公称板厚は2.5mmです。', 2)
    format_input = inputs.addDropDownCommandInput('format', '出力形式', adsk.core.DropDownStyles.TextListDropDownStyle)
    for name in ('DXF', 'SVG'):
        format_input.listItems.add(name, SETTINGS.get('format', 'SVG') == name, '')
    inputs.addBoolValueInput('hidden', '非表示のボディも含める', True, '', SETTINGS['hidden'])
    inputs.addBoolValueInput('allow_ambiguous', '板厚方向が複数候補でも警告付きで出力する', True, '', SETTINGS.get('allow_ambiguous', True))
    text_input(command, 'ambiguity_help', '有効時は板面積最大の候補を選び、出力前に警告します。「無視」で出力、「キャンセル」で終了します。板厚不一致や段差は対象外のままです。', 3)
    for key, label in [('tolerance', '板厚許容誤差 ±'), ('gap', '部品間隔'), ('width', '配置幅')]:
        inputs.addValueInput(key, label, 'mm', adsk.core.ValueInput.createByString(f'{SETTINGS[key]} mm'))

    def values():
        return dict(hidden=inputs.itemById('hidden').value, format=inputs.itemById('format').selectedItem.name,
                    allow_ambiguous=inputs.itemById('allow_ambiguous').value,
                    **{k: inputs.itemById(k).value*10 for k in ('tolerance', 'gap', 'width')})

    def valid(v):
        return valid_settings(v)

    def validate(event_args):
        try:
            event_args.areInputsValid = valid(values())
        except Exception:
            event_args.areInputsValid = False

    def execute(event_args):
        try:
            v = values()
            save_settings(v)
            SETTINGS.update(v)
        except Exception as exc:
            fail('設定を保存できませんでした。以前の設定を維持します。\n' + str(exc))
    futil.add_handler(command.validateInputs, validate, local_handlers=handlers)
    futil.add_handler(command.execute, execute, local_handlers=handlers)


# パネルの主ボタンで実行し、設定はパネルメニューに配置する。
def start():
    load_settings(on_error=fail)
    interface = ui()
    workspace = interface.workspaces.itemById(WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(TAB_ID) if workspace else None
    if not tab:
        raise RuntimeError('ユーティリティタブが見つかりません')
    stop()
    panel = tab.toolbarPanels.itemById(PANEL_ID)
    if not panel:
        panel = tab.toolbarPanels.add(PANEL_ID, PANEL_NAME)
    if not panel:
        raise RuntimeError('SHEET LAYOUTパネルを作成できません')
    try:
        for cid, name, description, callback in (
            (COMMAND_ID, 'Sheet Layout', '板状ボディを解析し、警告確認後に選択形式（DXF／SVG）で保存します。', export_created),
            (SETTINGS_ID, '設定', '出力形式・板厚許容誤差・間隔・配置幅・非表示対象を設定します。', settings_created)):
            definition = interface.commandDefinitions.addButtonDefinition(
                cid, name, description, ICON_FOLDER if cid == COMMAND_ID else '')
            futil.add_handler(definition.commandCreated, callback, local_handlers=_handlers)
            control = panel.controls.addCommand(definition)
            control.isPromotedByDefault = cid == COMMAND_ID
            control.isPromoted = cid == COMMAND_ID
    except Exception:
        stop()
        raise


# この機能のボタンとイベント参照を解放する。ユーザーのモデルは閉じない。
def stop():
    interface = ui()
    palette = interface.palettes.itemById(PROCESSING_ID)
    if palette:
        palette.deleteMe()
    workspace = interface.workspaces.itemById(WORKSPACE_ID)
    if workspace:
        for panel_id in (PANEL_ID, LEGACY_PANEL_ID):
            panel = workspace.toolbarPanels.itemById(panel_id)
            if not panel:
                continue
            for cid in (MENU_ID, COMMAND_ID, SETTINGS_ID):
                control = panel.controls.itemById(cid)
                if control:
                    control.deleteMe()
            # 他のコマンドが残っている間は共有パネルを維持する。
            if panel_id == PANEL_ID and panel.controls.count == 0:
                panel.deleteMe()
    for cid in (COMMAND_ID, SETTINGS_ID):
        definition = interface.commandDefinitions.itemById(cid)
        if definition:
            definition.deleteMe()
    _handlers.clear()
    for handlers in _commands:
        handlers.clear()
    _commands.clear()
