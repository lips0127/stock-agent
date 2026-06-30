"""统一任务类型注册表（Phase A, 2026-06-10）。

新增异步任务必须在 TASK_KINDS 中注册，否则前端无法正确展示标签。
"""

TASK_KINDS: dict[str, dict] = {
    "scan_index":                     {"label": "红利指数扫描",    "icon": "📡", "category": "扫描"},
    "scan_full":                      {"label": "全市场扫描",      "icon": "🔭", "category": "扫描"},
    "sentiment_batch":                {"label": "舆情批量分析",    "icon": "💬", "category": "舆情"},
    "sentiment_single":               {"label": "单股舆情分析",    "icon": "💬", "category": "舆情"},
    "sentiment_universe":             {"label": "全市场舆情爬取",  "icon": "🌐", "category": "舆情"},
    "sentiment_audit_rerun":          {"label": "标题真实性重审",  "icon": "🔍", "category": "舆情"},
    "vix_recompute":                  {"label": "VIX 重算",        "icon": "🌡️", "category": "风控"},
    "vix_backfill":                   {"label": "VIX 历史回填",    "icon": "📊", "category": "风控"},
    "vix2_train":                     {"label": "VIX2.0 模型训练", "icon": "🧠", "category": "风控"},
    "vix2_backfill":                  {"label": "VIX2.0 回填",     "icon": "🧠", "category": "风控"},
    "top_picks_refresh":              {"label": "热门股池刷新",    "icon": "⭐", "category": "舆情"},
    "top_picks_analyze":              {"label": "热门股池分析",    "icon": "🔥", "category": "舆情"},
    "indicators_recompute":           {"label": "时序因子重算",    "icon": "📈", "category": "舆情"},
    "universe_constituents_refresh":  {"label": "成分股周更",      "icon": "🔄", "category": "舆情"},
    "universe_aggregate":             {"label": "全市场指数聚合",  "icon": "🧮", "category": "舆情"},
    "zhihu_user_refresh":             {"label": "知乎用户抓取",    "icon": "🐝", "category": "知乎"},
    "zhihu_user_reanalyze":           {"label": "知乎用户重分析",  "icon": "🤖", "category": "知乎"},
    "zhihu_post_reanalyze":           {"label": "知乎单帖重分析",  "icon": "🤖", "category": "知乎"},
    "zhihu_check_all":                {"label": "知乎全量检查",    "icon": "📬", "category": "知乎"},
    "forum_prefetch":                 {"label": "股吧帖子预拉",    "icon": "📥", "category": "舆情"},
    "financial_report_parse":         {"label": "财报解析",        "icon": "📄", "category": "舆情"},
    "tenbag_scan":                    {"label": "十倍股扫描",      "icon": "🚀", "category": "选股"},
    "tenbag_report_analyze":          {"label": "年报深度分析",    "icon": "📑", "category": "选股"},
    "industry_prosperity_refresh":    {"label": "行业景气刷新",    "icon": "🏭", "category": "选股"},
}


def kind_label(kind: str) -> str:
    """返回 kind 的用户可读标签，未知 kind 返回原值。"""
    info = TASK_KINDS.get(kind)
    return info["label"] if info else kind


def kind_category(kind: str) -> str:
    """返回 kind 的分类名。"""
    info = TASK_KINDS.get(kind)
    return info["category"] if info else "其他"
