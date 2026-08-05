"""六边形能力雷达 - AI 工具函数。

AI 具备读取、写入/新建能力；不提供任何删除工具。
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Optional

from astrbot.api import FunctionTool, logger
from astrbot.api.event import AstrMessageEvent

from ..store import DIMENSIONS, DEFAULT_SCORE, SCORE_MAX, SCORE_MIN, RadarStore


def _text(result: object) -> str:
    return json.dumps(result, ensure_ascii=False)


@dataclass
class RadarGetTool(FunctionTool):
    """查询人员六边形数据（只读）。"""

    store: RadarStore | None = None

    name: str = "get_radar_scores"
    description: str = (
        "查询六边形能力雷达中的人员评分数据。不传 name 时返回全部人员；"
        "传入 name 时返回该人员详情（含六项评分与综合分）。综合分为 0-100。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "人员姓名（可选）。不传则返回全部人员。",
                },
            },
            "required": [],
        }
    )

    async def run(self, event: AstrMessageEvent, name: str = ""):
        try:
            if name and name.strip():
                person = await self.store.get_person(name.strip())
                if not person:
                    return _text({"ok": False, "error": f"未找到人员: {name}"})
                return _text({"ok": True, "person": person})
            persons = await self.store.list_persons()
            return _text({"ok": True, "count": len(persons), "persons": persons})
        except Exception as e:  # noqa: BLE001
            return _text({"ok": False, "error": str(e)})


@dataclass
class RadarSetTool(FunctionTool):
    """写入/新建人员六边形数据（upsert）。"""

    store: RadarStore | None = None

    name: str = "set_radar_scores"
    description: str = (
        "写入（新建或更新）六边形能力雷达中的人员评分。name 已存在则更新，不存在则创建。"
        "各评分为 0-100 的数值，可只传入部分项，缺省项保留原值或默认 60。"
        "综合分由系统按公式自动计算，无需传入。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "人员姓名，唯一标识",
                },
                **{
                    dim["key"]: {
                        "type": "number",
                        "description": f"{dim['label']}评分，范围 {SCORE_MIN}-{SCORE_MAX}，可选",
                    }
                    for dim in DIMENSIONS
                },
                "desc": {
                    "type": "string",
                    "description": "整体备注/评价说明（可选）",
                },
                "reasons": {
                    "type": "object",
                    "description": (
                        "逐项评价理由（可选）。键为六项维度英文键名（learning/psychology/social/"
                        "judgment/self_awareness/direction），值为该维度的评分理由字符串。"
                        "只传需要更新理由的项即可。"
                    ),
                    "properties": {
                        dim["key"]: {"type": "string", "description": f"{dim['label']}的评分理由"}
                        for dim in DIMENSIONS
                    },
                },
            },
            "required": ["name"],
        }
    )

    async def run(
        self,
        event: AstrMessageEvent,
        name: str,
        learning: Optional[float] = None,
        psychology: Optional[float] = None,
        social: Optional[float] = None,
        judgment: Optional[float] = None,
        self_awareness: Optional[float] = None,
        direction: Optional[float] = None,
        desc: str = "",
        reasons: Optional[Dict[str, str]] = None,
    ):
        try:
            scores: Dict[str, float] = {
                "learning": learning,
                "psychology": psychology,
                "social": social,
                "judgment": judgment,
                "self_awareness": self_awareness,
                "direction": direction,
            }
            for key, val in scores.items():
                if val is None:
                    continue
                if not (SCORE_MIN <= val <= SCORE_MAX):
                    raise ValueError(
                        f"{key} 评分 {val} 超出范围 {SCORE_MIN}-{SCORE_MAX}"
                    )
            existing = await self.store.get_person(name)
            if existing:
                for key, val in scores.items():
                    if val is None:
                        scores[key] = existing["scores"].get(key, DEFAULT_SCORE)
            person = await self.store.upsert_person(
                name, scores, desc=desc or "", reasons=reasons or {}
            )
            logger.info(f"astrbot_plugin_hexaradar: 已写入人员 {name} 的评分数据")
            return _text({"ok": True, "person": person})
        except Exception as e:  # noqa: BLE001
            return _text({"ok": False, "error": str(e)})


@dataclass
class RadarSearchTool(FunctionTool):
    """按拼音/同音模糊搜索人员（只读）。"""

    store: RadarStore | None = None

    name: str = "search_radar_persons"
    description: str = (
        "按关键词搜索六边形能力雷达中的人员，支持姓名、全拼、拼音首字母、同音模糊匹配"
        "（如搜「xm」「xiaom」「晓铭」均可命中「小明」）。返回匹配人员及其六项评分与综合分。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（姓名/拼音/首字母/同音）",
                },
            },
            "required": ["query"],
        }
    )

    async def run(self, event: AstrMessageEvent, query: str):
        try:
            persons = await self.store.search_persons(query or "")
            return _text({"ok": True, "count": len(persons), "persons": persons})
        except Exception as e:  # noqa: BLE001
            return _text({"ok": False, "error": str(e)})


@dataclass
class RadarRankingTool(FunctionTool):
    """按综合分或任一维度排行（只读）。"""

    store: RadarStore | None = None

    name: str = "get_radar_ranking"
    description: str = (
        "获取六边形能力雷达的人员排行。sort_by 可选 composite（综合分，默认）或六项维度键名"
        "（learning/psychology/social/judgment/self_awareness/direction），按分数降序返回前 limit 名。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "description": "排序维度：composite/learning/psychology/social/judgment/self_awareness/direction",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回人数上限，默认 10",
                },
            },
            "required": [],
        }
    )

    async def run(self, event: AstrMessageEvent, sort_by: str = "composite", limit: int = 10):
        try:
            persons = await self.store.ranking(sort_by=sort_by, limit=limit)
            return _text({"ok": True, "count": len(persons), "sort_by": sort_by, "persons": persons})
        except Exception as e:  # noqa: BLE001
            return _text({"ok": False, "error": str(e)})
