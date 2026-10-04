"""Validate a generated architecture document without importing product code."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            value = value or ''
            if key.startswith('on'):
                self.errors.append('inline event handler: ' + key)
            if key in ('src', 'href') and value.startswith(('http:', 'https:', '//')):
                self.errors.append('external resource: ' + value)


def validate(path):
    html = Path(path).read_text(encoding='utf-8')
    match = re.search(r'<script[^>]+id="atlas-data"[^>]*>(.*?)</script>', html, re.S)
    assert match, 'atlas-data missing'
    data = json.loads(match.group(1))
    files = {f['path']: f for f in data['files']}
    modules = {m['id']: m for m in data['modules']}
    assert len(files) == len(data['files']) == data['coverage']['trackedFiles']
    assert len(modules) == len(data['modules'])
    assert not data['coverage']['unmappedFiles']
    owners = [f for m in modules.values() for f in m['files']]
    assert len(owners) == len(files) and set(owners) == set(files)
    assert not data['coverage']['parseErrors'], data['coverage']['parseErrors']
    for module in modules.values():
        if module['parent']:
            assert module['parent'] in modules
    for file in files.values():
        assert file['module'] in modules
        for symbol in file['symbols'] + file['apis']:
            assert 1 <= symbol['line'] <= file['lines']
        for imp in file['imports']:
            if imp.get('target'):
                assert imp['target'] in files
    assert len({v['id'] for v in data['views']}) == len(data['views'])
    refs = 0
    for view in data['views']:
        ids = {n['id'] for n in view['nodes']}
        assert len(ids) == len(view['nodes'])
        for edge in view['edges']:
            assert edge['from'] in ids and edge['to'] in ids
        for item in view['nodes'] + view['edges']:
            assert item['refs'], item['id']
            for ref in item['refs']:
                assert ref['path'] in files
                assert 1 <= ref['line'] <= files[ref['path']]['lines']
                refs += 1
    parser = Resources()
    parser.feed(html)
    assert not parser.errors, parser.errors
    assert '__ATLAS_DATA__' not in html
    print(json.dumps({'valid': True, 'files': len(files), 'modules': len(modules),
                      'views': len(data['views']), 'evidenceReferences': refs,
                      'staleEvidence': data['meta'].get('staleEvidence', [])}, ensure_ascii=False))


if __name__ == '__main__':
    validate(sys.argv[1])
