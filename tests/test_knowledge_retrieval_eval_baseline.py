"""Retrieval golden-set baseline for the team-knowledge search pipeline.

Records the measurable BM25-only reality (2026-10-11) so upcoming changes —
semantic layer light-up, BM25 tuning, and financial date filtering pushed
earlier — have a repeatable before/after yardstick. Assertions are ratchets:
counts may only improve. Top-N containment only, never exact rank order.
"""

import os
from pathlib import Path

import pytest

from core.web.services import team_knowledge_service as knowledge
from core.web.services import unified_knowledge_search_service
from core.web.services.team_knowledge import retrieval
from core.web.services.team_knowledge import semantic
from tests.test_knowledge_lifecycle import _item, knowledge_env

TOP_N = 5

# ---------------------------------------------------------------------------
# Fixture corpus: 16 Chinese knowledge items in one governed team base.
#  a) exact-terminology entries (eval-001..004)
#  b) colloquial-paraphrase targets (eval-005..008): the query words share no
#     character n-gram with the target entry, so BM25 cannot bridge them today
#  c) dated/versioned entries (eval-009..015): same topic, different period or
#     version, raw material for the upcoming financial date-filter fix
#  plus one neutral distractor (eval-016)
# ---------------------------------------------------------------------------
EVAL_ITEMS = [
    dict(id="eval-001", title="随机对照试验设计要点", summary="临床试验方法论",
         content="随机对照试验（RCT）设计要点：随机分组、设置对照组、双盲评估与意向性分析，样本量需在方案阶段完成估算。",
         tags=["方法论"]),
    dict(id="eval-002", title="差分隐私入门", summary="隐私保护统计技术",
         content="差分隐私通过在查询结果中注入校准噪声，使单个记录对统计输出的影响可控，常用于用户数据发布场景。",
         tags=["隐私"]),
    dict(id="eval-003", title="灰度发布流程", summary="发布安全",
         content="灰度发布流程：新版本先对5%流量开放，观察错误率与性能指标24小时，再逐步放大至全量；异常时一键回切旧版本。",
         tags=["发布"]),
    dict(id="eval-004", title="版本回滚操作手册", summary="运维手册",
         content="版本回滚操作手册：保留最近三个稳定版本，回滚前导出当前配置，回滚后执行冒烟测试并通报当值同事。",
         tags=["运维"]),
    dict(id="eval-005", title="消融实验规范", summary="实验方法",
         content="消融实验：逐次移除单个组件并对比指标变化，用于量化各组件对整体性能的贡献，是论文评审的常规要求。",
         tags=["实验"]),
    dict(id="eval-006", title="过拟合的识别与缓解", summary="训练问题",
         content="过拟合指模型在训练样本上误差极低、在未见数据上误差显著升高的情形，可通过正则化、早停与数据增强缓解。",
         tags=["训练"]),
    dict(id="eval-007", title="数据脱敏实施指引", summary="合规",
         content="数据脱敏指对敏感字段（姓名、证件号、联系方式）进行遮蔽、哈希或替换，使其无法直接识别到个人，满足合规要求。",
         tags=["合规"]),
    dict(id="eval-008", title="预算压缩指引", summary="成本",
         content="预算压缩指引：优先保留核心业务系统，合并冗余实例，将低频任务迁移至按量计费，目标降低基础设施支出两成。",
         tags=["成本"]),
    dict(id="eval-009", title="2025年第四季度财务快报", summary="季度财报",
         content="2025年第四季度财务快报：营业收入4.1亿元，同比增长12%，净利润5,100万元，毛利率39%。",
         tags=["财报", "2025Q4"]),
    dict(id="eval-010", title="2026年第一季度财务快报", summary="季度财报",
         content="2026年第一季度财务快报：营业收入4.8亿元，同比增长18%，净利润6,200万元，毛利率41%。",
         tags=["财报", "2026Q1"]),
    dict(id="eval-011", title="2026年第二季度财务快报", summary="季度财报",
         content="2026年第二季度财务快报：营业收入5.2亿元，同比增长20%，净利润7,000万元，毛利率42%。",
         tags=["财报", "2026Q2"]),
    dict(id="eval-012", title="贷款利率政策（2025年版）", summary="利率",
         content="贷款利率政策（2025年版）：一年期LPR为3.10%，五年期以上为3.60%，自2025年10月起执行。",
         tags=["利率", "2025"]),
    dict(id="eval-013", title="贷款利率政策（2026年版）", summary="利率",
         content="贷款利率政策（2026年版）：一年期LPR为2.85%，五年期以上为3.30%，自2026年1月起执行。",
         tags=["利率", "2026"]),
    dict(id="eval-014", title="API网关 v2.3 变更记录", summary="变更",
         content="API网关 v2.3 变更记录：新增路由前缀改写能力，默认超时从30秒调整为60秒。",
         tags=["网关"]),
    dict(id="eval-015", title="API网关 v2.4 变更记录", summary="变更",
         content="API网关 v2.4 变更记录：限流阈值从每秒500提升至1000，修复了网关在高峰期的偶发超时。",
         tags=["网关"]),
    dict(id="eval-016", title="值班制度", summary="行政",
         content="值班制度：工作日9:00-18:00主值班，周末按值班表轮换，紧急事故先打电话再建工单。",
         tags=["行政"]),
]

# (category, query, expected item ids that must appear within TOP_N results)
GOLDEN_QUERIES = [
    ("exact", "随机对照试验", {"eval-001"}),
    ("exact", "差分隐私", {"eval-002"}),
    ("exact", "灰度发布", {"eval-003"}),
    ("exact", "版本回滚", {"eval-004"}),
    ("exact", "随机对照试验 样本量", {"eval-001"}),
    ("colloquial", "怎么证明每个部件都不是多余的", {"eval-005"}),
    ("colloquial", "考试成绩全靠死记硬背怎么办", {"eval-006"}),
    ("colloquial", "怎么把客户手机号藏起来", {"eval-007"}),
    ("colloquial", "服务器续费的钱不够了有哪些省钱的办法", {"eval-008"}),
    ("dated", "2026年第一季度净利润", {"eval-010"}),
    ("dated", "2025年第四季度营收", {"eval-009"}),
    ("dated", "2026年第二季度 毛利率", {"eval-011"}),
    ("dated", "2026年贷款利率政策", {"eval-013"}),
    ("dated", "v2.4 限流阈值", {"eval-015"}),
]

# --- Ratchet floors, measured 2026-10-11 against this exact corpus ---------
# BM25-only baseline: exact 5/5, dated 5/5, colloquial 0/4 (paraphrase queries
# return an EMPTY result set — zero lexical overlap, everything filtered).
# Semantic light-up or BM25 tuning must raise these floors, never lower them.
BM25_EXACT_FLOOR = 5
BM25_DATED_FLOOR = 5
BM25_COLLOQUIAL_FLOOR = 0
BM25_TOTAL_FLOOR = 10


@pytest.fixture()
def eval_env(knowledge_env):
    """One governed team base holding the 16-item golden corpus.

    Seeds a single governance-reviewed item to obtain a valid template row and
    source artifact, then rewrites the item store with the eval corpus (the
    bulk-write pattern used by test_knowledge_semantic_service).
    """
    _item(knowledge_env)
    owner, base = knowledge._require_base_with_owner(knowledge_env["base"]["knowledgeBaseId"])
    template = knowledge._read_jsonl(knowledge._items_path_for_owner(owner))[0]
    rows = []
    for index, spec in enumerate(EVAL_ITEMS):
        stamp = f"2026-09-{index + 1:02d}T00:00:00Z"
        rows.append({
            **template,
            "knowledgeItemId": spec["id"],
            "rootKnowledgeItemId": spec["id"],
            "title": spec["title"],
            "summary": spec["summary"],
            "content": spec["content"],
            "tags": list(spec["tags"]),
            "createdAt": stamp,
            "updatedAt": stamp,
        })
    knowledge._write_jsonl(knowledge._items_path_for_owner(owner), rows)
    return knowledge_env


def _search_ids(env, query, mode):
    payload = retrieval.search_knowledge_items(
        agent_id=env["lead"]["agentId"],
        knowledge_base_id=env["base"]["knowledgeBaseId"],
        query=query,
        search_mode=mode,
        limit=TOP_N,
    )
    return [row["knowledgeItemId"] for row in payload["results"]]


def _run_golden(env, mode):
    hits = {"exact": 0, "colloquial": 0, "dated": 0}
    misses = []
    for category, query, expected in GOLDEN_QUERIES:
        top_ids = _search_ids(env, query, mode)
        if expected & set(top_ids):
            hits[category] += 1
        else:
            misses.append(f"[{category}] {query!r} -> top{TOP_N}={top_ids}, 期望包含 {sorted(expected)}")
    return hits, misses


def test_bm25_golden_set_baseline_ratchet(eval_env):
    hits, misses = _run_golden(eval_env, "bm25")

    # 2026-10-11 基线：BM25 精确术语查询 5/5 全命中（目标条目均为 rank 1）。
    assert hits["exact"] >= BM25_EXACT_FLOOR, misses
    # 2026-10-11 基线：带日期/版本查询 5/5 命中；注意错误周期的条目会漏进 top-5
    # （如查 2026Q1 时 2026Q2/2025Q4 也在结果里），这是金融日期过滤前移要修的对象。
    assert hits["dated"] >= BM25_DATED_FLOOR, misses
    # 2026-10-11 基线：口语化转述查询 0/4 —— 查询与目标条目零词面重叠，BM25 直接
    # 返回空结果。这是语义层点亮后必须改善的缺口；改善后请把该下限上调到实测值。
    assert hits["colloquial"] >= BM25_COLLOQUIAL_FLOOR, misses
    assert sum(hits.values()) >= BM25_TOTAL_FLOOR, misses

    # Same input, same output: BM25 ranking must be a pure function of corpus + query.
    assert _search_ids(eval_env, "随机对照试验 样本量", "bm25") == _search_ids(eval_env, "随机对照试验 样本量", "bm25")


def _semantic_probe():
    """Semantic-layer gate: fastembed importable AND a prepared model, else skip."""
    try:
        import fastembed  # noqa: F401
    except Exception as exc:  # ImportError plus broken-install variants
        return False, None, f"fastembed 不可导入（{type(exc).__name__}）"
    # Follow the suite-wide convention for pointing at a prepared model cache.
    if os.environ.get("VIBELUTION_KNOWLEDGE_MODEL_CACHE"):
        cache = Path(os.environ["VIBELUTION_KNOWLEDGE_MODEL_CACHE"])
    else:
        cache = semantic._cache_dir()
    state = semantic.embeddings.readiness(cache_dir=cache)
    if not semantic._model_ready(state):
        return False, None, f"嵌入模型未 prepare（status={state.get('status') or 'unknown'}）"
    return True, cache, "ready"


def test_hybrid_golden_set_semantic_layer(eval_env, monkeypatch):
    available, cache, reason = _semantic_probe()
    if not available:
        pytest.skip(f"语义层不可用，跳过 hybrid 评测：{reason}")
    monkeypatch.setattr(semantic, "_cache_dir", lambda: cache)

    built = semantic.build_knowledge_index(
        eval_env["base"]["knowledgeBaseId"], agent_id=eval_env["lead"]["agentId"],
    )
    assert built["indexedItemCount"] == len(EVAL_ITEMS)

    hits, misses = _run_golden(eval_env, "hybrid")
    # 模型就绪时 exact/dated 仍必须全命中：hybrid=RRF(向量, BM25)，BM25 侧目标条目
    # 本来就是 rank 1，RRF 融合后不会掉出 top-5。
    assert hits["exact"] >= BM25_EXACT_FLOOR, misses
    assert hits["dated"] >= BM25_DATED_FLOOR, misses
    # 语义层对口语化查询的下限暂设 0：首次真实模型跑通后按实测值收紧此棘轮
    # （BAAI/bge-small-zh-v1.5 应能桥接"死记硬背"→过拟合这类转述）。
    assert hits["colloquial"] >= 0, misses

    payload = retrieval.search_knowledge_items(
        agent_id=eval_env["lead"]["agentId"],
        knowledge_base_id=eval_env["base"]["knowledgeBaseId"],
        query="怎么证明每个部件都不是多余的",
        search_mode="hybrid",
        limit=TOP_N,
    )
    assert payload["semanticRetrieval"]["status"] in {"ready", "degraded"}
    assert payload["semanticRetrieval"]["effectiveMode"] == "hybrid"


def test_unified_auto_query_mode_dispatches_to_hybrid_pipeline(eval_env):
    payload = unified_knowledge_search_service.search_unified_memory(
        agent_id=eval_env["lead"]["agentId"],
        knowledge_base_id=eval_env["base"]["knowledgeBaseId"],
        query="随机对照试验",
        query_mode="auto",
        limit=TOP_N,
    )
    # auto + 非空 query → hybrid 分派；语义模型缺失时服务端诚实降级为 bm25，
    # 两种有效状态都接受（unified_knowledge_search_service._effective_query_mode）。
    assert payload["request"]["queryMode"] == "auto"
    assert payload["request"]["effectiveQueryMode"] in {"hybrid", "bm25"}
    knowledge_ids = [
        row["knowledgeItemId"]
        for row in payload["results"]
        if row["resultType"] == "knowledge_item"
    ]
    assert "eval-001" in knowledge_ids
