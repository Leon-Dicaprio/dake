"""字段重复证明补齐仅接受本轮逐字原文，拒绝旧背景、错引和猜测。"""
from copy import deepcopy
import pytest
from dake.analysis.summary_changes import complete_field_changes
from test_attribution import candidate, message
from test_summary_history import change


@pytest.mark.parametrize("case", ["valid", "history", "wrong_quote", "invented_value", "review", "empty_changes", "mixed_refs"])
def test_field_completion_is_narrow_and_idempotent(case):
    current = message("current", 2, "合成工单仍在排查。")
    detail = message("detail", 2, "合成环境为集群甲。")
    old = message("old", 1, detail.content)
    c = candidate(current, changes=[change(current)])
    c.evidence_ids.extend([detail.key, old.key])
    c.extensions["extraction_v1"] = dict(attributes=[dict(name="合成环境", value="集群甲", quote=detail.content, evidence_ids=[detail.key])])
    f = c.extensions["extraction_v1"]["attributes"][0]
    if case == "history": f["evidence_ids"] = [old.key]
    if case == "wrong_quote": f["quote"] = "不存在的集群甲原文"
    if case == "invented_value": f["value"] = "集群乙"
    if case == "review": c.decision = "review"
    if case == "empty_changes": c.changes = []
    if case == "mixed_refs": f["evidence_ids"].append(old.key)
    before = deepcopy(c)
    available = {m.key: m for m in (current, detail, old)}
    normalized = complete_field_changes(c, available, {current.key, detail.key})
    if case == "valid":
        assert len(normalized) == 1 and len(c.changes) == 2
        assert c.changes[-1]["text"] == detail.content
        assert complete_field_changes(c, available, {current.key, detail.key}) == []
    else:
        assert normalized == [] and c == before
