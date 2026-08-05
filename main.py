"""六边形能力雷达 - AstrBot 插件主入口。

- WebUI Page API（受配置密码门禁保护，仅保护 WebUI）
- AI 工具函数注册（免密码，读/写/新建，无删除）
- /radar 聊天指令（只读文字展示）
"""

from pathlib import Path
from typing import Any, Dict

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .store import DIMENSIONS, DEFAULT_SCORE, RadarStore
from .tools.radar_tools import (
    RadarGetTool,
    RadarRankingTool,
    RadarSearchTool,
    RadarSetTool,
)

PLUGIN_NAME = "astrbot_plugin_hexaradar"
PASSWORD_HEADER = "X-Radar-Password"

DIMENSION_LABELS = {dim["key"]: dim["label"] for dim in DIMENSIONS}


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        self.store = RadarStore(data_dir)

        self.context.register_web_api(
            f"/{PLUGIN_NAME}/list", self.api_list, ["GET"], "获取人员列表（支持 q 搜索）"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/person", self.api_upsert, ["POST"], "新建或更新人员"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/person/delete",
            self.api_delete,
            ["POST"],
            "删除人员",
        )

        self.context.add_llm_tools(
            RadarGetTool(store=self.store),
            RadarSetTool(store=self.store),
            RadarSearchTool(store=self.store),
            RadarRankingTool(store=self.store),
        )
        logger.info("astrbot_plugin_hexaradar 已加载")

    # ---------- 密码门禁（仅 WebUI） ----------

    def _password_ok(self, payload: Dict[str, Any] | None = None) -> bool:
        if not self.config.get("password_enabled", False):
            return True
        expected = str(self.config.get("password", ""))
        if not expected:
            return True
        provided = ""
        if request.headers:
            provided = request.headers.get(PASSWORD_HEADER, "") or ""
        if not provided:
            provided = str(request.query.get("pwd", ""))
        if not provided and isinstance(payload, dict):
            provided = str(payload.get("pwd", ""))
        return provided == expected

    def _require_password(self, payload: Dict[str, Any] | None = None):
        if not self._password_ok(payload):
            return error_response("密码错误或未提供访问密码", status_code=401)
        return None

    # ---------- Web API ----------

    async def api_list(self):
        denied = self._require_password()
        if denied:
            return denied
        q = request.query.get("q", "")
        persons = await self.store.list_persons(query=q)
        file = self.store._file
        logger.info(
            f"astrbot_plugin_hexaradar: WebUI list 请求 q={q!r}，返回 {len(persons)} 人，"
            f"数据文件={file}（存在={file.exists()}）"
        )
        return json_response({"persons": persons, "count": len(persons)})

    async def api_upsert(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象")
        denied = self._require_password(payload)
        if denied:
            return denied
        name = str(payload.get("name", "")).strip()
        if not name:
            return error_response("人员名称不能为空")
        scores: Dict[str, Any] = payload.get("scores") or {}
        for dim in DIMENSIONS:
            key = dim["key"]
            try:
                val = float(scores.get(key, DEFAULT_SCORE))
            except (TypeError, ValueError):
                val = DEFAULT_SCORE
            if val < 0 or val > 100:
                return error_response(f"{DIMENSION_LABELS[key]} 评分必须在 0-100 之间")
            scores[key] = val
        reasons = payload.get("reasons")
        if not isinstance(reasons, dict):
            reasons = {}
        person = await self.store.upsert_person(
            name,
            scores,
            desc=str(payload.get("desc", "")),
            reasons=reasons,
        )
        return json_response({"person": person})

    async def api_delete(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象")
        denied = self._require_password(payload)
        if denied:
            return denied
        name = str(payload.get("name", "")).strip()
        if not name:
            return error_response("人员名称不能为空")
        ok = await self.store.delete_person(name)
        if not ok:
            return error_response(f"未找到人员: {name}", status_code=404)
        return json_response({"deleted": True, "name": name})

    # ---------- 聊天指令（只读） ----------

    @filter.command("radar")
    async def radar(
        self,
        event: AstrMessageEvent,
        arg1: str = "",
        arg2: str = "",
        arg3: str = "",
    ):
        """六边形能力雷达：/radar <名字> 查看详情；/radar list 排行；/radar rank [维度] [topN] 单项排行；/radar search <关键词> 模糊搜索"""
        sub = arg1.strip().lower()
        if sub in ("", "list"):
            persons = await self.store.ranking(sort_by="composite", limit=100)
            if not persons:
                yield event.plain_result("暂无人员数据")
                return
            lines = ["【六边形能力雷达 · 综合分排行】"]
            for i, p in enumerate(persons, 1):
                lines.append(f"{i}. {p['name']}  综合 {p['composite']} 分")
            yield event.plain_result("\n".join(lines))
            return

        if sub == "rank":
            dim_map = {
                "综合": "composite",
                "学习": "learning",
                "心理": "psychology",
                "社交": "social",
                "判断": "judgment",
                "认知": "self_awareness",
                "方向": "direction",
            }
            sort_by = dim_map.get(arg2.strip(), "composite")
            try:
                top = int(arg3)
            except ValueError:
                top = 10
            persons = await self.store.ranking(sort_by=sort_by, limit=top)
            if not persons:
                yield event.plain_result("暂无人员数据")
                return
            label = DIMENSION_LABELS.get(sort_by, "综合分")
            lines = [f"【六边形能力雷达 · {label}排行】"]
            for i, p in enumerate(persons, 1):
                value = p["composite"] if sort_by == "composite" else p["scores"].get(sort_by, 0)
                lines.append(f"{i}. {p['name']}  {label} {value} 分")
            yield event.plain_result("\n".join(lines))
            return

        if sub == "search":
            keyword = " ".join([x.strip() for x in (arg2, arg3) if x.strip()])
            if not keyword:
                yield event.plain_result("用法：/radar search <关键词>，支持姓名/拼音/首字母/同音")
                return
            persons = await self.store.search_persons(keyword)
            if not persons:
                yield event.plain_result(f"未找到与「{keyword}」匹配的人员")
                return
            lines = [f"【搜索「{keyword}」】共 {len(persons)} 人"]
            for p in persons:
                lines.append(f"{p['name']}  综合 {p['composite']} 分")
            yield event.plain_result("\n".join(lines))
            return

        name = " ".join([x.strip() for x in (arg1, arg2, arg3) if x.strip()])
        person = await self.store.get_person(name)
        if not person:
            yield event.plain_result(f"未找到人员: {name}")
            return
        scores = person["scores"]
        reasons = person.get("reasons") or {}
        lines = [f"【{person['name']}】综合 {person['composite']} 分"]
        for dim in DIMENSIONS:
            key = dim["key"]
            reason = reasons.get(key, "")
            lines.append(
                f"{dim['label']}: {scores.get(key, 0)}" + (f"（{reason}）" if reason else "")
            )
        if person.get("desc"):
            lines.append(f"备注: {person['desc']}")
        yield event.plain_result("\n".join(lines))

    async def terminate(self):
        pass
