"""Build a portable architecture snapshot from an immutable Git tree (stdlib only).

This is a documentation generator: no product imports, user data or network calls.
Manual flow evidence is fail-closed against source anchors. File navigation is a
complete inventory, not a claim that all dynamic calls were statically resolved.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from curated import DOMAINS, REVIEWED_COMMIT, describe_module, domain_for, make_views

HERE = Path(__file__).resolve().parent
TEXT_CODE = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.cs', '.rs'}
NO_CONTENT = ('core/core_prompt/', 'prompts/', 'mental_model/')


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(root), *args])


def read_tree(root: Path, commit: str):
    entries = []
    for entry in git(root, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not entry:
            continue
        meta, raw_path = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        path = raw_path.decode('utf-8')
        entries.append({'path': path, 'oid': oid, 'kind': kind, 'mode': mode})
    wanted = [e for e in entries if e['kind'] == 'blob' and
              PurePosixPath(e['path']).suffix in TEXT_CODE and
              not e['path'].startswith(NO_CONTENT)]
    proc = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch'],
                          input=('\n'.join(e['oid'] for e in wanted) + '\n').encode(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    data, offset, sources = proc.stdout, 0, {}
    for entry in wanted:
        end = data.index(b'\n', offset)
        size = int(data[offset:end].split()[-1])
        raw = data[end + 1:end + 1 + size]
        offset = end + 2 + size
        sources[entry['path']] = raw.decode('utf-8-sig', errors='replace')
    return entries, sources


def inspect_file(path: str, source: str, errors: list):
    record = {'lines': source.count('\n') + 1, 'summary': '', 'symbols': [], 'imports': [], 'apis': []}
    if path.endswith('.py'):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as error:
            errors.append({'path': path, 'line': error.lineno, 'reason': str(error.msg)})
            return record
        doc = ast.get_docstring(tree)
        if doc:
            record['summary'] = doc.splitlines()[0][:220]

        def visit(node, prefix=''):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + child.name
                    record['symbols'].append({'name': name, 'line': child.lineno,
                                              'kind': 'class' if isinstance(child, ast.ClassDef) else 'function'})
                    visit(child, name + '.')
                else:
                    visit(child, prefix)
        visit(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    record['imports'].append({'module': name.name, 'line': node.lineno})
            elif isinstance(node, ast.ImportFrom):
                record['imports'].append({'module': '.' * node.level + (node.module or ''),
                                          'line': node.lineno, 'names': [n.name for n in node.names]})
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                            and decorator.func.attr in {'get', 'post', 'put', 'patch', 'delete', 'websocket'}
                            and decorator.args and isinstance(decorator.args[0], ast.Constant)
                            and isinstance(decorator.args[0].value, str)):
                        record['apis'].append({'method': decorator.func.attr.upper(),
                                               'path': decorator.args[0].value, 'line': decorator.lineno})
    else:
        # Explicitly heuristic: TS/JS declaration/import navigation, not a call graph.
        pattern = r'^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:function|class|interface|type|const|let|enum)\s+([A-Za-z_$][\w$]*)'
        for number, line in enumerate(source.splitlines(), 1):
            match = re.match(pattern, line)
            if match:
                record['symbols'].append({'name': match.group(1), 'line': number, 'kind': 'declaration'})
        for match in re.finditer(r'(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s*)[\'\"]([^\'\"]+)[\'\"]', source):
            record['imports'].append({'module': match.group(1), 'line': source.count('\n', 0, match.start()) + 1})
    record['symbols'].sort(key=lambda n: n['line'])
    return record


def module_path(path: str):
    p = PurePosixPath(path)
    if str(p.parent) in {'core/web/services', 'core/web/routes', 'web/src/routes', 'web/src/api'} and p.suffix in TEXT_CODE:
        if '.test.' not in path and p.name not in {'__init__.py', 'types.ts'}:
            return path
    return str(p.parent) if str(p.parent) != '.' else '(root)'


def build(root: Path, ref: str, previous: Path | None):
    commit = git(root, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
    entries, sources = read_tree(root, commit)
    modules, files, errors = {}, [], []
    for entry in entries:
        path = entry['path']
        # The atlas indexes itself by path only; it never recursively embeds its output.
        domain = domain_for(path)
        owner = module_path(path)
        mid = domain + ':' + owner
        if mid not in modules:
            label, desc = describe_module(owner, domain)
            modules[mid] = {'id': mid, 'path': owner, 'domain': domain, 'parent': None,
                            'label': label, 'description': desc, 'files': [],
                            'status': '历史材料' if domain == 'archive' else '实验材料' if domain == 'experiments' else '源码索引'}
        modules[mid]['files'].append(path)
        detail = inspect_file(path, sources[path], errors) if path in sources else {
            'lines': 0, 'summary': '仅索引路径；不嵌入文档、提示词、配置值或二进制内容。', 'symbols': [], 'imports': [], 'apis': []}
        if detail['summary'] and path in sources and (owner == path or PurePosixPath(path).name == '__init__.py'):
            if modules[mid]['description'].endswith('查看文件符号和关联流程了解实际职责。'):
                modules[mid]['description'] = detail['summary']
        files.append({'path': path, 'module': mid, 'blob': entry['oid'], **detail, 'tests': []})
    for module in modules.values():
        candidates = [m for m in modules.values() if m['domain'] == module['domain']
                      and m['id'] != module['id'] and module['path'].startswith(m['path'] + '/')]
        if candidates:
            module['parent'] = max(candidates, key=lambda m: len(m['path']))['id']
    by_path = {f['path']: f for f in files}
    # Exact same-stem test links only; absence does not imply no test exists.
    tests = {}
    for file in files:
        path = file['path']
        stem = PurePosixPath(path).stem.replace('.test', '').removeprefix('test_')
        if '/tests/' in '/' + path or '.test.' in path:
            tests.setdefault(stem, []).append(path)
    for file in files:
        file['tests'] = tests.get(PurePosixPath(file['path']).stem, [])
        for imp in file['imports']:
            spec = imp['module']
            candidates = []
            if file['path'].endswith('.py'):
                if spec.startswith('.'):
                    dots = len(spec) - len(spec.lstrip('.'))
                    parent = PurePosixPath(file['path']).parent
                    for _ in range(dots - 1):
                        parent = parent.parent
                    base = str(parent / spec[dots:].replace('.', '/')).rstrip('/')
                else:
                    base = spec.replace('.', '/')
                candidates = [base + '.py', base + '/__init__.py']
            elif spec.startswith('.'):
                import posixpath
                base = posixpath.normpath(str(PurePosixPath(file['path']).parent / spec))
                candidates = [base] + [base + ext for ext in ('.ts', '.tsx', '.js', '/index.ts', '/index.tsx')]
            target = next((p for p in candidates if p in by_path), None)
            if target:
                imp['target'] = target
    def evidence(path, anchor):
        if path not in sources:
            raise ValueError('Evidence source missing: ' + path)
        matches = [i for i, line in enumerate(sources[path].splitlines(), 1) if anchor in line]
        if not matches:
            raise ValueError(f'Evidence anchor missing: {path}: {anchor}')
        return {'path': path, 'line': matches[0], 'symbol': anchor, 'blob': by_path[path]['blob']}
    views = make_views(evidence)
    reviewed_blobs = {}
    for entry in git(root, 'ls-tree', '-rz', '--full-tree', REVIEWED_COMMIT).split(b'\0'):
        if entry:
            metadata, pathname = entry.split(b'\t', 1)
            reviewed_blobs[pathname.decode('utf-8')] = metadata.decode().split()[2]
    stale_evidence = []
    for view in views:
        ids = {n['id'] for n in view['nodes']}
        assert len(ids) == len(view['nodes']), view['id']
        for node in view['nodes']:
            owner = node['ownerPath']
            candidates = [m for m in modules.values() if m['path'] == owner]
            if owner in by_path:
                node['module'] = by_path[owner]['module']
                node['implementationFile'] = owner
            elif candidates:
                node['module'] = candidates[0]['id']
            else:
                raise ValueError(f"Unknown implementation owner: {view['id']}/{node['id']}: {owner}")
            module = modules[node['module']]
            module.setdefault('learningViews', [])
            if view['id'] not in module['learningViews']:
                module['learningViews'].append(view['id'])
        for edge in view['edges']:
            assert edge['from'] in ids and edge['to'] in ids and edge['refs'], edge
        for item in view['nodes'] + view['edges'] + view.get('focusEdges', []):
            changed = [r['path'] for r in item['refs'] if reviewed_blobs.get(r['path']) != r['blob']]
            item['status'] = 'unknown' if changed else 'source_verified'
            if changed:
                stale_evidence.extend(changed)
                item['detail'] = '【源码已变化，流程语义待复核】' + item['detail']
    changes = {'added': [], 'removed': [], 'changed': []}
    if previous and previous.exists():
        match = re.search(r'<script[^>]+id="atlas-data"[^>]*>(.*?)</script>', previous.read_text(encoding='utf-8'), re.S)
        if not match:
            raise ValueError('Previous HTML has no embedded atlas-data')
        old = {f['path']: f.get('blob') for f in json.loads(match.group(1))['files']}
        now = {f['path']: f['blob'] for f in files}
        changes = {'added': sorted(now.keys() - old.keys()), 'removed': sorted(old.keys() - now.keys()),
                   'changed': sorted(p for p in now.keys() & old.keys() if old[p] != now[p])}
    return {'meta': {'title': 'Vibelution 开发架构地图', 'commit': commit, 'sourceBranch': ref,
                     'sourceRoot': str(root), 'reviewedCommit': REVIEWED_COMMIT,
                     'staleEvidence': sorted(set(stale_evidence)),
                     'generatedAt': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
                     'limitations': ['源码快照，未以本次文档工作验证产品运行。',
                     '覆盖指 Git 跟踪文件全部归类；不等于每个函数的调用语义均已审阅。',
                     '流程图为人工核实的关键路径；模块导航是目录归属关系。',
                     'Python 使用 AST；TS/JS 声明和 import 为启发式索引，不是完整调用图。',
                     'API 展示装饰器中的局部路径；完整 URL 还需叠加 router prefix 与 /api。',
                     '未读取活跃配置值、用户对话、密钥、完整提示词或运行数据库。',
                     '更新需重新核实变化的流程证据；锚点存在不代表语义未变。']},
            'domains': DOMAINS, 'modules': list(modules.values()), 'files': files, 'views': views,
            'coverage': {'trackedFiles': len(entries), 'indexedFiles': len(files), 'moduleCount': len(modules),
                         'unmappedFiles': [], 'parseErrors': errors,
                         'notes': [('流程证据发生变化，需重新审阅：' + ', '.join(sorted(set(stale_evidence)))) if stale_evidence else '关键流程证据与人工审阅版本一致。',
                                   '二进制、资源、文档、提示词和配置值仅列路径。',
                                   '历史、实验、工程辅助材料均单列领域；未跟踪文件和安装依赖不进入项目快照。',
                                   '测试关联只按同名文件匹配；进一步影响面分析使用 tests/select_tests.py。']},
            'changes': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE.parents[1])
    parser.add_argument('--ref', default='main')
    parser.add_argument('--output', type=Path, default=HERE / 'index.html')
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    data = build(args.source.resolve(), args.ref, args.previous)
    template = (HERE / 'viewer.template.html').read_text(encoding='utf-8')
    assert template.count('__ATLAS_DATA__') == 1
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    output = template.replace('__ATLAS_DATA__', payload)
    args.output.write_bytes(output.replace('\r\n', '\n').encode('utf-8'))
    print(json.dumps({'output': str(args.output), 'commit': data['meta']['commit'],
                      'files': len(data['files']), 'modules': len(data['modules']),
                      'views': len(data['views']), 'parseErrors': data['coverage']['parseErrors'],
                      'bytes': args.output.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
