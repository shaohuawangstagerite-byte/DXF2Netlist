"""Write only the complete wire chain with component information."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.chain import extract_chain_with_components

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--netlist', type=Path, required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument('--start')
    selector.add_argument('--device-name')
    parser.add_argument('--number', help='String terminal number; leading zeros are preserved')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出目录已存在，请使用新目录')
    try:
        result = extract_chain_with_components(args.netlist, args.start, device_name=args.device_name, number=args.number)
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'chain-with-components.json').write_text(payload, encoding='utf-8')
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({'nodes': len(result['nodes']), 'connections': len(result['connections']),
                      'components': len(result['components']), 'complete': result['complete'], 'stop': result['stop']}, ensure_ascii=False))
