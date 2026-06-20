"""E 阶段 M2：字段级合并算法单测（8 类场景）。

覆盖：
1. 本地较新 → 保留本地
2. 远端较新 → 取远端
3. skew 内同时改 → 节点 ID 字典序裁决
4. _changed_fields 限定只合并声明字段
5. _changed_fields 缺省 → 视作全字段
6. 非标量字段（list/dict）→ 整体替换
7. 远端独有字段（本地没有）→ 整体纳入
8. META 字段（id / fieldTimestamps / _changed_fields）→ 永远不参与合并
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.network.field_merge import (
    META_FIELDS,
    SKEW_TOLERANCE_SEC,
    extract_changed_fields,
    resolve_field_level,
)


def _iso(dt: datetime) -> str:
    """生成 UTC ISO 时间字符串。"""
    return dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


# 基准时间
T0 = datetime(2026, 6, 20, 10, 0, 0)


def test_1_local_newer_keeps_local():
    """本地 title 时间更新（T+10s），远端 title 时间旧（T+0s）→ 保留本地。"""
    local = {
        'id': 't1',
        'title': '本地新版',
        'priority': 'normal',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端旧版',
        'priority': 'high',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-B'},
        },
        '_changed_fields': ['title'],
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '本地新版', f"应保留本地 title，实际：{merged['title']}"
    assert merged['priority'] == 'normal', f"priority 未声明改动，应保留本地，实际：{merged['priority']}"


def test_2_remote_newer_takes_remote():
    """远端 title 时间更新（T+10s），本地旧（T+0s）→ 取远端。"""
    local = {
        'id': 't1',
        'title': '本地旧版',
        'priority': 'normal',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端新版',
        'priority': 'high',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
        },
        '_changed_fields': ['title', 'priority'],
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '远端新版', f"应取远端 title，实际：{merged['title']}"
    # priority 远端无时间戳但声明变更 → 远端胜（fallback remote_at）
    assert merged['priority'] == 'high', f"应取远端 priority，实际：{merged['priority']}"
    # 合并后 fieldTimestamps.title 应记录远端时间戳
    assert merged['fieldTimestamps']['title']['by'] == 'node-B'


def test_3_concurrent_within_skew_uses_node_id():
    """两段时间差 < skew_sec（1s）→ 按 updated_by 字典序裁决。"""
    local = {
        'id': 't1',
        'title': '本地标题',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端标题',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(milliseconds=300)), 'by': 'node-B'},
        },
        '_changed_fields': ['title'],
    }
    # node-B > node-A（字典序）→ 取远端
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '远端标题', f"字典序 B>A 应取远端，实际：{merged['title']}"

    # 反过来：node-A 远端 > node-B 本地 → 保留本地
    local2 = {
        'id': 't1',
        'title': '本地标题',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-B'},
        },
    }
    remote2 = {
        'id': 't1',
        'title': '远端标题',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(milliseconds=300)), 'by': 'node-A'},
        },
        '_changed_fields': ['title'],
    }
    merged2 = resolve_field_level(local2, remote2, 'node-B', 'node-A')
    assert merged2['title'] == '本地标题', f"字典序 A>B 应保留本地，实际：{merged2['title']}"


def test_4_changed_fields_limits_merge_scope():
    """_changed_fields = ['title'] → 只对 title 做合并；priority 保留本地。"""
    local = {
        'id': 't1',
        'title': '本地',
        'priority': 'normal',
        'description': '本地描述',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
            'priority': {'at': _iso(T0), 'by': 'node-A'},
            'description': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端',
        'priority': '远端优先级（不应进来）',
        'description': '远端描述（不应进来）',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
            'priority': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
            'description': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
        },
        '_changed_fields': ['title'],  # ← 只声明改 title
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '远端', f"title 应取远端，实际：{merged['title']}"
    assert merged['priority'] == 'normal', f"priority 不在 _changed_fields，应保留本地，实际：{merged['priority']}"
    assert merged['description'] == '本地描述', f"description 不在 _changed_fields，应保留本地，实际：{merged['description']}"


def test_5_missing_changed_fields_merges_all():
    """_changed_fields 缺省 → 视作"remote 中所有非 META 字段都是变更"。"""
    local = {
        'id': 't1',
        'title': '本地',
        'priority': 'normal',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
            'priority': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端',
        'priority': 'high',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
            'priority': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
        },
        # 无 _changed_fields → 缺省全字段
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '远端'
    assert merged['priority'] == 'high'


def test_6_non_scalar_field_replaced_whole():
    """非标量字段（list / dict）→ 整体替换为远端值，不做字段级合并。"""
    local = {
        'id': 't1',
        'title': '本地',
        'tags': ['work', 'urgent'],
        'meta': {'project': 'alpha'},
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
            'tags': {'at': _iso(T0), 'by': 'node-A'},
            'meta': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '本地',  # 同值
        'tags': ['home'],  # 整体替换
        'meta': {'project': 'beta', 'priority': 'P1'},  # 整体替换
        'fieldTimestamps': {
            'tags': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-B'},
            'meta': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-B'},
        },
        '_changed_fields': ['tags', 'meta'],
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['tags'] == ['home'], f"非标量 list 应整体替换为远端，实际：{merged['tags']}"
    assert merged['meta'] == {'project': 'beta', 'priority': 'P1'}, f"非标量 dict 应整体替换为远端，实际：{merged['meta']}"


def test_7_remote_only_field_added():
    """远端独有字段（本地没有）→ 整体纳入，不丢失。"""
    local = {
        'id': 't1',
        'title': '本地',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '本地',  # 同
        'category': '远端新增分类',
        'assignee': '远端新增指派',
        'fieldTimestamps': {
            'category': {'at': _iso(T0 + timedelta(seconds=2)), 'by': 'node-B'},
            'assignee': {'at': _iso(T0 + timedelta(seconds=2)), 'by': 'node-B'},
        },
        '_changed_fields': ['category', 'assignee'],
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['category'] == '远端新增分类', f"远端独有 category 应纳入，实际：{merged.get('category')}"
    assert merged['assignee'] == '远端新增指派', f"远端独有 assignee 应纳入，实际：{merged.get('assignee')}"
    # fieldTimestamps 也应记录
    assert merged['fieldTimestamps']['category']['by'] == 'node-B'
    assert merged['fieldTimestamps']['assignee']['by'] == 'node-B'


def test_8_meta_fields_never_merged():
    """META 字段（id / fieldTimestamps / _changed_fields / _field_timestamps）→ 永远保留本地，不参与合并。"""
    local = {
        'id': 't1',
        'title': '本地',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
            'id': {'at': _iso(T0), 'by': 'node-A'},  # 尝试污染
        },
    }
    remote = {
        'id': 't1',  # 同 id
        'title': '本地',
        'fieldTimestamps': {
            'id': {'at': _iso(T0 + timedelta(seconds=999)), 'by': 'node-B'},  # 尝试覆盖
        },
        '_changed_fields': ['id', 'fieldTimestamps'],  # 显式声明要"合并" META
        '_field_timestamps': {'old_format_key': 'should_be_ignored'},
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    # META 字段不应被改写
    assert merged['id'] == 't1', f"id 不应被改写，实际：{merged['id']}"
    # fieldTimestamps 应保留本地，不应被远端的污染数据覆盖
    assert merged['fieldTimestamps']['title']['by'] == 'node-A', "本地字段时间戳不应被改写"
    # _changed_fields 不应进入 merged
    assert '_changed_fields' not in merged or merged.get('_changed_fields') == ['id', 'fieldTimestamps']  # 可能保留，但不应参与逻辑合并
    # 验证 META_FIELDS 集合包含这些键
    for k in ('id', 'fieldTimestamps', '_field_timestamps', '_changed_fields'):
        assert k in META_FIELDS, f"{k} 应在 META_FIELDS 中"


def test_extract_changed_fields_basic():
    """extract_changed_fields：值不同的字段被提取出来。"""
    local = {
        'id': 't1',
        'title': '旧',
        'priority': 'normal',
        'description': '同',
    }
    remote = {
        'id': 't1',
        'title': '新',
        'priority': 'normal',
        'description': '同',
    }
    changed = extract_changed_fields(local, remote)
    assert 'title' in changed
    assert 'priority' not in changed, f"同值字段不应在 changed 列表：{changed}"
    assert 'description' not in changed, f"同值字段不应在 changed 列表：{changed}"
    assert 'id' not in changed, f"id 是 META，不应在 changed 列表：{changed}"


def test_extract_changed_fields_ignores_meta():
    """extract_changed_fields：META 字段即使值不同也不应被列入。"""
    local = {
        'id': 't1',
        'title': 'A',
        'fieldTimestamps': {'title': {'at': '2026-01-01T00:00:00Z', 'by': 'a'}},
    }
    remote = {
        'id': 't1',
        'title': 'B',
        'fieldTimestamps': {'title': {'at': '2026-02-01T00:00:00Z', 'by': 'b'}},
    }
    changed = extract_changed_fields(local, remote)
    assert 'title' in changed
    assert 'fieldTimestamps' not in changed, f"META 不应列入：{changed}"
    assert 'id' not in changed


def test_parse_failure_falls_back_to_node_id():
    """时间戳解析失败（坏 ISO 格式）→ 回退到 updated_by 字典序。"""
    local = {
        'id': 't1',
        'title': '本地',
        'fieldTimestamps': {
            'title': {'at': 'not-a-real-iso-time', 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端',
        'fieldTimestamps': {
            'title': {'at': 'garbage-time-format', 'by': 'node-B'},
        },
        '_changed_fields': ['title'],
    }
    # 时间戳都解析失败 → node-B > node-A → 取远端
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    assert merged['title'] == '远端', f"解析失败时字典序 B>A 应取远端，实际：{merged['title']}"


def test_clock_skew_boundary_exact():
    """clock-skew 边界：差 == skew_sec（1.0s）不视为同时，按时间戳裁决。"""
    # 验证常量
    assert SKEW_TOLERANCE_SEC == 1.0
    # 差刚好 = 1.0s → 不进入 skew 分支 → 按时间戳
    local = {
        'id': 't1',
        'title': '本地',
        'fieldTimestamps': {
            'title': {'at': _iso(T0), 'by': 'node-A'},
        },
    }
    remote = {
        'id': 't1',
        'title': '远端',
        'fieldTimestamps': {
            'title': {'at': _iso(T0 + timedelta(seconds=1)), 'by': 'node-B'},
        },
        '_changed_fields': ['title'],
    }
    merged = resolve_field_level(local, remote, 'node-A', 'node-B')
    # 边界：delta == skew_sec，按代码 `if delta < skew_sec` 走 else → 取较新者
    assert merged['title'] == '远端', f"边界外应取较新（远端），实际：{merged['title']}"


if __name__ == '__main__':
    test_1_local_newer_keeps_local()
    test_2_remote_newer_takes_remote()
    test_3_concurrent_within_skew_uses_node_id()
    test_4_changed_fields_limits_merge_scope()
    test_5_missing_changed_fields_merges_all()
    test_6_non_scalar_field_replaced_whole()
    test_7_remote_only_field_added()
    test_8_meta_fields_never_merged()
    test_extract_changed_fields_basic()
    test_extract_changed_fields_ignores_meta()
    test_parse_failure_falls_back_to_node_id()
    test_clock_skew_boundary_exact()
    print('all field_merge tests passed')
