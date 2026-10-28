import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calculator import calculate, validate_catalog, InputError
ROOT=Path(__file__).resolve().parents[1]

class ProcurementCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.cat=json.loads((ROOT/'data/catalog.json').read_text())
        self.req=copy.deepcopy(self.cat['default_request'])
        self.req['demo_estimation']=False  # These tests preserve strict matching semantics.
    def results(self,req=None,cat=None):return calculate(req or self.req,cat or self.cat)['results']
    def first(self,req=None,cat=None):return self.results(req,cat)[0]
    def plan(self,mode='air',service='door'):
        return next(p for p in self.cat['rate_plans'] if p['id']==f'SZ-BNE-DEMO-A-{mode}-{service}')
    def test_prd_eight_complete_references(self):
        refs={
          ('PALLET-1600',1000,'air'):('57617.59','57.6176',63,'101.64','4623','16940',4),
          ('PALLET-1600',3000,'air'):('170848.37','56.9495',188,'304.74','13848','50790',10),
          ('PALLET-1600',1000,'fcl'):('12434.83','12.4348',63,'101.64','4623',None,4),
          ('PALLET-1600',3000,'fcl'):('31239.83','10.4133',188,'304.74','13848',None,10),
          ('PALLET-1300',1000,'air'):('60666.66','60.6667',84,'105.42','5064','17570',5),
          ('PALLET-1300',3000,'air'):('179882.83','59.9609',250,'315.9','15150','52650',13),
          ('PALLET-1300',1000,'fcl'):('15572.00','15.5720',84,'105.42','5064',None,5),
          ('PALLET-1300',3000,'fcl'):('40633.33','13.5444',250,'315.9','15150',None,13),
        }
        for pid in ('PALLET-1600','PALLET-1300'):
            self.req['packaging_id']=pid
            for r in self.results():
                with self.subTest(pid=pid,q=r['quantity'],mode=r['mode']):
                    values=refs[(pid,r['quantity'],r['mode'])];s=r['shipping']
                    self.assertEqual((r['budget_total'],r['per_set'],s['pallet_count'],s['volume_m3'],s['gross_kg'],s['chargeable_kg'],s['container_count']),values)
                    self.assertTrue(r['complete']);self.assertEqual(r['status'],'estimated')
    def test_supplier_b_references(self):
        self.req.update(quantities=[1000],supplier_ids=['DEMO-B'])
        self.assertEqual([r['budget_total'] for r in self.results()],['60158.59','12034.83'])
    def test_main_full_and_tail_units(self):
        s=self.first()['shipping'];self.assertEqual(s['full_pallets'],62);self.assertEqual(s['tail_cartons'],8)
        self.assertEqual([(x['count'],x['cartons_per_unit'],x['height_mm'],x['gross_kg']) for x in s['handling_units']],[(62,16,'1354','73.8'),(1,8,'752','47.4')])
    def test_original_currency_group_totals(self):
        self.assertEqual(self.first()['original_totals'],{'AUD':'5938.00','CNY':'12988.00','USD':'51954.00'})
    def test_every_fee_adds_to_native_totals(self):
        for r in self.results():
            for cur,total in r['original_totals'].items():
                got=sum(Decimal(f['amount']) for f in r['fees'] if f['currency']==cur and f['amount'] is not None)
                self.assertEqual(got,Decimal(total))
    def test_missing_delivery_is_partial_not_zero(self):
        self.req['fee_overrides']={self.plan()['id']:{'delivery':None}}
        r=self.first();self.assertFalse(r['complete']);self.assertEqual(r['status'],'partial');self.assertIsNone(r['budget_total']);self.assertIsNone(r['per_set'])
        self.assertEqual(r['known_budget'],'56057.59');self.assertIn('destination_delivery',r['coverage']['missing'])
        f=next(f for f in r['fees'] if f['id']=='delivery');self.assertIsNone(f['amount']);self.assertEqual(f['state'],'missing')
    def test_absent_fee_detected_via_service_coverage(self):
        p=self.plan();p['fees']=[f for f in p['fees'] if f['id']!='delivery'];r=self.first()
        self.assertIsNone(r['budget_total']);self.assertTrue(any(f['id']=='coverage-destination_delivery' for f in r['fees']))
    def test_explicit_zero_does_not_become_missing(self):
        self.req['fee_overrides']={self.plan()['id']:{'delivery':'0'}};r=self.first()
        self.assertTrue(r['complete']);self.assertEqual(r['budget_total'],'56057.59');self.assertEqual(next(f for f in r['fees'] if f['id']=='delivery')['amount'],'0.00')
    def test_historical_preserves_only_reference_subtotal(self):
        self.req['departure_date']='2026-11-16';r=self.first()
        self.assertEqual(r['status'],'historical');self.assertFalse(r['complete']);self.assertIsNone(r['budget_total']);self.assertEqual(r['known_budget'],'57617.59')
    def test_first_and_last_valid_days(self):
        for d in ('2026-10-28','2026-11-15'):
            self.req['departure_date']=d;self.assertTrue(self.first()['complete'])
    def test_unmatched_route_does_not_reuse_australia_prices(self):
        self.cat['rate_plans']=[p for p in self.cat['rate_plans'] if p['route_id']!='SZ-RTM']
        self.req['destination_id']='NL-RTM-WH';r=self.first()
        self.assertEqual(r['status'],'not_applicable');self.assertIsNone(r['budget_total']);self.assertEqual(r['fees'],[]);self.assertEqual(r['shipping']['pallet_count'],63)
    def test_all_predefined_matching_routes(self):
        for route in self.cat['routes']:
            self.req.update(origin_id=route['origin_id'],destination_id=route['destination_id'])
            for r in self.results():self.assertTrue(r['complete'])
    def test_terminal_excludes_delivery_instead_of_guessing_door_total(self):
        self.req.update(service_id='terminal',quantities=[1000]);out=self.results()
        self.assertEqual([r['budget_total'] for r in out],['56057.59','10874.83'])
        self.assertFalse(any(f['id']=='delivery' for r in out for f in r['fees']))
    def test_secondary_products_and_partial_cartons(self):
        for pid in ('BX-002','TR-003'):
            p=next(x for x in self.cat['products'] if x['id']==pid)
            self.req.update(product_id=pid,packaging_id=p['default_packaging_id'],quantities=[21])
            for r in self.results():
                self.assertTrue(r['complete']);s=r['shipping'];self.assertEqual(s['carton_count'],(21+p['carton']['units_per_carton']-1)//p['carton']['units_per_carton'])
                self.assertEqual(Decimal(s['cargo_gross_kg']),Decimal('21')*Decimal(p['carton']['unit_net_kg'])+s['carton_count']*Decimal(p['carton']['tare_kg']))
    def test_unknown_tail_box_weight_blocks_only_actual_tail(self):
        p=self.cat['products'][1];p['carton']['partial_rule']='unknown';self.req.update(product_id=p['id'],packaging_id=p['default_packaging_id'],quantities=[21,20])
        r=self.results();self.assertEqual(r[0]['status'],'invalid');self.assertTrue(r[2]['complete'])
    def test_pallet_grid_exceeds_base(self):
        self.cat['packagings'][0]['layout']['across_length']=5
        self.assertEqual(self.first()['status'],'invalid');self.assertIsNone(self.first()['budget_total'])
    def test_approved_overhang_uses_real_outer_dimensions(self):
        pack=self.cat['packagings'][0];pack['allow_overhang']=True;pack['layout']['across_length']=5
        r=self.first();self.assertEqual(r['shipping']['handling_units'][0]['length_mm'],'1440')
        self.assertEqual(r['status'],'partial')  # template 1200mm no longer fits
        self.assertIsNone(r['shipping']['origin_trucks'])

    def test_pallet_limit_too_small_for_one_layer(self):
        self.cat['packagings'][0]['max_height_mm']='300'
        self.assertEqual(self.first()['status'],'invalid')
    def test_unapproved_packaging_not_used_as_confirmed(self):
        self.cat['packagings'][0]['confirmed']=False
        self.assertEqual(self.first()['status'],'invalid')
    def test_missing_fcl_template_does_not_make_free_ocean_freight(self):
        self.cat['load_templates'][1]['packaging_ids'].remove('PALLET-1600')
        r=self.results();self.assertTrue(r[0]['complete']);self.assertEqual(r[1]['status'],'partial');self.assertIsNone(r[1]['shipping']['container_count']);self.assertIsNone(r[1]['budget_total'])
    def test_door_height_validation(self):
        self.cat['load_templates'][0]['door_height_mm']='1000';r=self.first()
        self.assertEqual(r['status'],'partial');self.assertIsNone(r['shipping']['origin_trucks'])
    def test_weight_capacity_limits_slots_independently(self):
        self.cat['load_templates'][1]['max_total_kg']='740';r=self.results()[1]
        self.assertEqual(r['shipping']['container_count'],7)
    def test_air_whole_shipment_vs_piece_rule(self):
        self.plan()['air_rules']['scope']='piece';r=self.first()
        # 62 full pallets each ceil(270.8)=271; tail ceil(150.4)=151.
        self.assertEqual(r['shipping']['chargeable_kg'],'16953')
    def test_volume_divisor_is_not_silently_167(self):
        self.plan()['air_rules']['divisor_cm3']='5000';r=self.first()
        self.assertEqual(r['shipping']['chargeable_kg'],'20328')
    def test_weight_upper_bound_not_extrapolated(self):
        self.req['quantities']=[100000];r=self.first()
        self.assertEqual(r['status'],'not_applicable');self.assertIsNone(r['budget_total']);self.assertGreater(Decimal(r['shipping']['chargeable_kg']),100000)
    def test_weight_tiers_match_and_do_not_choose_cheapest(self):
        main=next(f for f in self.plan()['fees'] if f['id']=='main')
        main['tiers']=[{'min':'0','max':'20000','unit_price':'4'},{'min':'20000','max':None,'unit_price':'3'}]
        r=self.first();self.assertEqual(next(f for f in r['fees'] if f['id']=='main')['unit_price'],'4')
    def test_weight_tier_gap_is_missing_price(self):
        main=next(f for f in self.plan()['fees'] if f['id']=='main');main['tiers']=[{'min':'0','max':'100','unit_price':'4'},{'min':'20000','max':None,'unit_price':'3'}]
        r=self.first();self.assertEqual(r['status'],'partial');self.assertIsNone(r['budget_total'])
    def test_line_minimum_charge_in_native_currency(self):
        self.req['quantities']=[1];self.plan()['fees'][0]['minimum_amount']='100';r=self.first()
        self.assertEqual(r['fees'][0]['amount'],'100.00')
    def test_included_charge_is_not_counted_twice(self):
        self.plan()['fees'].append({'id':'fuel','label':'燃油安检（已含）','group':'freight','basis':'chargeable_kg','currency':'USD','unit_price':'1','state':'included','included_in':'main','covers':['fuel_security'],'source_id':'SIM-RATE-A'})
        r=self.first();self.assertTrue(r['complete']);self.assertEqual(r['budget_total'],'57617.59');self.assertIsNone(r['fees'][-1]['amount'])
    def test_priced_duplicate_coverage_requires_review(self):
        self.plan()['fees'].append({'id':'fuel','label':'重复燃油安检','group':'freight','basis':'chargeable_kg','currency':'USD','unit_price':'1','state':'priced','covers':['fuel_security'],'source_id':'SIM-RATE-A'})
        r=self.first();self.assertEqual(r['status'],'partial');self.assertIsNone(r['budget_total'])
    def test_included_parent_override_missing_not_complete(self):
        p=self.plan();p['fees'].append({'id':'other','label':'包含操作','group':'origin','basis':'shipment','currency':'CNY','unit_price':None,'state':'included','included_in':'main','covers':['test_service'],'source_id':'SIM-RATE-A'})
        self.cat['services'][0]['required_coverage'].append('test_service');self.req['fee_overrides']={p['id']:{'main':None}}
        r=self.first();self.assertIn('test_service',r['coverage']['missing']);self.assertEqual(r['status'],'partial')
    def test_unknown_fx_keeps_native_totals(self):
        del self.cat['fx'][0]['rates']['AUD'];r=self.first()
        self.assertEqual(r['status'],'partial');self.assertIsNone(r['known_budget']);self.assertEqual(r['original_totals']['AUD'],'5938.00')
    def test_invalid_request_values_raise(self):
        bads=[{'quantities':[True]},{'quantities':[0]},{'quantities':[1.1]},{'quantities':['NaN']},{'quantities':[1,'1.0']},{'modes':[]},{'product_id':[]},{'supplier_ids':[{}]},{'departure_date':'2026-02-30'},{'load_counts':[]}]
        for patch in bads:
            with self.subTest(patch=patch):
                req=copy.deepcopy(self.req);req.update(patch)
                with self.assertRaises(InputError):calculate(req,self.cat)
    def test_catalog_structure_failures_are_value_errors(self):
        patches=[('products',None),('packagings',{}),('fx',[])]
        for key,value in patches:
            cat=copy.deepcopy(self.cat);cat[key]=value
            with self.assertRaises(ValueError):validate_catalog(cat)
        self.cat['packagings'][0]['pallet']=None
        with self.assertRaises(ValueError):validate_catalog(self.cat)
    def test_nonfinite_and_bool_catalog_numbers_rejected(self):
        for value in ('NaN','Infinity',True,-1,'1e-100000','1e100000'):
            c=copy.deepcopy(self.cat);c['products'][0]['carton']['gross_kg']=value
            with self.assertRaises(ValueError):validate_catalog(c)
    def test_reference_and_duplicate_plan_validation(self):
        self.cat['rate_plans'][0]['origin_id']='unknown'
        with self.assertRaises(ValueError):validate_catalog(self.cat)
        self.setUp();self.cat['rate_plans'].append(copy.deepcopy(self.cat['rate_plans'][0]));self.cat['rate_plans'][-1]['id']+='-duplicate'
        with self.assertRaises(ValueError):validate_catalog(self.cat)
    def test_overlapping_tiers_rejected(self):
        self.plan()['fees'][0]['tiers']=[{'min':'0','max':'100','unit_price':'1'},{'min':'99','max':None,'unit_price':'2'}]
        with self.assertRaises(ValueError):validate_catalog(self.cat)
    def test_bad_fx_direction_rejected(self):
        self.cat['fx'][0]['rates']['CNY']='0.14'
        with self.assertRaises(ValueError):validate_catalog(self.cat)
    def test_input_and_catalog_not_mutated(self):
        before=json.dumps([self.cat,self.req],sort_keys=True);self.results()
        self.assertEqual(json.dumps([self.cat,self.req],sort_keys=True),before)

if __name__=='__main__':unittest.main()
