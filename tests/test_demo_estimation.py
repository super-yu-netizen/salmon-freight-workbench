from copy import deepcopy
import json
from pathlib import Path
import unittest

from calculator import calculate, InputError, validate_catalog

ROOT = Path(__file__).resolve().parents[1]


class DemoEstimationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / 'data/catalog.json').read_text())
        self.request = deepcopy(self.catalog['default_request'])
        self.request.update(quantities=[1000], modes=['air'], demo_estimation=True)

    def row(self):
        return calculate(self.request, self.catalog)['results'][0]

    def test_original_reference_is_unchanged(self):
        r = self.row()
        self.assertEqual(r['budget_total'], '57617.59')
        self.assertEqual(r['status'], 'estimated')

    def test_all_route_pairs_have_explicit_distinct_rates(self):
        self.assertEqual(len(self.catalog['routes']), 6)
        self.assertEqual(len(self.catalog['rate_plans']), 48)
        for origin in ('FACTORY-SZ-A', 'FACTORY-GZ-B'):
            for dest in ('AU-BNE-WH', 'SG-SIN-WH', 'NL-RTM-WH'):
                self.request.update(origin_id=origin, destination_id=dest)
                self.assertIsNotNone(self.row()['budget_total'])

    def test_outside_validity_is_explicit_estimate_not_fake_renewal(self):
        self.request['departure_date'] = '2029-01-12'
        frozen = deepcopy((self.request, self.catalog))
        r = self.row()
        self.assertEqual(r['budget_total'], '57617.59')
        self.assertEqual(r['status'], 'simulated')
        self.assertFalse(r['validity']['matched'])
        self.assertEqual(r['validity']['valid_until'], '2026-11-15')
        self.assertTrue(r['estimate']['reasons'])
        self.assertEqual((self.request, self.catalog), frozen)

    def test_strict_mode_still_has_no_current_quote_outside_validity(self):
        self.request.update(departure_date='2029-01-12', demo_estimation=False)
        self.assertEqual(self.row()['status'], 'historical')
        self.assertIsNone(self.row()['budget_total'])

    def test_missing_price_keeps_original_null_and_marks_virtual_line(self):
        self.request['fee_overrides'] = {'SZ-BNE-DEMO-A-air-door': {'delivery': None}}
        r = self.row()
        self.assertEqual(r['budget_total'], '57617.59')
        fee = next(f for f in r['fees'] if f['id'] == 'delivery')
        self.assertIsNone(fee['original_unit_price'])
        self.assertEqual(fee['unit_price'], '600')
        self.assertEqual(fee['simulation_origin'], 'SIM-DEMO-POLICY')
        self.assertIsNone(self.request['fee_overrides']['SZ-BNE-DEMO-A-air-door']['delivery'])

    def test_explicit_zero_is_preserved_during_other_price_estimation(self):
        self.request['fee_overrides'] = {'SZ-BNE-DEMO-A-air-door': {'delivery': '0', 'main': None}}
        r = self.row()
        self.assertEqual(r['budget_total'], '56057.59')
        self.assertEqual(next(f for f in r['fees'] if f['id'] == 'delivery')['amount'], '0.00')

    def test_removed_coverage_line_is_restored_from_scoped_template(self):
        plan = next(p for p in self.catalog['rate_plans'] if p['id'] == 'SZ-BNE-DEMO-A-air-door')
        plan['fees'] = [f for f in plan['fees'] if f['id'] != 'delivery']
        r = self.row()
        self.assertEqual(r['budget_total'], '57617.59')
        self.assertFalse(r['coverage']['missing'])
        self.assertEqual(r['status'], 'simulated')

    def test_large_air_shipment_has_disclosed_project_multiplier(self):
        self.request['quantities'] = [10000]
        r = self.row()
        self.assertEqual(r['status'], 'simulated')
        self.assertEqual(r['budget_total'], '628711.39')
        main = next(f for f in r['fees'] if f['id'] == 'main')
        self.assertEqual(main['unit_price'], '3.36')
        self.assertTrue(any('1.12' in x for x in r['estimate']['reasons']))

    def test_invalid_physical_packaging_does_not_become_a_fake_valid_shipment(self):
        self.catalog['packagings'][0]['max_height_mm'] = '200'
        r = self.row()
        self.assertEqual(r['status'], 'invalid')
        self.assertIsNone(r['budget_total'])

    def test_bad_policy_and_non_boolean_switch_rejected(self):
        self.catalog['demo_policy']['source_id'] = 'NOT-A-SOURCE'
        with self.assertRaises(InputError): validate_catalog(self.catalog)
        self.setUp()
        self.request['demo_estimation'] = 'true'
        with self.assertRaises(InputError): self.row()
