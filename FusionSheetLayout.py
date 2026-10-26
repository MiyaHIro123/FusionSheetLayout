from . import commands
from .lib import fusionAddInUtils as futil
import adsk.core, adsk.fusion, traceback


def run(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        

        commands.start()

    except:
        futil.handle_error('run')


def stop(context):
    try:
        futil.clear_handlers()

        commands.stop()

    except:
        futil.handle_error('stop')