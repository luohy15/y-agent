import click

from .activate import ui_activate
from .create import ui_create
from .enable import ui_disable, ui_enable
from .list import ui_list
from .publish import ui_publish
from .rollback import ui_rollback
from .versions import ui_versions


@click.group("ui")
def ui_group():
    """Manage dynamic UI artifacts (create, publish, version, rollback)."""
    pass


ui_group.add_command(ui_create)
ui_group.add_command(ui_list)
ui_group.add_command(ui_versions)
ui_group.add_command(ui_publish)
ui_group.add_command(ui_rollback)
ui_group.add_command(ui_activate)
ui_group.add_command(ui_enable)
ui_group.add_command(ui_disable)
