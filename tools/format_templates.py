"""Run pinned djlint while preserving explicitly ignored JS/CSS blocks verbatim."""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BLOCK=re.compile(r'<!-- djlint:off -->.*?<!-- djlint:on -->',re.S)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    failures=[]
    with tempfile.TemporaryDirectory(prefix='receipt-html-') as directory:
        folder=Path(directory)
        (folder/'.djlintrc').write_text((ROOT/'.djlintrc').read_text())
        originals={};blocks={}
        for path in sorted((ROOT/'web_control/templates').glob('*.html')):
            original=path.read_text();originals[path.name]=original;blocks[path.name]=[]
            def protect(match):
                index=len(blocks[path.name]);blocks[path.name].append(match.group(0))
                return f'<!-- RECEIPT_PRESERVED_BLOCK_{index} -->'
            (folder/path.name).write_text(BLOCK.sub(protect,original))
        result=subprocess.run([sys.executable,'-m','djlint',str(folder),'--reformat','--quiet'],capture_output=True,text=True,cwd=folder)
        if result.returncode not in (0,1):
            print('HTML formatter failed: '+result.stderr[-1000:]+result.stdout[-500:],file=sys.stderr);return 2
        for name,original in originals.items():
            formatted=(folder/name).read_text()
            for index,block in enumerate(blocks[name]):
                formatted=formatted.replace(f'<!-- RECEIPT_PRESERVED_BLOCK_{index} -->',block)
            if formatted!=original:
                failures.append(name)
                if not args.check:(ROOT/'web_control/templates'/name).write_text(formatted)
    if args.check and failures:
        print('Run python tools/format_templates.py for: '+', '.join(failures));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
