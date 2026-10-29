"""Semantic tests for the independent deterministic notice baseline."""
import unittest

from notice_benchmark.rules import extract_notice


CONTEXT = {
    'routes': [{'name': 'NL_ocean', 'lead': 5}, {'name': 'NL_air', 'lead': 1}],
    'horizon': 16,
    'scope_route': 'NL_ocean',
    'period': 'week',
    'window_semantics': 'dispatch_weeks_one_based_inclusive',
}


def ready(start, end, value):
    return {'status': 'ready', 'changes': [{'op': 'add_lead', 'route': 'NL_ocean',
                                          'start_week': start, 'end_week': end,
                                          'value': value}]}


class RuleNoticeTests(unittest.TestCase):
    def test_added_weeks_spelled_numbers_and_inclusive_window(self):
        self.assertEqual(extract_notice('NL_ocean dispatches in weeks five through nine require two extra weeks.', CONTEXT), ready(5, 9, 2))

    def test_added_days_convert_exactly(self):
        self.assertEqual(extract_notice('NL_ocean: weeks 5-9 dispatches are delayed by 14 days.', CONTEXT), ready(5, 9, 2))

    def test_nonintegral_days_require_clarification(self):
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 5-9: add 10 days.', CONTEXT)['status'], 'needs_clarification')

    def test_fortnight(self):
        self.assertEqual(extract_notice('NL_ocean dispatches during weeks 5 to 9: add a fortnight.', CONTEXT), ready(5, 9, 2))
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 3-6: the extra transit time is 2 fortnights.', CONTEXT), ready(3, 6, 4))

    def test_revised_total_uses_public_baseline(self):
        self.assertEqual(extract_notice('For NL_ocean dispatches in weeks 5 through 9, transit time is now 7 weeks.', CONTEXT), ready(5, 9, 2))

    def test_from_to_total_is_not_additional_lead(self):
        self.assertEqual(extract_notice('NL_ocean dispatches in weeks 5-9: transit time increases from 5 to 7 weeks.', CONTEXT), ready(5, 9, 2))

    def test_total_requires_known_baseline(self):
        context = {'routes': [{'name': 'NL_ocean'}], 'horizon': 16}
        self.assertEqual(extract_notice('NL_ocean dispatches in weeks 5-9: transit time is 7 weeks.', context)['status'], 'needs_clarification')

    def test_lower_total_not_negative_addition(self):
        self.assertEqual(extract_notice('NL_ocean weeks 5-9: transit time is 4 weeks.', CONTEXT)['status'], 'needs_clarification')

    def test_known_irrelevant_route_is_noop(self):
        self.assertEqual(extract_notice('NL_air departures in weeks 5-9: add two weeks.', CONTEXT), {'status': 'ready', 'changes': []})

    def test_unknown_and_missing_routes_are_not_guessed(self):
        for text in ['BE_ocean weeks 5-9: add 2 weeks.', 'Ocean dispatches in weeks 5-9: add 2 weeks.']:
            with self.subTest(text=text):
                self.assertEqual(extract_notice(text, CONTEXT)['status'], 'needs_clarification')

    def test_geographic_route_alias_requires_both_endpoints_and_mode(self):
        self.assertEqual(extract_notice('Rotterdam to Singapore sea dispatches in weeks 5-9: add 2 weeks.', CONTEXT), ready(5, 9, 2))

    def test_explicit_no_delay_requires_no_window(self):
        self.assertEqual(extract_notice('NL_ocean is not delayed.', CONTEXT), {'status': 'ready', 'changes': []})

    def test_negated_number_is_not_positive_or_zero_delay(self):
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 5-9 are not delayed by 2 weeks; the actual delay is unknown.', CONTEXT)['status'], 'needs_clarification')
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 5-9 are not delayed by 2 weeks.', CONTEXT)['status'], 'needs_clarification')
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 5-9: do not add 2 weeks.', CONTEXT)['status'], 'needs_clarification')

    def test_textual_baseline_conflict_requires_clarification(self):
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 5-9: transit time is 7 weeks, normally 6 weeks.', CONTEXT)['status'], 'needs_clarification')

    def test_correction_supersedes_original(self):
        text = 'NL_ocean dispatches in weeks 5-9: add one week. Correction: NL_ocean dispatches in weeks 5-9: add three weeks.'
        self.assertEqual(extract_notice(text, CONTEXT), ready(5, 9, 3))

    def test_partial_correction_inherits_explicit_route_and_window(self):
        text = 'NL_ocean dispatches in weeks 5-9: add one week. Correction: add three weeks.'
        self.assertEqual(extract_notice(text, CONTEXT), ready(5, 9, 3))

    def test_correction_not_old_but_new(self):
        self.assertEqual(extract_notice('NL_ocean dispatches in weeks 5-9: add not two but three weeks.', CONTEXT), ready(5, 9, 3))

    def test_uncertain_range_is_not_point_estimate(self):
        for text in ['NL_ocean weeks 5-9: add 1-3 weeks.', 'NL_ocean weeks 5-9: add up to 2 weeks.', 'NL_ocean weeks 5-9 may be delayed by 2 weeks.']:
            with self.subTest(text=text):
                self.assertEqual(extract_notice(text, CONTEXT)['status'], 'needs_clarification')

    def test_arrival_window_is_not_dispatch_window(self):
        self.assertEqual(extract_notice('NL_ocean arrivals in weeks 5-9: add 2 weeks.', CONTEXT)['status'], 'needs_clarification')
        self.assertEqual(extract_notice('NL_ocean weeks 3-6 refer to the arrival window, not dispatches. Add 2 weeks.', CONTEXT)['status'], 'needs_clarification')

    def test_reporting_week_does_not_replace_effective_window(self):
        self.assertEqual(extract_notice('Issued in planning week 3: NL_ocean needs 2 additional weeks. Dispatch weeks have not been announced.', CONTEXT)['status'], 'needs_clarification')

    def test_explicitly_retired_values_are_not_current_effects(self):
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 3-6: the earlier notice said add 2 weeks. Replace that figure with an extra 3 weeks; do not add both figures.', CONTEXT), ready(3, 6, 3))

    def test_retracted_alert_with_confirmed_normal_service(self):
        self.assertEqual(extract_notice('Cancel the earlier 2-week delay for NL_ocean dispatch weeks 3-6. Baseline transit duration is unchanged.', CONTEXT), {'status': 'ready', 'changes': []})

    def test_range_with_extra_unit_is_ambiguous(self):
        self.assertEqual(extract_notice('NL_ocean dispatch weeks 3-6: the delay range is 2-4 extra weeks.', CONTEXT)['status'], 'needs_clarification')

    def test_multiple_disjoint_windows(self):
        result = extract_notice('NL_ocean dispatch weeks 2-4: add 1 week; NL_ocean dispatch weeks 8-10: add 2 weeks.', CONTEXT)
        self.assertEqual(result, {'status': 'ready', 'changes': [ready(2, 4, 1)['changes'][0], ready(8, 10, 2)['changes'][0]]})

    def test_two_windows_same_value(self):
        result = extract_notice('NL_ocean dispatch weeks 2-4 and weeks 8-10: add 2 weeks.', CONTEXT)
        self.assertEqual(result, {'status': 'ready', 'changes': [ready(2, 4, 2)['changes'][0], ready(8, 10, 2)['changes'][0]]})

    def test_overlap_conflict_requires_clarification(self):
        result = extract_notice('NL_ocean weeks 2-6: add 1 week; NL_ocean weeks 5-9: add 2 weeks.', CONTEXT)
        self.assertEqual(result['status'], 'needs_clarification')

    def test_duplicate_statement_does_not_double_increment(self):
        result = extract_notice('NL_ocean weeks 2-4: add 1 week; NL_ocean weeks 2-4: add 1 week.', CONTEXT)
        self.assertEqual(result, ready(2, 4, 1))

    def test_window_boundaries(self):
        for window in ['0-4', '12-17', '9-5']:
            with self.subTest(window=window):
                self.assertEqual(extract_notice(f'NL_ocean weeks {window}: add 1 week.', CONTEXT)['status'], 'needs_clarification')

    def test_missing_critical_parameters(self):
        for text in ['NL_ocean dispatches will be delayed.', 'NL_ocean weeks 5-9: revised lead unknown.', 'NL_ocean: add 2 weeks.']:
            with self.subTest(text=text):
                self.assertEqual(extract_notice(text, CONTEXT)['status'], 'needs_clarification')

    def test_no_benchmark_metadata_is_required(self):
        self.assertEqual(extract_notice('NL_ocean week 3: add 1 week.', dict(CONTEXT, ignored_case_id='irrelevant')), ready(3, 3, 1))


if __name__ == '__main__':
    unittest.main()
