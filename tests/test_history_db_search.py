"""test_history_db_search.py — 历史搜索回归（P1：中文搜索失效 / FTS5 兜底）

背景（2026-09 修复）：
- FTS5 默认 unicode61 分词器不索引 CJK token（中文/日文/韩文 MATCH 恒为 0）；
- 历史遗留库的 FTS 索引是 trigram 语义，对 <3 字符查询无法子串命中；
- 含引号/括号等特殊字符的查询会让 MATCH 抛语法错误 500。

修复策略：含 CJK 或长度 < 3 的查询走 LIKE 子串匹配；其余走 FTS5，
MATCH 语法错误自动降级 LIKE。本文件守护这三条边界。
"""

from __future__ import annotations


def _seed(tmp_db) -> None:
    """构造混合中英文任务样本。"""
    tmp_db.create_task(task_id="c1", engine="test", prompt="一只戴着帽子的橘猫,赛博朋克风格")
    tmp_db.create_task(task_id="c2", engine="test", prompt="少女肖像，柔和自然光，胶片质感")
    tmp_db.create_task(task_id="e1", engine="test", prompt="a cat named capacity baseline")
    tmp_db.create_task(task_id="e2", engine="test", prompt="discount 100% off today", tags='["促销"]')


class TestCjkSearch:
    """中文搜索必须命中（此前 MATCH 恒 0）。"""

    def test_multi_char_substring(self, tmp_db):
        _seed(tmp_db)
        tasks, total = tmp_db.list_tasks(q="橘猫")
        assert total == 1 and tasks[0]["task_id"] == "c1"

    def test_single_char(self, tmp_db):
        _seed(tmp_db)
        tasks, total = tmp_db.list_tasks(q="猫")
        assert total == 1 and tasks[0]["task_id"] == "c1"

    def test_substring_not_whole_word(self, tmp_db):
        """LIKE 子串：搜「肖像」应命中 c2（含"肖像"），不要求整词。"""
        _seed(tmp_db)
        _, total = tmp_db.list_tasks(q="肖像")
        assert total == 1

    def test_no_match_returns_empty(self, tmp_db):
        _seed(tmp_db)
        _, total = tmp_db.list_tasks(q="水下世界")
        assert total == 0

    def test_tags_searchable(self, tmp_db):
        """tags 字段同样可被中文搜索命中。"""
        _seed(tmp_db)
        _, total = tmp_db.list_tasks(q="促销")
        assert total == 1


class TestShortAsciiSearch:
    """< 3 字符的 ASCII 查询走 LIKE 子串（trigram 索引对短查询失效）。"""

    def test_two_char_substring(self, tmp_db):
        _seed(tmp_db)
        tasks, total = tmp_db.list_tasks(q="ca")
        assert total == 1 and tasks[0]["task_id"] == "e1"  # "cat capacity"


class TestFtsPath:
    """非 CJK 长查询仍走 FTS5 索引，行为不变。"""

    def test_ascii_fts_hits(self, tmp_db):
        _seed(tmp_db)
        tasks, total = tmp_db.list_tasks(q="capacity")
        assert total == 1 and tasks[0]["task_id"] == "e1"

    def test_fts_with_status_filter(self, tmp_db):
        _seed(tmp_db)
        tmp_db.update_task_status("e1", "completed")
        tasks, total = tmp_db.list_tasks(q="capacity", status="completed")
        assert total == 1


class TestFtsFallback:
    """MATCH 语法错误 / 通配符注入必须降级为字面 LIKE，绝不 500。"""

    def test_syntax_error_falls_back(self, tmp_db):
        _seed(tmp_db)
        # 引号触发 FTS5 语法错误：应降级 LIKE 且不抛异常
        tasks, total = tmp_db.list_tasks(q='cat" OR 1=1 --')
        assert total == 0
        assert tasks == []

    def test_like_wildcard_escaped(self, tmp_db):
        """'%' 只按字面匹配，不会退化成全表扫描。"""
        _seed(tmp_db)
        assert tmp_db.list_tasks(q="100%")[1] == 1  # 命中 e2 的字面 "100%"
        assert tmp_db.list_tasks(q="%d%")[1] == 0  # 字面 "%d%" 不存在

    def test_underscore_escaped(self, tmp_db):
        _seed(tmp_db)
        # "10_0" 字面不存在（提示词里是 "100"），_ 通配符必须被转义
        _, total = tmp_db.list_tasks(q="10_0")
        assert total == 0


class TestSearchEdgeCases:
    def test_blank_query_no_filter(self, tmp_db):
        _seed(tmp_db)
        _, total = tmp_db.list_tasks(q="   ")
        assert total == 4  # 纯空白等价于无搜索条件

    def test_whitespace_stripped(self, tmp_db):
        _seed(tmp_db)
        _, total = tmp_db.list_tasks(q="  橘猫  ")
        assert total == 1
