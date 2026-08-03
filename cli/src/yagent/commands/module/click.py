import click

from .activate import module_activate
from .create import module_create
from .delete import module_delete
from .enable import module_disable, module_enable
from .list import module_list
from .publish import module_publish
from .rollback import module_rollback
from .versions import module_versions


@click.group("module")
def module_group():
    """Manage hot-loadable backend modules (create, publish, version, rollback)."""
    pass


module_group.add_command(module_create)
module_group.add_command(module_list)
module_group.add_command(module_versions)
module_group.add_command(module_publish)
module_group.add_command(module_rollback)
module_group.add_command(module_activate)
module_group.add_command(module_enable)
module_group.add_command(module_disable)
module_group.add_command(module_delete)
