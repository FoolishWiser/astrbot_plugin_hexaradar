"""六边形能力雷达 - AstrBot 插件主入口。

- WebUI Page API（受配置密码门禁保护，仅保护 WebUI）
- AI 工具函数注册（免密码，读/写/新建，无删除）
- /radar 聊天指令（只读文字展示）
- AI 回答后自动评审改分（on_llm_response 钩子 + 别名匹配）
"""

import json
import re
import time
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
        self._last_review_at: Dict[str, float] = {}

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
                "auto_review_trigger": str(self.config.get("auto_review_trigger", "both")),
                "auto_review_require_evidence": bool(
                    self.config.get("auto_review_require_evidence", True)
                ),
                "auto_review_max_delta": self._as_float(
                    self.config.get("auto_review_max_delta"), 0.0
                ),
                "auto_review_cooldown": self._as_int(
                    self.config.get("auto_review_cooldown"), 30
                ),
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
        booleans = [
            "password_enabled",
            "show_social_score",
            "show_scarcity_score",
            "auto_review",
            "auto_review_require_evidence",
        ]
        for key in booleans:
            if key in payload:
                self.config[key] = bool(payload[key])
        if "password" in payload:
            self.config["password"] = str(payload.get("password", ""))
        if "auto_review_trigger" in payload:
            trigger = str(payload["auto_review_trigger"]).strip().lower()
            if trigger in ("both", "user", "reply"):
                self.config["auto_review_trigger"] = trigger
        if "auto_review_max_delta" in payload:
            self.config["auto_review_max_delta"] = max(
                0.0, min(100.0, self._as_float(payload["auto_review_max_delta"], 0.0))
            )
        if "auto_review_cooldown" in payload:
            self.config["auto_review_cooldown"] = max(
                0, self._as_int(payload["auto_review_cooldown"], 30)
            )
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
        """回答结束后：若对话（按 auto_review_trigger 配置扫用户消息/AI 回复）命中库内姓名（含别名），
        调用模型评审并静默改分。仅当出现新的、可引用的信息时调整，改分写入更新记录并发送提示。"""
        try:
            if not self.config.get("auto_review", True):
                return
            umo = event.unified_msg_origin
            if umo in self._reviewing:
                return
            reply = self._response_text(resp)
            user_msg = self._user_text(event)
            trigger = str(self.config.get("auto_review_trigger", "both")).strip().lower()
            names: set = set()
            if trigger in ("both", "user") and user_msg:
                names.update(await self.store.match_names(user_msg))
            if trigger in ("both", "reply") and reply:
                names.update(await self.store.match_names(reply))
            if not names:
                return
            # 冷却过滤：同一人短时间重复提及不再重复发起评审
            now = time.monotonic()
            cooldown = self._as_int(self.config.get("auto_review_cooldown"), 30)
            active = [
                n
                for n in names
                if cooldown <= 0 or now - self._last_review_at.get(n, 0.0) >= cooldown
            ]
            if not active:
                return
            self._reviewing.add(umo)
            try:
                await self._run_review(event, active, user_msg, reply)
            finally:
                self._reviewing.discard(umo)
        except Exception as e:  # noqa: BLE001
            logger.error(f"astrbot_plugin_hexaradar: 自动评审出错: {e}")

    @staticmethod
    def _response_text(resp: Any) -> str:
        """从 LLMResponse（或其 result）中提取文本。"""
        if not resp or not resp.result:
            return ""
        result = resp.result
        if isinstance(result, str):
            return result
        return str(getattr(result, "text", result))

    @staticmethod
    def _user_text(event: AstrMessageEvent) -> str:
        """提取用户消息文本（AstrBot 4.x message_str，缺失时回退 message_obj）。"""
        text = getattr(event, "message_str", "") or ""
        if text:
            return str(text)
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is None:
            return ""
        return str(getattr(msg_obj, "message_str", "") or msg_obj)

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def _run_review(
        self,
        event: AstrMessageEvent,
        names: List[str],
        user_msg: str,
        reply: str,
    ) -> None:
        provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        if not provider:
            logger.warning("astrbot_plugin_hexaradar: 未找到提供商，跳过自动评审")
            return
        now = time.monotonic()
        for n in names:
            self._last_review_at[n] = now
        lines = [
            "你是六边形能力雷达的持续评估者。请判断本次对话是否包含关于以下人员的【新的、可引用的信息】",
            "（事件/行为/表态/事实），需要调整其能力评分。",
            "",
        ]
        for name in names:
            p = await self.store.get_person(name)
            if not p:
                continue
            scores = p["scores"]
            parts = ", ".join(
                f"{DIMENSION_LABELS[dim['key']]}={scores.get(dim['key'], 0)}" for dim in DIMENSIONS
            )
            lines.append(f"- {name}（年龄 {p.get('age', '未知')}）：{parts}")
            reasons = p.get("reasons") or {}
            reason_parts = [
                f"{DIMENSION_LABELS[dim['key']]}：{reasons.get(dim['key'], '无')}" for dim in DIMENSIONS
            ]
            lines.append(f"  现有评分理由：{'；'.join(reason_parts)}")
        lines += [
            "",
            "本次对话内容：",
            f"【用户消息】{user_msg[:800]}" if user_msg else "【用户消息】（无）",
            f"【AI 回复】{reply[:800]}" if reply else "【AI 回复】（无）",
            "",
            "规则：",
            "1. 仅当对话中出现新的、可引用的信息时才调整评分；没有新信息时只输出 NONE；",
            "2. 必须从对话原文引用一句作为 evidence；无法引用原文则输出 NONE；",
            "3. 已经反映在上述现有评分理由中的旧信息，不要重复调整；",
            "4. 评分范围 0-100；name 必须是上面列出的人员；changes 只含需要调整的维度键；",
            "5. 只输出一个紧凑 JSON 对象，不要输出任何其他文字：",
            '{"updates": [{"name": "小明", "changes": {"psychology": 90}, "reason": "一句话理由", "evidence": "对话原文引用"}]}',
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
        text = self._response_text(provider_result).strip()
        if not text or text.upper().startswith("NONE"):
            return
        proposals = self._parse_review_json(text)
        if not proposals:
            return
        require_evidence = bool(self.config.get("auto_review_require_evidence", True))
        delta_max = self._as_float(self.config.get("auto_review_max_delta"), 0.0)
        applied: List[Dict[str, Any]] = []
        for proposal in proposals:
            name = str(proposal.get("name", "")).strip()
            if not name or name not in names:
                continue
            changes = proposal.get("changes") or {}
            if not isinstance(changes, dict):
                continue
            reason = str(proposal.get("reason", "")).strip()
            evidence = str(proposal.get("evidence", "")).strip()
            if require_evidence and not evidence:
                continue
            person = await self.store.get_person(name)
            if not person:
                continue
            valid_changes: Dict[str, float] = {}
            clamped = False
            for key, value in changes.items():
                if key not in DIMENSION_LABELS:
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                if not (0 <= value <= 100):
                    continue
                old_v = float(person["scores"].get(key, 0))
                if abs(value - old_v) < 1e-9:
                    continue
                if delta_max > 0:
                    lo, hi = old_v - delta_max, old_v + delta_max
                    if value < lo or value > hi:
                        value = max(0.0, min(100.0, lo if value < old_v else hi))
                        clamped = True
                valid_changes[key] = value
            if not valid_changes:
                continue
            new_scores = dict(person["scores"])
            new_scores.update(valid_changes)
            batch = ""
            msg_obj = getattr(event, "message_obj", None)
            if msg_obj and getattr(msg_obj, "message_id", None):
                batch = str(msg_obj.message_id)
            history_meta: Dict[str, str] = {}
            if reason:
                history_meta["reason"] = reason
            if evidence:
                history_meta["evidence"] = evidence
            await self.store.upsert_person(
                name,
                new_scores,
                desc=person.get("desc", ""),
                reasons=person.get("reasons", {}),
                age=person.get("age"),
                keep_age=True,
                batch=batch or None,
                source="ai",
                history_meta=history_meta or None,
            )
            applied.append(
                {
                    "name": name,
                    "changes": valid_changes,
                    "old": person["scores"],
                    "reason": reason,
                    "evidence": evidence,
                    "clamped": clamped,
                }
            )
        if applied:
            await self._send_review_notice(event, applied)

    async def _send_review_notice(
        self, event: AstrMessageEvent, applied: List[Dict[str, Any]]
    ) -> None:
        lines: List[str] = []
        for a in applied:
            name = a["name"]
            lines.append(f"⚡ 已更新「{name}」的能力评分")
            for key, value in a["changes"].items():
                old_v = a["old"].get(key, 0)
                suffix = "（受单次上限限制）" if a["clamped"] else ""
                lines.append(f"· {DIMENSION_LABELS.get(key, key)}   {old_v} → {value}{suffix}")
            if a["reason"]:
                bolded = a["reason"]
                for key, value in a["changes"].items():
                    label = DIMENSION_LABELS.get(key, key)
                    bolded = bolded.replace(label, f"**{label}**")
                    bolded = bolded.replace(str(int(value)), f"**{int(value)}**")
                lines.append(f"理由：{bolded}")
            if a["evidence"]:
                lines.append(f"证据：「{a['evidence']}」")
            lines.append("")
        if lines:
            await event.send(event.plain_result("\n".join(lines).rstrip()))

    @staticmethod
    def _parse_review_json(text: str) -> List[Dict[str, Any]]:
        """解析评审输出。支持新格式 {"updates": [...]} 与旧格式 {"name","changes","reason"}。"""
        data = None
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:  # noqa: BLE001
                    return []
        if not isinstance(data, dict):
            return []
        updates = data.get("updates")
        if isinstance(updates, list):
            return [u for u in updates if isinstance(u, dict)]
        if isinstance(data.get("changes"), dict):
            return [data]
        return []

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
                "稀缺": "scarcity",
                "社会": "social_composite",
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
            if sort_by == "scarcity":
                label = "稀缺值"
            elif sort_by == "social_composite":
                label = "社会参考分"
            lines = [f"【六边形能力雷达 · {label}排行】"]
            for i, p in enumerate(persons, 1):
                if sort_by == "composite":
                    value = p["composite"]
                elif sort_by in ("scarcity", "social_composite"):
                    value = p[sort_by] if p[sort_by] is not None else "—"
                else:
                    value = p["scores"].get(sort_by, 0)
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
