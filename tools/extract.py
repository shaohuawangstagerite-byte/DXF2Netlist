"""Extract a DXF into one validated, query-ready netlist.json."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.extraction.extract import extract
from core.netlist import normalize_netlist
from core.validation import compare

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--rules', type=Path, default=ROOT / 'rules/extraction.md')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出目录已存在，请使用新目录')
    try:
        raw = extract(args.source, args.rules)
        check = compare(raw['geometry'], raw['graph'])
        if not check['passed']:
            raise ValueError('Independent geometry verification failed: ' + str(check))
        result = normalize_netlist(raw)
        result['verification'] = check
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'netlist.json').write_text(payload, encoding='utf-8')
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({'output': str(args.output / 'netlist.json'), 'geometry_passed': True,
                      'devices': len(result['devices']), 'coverage': result['coverage']}, ensure_ascii=False))
