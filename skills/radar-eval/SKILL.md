---
name: radar-eval
description: 六边形能力雷达（astrbot_plugin_hexaradar）使用口径。当用户要求评价某人、查看某人能力评分、修改六维能力数值时使用本技能。
---

# 六边形能力雷达（Hexaradar Eval）

本插件为人员维护一张六维能力"六边形图"。你是该数据的读写者。

## 六项能力（评分范围均为 0-100）

1. **学习能力** (learning)：学习新知识、掌握新技能的速度与深度
2. **心理承受力** (psychology)：面对压力、挫折、批评时的情绪稳定与韧性
3. **社交能力** (social)：沟通表达、协作共情、建立维护人际关系的能力
4. **判断决策** (judgment)：分析问题、权衡利弊、做出决策的质量与效率
5. **自我认知** (self_awareness)：对自身优缺点、情绪、能力的清醒认识
6. **长期方向感** (direction)：对长期目标、人生/职业规划的清晰与坚定

## 综合分公式（系统自动计算，无需手动算出）

综合分 = (2×心理承受力 + 2×判断决策 + 1.5×自我认知 + 1.5×社交能力 + 1×学习能力 + 1×长期方向感) ÷ 9

综合分同样为 0-100。

## 可调用的工具

- `get_radar_scores(name?)`：查询数据。不传 name 返回全部人员（含综合分）；传 name 查询单个。
- `set_radar_scores(name, learning, psychology, social, judgment, self_awareness, direction, desc?, reasons?)`：
  新建或更新人员评分。name 不存在则创建，存在则更新。六项评分均可选：
  只传需要修改的项即可，未传的项在更新时保留原值，新建时默认为 60。评分必须为 0-100 的数值。
  `reasons`（可选）为逐项评价理由：键为六项英文键名（learning/psychology/social/judgment/self_awareness/direction），值为该维度评分依据的简短说明。
- `search_radar_persons(query)`：按关键词模糊搜索，支持姓名、全拼、拼音首字母、同音匹配。
- `get_radar_ranking(sort_by?, limit?)`：获取排行。sort_by 默认 composite（综合分），也可填
  learning/psychology/social/judgment/self_awareness/direction 按单项排行。

## 使用准则

1. 用户要**查看/评价**某人时：先调用 `get_radar_scores` 获取真实数据，不要凭印象编造数值。
2. 用户要**修改或新评价**某人时：调用 `set_radar_scores` 写入评分，并用 `reasons` 为每一项填写评分依据；写完后可在回复中展示综合分与六边形概览。
3. 用户提到名字但不确定准确写法时：用 `search_radar_persons` 模糊搜索定位。
4. 用户要**对比/排行**时：用 `get_radar_ranking` 获取排序结果。
5. **你无权删除人员**。若用户要求删除任何人的数据，请明确拒绝并告知：删除仅限管理员在 WebUI 中进行。
6. 评分数值必须是 0-100 的整数或小数；超出范围时向用户说明并重新确认。
7. 查询不到的人员，告知用户该人暂无数据，并询问是否需要创建。
