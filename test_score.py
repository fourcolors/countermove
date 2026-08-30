import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import score


ROOT = Path(__file__).parent


def company(customers=300, elasticity=-1.1, competitor_price=45):
    return {
        "name": "Test Co",
        "plans": [{
            "id": "pro",
            "price": 49,
            "segments": [{
                "id": "smb",
                "customers": customers,
                "monthly_churn": 0.04,
                "elasticity": elasticity,
                "cross_elasticity": 0.4,
            }],
        }],
        "competitors": [{"name": "Rival", "price": competitor_price}],
    }


def move(to=59):
    return {"plan": "pro", "from": 49, "to": to, "action": "open_pr"}


def leaf(c_prime=45, eps=None, choice="hold"):
    assumptions = {"competitor_average_after": c_prime}
    if eps is not None:
        assumptions["eps"] = eps
    return {"id": "leaf-test", "choice": choice, "assumptions": assumptions}


class ReviewRegressionTests(unittest.TestCase):
    def test_displayed_eta_matches_segment_cross_elasticity(self):
        co = company()
        co["plans"][0]["segments"][0]["cross_elasticity"] = 0.3
        result = score.score_leaf(co, move(), leaf())
        self.assertEqual(result["assumptions"]["eta"], 0.3)

    def test_displayed_eta_is_per_segment_when_segments_differ(self):
        co = company()
        co["plans"][0]["segments"].append({
            "id": "mid", "customers": 120, "monthly_churn": 0.02,
            "elasticity": -0.8, "cross_elasticity": 0.3,
        })
        result = score.score_leaf(co, move(), leaf())
        self.assertEqual(result["assumptions"]["eta"], {"smb": 0.4, "mid": 0.3})

    def test_unresolvable_competitor_prices_raise(self):
        bad = {"id": "leaf-x", "choice": "hold", "parent": "not-a-response", "assumptions": {}}
        with self.assertRaises(ValueError):
            score.score_leaf(company(), move(), bad)

    def test_expanded_high_band_is_strictly_negative(self):
        for mid in (-0.05, -0.1, -0.15, -1.1):
            self.assertLess(score.expand_elasticity(mid)["high"], 0.0)

    def test_monthly_sum_matches_pinned_formula(self):
        expected = 300 * sum((1 - 0.04) ** t for t in range(1, 7))
        self.assertAlmostEqual(
            score.surviving_customer_months(300, 0.04, 6), expected, places=9)


class FeatureScorerTests(unittest.TestCase):
    def test_baseline_equals_no_move_revenue(self):
        result = score.score_leaf(company(), move(49), leaf())
        self.assertEqual({result[name] for name in score.BANDS}, {0.0})

    def test_inelastic_segment_gains_revenue_on_a_price_increase(self):
        result = score.score_leaf(company(elasticity=-0.8), move(), leaf(eps=-0.8))
        self.assertGreater(result["mid"], 0)

    def test_elastic_segment_loses_revenue_on_a_price_increase(self):
        result = score.score_leaf(company(elasticity=-1.5), move(), leaf(eps=-1.5))
        self.assertLess(result["mid"], 0)

    def test_competitor_undercut_reduces_the_price_factor_and_score_band(self):
        unchanged_factor = score.price_factor(49, 59, 45, 45, -1.1, 0.4)
        undercut_factor = score.price_factor(49, 59, 45, 39, -1.1, 0.4)
        unchanged = score.score_leaf(company(), move(), leaf(45))
        undercut = score.score_leaf(company(), move(), leaf(39))
        self.assertLess(undercut_factor, unchanged_factor)
        for band in score.BANDS:
            self.assertLess(undercut[band], unchanged[band])

    def test_price_factor_is_capped_at_one(self):
        factor = score.price_factor(49, 20, 45, 45, -0.1, 0.4)
        organic = score.surviving_customer_months(300, 0.04, 6)
        self.assertEqual(factor, 1.0)
        self.assertLessEqual(organic * factor, organic)

    def test_competitor_raise_does_not_invent_customers(self):
        factor = score.price_factor(49, 49, 45, 50, -1.1, 0.4)
        result = score.score_leaf(company(), move(49), leaf(50))
        self.assertEqual(factor, 1.0)
        self.assertEqual(result["mid"], 0.0)

    def test_score_is_a_band_not_a_number(self):
        result = score.score_leaf(company(elasticity=-1.1), move(), leaf(eps=-1.1))
        self.assertEqual(result["assumptions"]["eps"], {"low": -1.25, "mid": -1.1, "high": -0.95})
        self.assertTrue(set(("low", "mid", "high", "low_pct", "mid_pct", "high_pct")).issubset(result))
        self.assertNotIn("confidence", result)

    def test_scorer_runs_in_the_sandbox(self):
        fixture_company = json.loads((ROOT / "contracts/fixtures/company.json").read_text())
        tree = json.loads((ROOT / "contracts/fixtures/tree.json").read_text())
        fixture_leaf = next(node for node in tree["nodes"] if node["id"] == "leaf-rival-a-undercut-hold")
        payload = {"company": fixture_company, "move": move(), "leaf": fixture_leaf}
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as input_file:
            json.dump(payload, input_file)
            input_file.flush()
            completed = subprocess.run(
                [sys.executable, str(ROOT / "score.py"), input_file.name],
                check=True,
                capture_output=True,
                text=True,
            )
        result = json.loads(completed.stdout)
        event = json.loads(completed.stderr)
        required = {"leaf_id", "low", "mid", "high", "low_pct", "mid_pct", "high_pct", "assumptions"}
        self.assertEqual(set(result), required)
        self.assertEqual(event["tool"], "trueforge.sandbox.exec")
        self.assertEqual(event["detail"]["output"], result)
        self.assertEqual(event["detail"]["input"], payload)

    def test_rerunning_with_a_changed_assumption_produces_a_new_band(self):
        original = score.score_leaf(company(), move(), leaf(eps=-1.1))
        changed = score.score_leaf(company(), move(), leaf(eps=-0.9))
        self.assertNotEqual([original[name] for name in score.BANDS], [changed[name] for name in score.BANDS])

    def test_zero_baseline_percent_is_na(self):
        result = score.score_leaf(company(customers=0), move(), leaf())
        self.assertEqual([result[f"{band}_pct"] for band in score.BANDS], ["n/a"] * 3)

    def test_counter_move_defaults(self):
        partial = score.counter_terms(move(), leaf(choice="partial_rollback"), 300, 6)
        discount = score.counter_terms(move(), leaf(choice="annual_discount"), 300, 6)
        self.assertEqual(partial[:2], (54.0, 0.0))
        self.assertEqual(partial[2], {"choice": "partial_rollback", "rollback_fraction": 0.5})
        self.assertEqual(discount[0], 59.0)
        self.assertAlmostEqual(discount[1], 3186.0)
        self.assertEqual(discount[2], {"choice": "annual_discount", "discount_rate": 0.1, "uptake": 0.3})

    def test_monthly_sum_not_end_of_horizon_times_months(self):
        monthly_sum = score.surviving_customer_months(300, 0.04, 6)
        end_times_months = 300 * (1 - 0.04) ** 6 * 6
        self.assertNotAlmostEqual(monthly_sum, end_times_months)


if __name__ == "__main__":
    unittest.main()


class QodoRegressionTests(unittest.TestCase):
    def test_counter_parameters_are_displayed(self):
        rollback = score.score_leaf(company(), move(), leaf(choice="partial_rollback"))
        self.assertEqual(rollback["assumptions"]["counter"],
                         {"choice": "partial_rollback", "rollback_fraction": 0.5})
        discount = score.score_leaf(company(), move(), leaf(choice="annual_discount"))
        self.assertEqual(discount["assumptions"]["counter"],
                         {"choice": "annual_discount", "discount_rate": 0.1, "uptake": 0.3})

    def test_zero_resulting_price_raises_not_crashes(self):
        with self.assertRaises(ValueError):
            score.price_factor(49, 0, 45, 45, -1.1, 0.4)
