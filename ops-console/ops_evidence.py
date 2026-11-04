"""Project operational evidence into display rows without exporting raw responses."""

SHELF_NAMES = {'beer_2019_known':'맥주 2019년 출시 시점','beer_2023_known':'맥주 2023년 상반기',
               'beer_2019_annual_known':'맥주 2019년 연간','beer_2023h2_known':'맥주 2023년 하반기',
               'soda_2023_known':'탄산 2023년'}


def product_labels(demo, base):
    import json
    names={p['id']:p.get('real_name') or p['id'] for p in base}
    for filename in ('sets_known_sym.json','sets_known.json'):
        path=demo/'config'/filename
        if not path.is_file():
            continue
        for shelf in json.loads(path.read_bytes()):
            for product in [*shelf.get('products',[]),*shelf.get('products_inline',[])]:
                names[product['id']]=product.get('real_name') or product['id']
    return names


def reproduction(detail, truth, products):
    metric=detail['metrics'].get(detail['metric_key'],{})
    raw=detail['primary_observations'].get('shelves',{})
    result=[]
    def ranked(shares):
        groups={}
        for key,value in shares.items():
            groups.setdefault(value,[]).append(products.get(key,key))
        return ' → '.join(' = '.join(names) for _,names in sorted(groups.items(),reverse=True))
    for key,row in metric.get('shelves',{}).items():
        actual=row.get('truth') or truth.get(key, {})
        if not isinstance(actual,dict):actual={}
        actual=actual.get('value',actual)
        shares={k:v for k,v in actual.items() if isinstance(v,(int,float))}
        result.append({'shelf':SHELF_NAMES.get(key,key),'actual':ranked(shares),
                       'virtual':ranked(row.get('sim',{})) if raw.get(key,{}).get('valid_n',0) else '유효 응답 없음',
                       'last_match':bool(row.get('last_match')),'valid':raw.get(key,{}).get('valid_n',0),
                       'total':row.get('n',0)})
    return result
