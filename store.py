"""六边形能力雷达 - 数据管理层。

负责人员数据的 JSON 持久化、综合分计算、拼音/同音搜索。
WebUI、AI 工具、聊天指令共用同一个 store 实例，保证数据与口径一致。
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from astrbot.api import logger

try:
    from pypinyin import Style, pinyin

    _HAS_PYPINYIN = True
except ImportError:  # pragma: no cover
    _HAS_PYPINYIN = False
    logger.warning(
        "astrbot_plugin_hexaradar: 未安装 pypinyin，拼音/同音搜索降级为纯文本匹配"
    )

# 六项能力定义（顺序即雷达图顶点顺序）
DIMENSIONS: List[Dict[str, Any]] = [
    {"key": "learning", "label": "学习能力"},
    {"key": "psychology", "label": "心理承受力"},
    {"key": "social", "label": "社交能力"},
    {"key": "judgment", "label": "判断决策"},
    {"key": "self_awareness", "label": "自我认知"},
    {"key": "direction", "label": "长期方向感"},
]

# 综合分权重（权重和为 9）
WEIGHTS: Dict[str, float] = {
    "learning": 1.0,
    "psychology": 2.0,
    "social": 1.5,
    "judgment": 2.0,
    "self_awareness": 1.5,
    "direction": 1.0,
}

SCORE_MIN, SCORE_MAX = 0, 100
DEFAULT_SCORE = 60

# 中文标签 → 键名，用于容错输入
LABEL_TO_KEY: Dict[str, str] = {dim["label"]: dim["key"] for dim in DIMENSIONS}


def compute_composite(scores: Dict[str, float]) -> float:
    """综合分 = (2×心理 + 2×判断 + 1.5×自我认知 + 1.5×社交 + 1×学习 + 1×方向感) ÷ 9"""
    total = sum(WEIGHTS[k] * float(scores.get(k, 0)) for k in WEIGHTS)
    return round(total / 9, 1)


def _pinyin_of(text: str) -> str:
    """返回无声调全拼字符串，如 '小明' -> 'xiaoming'。"""
    if not _HAS_PYPINYIN:
        return ""
    return "".join(part[0] for part in pinyin(text, style=Style.NORMAL, errors="ignore"))


def _pinyin_initials(text: str) -> str:
    """返回首字母缩写字符串，如 '小明' -> 'xm'。"""
    if not _HAS_PYPINYIN:
        return ""
    return "".join(part[0] for part in pinyin(text, style=Style.FIRST_LETTER, errors="ignore"))


class RadarStore:
    """人员六边形数据存储。线程安全（asyncio.Lock）。"""

    def __init__(self, data_dir: str | Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "scores.json"
        self._lock = asyncio.Lock()
        self._persons: Dict[str, Dict[str, Any]] = {}
        self._mtime: float | None = None
        self._load()

    # ---------- 内部 ----------

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                self._persons = raw.get("persons", {})
                self._mtime = self._file.stat().st_mtime
        except Exception as e:  # noqa: BLE001
            logger.error(f"astrbot_plugin_hexaradar: 读取数据文件失败，将重置: {e}")
            self._persons = {}
            self._mtime = None

    def _sync_from_disk(self) -> None:
        """若磁盘文件已被其他实例修改，则重新加载，保证跨实例一致。"""
        try:
            if self._file.exists() and self._file.stat().st_mtime != self._mtime:
                self._load()
        except OSError:
            pass

    async def _save(self) -> None:
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"persons": self._persons}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._file)
        self._mtime = self._file.stat().st_mtime

    @staticmethod
    def _normalize_scores(scores: Dict[str, Any]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for dim in DIMENSIONS:
            key = dim["key"]
            raw = scores.get(key, scores.get(dim["label"], DEFAULT_SCORE))
            try:
                val = float(raw)
            except (TypeError, ValueError):
                val = DEFAULT_SCORE
            result[key] = max(SCORE_MIN, min(SCORE_MAX, val))
        return result

    @staticmethod
    def _to_public(person: Dict[str, Any]) -> Dict[str, Any]:
        """附加综合分等展示字段，返回副本。"""
        out = dict(person)
        out["scores"] = dict(person.get("scores", {}))
        out["composite"] = compute_composite(out["scores"])
        return out

    # ---------- 查询 ----------

    async def list_persons(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        async with self._lock:
            self._sync_from_disk()
            persons = [self._to_public(p) for p in self._persons.values()]
        if query:
            query = query.strip().lower()
            if query:
                persons = [p for p in persons if self._match(p["name"], query)]
        persons.sort(key=lambda p: p["name"])
        return persons

    async def get_person(self, name: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            self._sync_from_disk()
            person = self._persons.get(name)
            return self._to_public(person) if person else None

    # ---------- 写入 ----------

    async def upsert_person(
        self, name: str, scores: Dict[str, Any], desc: str = ""
    ) -> Dict[str, Any]:
        """新建或更新人员。name 唯一，存在则覆盖。"""
        name = name.strip()
        if not name:
            raise ValueError("人员名称不能为空")
        scores_norm = self._normalize_scores(scores)
        async with self._lock:
            old = self._persons.get(name, {})
            person = {
                "name": name,
                "desc": desc.strip() or old.get("desc", ""),
                "scores": scores_norm,
                "updated_at": int(time.time()),
            }
            self._persons[name] = person
            await self._save()
        return self._to_public(person)

    async def delete_person(self, name: str) -> bool:
        async with self._lock:
            if name not in self._persons:
                return False
            del self._persons[name]
            await self._save()
            return True

    # ---------- 搜索 ----------

    @staticmethod
    def _match(name: str, query: str) -> bool:
        """匹配规则：姓名包含 / 全拼包含 / 首字母缩写包含 / 与全拼同音。"""
        name_lower = name.lower()
        if query in name_lower:
            return True
        if not _HAS_PYPINYIN:
            return False
        full_py = _pinyin_of(name)
        initials = _pinyin_initials(name)
        if query in full_py or query in initials:
            return True
        query_py = _pinyin_of(query)
        return bool(query_py) and query_py in full_py
