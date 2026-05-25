import unittest
from types import SimpleNamespace

from api import service_finance_derived as derived_service
from storage.dto.finance_holding import FinanceHolding
from storage.dto.finance_transaction import FinanceTransaction
from storage.service import finance_holding as holding_service
from storage.service import finance_transaction as transaction_service


class FinanceApiServicesTest(unittest.TestCase):
    def test_prune_zero_balance_accounts_keeps_nonzero_branches(self):
        tree = {
            "account": "Assets",
            "balance": {},
            "children": [
                {"account": "Assets:Closed", "balance": {"USD": 0}, "children": []},
                {"account": "Assets:Tiny", "balance": {"USD": 0.004}, "children": []},
                {"account": "Assets:Brokerage", "balance": {}, "children": [
                    {"account": "Assets:Brokerage:AAPL", "balance": {"USD": 10}, "children": []},
                ]},
            ],
        }

        pruned = derived_service.prune_zero_balance_accounts(tree)

        self.assertEqual([child["account"] for child in pruned["children"]], ["Assets:Brokerage"])
        self.assertEqual(pruned["children"][0]["children"][0]["account"], "Assets:Brokerage:AAPL")

    def test_filter_holdings_hides_zero_and_applies_risky_only(self):
        stock = SimpleNamespace(symbol="AAPL", quantity=1, market_value=100, cost_currency="USD", is_cash=False)
        cash = SimpleNamespace(symbol="USD", quantity=100, market_value=100, cost_currency="USD", is_cash=True)
        zero_quantity = SimpleNamespace(symbol="MSFT", quantity=0, market_value=100, cost_currency="USD", is_cash=False)
        zero_market = SimpleNamespace(symbol="GOOG", quantity=1, market_value=0, cost_currency="USD", is_cash=False)

        self.assertEqual(holding_service.filter_holdings([stock, cash, zero_quantity, zero_market]), [stock, cash])
        self.assertEqual(holding_service.filter_holdings([stock, cash], risky_only=True), [stock])

    def test_positions_payload_uses_quantity_for_cash_market_value(self):
        cash = self._holding("USD", 100, None, "USD", True)
        stock = self._holding("AAPL", 1, 200, "USD", False)

        rows = holding_service.with_effective_values(holding_service.filter_holdings([stock, cash]))

        self.assertEqual(rows[0]["market_value"], 200)
        self.assertEqual(rows[1]["market_value"], 100)
        self.assertEqual(sum(row["market_value"] for row in rows), 300)

    def test_entry_rows_returns_one_row_per_beancount_entry(self):
        rows = [
            self._transaction("entry-1", 0, "AAPL", "Buy", 1, "AAPL"),
            self._transaction("entry-1", 1, "USD", "Withdrawal", -100, "USD"),
            self._transaction("entry-2", 0, "USD", "Dividend", 5, "USD", narration="Dividend"),
        ]

        entries = transaction_service.entry_rows(rows)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["entry_id"], "entry-1")
        self.assertEqual(entries[0]["symbol"], "AAPL, USD")
        self.assertEqual(entries[0]["side"], "Buy, Withdrawal")
        self.assertEqual(len(entries[0]["postings"]), 2)
        self.assertEqual(entries[0]["quantity"], [{"amount": 1.0, "currency": "AAPL"}, {"amount": -100.0, "currency": "USD"}])

    def _transaction(self, entry_id, posting_index, symbol, side, amount, currency, narration="Buy AAPL"):
        return FinanceTransaction(
            id=posting_index,
            user_id=123,
            vm_name="",
            transaction_date="2026-05-01",
            entry_id=entry_id,
            posting_index=posting_index,
            account="Assets:Broker",
            symbol=symbol,
            side=side,
            quantity=amount,
            price=None,
            price_currency="",
            amount=amount,
            amount_currency=currency,
            cost=None,
            cost_currency="",
            commission=None,
            commission_currency="",
            payee="Broker",
            narration=narration,
            tags=[],
            links=[],
            synced_at="2026-05-25T00:00:00Z",
            source="test",
        )

    def _holding(self, symbol, quantity, market_value, cost_currency, is_cash):
        return FinanceHolding(
            id=None,
            user_id=123,
            vm_name="",
            snapshot_at="2026-05-25T00:00:00+00:00",
            snapshot_date="2026-05-25",
            symbol=symbol,
            quantity=quantity,
            average_cost=None,
            price=None,
            book_value=None,
            market_value=market_value,
            unrealized_profit_pct=None,
            cost_currency=cost_currency,
            is_cash=is_cash,
            synced_at="2026-05-25T00:00:00Z",
            source="test",
        )


if __name__ == "__main__":
    unittest.main()
