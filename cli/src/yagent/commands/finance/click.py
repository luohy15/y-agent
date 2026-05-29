import click

from yagent.commands.beancount.click import beancount_group

from .balance_sheet import balance_sheet
from .fire_progress import fire_progress
from .income_statement import income_statement
from .holdings import holdings
from .prices import prices
from .transactions import transactions


@click.group("finance")
def finance_group():
    """DB-backed finance views (mirror of /api/finance/*).

    Daily-use read path; commands print friendly tables by default, with the raw
    JSON envelope behind --json. Use y finance beancount for raw ledger access.
    """


finance_group.add_command(balance_sheet)
finance_group.add_command(income_statement)
finance_group.add_command(holdings)
finance_group.add_command(transactions)
finance_group.add_command(prices)
finance_group.add_command(fire_progress)
finance_group.add_command(beancount_group)
