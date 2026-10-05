"""Validate a generated architecture document without importing product code."""
import json
from datetime import datetime
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
    wiki = data['wiki']
    assert wiki['schemaVersion'] == 1
    domain_ids = {d['id'] for d in data['domains']}
    pages = {p['id']: p for p in wiki['pages']}
    assert len(pages) == len(wiki['pages']) and pages.keys() == domain_ids, 'Wiki page coverage'
    grouped = [domain_id for group in wiki['groups'] for domain_id in group['domainIds']]
    assert len(grouped) == len(set(grouped)) and set(grouped) == domain_ids, 'Wiki group coverage'
    assert len({g['id'] for g in wiki['groups']}) == len(wiki['groups'])
    for group in wiki['groups']:
        assert group['role'] in {'runtime', 'support', 'reference'}
        assert group['label'].strip() and group['description'].strip() and group['domainIds']
    assert {'experiments', 'archive'} <= {
        domain_id for group in wiki['groups'] if group['role'] == 'reference'
        for domain_id in group['domainIds']
    }, 'Historical and experimental content must be separate'
    wiki_refs = []
    for page in pages.values():
        for field in ('title', 'summary'):
            assert isinstance(page[field], str) and page[field].strip(), (page['id'], field)
        for field in ('responsibilities', 'boundaries'):
            assert page[field] and all(isinstance(s, str) and s.strip() for s in page[field])
        assert page['entryPoints'], page['id']
        assert len(page['scenarioIds']) == len(set(page['scenarioIds']))
        assert set(page['scenarioIds']) <= views.keys(), page['id']
        assert set(page['relatedDomainIds']) <= domain_ids - {page['id']}, page['id']
        for entry in page['entryPoints']:
            assert entry['label'].strip() and entry['note'].strip()
            wiki_refs.append(entry['ref'])
        assert page['status'] == 'source_verified', page['id']
    assert len({r['id'] for r in wiki['relationships']}) == len(wiki['relationships'])
    for relation in wiki['relationships']:
        assert relation['from'] in domain_ids and relation['to'] in domain_ids
        assert relation['from'] != relation['to'] and relation['label'].strip() and relation['detail'].strip()
        assert relation['kind'] in {'lifecycle', 'request', 'execution', 'data', 'capability'}
        assert relation['refs'] and all(not r.get('pathOnly') for r in relation['refs'])
        assert relation['status'] == 'source_verified', relation['id']
        wiki_refs.extend(relation['refs'])
    for ref in wiki_refs:
        assert ref['path'] in files
        assert ref['blob'] == files[ref['path']]['blob']
        if ref.get('pathOnly'):
            assert ref['line'] == 0 and ref['symbol'] == ''
        else:
            assert ref['symbol'] and 1 <= ref['line'] <= files[ref['path']]['lines']
    assert len(data['meta']['commit']) == 40
    assert datetime.fromisoformat(data['meta']['sourceCommittedAt']).tzinfo is not None
    assert datetime.fromisoformat(data['meta']['generatedAt']).tzinfo is not None
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
            assert node['role'] in ('entry', 'process', 'control', 'store', 'related', 'external'), node['id']
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
        from wiki_structure import make_wiki
        refs_by_anchor = {(r['path'], r['symbol']): r for v in data['views']
                          for item in v['nodes'] + v['edges'] for r in item['refs']}
        refs_by_anchor.update({(r['path'], None if r.get('pathOnly') else r['symbol']): r for r in wiki_refs})
        expected_views = make_views(lambda p, a: dict(refs_by_anchor[(p, a)]))
        expected_wiki = make_wiki(lambda p, a: dict(refs_by_anchor[(p, a)]))
        for page in expected_wiki['pages']:
            page['status'] = 'source_verified'
        for relation in expected_wiki['relationships']:
            relation['status'] = 'source_verified'
        assert expected_wiki == wiki, 'Wiki sidecar differs from generated HTML'
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
                      'wikiPages': len(pages), 'wikiEvidenceReferences': len(wiki_refs),
                      'staleEvidence': data['meta'].get('staleEvidence', [])}, ensure_ascii=False))


if __name__ == '__main__':
    validate(sys.argv[1])
