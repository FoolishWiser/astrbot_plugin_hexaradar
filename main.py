"""六边形能力雷达 - AstrBot 插件主入口。

- WebUI Page API（受配置密码门禁保护，仅保护 WebUI）
- AI 工具函数注册（免密码，读/写/新建，无删除）
- /radar 聊天指令（只读文字展示）
- AI 回答后自动评审改分（on_llm_response 钩子 + 别名匹配）
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .store import DIMENSIONS, DEFAULT_SCORE, RadarStore
from .tools.radar_tools import (
    RadarGetTool,
    RadarRankingTool,
    RadarScarcityTool,
    RadarSearchTool,
    RadarSetTool,
    RadarSocialTool,
)

PLUGIN_NAME = "astrbot_plugin_hexaradar"
PASSWORD_HEADER = "X-Radar-Password"

DIMENSION_LABELS = {dim["key"]: dim["label"] for dim in DIMENSIONS}


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        self.store = RadarStore(
            data_dir,
            social_enabled=bool(config.get("show_social_score", False)),
            scarcity_enabled=bool(config.get("show_scarcity_score", False)),
        )
        self._reviewing: set = set()

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
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/person/history",
            self.api_history,
            ["GET"],
            "获取人员更新记录",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/settings",
            self.api_get_settings,
            ["GET"],
            "读取插件设置",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/settings",
            self.api_save_settings,
            ["POST"],
            "保存插件设置",
        )

        self.context.add_llm_tools(
            RadarGetTool(store=self.store),
            RadarSetTool(store=self.store),
            RadarSearchTool(store=self.store),
            RadarRankingTool(store=self.store),
            RadarSocialTool(store=self.store),
            RadarScarcityTool(store=self.store),
        )
        logger.info("astrbot_plugin_hexaradar 已加载")

    def _sync_flags(self) -> None:
        """显示类开关实时同步（设置页修改后无需重载插件）。"""
        self.store._social_enabled = bool(self.config.get("show_social_score", False))
        self.store._scarcity_enabled = bool(self.config.get("show_scarcity_score", False))

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
        self._sync_flags()
        q = request.query.get("q", "")
        persons = await self.store.list_persons(query=q)
        file = self.store._file
        logger.info(
            f"astrbot_plugin_hexaradar: WebUI list 请求 q={q!r}，返回 {len(persons)} 人，"
            f"数据文件={file}（存在={file.exists()}）"
        )
        return json_response(
            {
                "persons": persons,
                "count": len(persons),
                "social_enabled": bool(self.config.get("show_social_score", False)),
                "scarcity_enabled": bool(self.config.get("show_scarcity_score", False)),
            }
        )

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
        if "age" in payload and payload["age"] is not None and payload["age"] != "":
            try:
                age = int(payload["age"])
            except (TypeError, ValueError):
                return error_response("年龄必须为整数")
            if age < 0 or age > 120:
                return error_response("年龄必须在 0-120 之间")
        else:
            age = None
        person = await self.store.upsert_person(
            name,
            scores,
            desc=str(payload.get("desc", "")),
            reasons=reasons,
            age=age,
            keep_age="age" not in payload,
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

    async def api_history(self):
        denied = self._require_password()
        if denied:
            return denied
        name = request.query.get("name", "")
        if not name:
            return error_response("缺少 name 参数")
        history = await self.store.get_person_history(name)
        return json_response({"name": name, "history": history})

    # ---------- 设置（WebUI 设置页） ----------

    async def api_get_settings(self):
        denied = self._require_password()
        if denied:
            return denied
        aliases = await self.store.get_aliases()
        return json_response(
            {
                "password_enabled": bool(self.config.get("password_enabled", False)),
                "password": str(self.config.get("password", "")),
                "show_social_score": bool(self.config.get("show_social_score", False)),
                "show_scarcity_score": bool(self.config.get("show_scarcity_score", False)),
                "auto_review": bool(self.config.get("auto_review", True)),
                "aliases": aliases,
            }
        )

    async def api_save_settings(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象")
        denied = self._require_password(payload)
        if denied:
            return denied
        booleans = ["password_enabled", "show_social_score", "show_scarcity_score", "auto_review"]
        for key in booleans:
            if key in payload:
                self.config[key] = bool(payload[key])
        if "password" in payload:
            self.config["password"] = str(payload.get("password", ""))
        self.config.save_config()
        self._sync_flags()
        if "aliases" in payload and isinstance(payload["aliases"], dict):
            for name, alias in payload["aliases"].items():
                await self.store.set_alias(str(name), str(alias))
        aliases = await self.store.get_aliases()
        return json_response({"saved": True, "aliases": aliases})

    # ---------- AI 回答后自动评审改分 ----------

    @filter.on_llm_response()
    async def auto_review(self, event: AstrMessageEvent, resp: LLMResponse):
        """回答结束后：若回复命中库内姓名（含别名），调用模型评审并静默改分。"""
        try:
            if not self.config.get("auto_review", True):
                return
            umo = event.unified_msg_origin
            if umo in self._reviewing:
                return
            reply = ""
            if resp and resp.result:
                result = resp.result
                if isinstance(result, str):
                    reply = result
                else:
                    reply = str(getattr(result, "text", result))
            names = await self.store.match_names(reply or "")
            if not names:
                return
            self._reviewing.add(umo)
            try:
                await self._run_review(event, names, reply)
            finally:
                self._reviewing.discard(umo)
        except Exception as e:  # noqa: BLE001
            logger.error(f"astrbot_plugin_hexaradar: 自动评审出错: {e}")

    async def _run_review(self, event: AstrMessageEvent, names: List[str], reply: str) -> None:
        provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        if not provider:
            logger.warning("astrbot_plugin_hexaradar: 未找到提供商，跳过自动评审")
            return
        lines = ["请根据对话中关于以下人员的最新信息，判断是否需要调整其能力评分。", ""]
        for name in names:
            p = await self.store.get_person(name)
            if not p:
                continue
            scores = p["scores"]
            parts = ", ".join(
                f"{DIMENSION_LABELS[dim['key']]}={scores.get(dim['key'], 0)}" for dim in DIMENSIONS
            )
            lines.append(f"- {name}（年龄 {p.get('age', '未知')}）：{parts}")
        lines += [
            "",
            "最新对话内容（供评审参考）：",
            reply[:1500],
            "",
            "规则：仅当出现新的有效信息（事件/行为/表态）时调整，评分范围 0-100。",
            "只输出一个紧凑 JSON 对象，不要输出任何其他文字：",
            '{"changes": {"psychology": 90}, "reason": "一句话理由"}',
            "若无需调整，只输出 NONE。",
        ]
        prompt = "\n".join(lines)
        try:
            provider_result = await provider.text_chat(
                prompt=prompt, session_id=None, image_urls=None, func_tool=None
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"astrbot_plugin_hexaradar: 评审调用失败: {e}")
            return
        text = ""
        if provider_result:
            result = provider_result.result
            if isinstance(result, str):
                text = result
            else:
                text = str(getattr(result, "text", result))
        text = (text or "").strip()
        if not text or text.upper().startswith("NONE"):
            return
        proposal = self._parse_review_json(text)
        if not proposal:
            return
        changes = proposal.get("changes") or {}
        reason = str(proposal.get("reason", ""))
        name = str(proposal.get("name", "")).strip() or names[0]
        person = await self.store.get_person(name)
        if not person:
            return
        key_to_label = {dim["key"]: dim["label"] for dim in DIMENSIONS}
        valid_changes: Dict[str, float] = {}
        for key, value in changes.items():
            label = key_to_label.get(key, key)
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if not (0 <= value <= 100):
                continue
            if abs(value - float(person["scores"].get(key, 0))) < 1e-9:
                continue
            valid_changes[key] = value
        if not valid_changes:
            return
        new_scores = dict(person["scores"])
        for key, value in valid_changes.items():
            new_scores[key] = value
        batch = ""
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj and getattr(msg_obj, "message_id", None):
            batch = str(msg_obj.message_id)
        updated = await self.store.upsert_person(
            name,
            new_scores,
            desc=person.get("desc", ""),
            reasons=person.get("reasons", {}),
            age=person.get("age"),
            keep_age=True,
            batch=batch or None,
            source="ai",
        )
        lines = [f"⚡ 已更新「{name}」的能力评分"]
        for key, value in valid_changes.items():
            old_v = person["scores"].get(key, 0)
            lines.append(f"· {key_to_label.get(key, key)}   {old_v} → {value}")
        if reason:
            bolded = reason
            for key, value in valid_changes.items():
                label = key_to_label.get(key, key)
                bolded = bolded.replace(label, f"**{label}**")
                bolded = bolded.replace(str(int(value)), f"**{int(value)}**")
            lines.append("")
            lines.append(f"理由：{bolded}")
        await event.send(event.plain_result("\n".join(lines)))

    @staticmethod
    def _parse_review_json(text: str) -> Dict[str, Any]:
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return {}
            try:
                data = json.loads(match.group(0))
            except Exception:  # noqa: BLE001
                return {}
        if isinstance(data, dict) and (data.get("changes") or data.get("name")):
            return data
        return {}

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
