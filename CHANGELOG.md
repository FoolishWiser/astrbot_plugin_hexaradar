# Changelog

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.1.3] - 2026-08-04

### 修复

- 解决「LLM 提示写入成功但 WebUI 无数据」：读取数据时按文件修改时间自动同步磁盘，WebUI 与 AI 工具即使分属不同插件实例也能看到彼此写入的数据
- `set_radar_scores` 工具写入容错：六项评分改为可选，缺省项保留原值（新建时默认 60），不再因缺参报错；成功写入时输出日志便于排查

## [v0.1.2] - 2026-08-04

### 修复

- 修复 WebUI 弹窗/视图隐藏失效问题：CSS 中 `.modal-mask`、`.cards` 等 `display` 样式覆盖了 HTML `hidden` 属性，导致编辑弹窗常驻无法关闭（新增全局 `[hidden] { display: none !important; }` 规则）

## [v0.1.1] - 2026-08-04

### 修复

- 修复 AI 工具类 dataclass 定义报错「non-default argument 'store' follows default argument」（`store` 字段增加默认值）

## [v0.1.0] - 2026-08-04

### 新增

- WebUI Page：卡片/列表双视图，支持按名称拼音、六项单项、综合分排序
- 搜索：姓名、全拼、拼音首字母、同音模糊匹配（基于 pypinyin）
- 数据双向修改：WebUI 增删改；AI 工具读写/新建
- AI 工具：`get_radar_scores`（只读查询）、`set_radar_scores`（新建/更新）
- Skill：`radar-eval`，说明六项口径、综合分公式与「AI 无权删除」约束
- 聊天指令：`/radar <名字>`、`/radar list`
- 配置项：`password_enabled` / `password`（WebUI 密码门禁，仅保护 WebUI）
- 六维能力（学习能力、心理承受力、社交能力、判断决策、自我认知、长期方向感），综合分按权重公式统一计算
- 数据持久化至 `data/plugin_data/astrbot_plugin_hexaradar/scores.json`
- 亮/暗主题跟随 WebUI
