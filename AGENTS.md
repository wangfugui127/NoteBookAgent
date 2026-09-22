# NotebookAgent — agent 工作约定

## 前端（frontend/）
- **任何前端 / UI 改动都必须先应用 `frontend-design` skill**（位于 `.opencode/skills/frontend-design/SKILL.md`）：先确定美学方向、给出 token/字体/布局设计计划，再写代码，并避免模板化默认样式。
- 设计方向：Calm Research Desk（仅亮色；中文优先排版；桌面优先）。
- 设计 token 统一在 `frontend/src/styles/tokens.css`，基础排版在 `frontend/src/styles/base.css`，由 `frontend/src/style.css` 汇总导入。不要在组件里写死颜色/字号。
- 视图逻辑抽到 `frontend/src/composables/`，视图与组件只负责渲染。
- 验证：`npm run build`（含 `vue-tsc` 类型检查）与 `npm run lint` 必须通过。

## 后端（backend/）
- 不在本任务范围内，保持不动。
