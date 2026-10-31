import copy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from rolling_recourse.experiment import (actions, audit_physics, configuration, cost,
                                         emission, leaves, marginals, optimize, verify)


class RecourseTests(unittest.TestCase):
    def test_exact_marginals_and_unresolved_future_at_same_history(self):
        margins = []
        for coupling in ('positive', 'independent', 'negative'):
            rows, d = leaves(coupling, [3, 4], 2)
            self.assertEqual(sum(Fraction(r['weight'], d) for r in rows), 1)
            margins.append(marginals(rows, d))
            histories = {tuple(r['signal']) for r in rows}
            self.assertEqual(len(histories), 4)
            for history in histories:
                futures = {tuple(r['terminal_high']) for r in rows if tuple(r['signal']) == history}
                self.assertGreater(len(futures), 1)
        self.assertEqual(margins[0], margins[1])
        self.assertEqual(margins[1], margins[2])

    def test_arrivals_and_final_backlog_in_hand_calculated_ledger(self):
        cfg = configuration()
        # Start [1,1], consume [1,1], then [2,2]. No shipments => 4*12 final penalty.
        self.assertEqual(cost(cfg, (0, 0, 0, 0), (0, 0, 0, 0),
                              [[1, 1], [0, 0], [2, 2]]), 48)
        # One slow unit each arrives at t=2: freight 2 + remaining backlog 2*12.
        self.assertEqual(cost(cfg, (1, 0, 1, 0), (0, 0, 0, 0),
                              [[1, 1], [0, 0], [2, 2]]), 26)

    def test_pathwise_carbon_and_nonanticipative_policy_replay(self):
        cfg = configuration()
        result = optimize(cfg, 1, 6, 'independent', [3, 4])
        method = result['methods']['history_recourse']
        root_carbon = emission(method['first'], cfg)
        # Mutually exclusive branches share a budget, not a sum of all branches.
        self.assertGreater(root_carbon + sum(emission(n['second'], cfg) for n in method['nodes']), 6)
        self.assertTrue(all(root_carbon+emission(n['second'], cfg) <= 6 for n in method['nodes']))
        self.assertEqual(len(method['nodes']), 4)
        audit_physics(cfg, result)
        altered = copy.deepcopy(result)
        altered['methods']['history_recourse']['nodes'][0]['second'] = [0, 3, 0, 0]
        with self.assertRaisesRegex(ValueError, 'shared_route_capacity'):
            audit_physics(cfg, altered, check_milp=False)

    def test_enumeration_invariance_and_MILP_crosscheck(self):
        cfg = configuration()
        values = []
        recourse_values = []
        for coupling in cfg['couplings']:
            result = optimize(cfg, 1, 6, coupling, [3, 4])
            audit_physics(cfg, result)
            values.append(result['methods']['open_loop']['cost_numerator'])
            recourse_values.append(result['methods']['history_recourse']['cost_numerator'])
        self.assertEqual(len(set(values)), 1)
        self.assertGreater(len(set(recourse_values)), 1)

    def test_tie_robust_baseline_eliminates_apparent_gain(self):
        result = optimize(configuration(), 1, 6, 'independent', [3, 4])
        m = result['methods']
        self.assertLess(m['history_recourse']['cost_numerator'], m['rolling_open_loop']['cost_numerator'])
        self.assertEqual(m['history_recourse']['cost_numerator'], m['rolling_best_open_tie']['cost_numerator'])
        self.assertIn(m['history_recourse']['first'], result['open_loop_optimal_first_actions'])
        self.assertGreater(len(result['open_loop_optimal_first_actions']), 1)

    def test_action_enumeration_excludes_late_arrivals(self):
        cfg = configuration()
        self.assertEqual(actions(cfg, 4, 100, 2), [(0, 0, 0, 0)])
        for action in actions(cfg, 4, 6, 1):
            self.assertEqual(action[0]+action[2], 0)
            self.assertLessEqual(emission(action, cfg), 6)

    def test_full_reexecution_rejects_rehashed_policy_tampering(self):
        root = Path(__file__).resolve().parents[1]
        saved = root / 'benchmark_results/rolling_recourse_mechanism'
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            for name in ('results.json', 'manifest.json'):
                (target/name).write_bytes((saved/name).read_bytes())
            result = json.loads((target/'results.json').read_text())
            result['models'][0]['methods']['history_recourse']['first'][0] += 1
            data = json.dumps(result).encode()
            (target/'results.json').write_bytes(data)
            manifest = json.loads((target/'manifest.json').read_text())
            manifest['files']['results.json'] = sha256(data).hexdigest()
            (target/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'full_policy_reexecution_mismatch'):
                verify(target)


if __name__ == '__main__':
    unittest.main()
