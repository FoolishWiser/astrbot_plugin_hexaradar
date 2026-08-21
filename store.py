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
AGE_MIN, AGE_MAX = 0, 120

# 中文标签 → 键名，用于容错输入
LABEL_TO_KEY: Dict[str, str] = {dim["label"]: dim["key"] for dim in DIMENSIONS}

# ---- 社会参考分算法（25 岁成熟基准）----

# 25 岁基准权重
SOCIAL_WEIGHTS: Dict[str, float] = {
    "learning": 1.0,
    "psychology": 2.5,
    "social": 2.5,
    "judgment": 3.0,
    "self_awareness": 2.0,
    "direction": 1.5,
}

# 年龄系数节点表：[(年龄, {维度: 系数}), ...]
SOCIAL_AGE_NODES: List[tuple] = [
    (10, {"learning": 2.5, "psychology": 0.4, "social": 0.6, "judgment": 0.2, "self_awareness": 0.2, "direction": 0.1}),
    (16, {"learning": 1.8, "psychology": 0.8, "social": 0.7, "judgment": 0.6, "self_awareness": 0.6, "direction": 0.4}),
    (20, {"learning": 1.4, "psychology": 0.95, "social": 0.9, "judgment": 0.8, "self_awareness": 0.8, "direction": 0.65}),
    (25, {"learning": 1.0, "psychology": 1.0, "social": 1.0, "judgment": 1.0, "self_awareness": 1.0, "direction": 1.0}),
    (30, {"learning": 0.7, "psychology": 0.95, "social": 0.9, "judgment": 1.1, "self_awareness": 1.2, "direction": 1.5}),
    (40, {"learning": 0.4, "psychology": 0.9, "social": 0.7, "judgment": 1.2, "self_awareness": 1.4, "direction": 2.0}),
]


def _social_coefficients(age: int) -> Dict[str, float]:
    """分段线性插值计算各维度年龄系数。x<=10 取 10 岁节点，x>=40 取 40 岁节点。"""
    x = max(10, min(40, age))
    for i, (a1, c1) in enumerate(SOCIAL_AGE_NODES):
        a2, c2 = SOCIAL_AGE_NODES[i + 1] if i + 1 < len(SOCIAL_AGE_NODES) else (a1, c1)
        if a1 <= x <= a2:
            if a1 == a2:
                return dict(c1)
            ratio = (x - a1) / (a2 - a1)
            return {k: c1[k] + ratio * (c2[k] - c1[k]) for k in c1}
    return dict(SOCIAL_AGE_NODES[-1][1])


def compute_social(scores: Dict[str, float], age: Optional[int]) -> Optional[float]:
    """社会参考分 = Σ(W·c·S) / Σ(W·c)，百分制。无年龄返回 None。"""
    if age is None:
        return None
    coeff = _social_coefficients(int(age))
    num = sum(SOCIAL_WEIGHTS[k] * coeff[k] * float(scores.get(k, 0)) for k in SOCIAL_WEIGHTS)
    den = sum(SOCIAL_WEIGHTS[k] * coeff[k] for k in SOCIAL_WEIGHTS)
    if den <= 0:
        return None
    return round(num / den, 1)


# ---- 稀缺值（独特性）算法 ----

SCAR_MEAN = 50.0  # 同龄人平均分基准


def _scar_beta(age: int) -> float:
    """全面性权重参数 β(x)。"""
    if age <= 10:
        return 0.2
    if age <= 25:
        return 0.2 + 0.8 * (age - 10) / 15
    if age <= 40:
        return 1.0 + 0.5 * (age - 25) / 15
    return 1.5


def _scar_uref(age: int) -> float:
    """归一化基准 U_ref(x)：x≤10 为 40；10<x<16 线性至 85.73；x≥16 为 85.73。"""
    if age <= 10:
        return 40.0
    if age < 16:
        return 40.0 + 45.73 * (age - 10) / 6
    return 85.73


def compute_scarcity(scores: Dict[str, float], age: Optional[int]) -> Optional[float]:
    """稀缺值 = min(100, U_raw/U_ref × 100)，百分制。无年龄返回 None。

    全面性映射 φ = (cosθ+1)/2 将 [-1,1] 映射到 [0,1]，总偏差为负时不再直接归零。
    """
    if age is None:
        return None
    d = [float(scores.get(k, 0)) - SCAR_MEAN for k in SOCIAL_WEIGHTS]
    L = sum(x * x for x in d) ** 0.5
    if L == 0:
        return 0.0
    cos_theta = sum(d) / (6 ** 0.5 * L)
    phi = (cos_theta + 1.0) / 2.0
    beta = _scar_beta(int(age))
    u_raw = L * (phi ** beta)
    uref = _scar_uref(int(age))
    if uref <= 0:
        return None
    return round(min(100.0, u_raw / uref * 100.0), 1)


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

    def __init__(self, data_dir: str | Path, social_enabled: bool = False, scarcity_enabled: bool = False):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "scores.json"
        self._lock = asyncio.Lock()
        self._persons: Dict[str, Dict[str, Any]] = {}
        self._aliases: Dict[str, str] = {}
        self._mtime: float | None = None
        self._social_enabled = social_enabled
        self._scarcity_enabled = scarcity_enabled
        self._load()

    # ---------- 内部 ----------

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                self._persons = raw.get("persons", {})
                self._aliases = dict(raw.get("aliases") or {})
                self._mtime = self._file.stat().st_mtime
        except Exception as e:  # noqa: BLE001
            logger.error(f"astrbot_plugin_hexaradar: 读取数据文件失败，将重置: {e}")
            self._persons = {}
            self._aliases = {}
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
            json.dumps(
                {"persons": self._persons, "aliases": self._aliases},
                ensure_ascii=False,
                indent=2,
            ),
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

    def _rollover_ages(self) -> bool:
        """已填年龄的人员跨年后自动加龄：按记录年份与当前年份之差递增。返回是否有变更。"""
        year = time.localtime().tm_year
        changed = False
        for person in self._persons.values():
            age = person.get("age")
            if age is None:
                continue
            age_year = person.get("age_year")
            if age_year is None:
                person["age_year"] = year
                changed = True
                continue
            try:
                age_year = int(age_year)
            except (TypeError, ValueError):
                person["age_year"] = year
                changed = True
                continue
            if age_year < year:
                person["age"] = age + (year - age_year)
                person["age_year"] = year
                changed = True
        return changed

    def _to_public(self, person: Dict[str, Any]) -> Dict[str, Any]:
        """附加综合分等展示字段，返回副本。"""
        out = dict(person)
        out.pop("age_year", None)
        out.pop("history", None)
        out["scores"] = dict(person.get("scores", {}))
        out["reasons"] = dict(person.get("reasons") or {})
        out["composite"] = compute_composite(out["scores"])
        out["age"] = person.get("age")
        out["social_enabled"] = self._social_enabled
        out["social_composite"] = None
        out["social_coeffs"] = None
        out["scarcity_enabled"] = self._scarcity_enabled
        out["scarcity"] = None
        out["scarcity_params"] = None
        if person.get("age") is not None:
            age = int(person["age"])
            if self._social_enabled:
                out["social_composite"] = compute_social(out["scores"], age)
                out["social_coeffs"] = _social_coefficients(age)
            if self._scarcity_enabled:
                out["scarcity"] = compute_scarcity(out["scores"], age)
                out["scarcity_params"] = {"beta": round(_scar_beta(age), 4), "uref": round(_scar_uref(age), 4)}
        name = str(person.get("name", ""))
        initials = _pinyin_initials(name).upper()
        first = initials[:1] if initials else ""
        if not first:
            ch = name[:1].upper()
            first = ch if ch.isalpha() else "#"
        out["py_initial"] = first
        return out

    # ---------- 查询 ----------

    async def list_persons(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        async with self._lock:
            self._sync_from_disk()
            if self._rollover_ages():
                await self._save()
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
            if self._rollover_ages():
                await self._save()
            person = self._persons.get(name)
            return self._to_public(person) if person else None

    async def get_person_history(self, name: str) -> List[Dict[str, Any]]:
        """获取某人的更新记录（时间倒序，最多 10 条）。"""
        async with self._lock:
            self._sync_from_disk()
            person = self._persons.get(name)
            if not person:
                return []
            return list(person.get("history") or [])

    async def search_persons(self, query: str) -> List[Dict[str, Any]]:
        """按姓名/全拼/首字母/同音模糊搜索。"""
        return await self.list_persons(query=query)

    async def ranking(
        self, sort_by: str = "composite", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """按综合分/社会参考分/任一维度降序排行。"""
        valid = [dim["key"] for dim in DIMENSIONS] + ["composite", "social_composite", "scarcity"]
        if sort_by not in valid:
            sort_by = "composite"
        async with self._lock:
            self._sync_from_disk()
            if self._rollover_ages():
                await self._save()
            persons = [self._to_public(p) for p in self._persons.values()]
        if sort_by in ("social_composite", "scarcity"):
            persons.sort(
                key=lambda p: (p[sort_by] is None, -(p[sort_by] or 0))
            )
        elif sort_by == "composite":
            persons.sort(key=lambda p: p["composite"], reverse=True)
        else:
            persons.sort(key=lambda p: p["scores"].get(sort_by, 0), reverse=True)
        return persons[: max(1, min(limit, 100))]

    # ---------- 写入 ----------

    async def upsert_person(
        self,
        name: str,
        scores: Dict[str, Any],
        desc: str = "",
        reasons: Optional[Dict[str, Any]] = None,
        age: Optional[int] = None,
        keep_age: bool = True,
        batch: Optional[str] = None,
        source: str = "web",
        history_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """新建或更新人员。name 唯一，存在则覆盖。

        age: 显式传 None 表示清空年龄；keep_age=True 且未显式传 age 时保留旧值。
        batch: 批次号（如 AI 同一次回答的 message_id），同批写入合并为一条更新记录。
        source: 更新来源 "ai" / "web"。
        history_meta: 附加到更新记录的元数据（如 {"reason": ..., "evidence": ...}，自动评审改分用）。
        """
        name = name.strip()
        if not name:
            raise ValueError("人员名称不能为空")
        if age is not None:
            if not (AGE_MIN <= age <= AGE_MAX):
                raise ValueError(f"年龄必须在 {AGE_MIN}-{AGE_MAX} 之间")
        scores_norm = self._normalize_scores(scores)
        reasons_norm: Dict[str, str] = {}
        if isinstance(reasons, dict):
            for dim in DIMENSIONS:
                raw = reasons.get(dim["key"], reasons.get(dim["label"], ""))
                if isinstance(raw, str) and raw.strip():
                    reasons_norm[dim["key"]] = raw.strip()
        async with self._lock:
            old = self._persons.get(name, {})
            merged_reasons = dict(old.get("reasons") or {})
            merged_reasons.update(reasons_norm)
            new_age = old.get("age")
            new_age_year = old.get("age_year")
            if age is not None or not keep_age:
                new_age = age
                new_age_year = time.localtime().tm_year if age is not None else None
            changes = []
            old_scores = old.get("scores", {})
            for dim in DIMENSIONS:
                key = dim["key"]
                old_v = old_scores.get(key)
                if old_v is not None and float(old_v) != float(scores_norm[key]):
                    changes.append({"field": key, "label": dim["label"], "from": old_v, "to": scores_norm[key]})
            if desc.strip() != old.get("desc", ""):
                changes.append({"field": "desc", "label": "备注", "from": old.get("desc", ""), "to": desc.strip()})
            old_age = old.get("age")
            if (age is not None or not keep_age) and old_age != new_age:
                changes.append({"field": "age", "label": "年龄", "from": old_age, "to": new_age})
            if reasons_norm and reasons_norm != dict(old.get("reasons") or {}):
                changes.append({"field": "reasons", "label": "评分理由", "from": "…", "to": "已更新"})
            person = {
                "name": name,
                "desc": desc.strip() or old.get("desc", ""),
                "scores": scores_norm,
                "reasons": merged_reasons,
                "age": new_age,
                "age_year": new_age_year,
                "history": self._append_history(old, changes, batch, source, history_meta),
                "updated_at": int(time.time()),
            }
            self._persons[name] = person
            await self._save()
        return self._to_public(person)

    @staticmethod
    def _append_history(
        old: Dict[str, Any],
        changes: List[Dict[str, Any]],
        batch: Optional[str],
        source: str,
        history_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """追加更新记录，上限 10 条；同批次（如同一 AI 回答）合并为一条。

        history_meta 的键值（如 reason/evidence）随记录一并保存，合并时取最新。
        """
        history = list(old.get("history") or [])
        if changes:
            if batch and history and history[0].get("batch") == batch:
                entry = history[0]
                by_field: Dict[str, Dict[str, Any]] = {}
                for c in entry["changes"]:
                    by_field.setdefault(c["field"], c)
                for c in changes:
                    if c["field"] in by_field:
                        by_field[c["field"]]["to"] = c["to"]
                    else:
                        by_field[c["field"]] = c
                entry["changes"] = list(by_field.values())
                entry["ts"] = int(time.time())
                if history_meta:
                    for k, v in history_meta.items():
                        if v:
                            entry[k] = v
            else:
                entry: Dict[str, Any] = {
                    "ts": int(time.time()),
                    "source": source,
                    "batch": batch,
                    "changes": changes,
                }
                if history_meta:
                    for k, v in history_meta.items():
                        if v:
                            entry[k] = v
                history.insert(0, entry)
        return history[:10]

    async def delete_person(self, name: str) -> bool:
        async with self._lock:
            if name not in self._persons:
                return False
            del self._persons[name]
            await self._save()
            return True

    # ---------- 别名（匹配库内姓名自定义） ----------

    async def get_aliases(self) -> Dict[str, str]:
        async with self._lock:
            self._sync_from_disk()
            return dict(self._aliases)

    async def set_alias(self, name: str, alias: str) -> Dict[str, str]:
        """设置或更新别名；alias 为空时删除该别名。"""
        name = name.strip()
        alias = alias.strip()
        async with self._lock:
            if alias:
                self._aliases[name] = alias
            else:
                self._aliases.pop(name, None)
            await self._save()
            return dict(self._aliases)

    async def match_names(self, text: str) -> List[str]:
        """返回文本中命中的库内真实姓名（同时匹配库内姓名与别名）。"""
        if not text:
            return []
        async with self._lock:
            self._sync_from_disk()
            names = list(self._persons.keys())
            aliases = dict(self._aliases)
        hits = []
        for n in names:
            if n and n in text:
                hits.append(n)
                continue
            alias = aliases.get(n, "")
            if alias and alias in text:
                hits.append(n)
        return hits

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
