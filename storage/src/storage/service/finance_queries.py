"""Shared finance beancount query definitions."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FinanceQuery:
    view: str
    subcommand: str
    time_filter: str = ""
    history: bool = False
    granularity: str = ""
    convert: str = ""


CANONICAL_QUERIES: List[FinanceQuery] = [
    FinanceQuery("balance_sheet", "balance-sheet", time_filter="year", convert="USD"),
    FinanceQuery("balance_sheet", "balance-sheet", time_filter="year", history=True, granularity="monthly", convert="USD"),
    FinanceQuery("balance_sheet", "balance-sheet", time_filter="year", history=True, granularity="yearly", convert="USD"),
    FinanceQuery("income_statement", "income-statement", time_filter="year"),
    FinanceQuery("income_statement", "income-statement", time_filter="year", history=True, granularity="monthly", convert="USD"),
    FinanceQuery("income_statement", "income-statement", time_filter="year", history=True, granularity="yearly", convert="USD"),
    FinanceQuery("fire_progress", "fire-progress", convert="USD"),
]


def beancount_cmd(query: FinanceQuery) -> list[str]:
    cmd = ["y", "beancount"]
    if query.time_filter:
        cmd += ["--time", query.time_filter]
    if query.history:
        cmd += ["--history", "--granularity", query.granularity or "monthly"]
    if query.convert:
        cmd += ["--convert", query.convert]
    cmd.append(query.subcommand)
    return cmd
