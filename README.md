# 六边形能力雷达 (Hexaradar Eval)

为人员制定并展示六维能力「六边形图」的 AstrBot 插件。支持 WebUI 双视图展示、拼音/同音搜索、数据双向修改（WebUI 与 AI），并提供 AI 读写工具与聊天指令。

## 功能特性

- **WebUI 展示**：卡片（图标）与列表两种视图，均支持排序（按名称拼音、六项单项分数、综合分）
- **双向数据修改**：WebUI 可直接增删改；AI 通过工具函数读取、写入/新建人员数据
- **AI 调用能力**：随插件注册 `get_radar_scores` / `set_radar_scores` 工具，并附带 `radar-eval` Skill 说明评价口径
- **搜索**：支持姓名、全拼、拼音首字母、同音模糊匹配（如搜「晓铭」可命中「小明」）
- **密码门禁**：可配置 WebUI 访问密码（仅保护 WebUI，不影响 AI 工具）
- **聊天指令**：`/radar <名字>` 查看某人六项评分，`/radar list` 查看综合分排行
- **亮/暗主题**：自动跟随 AstrBot WebUI 主题

## 六项能力与综合分

| 能力 | 键名 | 权重 |
|---|---|---|
| 学习能力 | `learning` | 1.0 |
| 心理承受力 | `psychology` | 2.0 |
| 社交能力 | `social` | 1.5 |
| 判断决策 | `judgment` | 2.0 |
| 自我认知 | `self_awareness` | 1.5 |
| 长期方向感 | `direction` | 1.0 |

个人基准分综合分 = (2×心理承受力 + 2×判断决策 + 1.5×自我认知 + 1.5×社交能力 + 1×学习能力 + 1×长期方向感) ÷ 9

评分范围为 0-100（含小数），综合分同为 0-100，由系统统一计算。

## 社会参考分（可选）

开启配置 `show_social_score` 后，系统基于六项评分与**年龄**自动计算社会参考分（25 岁成熟基准）：

- 25 岁基准权重：判断 3.0 / 心理 2.5 / 社交 2.5 / 认知 2.0 / 方向 1.5 / 学习 1.0
- 年龄系数：10/16/20/25/30/40 岁节点分段线性插值，10 岁以下按 10 岁、40 岁以上按 40 岁
- 公式：社会参考分 = Σ(权重 × 年龄系数 × 评分) ÷ Σ(权重 × 年龄系数)

未填年龄的人员不显示社会参考分，也不参与社会分排序。首页社会参考分仅展示综合分（青色胶囊，与个人基准分并列）；详情页可切换查看。社会参考分的 6 个小项不参与排序。

## 安装

1. 将本仓库克隆（或下载解压）到 AstrBot 的 `data/plugins/` 目录：
   ```
   git clone https://github.com/FoolishWiser/astrbot_plugin_hexaradar.git data/plugins/astrbot_plugin_hexaradar
   ```
2. 在 AstrBot WebUI 的插件管理页启用/重载插件（首次加载自动安装依赖 `pypinyin`）
3. 进入插件详情页，打开 **六边形能力雷达** Page

## 使用

### WebUI

- **搜索**：顶部输入框支持姓名/全拼/首字母/同音匹配，输入即查
- **视图切换**：卡片视图（▦）与列表视图（☰）
- **排序**：卡片视图用右上角下拉框；列表视图点击表头
- **详情页**：点击卡片头像或列表中的姓名，进入详情页——左侧大尺寸雷达图，右侧六项评分明细、逐项评价理由与整体备注
- **编辑**：点击卡片或「编辑」按钮，拖拽滑块实时预览综合分，可为每项填写评分理由
- **新建**：点击「+ 新建人员」，默认六项 60 分
- **删除**：编辑弹窗、详情页或列表中的「删除」按钮（需确认）

### 密码保护（可选）

在插件配置中：

```json
{
  "password_enabled": true,
  "password": "你的密码"
}
```

启用后访问 WebUI 需输入密码（密码保存在浏览器会话中，刷新后需重新输入）。此密码仅保护 WebUI 页面数据，**不影响 AI 工具调用**。

### 聊天指令

```
/radar 小明           查看「小明」的六项评分、逐项理由与综合分
/radar list           按综合分从高到低列出全部人员
/radar rank 学习 5    按指定维度排行（综合/学习/心理/社交/判断/认知/方向，可加人数）
/radar search 晓铭    模糊搜索（支持姓名/拼音/首字母/同音）
```

### AI 能力

| 工具 | 说明 |
|---|---|
| `get_radar_scores(name?)` | 查询单个或全部人员数据（只读） |
| `set_radar_scores(name, learning, ..., direction, desc?, reasons?)` | 新建或更新人员评分（upsert），`reasons` 为逐项评价理由 |
| `search_radar_persons(query)` | 拼音/首字母/同音模糊搜索 |
| `get_radar_ranking(sort_by?, limit?)` | 按综合分或任一维度排行 |

AI **不具备删除人员的能力**；删除仅限 WebUI 管理员操作。

## 数据存储

人员数据保存在 `data/plugin_data/astrbot_plugin_hexaradar/scores.json`，插件更新/重装不会丢失。

## 开发

- 数据层：`store.py`（JSON 持久化 + 综合分计算 + 拼音/同音搜索）
- Web API：`main.py`（`/astrbot_plugin_hexaradar/list`、`/person`、`/person/delete`）
- AI 工具：`tools/radar_tools.py`
- 前端：`pages/radar/`（原生 JS + SVG，零外部依赖）
- Skill：`skills/radar-eval/SKILL.md`

## 兼容性

- AstrBot `>= 4.17.0`（需要插件 Pages 与 Web API 支持）

## License

MIT
