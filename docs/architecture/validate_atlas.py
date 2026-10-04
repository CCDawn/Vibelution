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
    views = {v['id']: v for v in data['views']}
    assert len(views) == len(data['views'])
    refs = 0
    for view in data['views']:
        ids = {n['id'] for n in view['nodes']}
        assert len(ids) == len(view['nodes'])
        order = view['readingOrder']
        assert len(order) == len(ids) and set(order) == ids, (view['id'], 'reading order')
        for field in ('question', 'entry', 'outcome', 'category'):
            assert isinstance(view[field], str) and view[field].strip(), (view['id'], field)
        assert set(view['relatedViews']) <= views.keys(), view['id']
        assert len({e['id'] for e in view['edges']}) == len(view['edges'])
        for edge in view['edges']:
            assert edge['from'] in ids and edge['to'] in ids
        for node in view['nodes']:
            assert node['role'] in ('entry', 'process', 'control', 'store', 'external'), node['id']
            for field in ('label', 'subtitle', 'summary', 'ownerPath'):
                assert isinstance(node[field], str) and node[field].strip(), (view['id'], node['id'], field)
            for field in ('inputs', 'mechanism', 'outputs', 'boundaries'):
                values = node[field]
                assert isinstance(values, list) and values, (view['id'], node['id'], field)
                assert all(isinstance(s, str) and s.strip() for s in values), (node['id'], field)
            assert len(node['mechanism']) >= 2, node['id']
            assert set(node['relatedViews']) <= views.keys(), node['id']
            assert node['module'] in modules, node['id']
            owner = node['ownerPath']
            if owner in files:
                assert node['module'] == files[owner]['module'] and node['implementationFile'] == owner
            else:
                assert modules[node['module']]['path'] == owner, (node['id'], owner)
            assert view['id'] in modules[node['module']]['learningViews']
            containing = [z for z in view['zones'] if z['x'] <= node['x'] and z['y'] <= node['y']
                          and node['x'] + 244 <= z['x'] + z['w'] and node['y'] + 132 <= z['y'] + z['h']]
            assert len(containing) == 1, (view['id'], node['id'], 'responsibility zone')
        focus = view.get('focusNodes', [])
        if focus:
            assert len(focus) == len(set(focus)) and set(focus) < ids
            assert set(view['focusPositions']) == set(focus)
            assert view['hiddenImplementation'] == [nid for nid in order if nid not in focus]
        original = {e['id']: e for e in view['edges']}
        focus_edges = view.get('focusEdges', [])
        assert len({e['id'] for e in focus_edges}) == len(focus_edges)
        for edge in focus_edges:
            assert edge['from'] in focus and edge['to'] in focus
            if edge.get('relationKind') == 'composed_path':
                node_path = [edge['from'], *edge['via'], edge['to']]
                chain = [original[eid] for eid in edge['pathEdges']]
                assert len(chain) == len(node_path) - 1
                assert all(part['from'] == a and part['to'] == b for part, a, b in zip(chain, node_path, node_path[1:]))
                assert all(nid not in focus for nid in edge['via'])
                assert edge['refs'] == [r for part in chain for r in part['refs']]
            else:
                assert edge['id'] in original and edge == original[edge['id']]
        for item in view['nodes'] + view['edges'] + focus_edges:
            assert item['refs'], item['id']
            for ref in item['refs']:
                assert ref['path'] in files
                assert 1 <= ref['line'] <= files[ref['path']]['lines']
                refs += 1
    overview = {n['id']: n for n in views['overview']['nodes']}
    assert {'web', 'api', 'session', 'agent', 'llm', 'tools', 'journal', 'stream'} <= overview.keys()
    assert overview['session']['ownerPath'] == 'core/web/services/session'
    assert modules[overview['session']['module']]['path'] == 'core/web/services/session'
    assert 'session' in overview['session']['relatedViews']
    assert not data['meta'].get('staleEvidence'), 'changed source evidence requires review'
    # Sidecars are optional for a portable HTML, but when validating next to the
    # generator they must describe exactly the embedded document being shipped.
    source_dir = Path(__file__).resolve().parent
    if source_dir == Path(path).resolve().parent and (source_dir / 'curated.py').exists():
        from curated import REVIEWED_COMMIT, make_views
        refs_by_anchor = {(r['path'], r['symbol']): r for v in data['views']
                          for item in v['nodes'] + v['edges'] for r in item['refs']}
        expected_views = make_views(lambda p, a: dict(refs_by_anchor[(p, a)]))
        assert data['meta']['reviewedCommit'] == REVIEWED_COMMIT
        for expected in expected_views:
            actual = views[expected['id']]
            for key, value in expected.items():
                if key == 'nodes':
                    actual_nodes = {n['id']: n for n in actual['nodes']}
                    for node in value:
                        for field, content in node.items():
                            assert actual_nodes[node['id']][field] == content, (expected['id'], node['id'], field)
                elif key in ('edges', 'focusEdges'):
                    actual_edges = {e['id']: e for e in actual[key]}
                    assert set(actual_edges) == {e['id'] for e in value}
                    for edge in value:
                        for field, content in edge.items():
                            assert actual_edges[edge['id']][field] == content, (expected['id'], edge['id'], field)
                else:
                    assert actual[key] == value, (expected['id'], key)
        template = (source_dir / 'viewer.template.html').read_text(encoding='utf-8')
        assert template.replace('__ATLAS_DATA__', match.group(1)) == html, 'viewer template differs from generated HTML'
    parser = Resources()
    parser.feed(html)
    assert not parser.errors, parser.errors
    assert '__ATLAS_DATA__' not in html
    print(json.dumps({'valid': True, 'files': len(files), 'modules': len(modules),
                      'views': len(data['views']), 'evidenceReferences': refs,
                      'staleEvidence': data['meta'].get('staleEvidence', [])}, ensure_ascii=False))


if __name__ == '__main__':
    validate(sys.argv[1])
