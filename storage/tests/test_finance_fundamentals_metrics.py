"""Unit tests for finance_fundamentals.compute_metrics."""

import unittest

from storage.service.finance_fundamentals import compute_metrics, _num


class ComputeMetricsTest(unittest.TestCase):
    def test_num_treats_none_sentinel(self):
        self.assertIsNone(_num("None"))
        self.assertIsNone(_num("none"))
        self.assertIsNone(_num("-"))
        self.assertIsNone(_num(None))
        self.assertEqual(_num("12.5"), 12.5)
        self.assertEqual(_num(10), 10.0)

    def test_hand_computed_example(self):
        # Hand-built annual pair so every formula is independently checkable.
        overview = {
            "MarketCapitalization": "1000000000",
            "PERatio": "20.0",
            "PriceToSalesRatioTTM": "5.0",
            "PriceToBookRatio": "4.0",
            "ReturnOnEquityTTM": "0.25",  # 25%
            "DividendYield": "0.015",  # 1.5%
            "PEGRatio": "1.0",
        }
        balance_sheet = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "totalAssets": "500000000",
                    "totalLiabilities": "200000000",
                    "totalShareholderEquity": "300000000",
                    "shortTermDebt": "20000000",
                    "longTermDebt": "80000000",
                    "totalCurrentAssets": "150000000",
                    "totalCurrentLiabilities": "50000000",
                    "inventory": "10000000",
                },
                {
                    "fiscalDateEnding": "2024-12-31",
                    "totalAssets": "400000000",
                    "totalLiabilities": "180000000",
                    "totalShareholderEquity": "250000000",
                },
            ]
        }
        income_statement = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "totalRevenue": "200000000",
                    "costOfRevenue": "80000000",
                    "grossProfit": "120000000",
                    "operatingExpenses": "40000000",
                    "sellingGeneralAndAdministrative": "20000000",
                    "researchAndDevelopment": "10000000",
                    "interestExpense": "2000000",
                    "netIncome": "50000000",
                },
                {
                    "fiscalDateEnding": "2024-12-31",
                    "totalRevenue": "160000000",
                    "netIncome": "40000000",
                },
            ]
        }
        cash_flow = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "operatingCashflow": "60000000",
                    "capitalExpenditures": "-15000000",
                }
            ]
        }
        earnings = {
            "quarterlyEarnings": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "reportedEPS": "1.25",
                    "estimatedEPS": "1.20",
                    "surprise": "0.05",
                    "surprisePercentage": "4.1667",
                }
            ]
        }

        m = compute_metrics(overview, balance_sheet, income_statement, cash_flow, earnings)

        self.assertEqual(m["market"]["market_cap"], 1_000_000_000.0)
        self.assertAlmostEqual(m["market"]["dividend_yield"], 1.5)
        self.assertEqual(m["valuation"]["pe_ratio"], 20.0)
        self.assertEqual(m["valuation"]["ps_ratio"], 5.0)
        self.assertEqual(m["valuation"]["pb_ratio"], 4.0)
        self.assertAlmostEqual(m["valuation"]["roe"], 25.0)

        self.assertEqual(m["balance_sheet"]["assets"], 500_000_000.0)
        self.assertEqual(m["balance_sheet"]["liabilities"], 200_000_000.0)
        self.assertEqual(m["balance_sheet"]["equity"], 300_000_000.0)
        self.assertAlmostEqual(m["balance_sheet"]["leverage_ratio"], 500_000_000 / 300_000_000)

        self.assertEqual(m["income_statement"]["revenue"], 200_000_000.0)
        self.assertEqual(m["income_statement"]["net_income"], 50_000_000.0)
        # Doc identity: Expenses = Revenue - Net Income = 150M (not AV's 40M
        # operatingExpenses, which is only R&D + SG&A); ratio = 150/200 = 75%
        self.assertEqual(m["income_statement"]["expenses"], 150_000_000.0)
        self.assertAlmostEqual(m["income_statement"]["expense_ratio"], 75.0)

        # Gross margin = (200-80)/200 = 60%
        self.assertAlmostEqual(m["profitability"]["gross_margin"], 60.0)
        # Net margin = 50/200 = 25%
        self.assertAlmostEqual(m["profitability"]["net_margin"], 25.0)
        # ROA = 50/500 = 10%
        self.assertAlmostEqual(m["profitability"]["roa"], 10.0)
        # SG&A / Revenue = 20/200 = 10%; R&D / Revenue = 10/200 = 5%
        self.assertAlmostEqual(m["profitability"]["sga_expense_ratio"], 10.0)
        self.assertAlmostEqual(m["profitability"]["rd_expense_ratio"], 5.0)

        # Revenue growth = (200-160)/160 = 25%
        self.assertAlmostEqual(m["growth"]["revenue_growth"], 25.0)
        # Profit growth = (50-40)/40 = 25%
        self.assertAlmostEqual(m["growth"]["profit_growth"], 25.0)
        # PEG = PE / profit_growth = 20 / 25 = 0.8
        self.assertAlmostEqual(m["growth"]["peg"], 0.8)

        # FCF = 60M - 15M = 45M
        self.assertEqual(m["cash_flow"]["operating_cash_flow"], 60_000_000.0)
        self.assertEqual(m["cash_flow"]["free_cash_flow"], 45_000_000.0)

        # Debt = 20M + 80M = 100M; debt/assets = 20%
        self.assertAlmostEqual(m["solvency"]["debt_to_asset"], 20.0)
        # Years to clear = 100M / 50M = 2
        self.assertAlmostEqual(m["solvency"]["years_to_clear_debt"], 2.0)
        # Current = 150/50 = 3; Quick = (150-10)/50 = 2.8
        self.assertAlmostEqual(m["solvency"]["current_ratio"], 3.0)
        self.assertAlmostEqual(m["solvency"]["quick_ratio"], 2.8)

        self.assertEqual(len(m["earnings_history"]), 1)
        self.assertEqual(m["earnings_history"][0]["reported_eps"], 1.25)

    def test_roe_above_100_pct_is_not_rescaled(self):
        # AV always returns ReturnOnEquityTTM as a decimal; AAPL's 1.415 is 141.5%,
        # not 1.415% (the old <= 1.5 guard silently divided high-ROE names by 100).
        m = compute_metrics({"ReturnOnEquityTTM": "1.415"}, None, None, None, None)
        self.assertAlmostEqual(m["valuation"]["roe"], 141.5)

    def test_fcf_is_null_without_capex(self):
        cash_flow = {"annualReports": [{"operatingCashflow": "60000000", "capitalExpenditures": "None"}]}
        m = compute_metrics(None, None, None, cash_flow, None)
        self.assertEqual(m["cash_flow"]["operating_cash_flow"], 60_000_000.0)
        self.assertIsNone(m["cash_flow"]["free_cash_flow"])

    def test_zero_debt_reports_zero_not_missing(self):
        balance_sheet = {
            "annualReports": [
                {
                    "totalAssets": "500000000",
                    "shortTermDebt": "0",
                    "longTermDebt": "0",
                }
            ]
        }
        m = compute_metrics(None, balance_sheet, None, None, None)
        self.assertEqual(m["solvency"]["debt_to_asset"], 0.0)

    def test_expenses_fall_back_to_operating_expenses(self):
        # Net income missing → the doc identity cannot be applied, so AV's
        # operatingExpenses is the fallback.
        income_statement = {
            "annualReports": [{"totalRevenue": "200000000", "operatingExpenses": "40000000"}]
        }
        m = compute_metrics(None, None, income_statement, None, None)
        self.assertEqual(m["income_statement"]["expenses"], 40_000_000.0)
        self.assertAlmostEqual(m["income_statement"]["expense_ratio"], 20.0)

    def test_missing_inputs_yield_nulls(self):
        m = compute_metrics(None, None, None, None, None)
        self.assertIsNone(m["valuation"]["pe_ratio"])
        self.assertIsNone(m["balance_sheet"]["assets"])
        self.assertIsNone(m["growth"]["revenue_growth"])
        self.assertEqual(m["earnings_history"], [])


if __name__ == "__main__":
    unittest.main()
