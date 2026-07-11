import unittest

from storage.repository.bot_route_state import _next_selection, _pool_key


class SmoothWeightedRoundRobinTest(unittest.TestCase):
    def test_equal_weights_alternate(self):
        candidates = [("opus", 1.0), ("sol", 1.0)]
        current_weights = {}
        selected = []

        for _ in range(6):
            name, current_weights = _next_selection(candidates, current_weights)
            selected.append(name)

        self.assertEqual(selected, ["sol", "opus", "sol", "opus", "sol", "opus"])

    def test_weight_two_receives_twice_the_slots(self):
        candidates = [("a", 2.0), ("b", 1.0)]
        current_weights = {}
        selected = []

        for _ in range(6):
            name, current_weights = _next_selection(candidates, current_weights)
            selected.append(name)

        self.assertEqual(selected.count("a"), 4)
        self.assertEqual(selected.count("b"), 2)

    def test_filtered_pool_does_not_reset_full_tier_cursor(self):
        full_tier = [("opus", 1.0), ("sol", 1.0)]
        filtered_tier = [("sol", 1.0), ("terra", 1.0)]
        current_weights = {}

        full_key = _pool_key(full_tier)
        filtered_key = _pool_key(filtered_tier)
        self.assertNotEqual(full_key, filtered_key)

        first, current_weights[full_key] = _next_selection(full_tier, current_weights.get(full_key, {}))
        filtered, current_weights[filtered_key] = _next_selection(filtered_tier, current_weights.get(filtered_key, {}))
        second, current_weights[full_key] = _next_selection(full_tier, current_weights.get(full_key, {}))

        self.assertEqual([first, filtered, second], ["sol", "terra", "opus"])


if __name__ == "__main__":
    unittest.main()
