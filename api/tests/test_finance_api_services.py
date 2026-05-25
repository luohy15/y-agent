import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_holding_positions_allocation_converts_to_usd_base(self):
        usd_stock = self._holding("QQQ", 1, 23020.97, "USD", False)
        usd_stock_2 = self._holding("NVDA", 1, 60000, "USD", False)
        hkd_stock = self._holding("0700", 1, 14311.85, "HKD", False)

        def fake_convert(_user_id, _vm_name, amount, currency, _base_currency, _as_of):
            rates = {"USD": 1, "HKD": 0.128, "CNY": 0.138}
            return amount * rates[currency]

        with patch.object(holding_service, "list_for", return_value=[usd_stock, usd_stock_2, hkd_stock]), patch.object(derived_service, "convert", side_effect=fake_convert):
            result = derived_service.holding_positions(123, "")

        rows = result.data
        gross_asset_base = 23020.97 + 60000 + 14311.85 * 0.128
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["symbol"] for row in rows], ["QQQ", "NVDA", "0700"])
        self.assertAlmostEqual(rows[0]["market_value_base"], 23020.97, places=2)
        self.assertAlmostEqual(rows[1]["market_value_base"], 60000, places=2)
        self.assertAlmostEqual(rows[2]["market_value_base"], 1831.92, places=2)
        self.assertAlmostEqual(rows[0]["allocation_pct"], 23020.97 / gross_asset_base, places=6)
        self.assertAlmostEqual(rows[1]["allocation_pct"], 60000 / gross_asset_base, places=6)
        self.assertAlmostEqual(rows[2]["allocation_pct"], (14311.85 * 0.128) / gross_asset_base, places=6)
        self.assertTrue(all(row["allocation_pct"] > 0 for row in rows))
        self.assertTrue(all(row["market_value_base"] > 0 for row in rows))
        self.assertAlmostEqual(sum(row["allocation_pct"] for row in rows), 1.0, places=4)
        self.assertEqual(rows[0]["allocation_base_currency"], "USD")

    def test_holding_positions_keeps_negative_balance_asset(self):
        # Source-level classification (BQL `^0` = Assets sortkey) filters out Liabilities
        # rows entirely, so anything that reaches list_for is Asset-class. The API layer
        # must NOT then drop a row by sign — a negative-balance Asset (e.g. temporary
        # overdraft on Assets:Cash:CNY) should still appear in the response.
        usd_stock = self._holding("QQQ", 1, 1000, "USD", False)
        negative_cash_asset = self._holding("CNY", -500, None, "CNY", True)

        def fake_convert(_user_id, _vm_name, amount, currency, _base_currency, _as_of):
            rates = {"USD": 1, "CNY": 0.14}
            return amount * rates[currency]

        with patch.object(holding_service, "list_for", return_value=[usd_stock, negative_cash_asset]), patch.object(derived_service, "convert", side_effect=fake_convert):
            result = derived_service.holding_positions(123, "")

        rows = result.data
        self.assertEqual([row["symbol"] for row in rows], ["QQQ", "CNY"])
        self.assertLess(rows[1]["market_value_base"], 0)
        self.assertLess(rows[1]["allocation_pct"], 0)

    def test_period_boundaries_supports_weekly_granularity(self):
        periods = derived_service.period_boundaries(datetime.date(2026, 5, 6), datetime.date(2026, 5, 25), "weekly")

        self.assertEqual(
            periods,
            [
                (datetime.date(2026, 5, 4), datetime.date(2026, 5, 11), "2026-W19"),
                (datetime.date(2026, 5, 11), datetime.date(2026, 5, 18), "2026-W20"),
                (datetime.date(2026, 5, 18), datetime.date(2026, 5, 25), "2026-W21"),
            ],
        )

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
