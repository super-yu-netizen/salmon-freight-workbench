"""Independent Fraction arithmetic against the running API; never imports calculator."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction as F
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def ceil(value):
    return -(-value.numerator // value.denominator)


def rounded(value, places=2):
    scale = 10**places
    scaled = value * scale + F(1, 2)
    n = scaled.numerator // scaled.denominator
    return f'{n // scale}.{n % scale:0{places}d}'


def reference(q, layers, mode, supplier):
    full, tail = divmod(q, 4*layers)
    pallets = full + bool(tail)
    h = 150 + 301*layers
    tail_h = 150 + 301*((tail+3)//4)
    volume = F(full*1200*1000*h + (1200*1000*tail_h if tail else 0), 10**9)
    gross = F(q*33,10) + pallets*21
    cw = ceil(max(gross, volume*F(500,3)))
    count = (pallets+19)//20
    main = (cw*(F(3) if supplier=='DEMO-A' else F(315,100))) if mode=='air' else count*(1600 if supplier=='DEMO-A' else 1500)
    usd = pallets*18 + main
    cny = count*2100+1200+(F(cw,5) if mode=='air' else count*1800)
    aud = 150+count*600+(F(cw,5) if mode=='air' else count*350)
    # Independent policy: native-currency subtotals converted once, then added.
    total = F(rounded(F(usd)))+F(rounded(F(cny)*F(5,36)))+F(rounded(F(aud)*F(13,20)))
    return {'shipping': {'carton_count':q,'pallet_count':pallets,'full_pallets':full,'tail_cartons':tail,
                         'volume_m3':volume,'gross_kg':gross,'origin_trucks':count,'destination_trucks':count,
                         'container_count':count},
            'chargeable_kg':cw,'original_totals':{'USD':rounded(F(usd)),'CNY':rounded(F(cny)),'AUD':rounded(F(aud))},
            'budget_total':rounded(total),'per_set':rounded(total/q,4)}


def run(base):
    def api(route, body=None):
        r = Request(base+route, data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'})
        with urlopen(r,timeout=20) as response: return json.loads(response.read())
    cat=api('/api/catalog')
    records=[]; checks=0
    for layers,pack in [(4,'PALLET-1600'),(3,'PALLET-1300')]:
        req=deepcopy(cat['default_request'])
        req.update(packaging_id=pack,quantities=[1,16,17,1000,3000,4000],supplier_ids=['DEMO-A','DEMO-B'])
        result=api('/api/calculate',req)
        for actual in result['results']:
            q,mode,supplier=actual['quantity'],actual['mode'],actual['supplier_id']
            expected=reference(q,layers,mode,supplier)
            for key,value in expected['shipping'].items():
                assert F(str(actual['shipping'][key]))==F(value),(q,layers,mode,supplier,key,actual['shipping'][key],str(value))
                checks+=1
            if mode=='air':
                assert F(actual['shipping']['chargeable_kg'])==expected['chargeable_kg']
                checks+=1
            for currency,value in expected['original_totals'].items():
                assert actual['original_totals'][currency]==value
                checks+=1
            for field in ('budget_total','per_set'):
                assert actual[field]==expected[field],(q,layers,mode,supplier,field,actual[field],expected[field])
                checks+=1
            assert actual['complete'] and actual['status']=='estimated'
            checks+=1
            records.append({'quantity':q,'layers':layers,'mode':mode,'supplier':supplier,
                            'budget_total':actual['budget_total'],'per_set':actual['per_set'],'pass':True})
    out={'checked_at':datetime.now(timezone.utc).isoformat(),'method':'Fraction independent arithmetic; no calculator import',
         'base_url':base,'catalog_version':cat['version'],'comparisons':checks,'scenarios':len(records),'failures':0,'results':records}
    (ROOT/'validation/独立验算.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({k:out[k] for k in ('comparisons','scenarios','failures')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:8879')
    run(parser.parse_args().base)
