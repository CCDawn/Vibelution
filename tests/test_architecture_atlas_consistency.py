"""Atlas 模块表与磁盘源码的一致性守卫。

docs/architecture/wiki_structure.py 的 make_wiki() 是 curate 过的领域模块表
（15 个领域页的 entryPoints + relationships 证据引用）。本测试不构建 HTML、
不导入任何产品代码，只把 wiki_structure / curated 当数据加载（与
validate_atlas.py 160-168 行的 sidecar 加载约定一致），对当前 checkout 磁盘
做三类断言：

1. 表结构自洽：页面 id 与 curated.DOMAINS 一一对应、分组覆盖全部领域、
   relationship 证据不允许 pathOnly（对齐 validate_atlas.py 52-55、82 行约定）。
2. 表内登记的每个源码路径在磁盘存在——防模块表指向已删除/改名文件。
3. 每个 curate 锚点仍能在目标文件中解析，且解析行号落在文件行数范围内——
   防 curate 锚点随源码漂移失配。解析语义复用 build_atlas.py evidence()
   的约定：锚点为子串匹配，取首个命中行。

双向断言取舍：wiki_structure 不提供「未映射文件」清单逻辑。make_wiki 只
curate 入口与关系证据，刻意不是全量清单；全量归类由 curated.domain_for()
承担，而它是带 catch-all 分支的全函数（任意路径都归入 15 领域之一），
build_atlas 因此把 coverage.unmappedFiles 硬编码为空列表。所以「src 关键
目录新增 .py 未登记则红」在这里不可表达：模块表本就不要求认领全部文件，
现有大量 core/ 文件也合法地只是索引条目而非表内入口。故降级为单向断言
（表内路径全存在 + 锚点全可解析，见 test_registered_paths_exist_on_disk
的注释），新文件的领域认领仍由 atlas 重建流程（build_atlas + validate_atlas）
兜底。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARCHITECTURE_DIR = ROOT / 'docs' / 'architecture'
if str(ARCHITECTURE_DIR) not in sys.path:
    # 与 validate_atlas.py 相同的 sidecar 加载方式：docs 目录下的模块按路径
    # 导入，不经过包系统，也不触发任何产品代码导入。
    sys.path.insert(0, str(ARCHITECTURE_DIR))

from curated import DOMAINS  # noqa: E402
from wiki_structure import make_wiki  # noqa: E402


def _collect_table():
    """Load the curated module table, recording every (path, anchor) pair.

    The recorder mirrors the build_atlas.evidence() resolver signature but
    never touches disk, so each test can assert one concern against the same
    pair list. The anchor is preserved verbatim (None stays None) so tests
    can distinguish pathOnly entries from anchored evidence.
    """
    pairs: list[tuple[str, str | None]] = []

    def recorder(path, anchor):
        pairs.append((path, anchor))
        return {'path': path, 'line': 0, 'symbol': anchor, 'blob': ''}

    return make_wiki(recorder), pairs


@pytest.fixture(scope='module')
def atlas_table():
    return _collect_table()


@pytest.mark.integration
def test_module_table_matches_curated_domain_registry(atlas_table):
    """表结构自洽：页面/分组与 curated 领域注册表一一对应。"""
    wiki, _ = atlas_table
    assert wiki['schemaVersion'] == 1
    domain_ids = {domain['id'] for domain in DOMAINS}
    pages = {page['id']: page for page in wiki['pages']}
    assert len(pages) == len(wiki['pages'])
    assert set(pages) == domain_ids, '模块表页面必须与 curated 领域一一对应'
    for page in pages.values():
        assert page['entryPoints'], page['id']
        for entry_point in page['entryPoints']:
            assert entry_point['label'].strip() and entry_point['note'].strip(), page['id']
    grouped = [domain_id for group in wiki['groups'] for domain_id in group['domainIds']]
    assert len(grouped) == len(set(grouped)), '同一领域不得重复分组'
    assert set(grouped) == domain_ids, '分组必须覆盖全部领域'
    for relation in wiki['relationships']:
        assert relation['refs'], relation['id']
        # validate_atlas.py 约定：关系证据必须带锚点，不允许 pathOnly。
        assert all(entry_ref['symbol'] for entry_ref in relation['refs']), relation['id']


@pytest.mark.integration
def test_registered_paths_exist_on_disk(atlas_table):
    """单向断言：表内登记的每个路径必须在磁盘存在。

    取舍说明见模块 docstring：wiki_structure 没有「未映射文件」清单逻辑，
    模块表只 curate 入口而非全量清单，curated.domain_for 又是带 catch-all
    的全函数，「关键目录新增 .py 未登记则红」的双向断言不可表达，故降级
    为单向。删掉任一登记文件（或改名）时本测试变红，提示重新 curate。
    """
    _, pairs = atlas_table
    paths = sorted({path for path, _ in pairs})
    assert paths, '模块表必须登记至少一个源码路径'
    missing = [path for path in paths if not (ROOT / path).is_file()]
    assert not missing, '模块表指向磁盘上已不存在的文件: ' + ', '.join(missing)


@pytest.mark.integration
def test_curated_anchors_resolve_in_file_bounds(atlas_table):
    """每个 curate 锚点仍在目标文件中可解析，且行号落在 1..总行数。

    解析语义与 build_atlas.evidence() 一致：锚点是逐行子串匹配，取首个
    命中行。行号由锚点解析得出，因此「范围内」与「可解析」一并校验。
    """
    _, pairs = atlas_table
    anchored = sorted({(path, anchor) for path, anchor in pairs if anchor})
    assert anchored, '模块表必须包含带锚点的证据引用'
    drift: list[str] = []
    for path, anchor in anchored:
        source = (ROOT / path).read_text(encoding='utf-8-sig', errors='replace')
        lines = source.splitlines()
        matches = [number for number, line in enumerate(lines, 1) if anchor in line]
        if not matches:
            drift.append(f'{path}: 锚点已无法定位: {anchor!r}')
            continue
        line = matches[0]
        if not 1 <= line <= len(lines):
            drift.append(f'{path}: 锚点行号 {line} 越界（文件共 {len(lines)} 行）')
    assert not drift, 'curate 锚点与磁盘源码漂移:\n' + '\n'.join(drift)
