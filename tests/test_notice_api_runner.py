"""Offline transport-contract, budget, and resume tests; never call a live API."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from notice_benchmark import api_runner as runner


# Deliberately generated test-only token, never a provisioned credential.
FAKE_KEY = 'sk-proj-' + ('TEST_ONLY_' * 8)
CONTEXT = {
    'routes': [{'name': 'NL_air', 'lead': 1}, {'name': 'NL_ocean', 'lead': 5}],
    'horizon': 16, 'scope_route': 'NL_ocean', 'period': 'week',
    'window_semantics': 'dispatch_weeks_one_based_inclusive',
}
OUTPUT = {'status': 'ready', 'changes': [{'op': 'add_lead', 'route': 'NL_ocean',
                                        'start_week': 3, 'end_week': 5, 'value': 2}]}


def response(output=None, model='gpt-6-luna', *, input_tokens=150, output_tokens=40):
    return {'id': 'resp_offline_mock', 'model': model, 'status': 'completed', 'error': None,
            'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens,
                      'total_tokens': input_tokens + output_tokens},
            'output': [{'type': 'message', 'content': [{'type': 'output_text',
                        'text': json.dumps(OUTPUT if output is None else output)}]}]}


def dataset(rows=2):
    return {'schema_version': 'offline_test', 'synthetic': True, 'splits': {
        split: [{'id': f'{split}-case-{i}', 'category': 'NEVER_SEND_CATEGORY',
                 'reference': {'secret_ground_truth': 'NEVER_SEND_REFERENCE'},
                 'event_id': f'NEVER_SEND_EVENT_{i}', 'template_family_id': 'NEVER_SEND_TEMPLATE',
                 'model_input': {'text': f'NL_ocean notice {i}: dispatch weeks 3-5 add 2 weeks.',
                                 'context': deepcopy(CONTEXT)}} for i in range(rows)]
        for split in ['development', 'test']}}


class ApiRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dataset_path = self.root / 'dataset.json'
        self.dataset_path.write_text(json.dumps(dataset()))
        self.output = self.root / 'run'

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, **kwargs):
        values = {'execute': True, 'max_usd': '1', 'api_key': FAKE_KEY,
                  'transport': lambda body, key, timeout: response()}
        values.update(kwargs)
        return runner.run_benchmark(self.dataset_path, self.output, **values)

    def read_results(self):
        return [json.loads(line) for line in (self.output / 'records.jsonl').read_text().splitlines()
                if json.loads(line)['kind'] == 'result']

    def test_default_dry_run_never_reads_key_or_calls_transport(self):
        with patch.object(runner, '_load_api_key', side_effect=AssertionError('must not read key')):
            result = runner.run_benchmark(self.dataset_path, self.output,
                                          transport=lambda *args: self.fail('network called'))
        self.assertEqual(result['mode'], 'dry_run')
        self.assertEqual(result['executed_requests'], 0)
        self.assertGreater(float(result['estimated_max_usd']), 0)
        self.assertIn('not_fully_pinned', result['model_pinning'])
        self.assertFalse((self.output / 'records.jsonl').exists())
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_payload_contains_only_public_model_input_not_answer_metadata(self):
        seen = []
        def transport(body, key, timeout):
            seen.append(body)
            self.assertEqual(key, FAKE_KEY)
            self.assertEqual(body['reasoning'], {'effort': 'none'})
            self.assertFalse(body['store'])
            self.assertEqual(body['text']['format']['type'], 'json_schema')
            self.assertTrue(body['text']['format']['strict'])
            parsed = json.loads(body['input'][1]['content'][0]['text'])
            self.assertEqual(set(parsed), {'text', 'context'})
            text = json.dumps(body)
            for value in ['NEVER_SEND_CATEGORY', 'NEVER_SEND_REFERENCE', 'NEVER_SEND_EVENT', 'NEVER_SEND_TEMPLATE', FAKE_KEY]:
                self.assertNotIn(value, text)
            return response()
        result = self.execute(transport=transport)
        self.assertEqual(len(seen), 2)
        self.assertTrue(result['complete'])
        self.assertEqual(result['transport_mode'], 'injected_test_transport')
        self.assertEqual(result['live_api_requests'], 0)
        self.assertEqual(result['injected_transport_calls'], 2)
        self.assertEqual(result['completed_requests'], 2)
        self.assertLessEqual(float(result['usage_reported_usd']), float(result['reserved_usd']))

    def test_null_error_response_retains_output_usage_and_resumes_without_a_call(self):
        first = self.execute()
        self.assertTrue(first['complete'])
        record = self.read_results()[0]
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['parsed_output'], OUTPUT)
        self.assertEqual(record['usage']['input_tokens'], 150)
        self.assertGreater(float(record['usage_cost_usd']), 0)
        self.assertIsNone(record['raw_response']['error'])
        second = self.execute(transport=lambda *args: self.fail('successful call repeated'))
        self.assertTrue(second['complete'])
        self.assertEqual(second['executed_requests'], 0)

    def test_response_without_error_field_remains_supported(self):
        payload = response()
        del payload['error']
        self.assertTrue(self.execute(transport=lambda *args: payload)['complete'])

    def test_non_null_errors_stop_without_persisting_free_text(self):
        for error_value in [
            {'type': 'server_error', 'code': 'server_error',
             'message': 'PRIVATE_ERROR_MESSAGE ' + FAKE_KEY},
            {}, '', False, 0, [],
        ]:
            with self.subTest(error_value=type(error_value).__name__):
                target = self.root / ('error-run-' + str(len(list(self.root.iterdir()))))
                payload = response()
                payload['error'] = error_value
                result = runner.run_benchmark(self.dataset_path, target,
                    execute=True, max_usd='1', api_key=FAKE_KEY,
                    transport=lambda *args: payload)
                self.assertEqual(result['executed_requests'], 1)
                self.assertEqual(result['completed_requests'], 0)
                self.assertEqual(result['remaining_unattempted_requests'], 1)
                records = [json.loads(line) for line in (target / 'records.jsonl').read_text().splitlines()]
                record = records[-1]
                self.assertEqual(record['status'], 'api_error')
                self.assertNotIn('raw_response', record)
                if isinstance(error_value, dict) and error_value:
                    self.assertEqual(record['error_code'], 'server_error')
                for path in target.iterdir():
                    if path.is_file():
                        self.assertNotIn('PRIVATE_ERROR_MESSAGE', path.read_text())
                        self.assertNotIn(FAKE_KEY, path.read_text())

    def test_failed_response_with_null_error_is_not_completed(self):
        payload = response()
        payload['status'] = 'failed'
        result = self.execute(transport=lambda *args: payload)
        self.assertEqual(result['completed_requests'], 0)
        self.assertEqual(self.read_results()[0]['status'], 'incomplete_response')

    def test_positive_budget_is_mandatory_before_key_access(self):
        for cap in [None, 0, -1, 'NaN', 'Infinity']:
            with self.subTest(cap=cap), patch.object(runner, '_load_api_key', side_effect=AssertionError('key read')):
                with self.assertRaises(runner.RunnerError):
                    runner.run_benchmark(self.dataset_path, self.output, execute=True, max_usd=cap)

    def test_full_batch_budget_preflight_prevents_all_calls(self):
        called = []
        with patch.object(runner, '_load_api_key', side_effect=AssertionError('key read')):
            with self.assertRaisesRegex(runner.RunnerError, 'preflight_budget_cap_exceeded'):
                runner.run_benchmark(self.dataset_path, self.output, execute=True, max_usd='.000001',
                                     transport=lambda *args: called.append(True))
        self.assertFalse(called)
        self.assertFalse((self.output / 'records.jsonl').exists())

    def test_resuming_completed_run_does_not_read_key_or_call_again(self):
        first = self.execute()
        with patch.object(runner, '_load_api_key', side_effect=AssertionError('must use cache')):
            second = runner.run_benchmark(self.dataset_path, self.output, execute=True, max_usd='1',
                                          transport=lambda *args: self.fail('duplicate request'))
        self.assertEqual(second['executed_requests'], 0)
        self.assertEqual(second['cached_attempts'], 2)
        self.assertEqual(second['reserved_usd'], first['reserved_usd'])
        self.assertTrue(second['complete'])

    def test_resume_rejects_modified_prompt_config_and_dataset(self):
        self.execute()
        with patch.object(runner, 'PROMPT', runner.PROMPT + '\nchanged'):
            with self.assertRaises(runner.RunnerError):
                self.execute(transport=lambda *args: self.fail('network called'))
        with self.assertRaises(runner.RunnerError):
            self.execute(max_usd='2', transport=lambda *args: self.fail('network called'))
        self.dataset_path.write_text(self.dataset_path.read_text() + '\n')
        with self.assertRaises(runner.RunnerError):
            self.execute(transport=lambda *args: self.fail('network called'))

    def test_resume_rejects_tampered_records_and_static_schema(self):
        self.execute()
        path = self.output / 'records.jsonl'
        original = path.read_text()
        path.write_text(original.replace('resp_offline_mock', 'resp_tampered'))
        with self.assertRaises(runner.RunnerError):
            self.execute(transport=lambda *args: self.fail('network called'))
        path.write_text(original)
        (self.output / 'schema.json').write_text('{}')
        with self.assertRaises(runner.RunnerError):
            self.execute(transport=lambda *args: self.fail('network called'))

    def test_valid_prefix_truncation_cannot_repeat_an_attempt(self):
        self.execute()
        path = self.output / 'records.jsonl'
        lines = path.read_text().splitlines()
        # Removing an entire reservation/result pair leaves a valid hash chain,
        # but violates the independently committed ledger prefix anchor.
        path.write_text('\n'.join(lines[:-2]) + '\n')
        with self.assertRaisesRegex(runner.RunnerError, 'resume_ledger_anchor_mismatch'):
            self.execute(transport=lambda *args: self.fail('duplicate request'))

    def test_unknown_interrupted_attempt_is_reserved_and_never_retried(self):
        self.dataset_path.write_text(json.dumps(dataset(rows=1)))
        with self.assertRaises(KeyboardInterrupt):
            self.execute(transport=lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        with patch.object(runner, '_load_api_key', side_effect=AssertionError('must not read key')):
            result = runner.run_benchmark(self.dataset_path, self.output, execute=True, max_usd='1',
                                          transport=lambda *args: self.fail('interrupted call retried'))
        self.assertEqual(result['attempted_requests'], 1)
        self.assertEqual(result['unknown_outcome_attempts'], 1)
        self.assertGreater(float(result['reserved_usd']), 0)
        self.assertFalse(result['complete'])

    def test_transport_errors_are_sanitized_and_not_retried(self):
        calls = []
        def bad_transport(*args):
            calls.append(True)
            raise RuntimeError('Authorization: Bearer ' + FAKE_KEY)
        result = self.execute(transport=bad_transport)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['failed_requests'], 1)
        self.assertEqual(result['usage_unknown_attempts'], 1)
        self.assertEqual(result['remaining_unattempted_requests'], 1)
        for path in self.output.iterdir():
            if path.is_file():
                self.assertNotIn(FAKE_KEY, path.read_text())
        # An explicit resume may attempt the next input, never the failed one.
        result = self.execute()
        self.assertEqual(result['attempted_requests'], 2)
        self.assertEqual(result['completed_requests'], 1)
        self.assertEqual(result['failed_requests'], 1)

    def test_wrong_returned_model_is_fail_closed(self):
        result = self.execute(expected_returned_model='gpt-6-luna-2026-10-01',
                              transport=lambda *args: response(model='gpt-6-luna-2026-10-02'))
        self.assertEqual(result['executed_requests'], 1)
        record = self.read_results()[0]
        self.assertEqual(record['status'], 'model_drift')
        self.assertIsNone(record['parsed_output'])

    def test_dated_snapshot_request_is_checked_even_without_explicit_expectation(self):
        result = self.execute(model='gpt-6-luna-2026-10-01', transport=lambda *args: response())
        self.assertEqual(result['completed_requests'], 0)
        self.assertEqual(self.read_results()[0]['status'], 'model_drift')

    def test_malformed_structured_output_is_not_a_real_success(self):
        malformed = {'status': 'needs_clarification', 'changes': OUTPUT['changes']}
        result = self.execute(transport=lambda *args: response(malformed))
        self.assertFalse(result['complete'])
        self.assertEqual(result['completed_requests'], 0)
        self.assertEqual(self.read_results()[0]['status'], 'invalid_output')
        self.assertIsNone(self.read_results()[0]['parsed_output'])

    def test_output_semantics_and_extra_fields_are_validated(self):
        payload = {'text': 'notice', 'context': CONTEXT}
        for invalid in [
            {'status': [], 'changes': []},
            {'status': 'ready', 'changes': [], 'explanation': 'not allowed'},
            {'status': 'ready', 'changes': [dict(OUTPUT['changes'][0], value=True)]},
            {'status': 'ready', 'changes': [dict(OUTPUT['changes'][0], end_week=17)]},
            {'status': 'ready', 'changes': [dict(OUTPUT['changes'][0], route='NL_air')]},
        ]:
            with self.subTest(value=invalid):
                self.assertFalse(runner.validate_output(invalid, payload))

    def test_reservation_bound_violation_stops_live_and_resume(self):
        calls = []
        def expensive(*args):
            calls.append(True)
            return response(input_tokens=1000000)
        with self.assertRaisesRegex(runner.RunnerError, 'observed_usage_exceeded_reserved_bound_stop'):
            self.execute(transport=expensive)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(runner.RunnerError, 'observed_usage_exceeded_reserved_bound_stop'):
            self.execute(transport=lambda *args: self.fail('network called'))

    def test_oversized_inputs_are_rejected_before_credentials_or_network(self):
        data = dataset(rows=1)
        data['splits']['test'][0]['model_input']['text'] = 'x' * runner.MAX_INPUT_TOKEN_UPPER_BOUND
        self.dataset_path.write_text(json.dumps(data))
        with patch.object(runner, '_load_api_key', side_effect=AssertionError('key read')):
            with self.assertRaisesRegex(runner.RunnerError, 'short_input_bound_exceeded'):
                runner.run_benchmark(self.dataset_path, self.output, execute=True, max_usd='1')

    def test_successful_raw_response_redacts_secret_in_keys_and_values(self):
        def transport(*args):
            value = response()
            value['provider_metadata'] = {FAKE_KEY: 'Bearer ' + FAKE_KEY}
            return value
        result = self.execute(transport=transport)
        self.assertTrue(result['complete'])
        self.assertNotIn(FAKE_KEY, (self.output / 'records.jsonl').read_text())
        # The redacted response is still reproducible and schema-validated.
        self.assertTrue(self.execute(transport=lambda *args: self.fail('network called'))['complete'])

    def test_repeats_and_call_limit_have_distinct_cache_identities(self):
        result = self.execute(repeats=2, max_calls=3)
        self.assertEqual(result['attempted_requests'], 3)
        records = self.read_results()
        self.assertEqual(len({record['request_key'] for record in records}), 3)
        self.assertEqual([record['repeat_index'] for record in records], [0, 1, 0])
        self.assertEqual(records[0]['input_sha256'], records[1]['input_sha256'])
        self.assertNotEqual(records[1]['input_sha256'], records[2]['input_sha256'])

    def test_other_model_family_requires_explicit_prices(self):
        with self.assertRaisesRegex(runner.RunnerError, 'explicit_prices_required'):
            runner.run_benchmark(self.dataset_path, self.output, model='other-model')
        result = runner.run_benchmark(self.dataset_path, self.output, model='other-model',
                                      input_usd_per_million='2', output_usd_per_million='5')
        self.assertEqual(result['mode'], 'dry_run')

    def test_context_answer_metadata_is_rejected_before_request(self):
        data = dataset(rows=1)
        data['splits']['test'][0]['model_input']['context']['reference'] = OUTPUT
        self.dataset_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(runner.RunnerError, 'unexpected_context_fields'):
            self.execute(transport=lambda *args: self.fail('network called'))

    def test_duplicate_inputs_are_not_counted_as_new_independent_calls(self):
        data = dataset()
        data['splits']['test'][1]['model_input'] = deepcopy(data['splits']['test'][0]['model_input'])
        self.dataset_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(runner.RunnerError, 'duplicate_case_or_model_input'):
            self.execute(transport=lambda *args: self.fail('network called'))

    def test_http_error_free_text_and_credentials_never_escape(self):
        body = json.dumps({'error': {'type': 'authentication_error', 'code': FAKE_KEY,
                                    'message': 'Key was ' + FAKE_KEY}}).encode()
        error = HTTPError(runner.ENDPOINT, 401, 'bad key ' + FAKE_KEY, {}, io.BytesIO(body))
        class Opener:
            def open(self, *args, **kwargs):
                raise error
        with patch.object(runner, 'build_opener', return_value=Opener()):
            with self.assertRaises(runner.TransportError) as caught:
                runner._default_transport({}, FAKE_KEY, 1)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(caught.exception.error_type, 'authentication_error')
        self.assertEqual(caught.exception.error_code, 'redacted_error_metadata')
        self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_redirects_are_rejected(self):
        with self.assertRaises(runner.TransportError) as caught:
            runner._NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://untrusted.invalid')
        self.assertEqual(caught.exception.status, 302)
        self.assertEqual(caught.exception.error_code, 'redirect_rejected')

    def test_completely_truncated_ledger_cannot_repeat_billed_attempts(self):
        self.execute()
        (self.output / 'records.jsonl').write_text('')
        with self.assertRaisesRegex(runner.RunnerError, 'resume_empty_ledger_but_anchor_exists'):
            self.execute(transport=lambda *args: self.fail('must not send duplicate calls'))

    def test_default_transport_uses_only_fixed_endpoint(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return json.dumps(response()).encode()
        class Opener:
            def open(self, request, **kwargs):
                calls.append(request.full_url)
                self_header = request.get_header('Authorization')
                if self_header != 'Bearer ' + FAKE_KEY:
                    raise AssertionError('missing authentication')
                return Response()
        with patch.object(runner, 'build_opener', return_value=Opener()), patch.dict('os.environ', {'OPENAI_BASE_URL': 'https://untrusted.invalid'}):
            result = runner._default_transport({}, FAKE_KEY, 1)
        self.assertEqual(calls, [runner.ENDPOINT])
        self.assertEqual(result['id'], 'resp_offline_mock')


if __name__ == '__main__':
    unittest.main()
