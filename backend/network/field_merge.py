"""E 阶段：字段级合并算法（field-level Last-Write-Wins + clock-skew 容忍）。

设计要点：
- 字段级 LWW：每个字段独立比较 updated_at，决定保留本地或远端值。
- clock-skew 容忍：两端时间差 < skew_sec（默认 1s）视为同时，按 updated_by 节点 ID 字典序裁决。
- 协议字段约定：远端 entity 可携带 _changed_fields 列表（驼峰名），
  接收方只对列表内的字段做字段级合并；未列出的字段保留本地。
- 兜底：时间戳解析失败时回退到 updated_by 字典序。
- 非标量字段（list/dict）：不做字段级合并，整体替换为远端值。
- 字段白名单外：id / fieldTimestamps / _field_timestamps / _changed_fields 永远不参与字段级合并。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

# 字段级 LWW 时钟偏移容忍窗口（秒）
SKEW_TOLERANCE_SEC = 1.0

# 永远不参与字段级合并的元字段
META_FIELDS = frozenset({
    'id',
    'fieldTimestamps',
    '_field_timestamps',
    '_changed_fields',
    'createdAt',
    'created_at',
})


def _parse_ts(s: Any) -> Optional[datetime]:
    """解析 ISO 8601 时间戳，统一为 UTC-aware。失败返回 None。"""
    if not s or not isinstance(s, str):
        return None
    try:
        # 兼容 "...Z" 形式
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        # naive datetime 默认当 UTC（db 存的 updated_at 多为本地 iso 格式，无时区）
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _pick_winner(
    lf: Dict[str, str],
    rf: Dict[str, str],
    ldt: Optional[datetime],
    rdt: Optional[datetime],
    skew_sec: float,
    fallback_local_id: str,
    fallback_remote_id: str,
) -> str:
    """裁决单个字段：'local' 或 'remote'。

    规则：
    1. 两端时间戳都解析成功：
       - 差 < skew_sec：按 updated_by 字典序（remote 大则取 remote）
       - 差 ≥ skew_sec：取较新者
    2. 任一端时间戳解析失败：回退到 updated_by 字典序
    """
    local_by = (lf.get('by') if isinstance(lf, dict) else None) or fallback_local_id or ''
    remote_by = (rf.get('by') if isinstance(rf, dict) else None) or fallback_remote_id or ''

    if ldt and rdt:
        delta = abs((rdt - ldt).total_seconds())
        if delta < skew_sec:
            return 'remote' if remote_by > local_by else 'local'
        return 'remote' if rdt > ldt else 'local'
    # 时间戳解析失败：回退到节点 ID 字典序
    return 'remote' if remote_by > local_by else 'local'


def _is_scalar(v: Any) -> bool:
    """非标量（list/dict）字段：不做字段级合并。"""
    return not isinstance(v, (list, dict))


def resolve_field_level(
    local: Dict[str, Any],
    remote: Dict[str, Any],
    local_node_id: str = '',
    remote_node_id: str = '',
    skew_sec: float = SKEW_TOLERANCE_SEC,
) -> Dict[str, Any]:
    """字段级合并：返回合并后的 entity 字典（基于 local 复制）。

    输入约定：
    - local / remote：任务 entity 字典（驼峰 key）
    - 字段级时间戳键：'fieldTimestamps'（驼峰，与 Task.to_dict() 一致）
    - 远端协议字段：'_changed_fields'（可选，未提供视为全字段）

    输出：
    - 合并后的 entity 字典（与 local 字段集一致 + remote 远端独有字段）
    - 'fieldTimestamps' 被更新为合并后每个字段的"赢家"时间戳
    - 远端 entity 中"非标量"字段（list/dict）按整体替换处理
    """
    merged: Dict[str, Any] = dict(local or {})
    local_ts: Dict[str, Dict[str, str]] = dict(
        (local or {}).get('fieldTimestamps') or {}
    )
    remote_ts: Dict[str, Dict[str, str]] = dict(
        (remote or {}).get('fieldTimestamps') or {}
    )

    # 远端声明的变更字段（缺省 = 视 remote 中所有非 META 字段为变更）
    declared = remote.get('_changed_fields')
    if declared is None:
        changed = [k for k in (remote or {}).keys() if k not in META_FIELDS]
    else:
        changed = list(declared)

    # 远端 entity 顶层 updatedAt 作为"远端字段时间戳缺省"时的兜底；
    # 本地顶层 updatedAt 是 db add_task 时间，不能作为字段历史时间，会误导裁决。
    fallback_remote_at = (remote or {}).get('updatedAt') or (remote or {}).get('updated_at') or ''

    for field in changed:
        if field in META_FIELDS:
            continue
        if field not in remote:
            continue  # 远端没声明该字段，跳过
        new_val = remote[field]

        # 非标量字段：整体替换（不做字段级合并）
        if not _is_scalar(new_val):
            if field in local and _is_scalar(local.get(field)):
                # 本地是标量、远端是非标量 → 不合并，保留本地
                continue
            merged[field] = new_val
            if field in remote_ts:
                local_ts[field] = remote_ts[field]
            continue

        # 字段时间戳缺省回退：远端用 entity 顶层 updatedAt；本地无字段时间戳视为"未知"，ldt=None
        # → 走字典序兜底（避免被 db add_task 的"现在"时间误导为 local 永远胜出）
        lf = local_ts.get(field)
        rf = remote_ts.get(field, {'at': fallback_remote_at, 'by': remote_node_id})
        if lf is None:
            lf = {'at': '', 'by': local_node_id}
        ldt = _parse_ts(lf.get('at')) if lf.get('at') else None
        rdt = _parse_ts(rf.get('at')) if rf.get('at') else _parse_ts(fallback_remote_at)

        winner = _pick_winner(lf, rf, ldt, rdt, skew_sec, local_node_id, remote_node_id)
        if winner == 'remote':
            merged[field] = new_val
            local_ts[field] = {'at': rf.get('at') or fallback_remote_at, 'by': rf.get('by') or remote_node_id}

    # 远端独有的字段（如远端新增的字段本地没有）整体纳入
    for k, v in (remote or {}).items():
        if k in META_FIELDS:
            continue
        if k not in merged:
            merged[k] = v
            if k in remote_ts:
                local_ts[k] = remote_ts[k]

    merged['fieldTimestamps'] = local_ts
    return merged


def extract_changed_fields(local: Dict[str, Any], remote: Dict[str, Any]) -> list:
    """比对 local/remote（纯 dict）返回真正值不同的字段名列表（驼峰）。

    用于：
    - 协议层 broadcast 时携带 _changed_fields
    - sync_engine 在本地变更时计算改动列表
    """
    changed = []
    keys = set((local or {}).keys()) | set((remote or {}).keys())
    for k in keys:
        if k in META_FIELDS:
            continue
        lv = (local or {}).get(k)
        rv = (remote or {}).get(k)
        # 标量直接比；非标量 JSON 序列化后比（避免 list 顺序敏感）
        if _is_scalar(lv) and _is_scalar(rv):
            if str(lv) != str(rv):
                changed.append(k)
        else:
            import json
            try:
                if json.dumps(lv, sort_keys=True, ensure_ascii=False) != json.dumps(rv, sort_keys=True, ensure_ascii=False):
                    changed.append(k)
            except (TypeError, ValueError):
                if str(lv) != str(rv):
                    changed.append(k)
    return changed
