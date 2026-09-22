# NotebookAgent：Codex 聊天记录与 OpenCode 交接

> 记录来源：Codex 任务 `01a0c707-ea65-7ca2-8d48-cc16f16ebc69`（任务名：搭建 Open Notebook Agent）  
> 项目目录：`F:\Project Practice\notebook\notebookagent`  
> 整理日期：2026-09-22  
> 用途：供 OpenCode 接手当前项目。本文是按时间整理的交接版聊天记录，不包含 Codex 的内部推理和冗长工具输出，也不记录 API Key、令牌或其他密钥。

## 0. 接手时的真实状态

这不是一个只有骨架的项目。Codex 已完成第一版实现、缺口修复、Docker 构建和真实端到端验证。

当前 Docker 服务可运行：

```text
前端：http://localhost:3000
API：http://localhost:8001
健康检查：http://localhost:8001/health
Neo4j：http://localhost:7474
```

最终验证结果：

- `docker compose --profile core --profile graph ps` 中 API、Frontend、Worker 正常运行。
- MySQL、Redis、Milvus、MinIO、Neo4j 为 healthy，etcd 正常运行。
- API `/health` 返回 `{"status":"ok"}`。
- 前端返回 HTTP 200。
- DeepSeek 与 SiliconFlow 真实 Provider 请求均返回 HTTP 200。
- 上传 `NotebookAgent_核心闭环设计.md` 后，MySQL 生成 2 个 Chunk，Milvus 写入 2 条记录，Neo4j 生成 2 个 Section 和 2 个 Chunk。
- 当前 Query 全文附件 Agent 回答成功：回答约 2656 字符、2 条 Citation、1 份 ContextManifest。
- RAG/GraphRAG Agent 成功：`mode_used=hybrid_graph`、`graph_attempted=true`、`graph_used=true`、`graph_degraded=false`，并产生 2 次工具调用、2 次工具结果、2 条引用。
- OpenAlex 论文搜索接口和前端页面可用。
- SSE 游标续读实测成功：最后事件后继续请求返回 0 字节，没有重复事件。
- Skills Reload 成功，当前内置 1 个 Skill。
- 外部 MCP Server 尚未配置，因此运行时显示 0 个外部 Server/Tool；但真实 stdio MCP Client 测试已经通过。
- `uv run ruff check .` 通过。
- 后端测试：20 个测试通过，只有 1 个 Starlette 弃用警告。
- 前端 `npm run build` 通过，共构建 87 个模块。
- Compose 配置检查通过，最终镜像已经重新构建。
- 最终重启后日志中没有 Error 或 Traceback。

当前非阻塞提示：

- Celery 开发容器以 root 运行时会打印警告。
- Starlette TestClient 有弃用警告。
- `config/mcp_servers.yaml` 目前有意保持为空；若要验证外部 MCP，需要自行配置真实 Server。
- Docker Volume 中保留了端到端测试数据，不要在未确认前删除 Volume。

## 1. 最初需求

用户最初要求参考四个已有 Codex 对话和 `F:\Project Practice\notebook\notebookagent` 中的设计文档，编写项目开发指南并生成第一版代码。

主要关注点：

```text
判断和路由通常在哪里做
上下文压缩在哪里发生
Tool Call 怎样执行和校验
Skills / MCP / RAG 是否需要路由
混合检索怎样决定
工具参数是否合理、工具是否存在
以后能否把候选工具路由替换为 JEV
```

指定技术与服务：

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_API_KEY=

SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

用户随后强调：Notebook 是论文级场景，上下文不应固定得很小，应按模型真实上下文窗口动态计算。

## 2. 关于全文 Query 和第一版范围的补充

用户要求：

- 用户当前 Query 中附带的文章优先全文进入逻辑 Query，而不是先变成 Top-K RAG。
- Neo4j、MCP、Skills 第一版必须实现。
- MCP 和 Skills 必须能通过配置文件自行添加。
- 跨会话长期 Memory 延期。
- Subagent 和 MoA 延期。
- 同步修改以下文档：

```text
NotebookAgent_核心闭环设计.md
NotebookAgent_开发方案.md
NotebookAgent_文件结构与代码架构.md
NotebookAgent_项目开发指南.md
```

## 3. 用户确认的完整第一版计划

### 3.1 技术栈与功能

```text
Vue 3 + FastAPI
MySQL + Redis + Celery
Milvus 混合检索
Neo4j GraphRAG
DeepSeek Root Agent Loop
论文级上下文与自动分窗
6 个原生业务工具
MCP Client 与 Server
配置式 Skills
动态 Tool Search
权限确认、Checkpoint、SSE、引用
Docker Compose
```

延期功能：

```text
跨会话长期 Memory
Subagent Runtime
MoA Planner
Agent CLI
```

### 3.2 文档要求

新建 `NotebookAgent_项目开发指南.md`，每一步按以下结构说明：

```text
为什么做
→ 涉及哪些文件
→ 每个文件负责什么
→ 横向数据流
→ 完成后怎么验收
```

其他三份设计文档同步调整第一版范围，删除长期 Memory、Subagent、MoA 的第一版运行目录和实现承诺，增加 MCP、Skills、附件分窗和 Neo4j 实现目录。

### 3.3 当前 Query 全文处理

逻辑上的 `QueryEnvelope`：

```text
用户原始文字
+ 附件名称、ID、类型
+ 用户对附件的指令
+ 每篇附件解析后的完整正文
```

当全部正文能放进有效上下文时，单次请求包含原始 Query 和全部附件正文；超过模型物理窗口时，按论文、章节和页码完整分窗，每个窗口重复原始任务要求，每一段正文至少处理一次，保存窗口级结论和 Citation，最后由 Root Agent 汇总。

强约束：

- 不静默截断。
- 不自动退化成普通 RAG。
- 每个正文范围至少处理一次。
- `ContextManifest` 记录文档、页码和字符范围。
- 最终答案可回链到附件页码或文本位置。
- 原始二进制文件只保存在文件系统和 MySQL，不直接传给模型。

默认上下文配置：

```dotenv
MODEL_CONTEXT_WINDOW=1048576
MAX_OUTPUT_TOKENS=32768
CONTEXT_SAFETY_RATIO=0.95
```

### 3.4 RAG 与 Neo4j GraphRAG

MySQL 保存业务事实和原文；Milvus、Neo4j 都是可重建索引。

Neo4j 节点：

```text
DocumentVersion
Section
Chunk
Entity
Method
Dataset
Metric
Paper
```

主要关系：

```text
HAS_SECTION
HAS_CHUNK
NEXT_CHUNK
MENTIONS
USES_METHOD
USES_DATASET
MEASURES_METRIC
CITES
COMPARES_WITH
SUPPORTS
CONTRADICTS
RELATED_TO
```

模型抽取关系必须保存 `notebook_id`、`document_version_id`、`evidence_chunk_ids`、`confidence`、`extractor_model`、`extractor_version`。没有有效 `evidence_chunk_ids` 的关系不能作为答案证据。

统一检索链路：

```text
Dense Top 30
+ BM25 Top 30
+ 可选 Neo4j 1～2 跳扩展
→ 映射回 chunk_id
→ 去重与 RRF
→ SiliconFlow Rerank
→ Evidence
```

`retrieval_mode`：

```text
hybrid
hybrid_graph
auto
comprehensive
```

`auto` 使用确定性问题特征和实体命中决定是否进行图扩展，不额外调用路由模型。Neo4j 不可用时降级为 `hybrid` 并记录 `graph_degraded=true`。

### 3.5 Root Agent、工具与 JEV 扩展点

主循环：

```text
prepare_context
→ select_candidate_tools
→ call_deepseek
→ direct answer 或 tool_calls
→ Tool Registry 校验
→ 权限/审批
→ Dispatcher 执行
→ ToolObservation
→ compact_or_split
→ 下一轮 DeepSeek
```

六个业务工具：

```text
task_update
list_notebook_sources
search_notebook
get_notebook_items
search_papers
get_paper_details
```

Harness 基础工具：

```text
load_skill
tool_search
read_mcp_resource
```

JEV 只作为以后可替换的候选工具筛选器，最终动作仍由 DeepSeek Tool Calling 决定，且 JEV 不能绕过权限、Schema 或 Dispatcher。

### 3.6 配置式 MCP

配置文件：

```text
config/mcp_servers.yaml
config/mcp_expose.yaml
```

规则：

- 本地 Server 使用 stdio。
- 远程 Server 使用 Streamable HTTP。
- 配置文件只引用环境变量，不保存密钥。
- 外部工具统一命名为 `mcp.<server_id>.<tool_name>`。
- 启动或 Reload 时做能力协商和工具发现。
- MCP 异常转换成 `ToolObservation`。
- 未声明风险等级的外部工具默认按写操作处理。
- NotebookAgent 自身通过 `POST /mcp` 暴露白名单中的只读能力，并执行同样的用户、Notebook 和文档权限检查。

### 3.7 配置式 Skills

```text
config/skills.yaml
skills/
└─ literature-review/
   ├─ SKILL.md
   └─ references/
```

规则：

- System Prompt 只常驻 Skill 名称和短描述。
- 模型调用 `load_skill(name)` 后才加载完整正文。
- 引用的 Supporting References 按需继续加载。
- Reload 时校验名称、描述、重复 ID 和允许工具。
- 第一版 Skill 只提供指令与静态资源，不自行执行脚本。
- `allowed_tools` 只能缩小权限，不能提升权限。

### 3.8 权限、审批和 Tool Search

工具风险等级：`read`、`write`、`destructive`。

- 原生查询工具为 read。
- `task_update` 只修改当前 Agent State。
- MCP 只读工具可以直接执行。
- MCP 写操作和破坏性操作必须暂停 Run 并请求确认。
- 未知 MCP 工具默认要求确认。
- 工具多时先用短 Catalog 和 Router/`tool_search` 选择最多 12 个候选，再把完整 JSON Schema 交给 DeepSeek。

### 3.9 上下文压缩

上下文层次：

```text
System Prompt
+ 当前完整 Query 或当前附件分窗
+ 最近完整 Turn
+ Conversation Summary
+ Agent State
+ Notebook Index
+ 本轮 RAG/Graph Evidence
+ 已加载 Skill
+ 候选 Tool/MCP Definitions
```

Conversation Summary 只服务当前会话连续性，不属于长期 Memory。

压缩规则：

- 70%：清理旧 Evidence 正文和大型 Tool Result。
- 85%：压缩较旧且已完成的 Turn。
- 95%：当前附件改用完整分窗；普通会话保存 Checkpoint 后重新装箱。
- 不删除当前 Query、当前附件窗口、任务状态、有效引用、安全规则或进行中的 Tool Call。

## 4. 用户提供的环境配置问题

用户询问哪些配置是启动必需项，并追问 `OPENALEX_MAILTO` 的含义。

结论：

- 必须填写真实的 `DEEPSEEK_API_KEY` 和 `SILICONFLOW_API_KEY`，否则只能启动本地基础设施，不能完成真实模型与向量服务调用。
- `OPENALEX_MAILTO` 是发送给 OpenAlex 的联系邮箱，用于进入 polite pool、便于对方联系调用者；它不是密码，也不是 OpenAlex API Key。可以填写常用邮箱，不使用 OpenAlex 时可留空。
- `.env` 中的 URL 必须写纯文本，不能保留 Markdown 链接括号。
- 本文不保存 `APP_SECRET_KEY`、数据库密码、Neo4j 密码、API Key 等实际值。

## 5. OpenCode 审计指出的问题

用户给出 OpenCode 的审计结果，要求仔细核对代码是否全部满足设计并能正常运行。

审计确认 MCP SDK 代码并没有写错；当时指出的真实缺口包括：

1. 工具循环中没有每轮重新进行上下文预算和压缩。
2. 只有 70% 和 85% 分支，缺少明确的 95% 附件分窗与普通会话 Checkpoint 重新装箱。
3. `ConversationSummary` 虽然有模型和临时合成逻辑，但没有真正持久化和跨轮复用。
4. 全文附件和分窗 Evidence 缺少真实 `chunk_id`。
5. 前端 SSE 没有基于 `Last-Event-ID` 或 `after` 游标续读。
6. 中文分窗尺寸估算错误，可能使窗口超过 Token 预算。
7. 同一轮多个 Tool Call 中途遇到审批时，后续 Tool Call 没有配对的 `role=tool` 结果，可能违反 DeepSeek/OpenAI 消息协议。

用户还要求使用 `frontend-design` Skill 重做前端，主要场景是：

```text
登录页
Notebook / Chat 研究工作台
论文搜索页
```

## 6. 用户对实施方式的最后补充

用户明确：

- 只需要保证 Docker 链路，宿主机直接运行不是验收目标。
- 后端新建专门的提示词目录。
- 遇到问题继续分析并完成；确实无法解决时再询问。
- 本机代理端口为 7897。
- Docker 可能已经配置镜像或代理，需要实际检查。

## 7. Codex 最终完成的修复与实现

### 7.1 Prompt 独立目录

新增：

```text
backend/app/prompts/__init__.py
backend/app/prompts/agent.py
backend/app/prompts/graph.py
```

Runtime、Context 和图谱抽取均从 Prompt 模块导入提示词。

### 7.2 Context

- 使用二分搜索实现 CJK 安全的附件分窗。
- 接入 95% 附件装箱阈值。
- 每轮工具循环执行 70% / 85% / 95% 压缩与重新装箱。
- `ConversationSummary` 持久化并跨轮复用。
- 当前 Query 不再被历史记录重复注入。

### 7.3 Evidence 与 Citation

- 附件 Evidence 关联真实 MySQL Chunk。
- ContextManifest 保存 chunk、页码和字符范围。
- 最终 Citation 只接受有效 Evidence ID；无效引用标记会被清理。

### 7.4 多工具调用和审批

- 支持 `pending_batch` 审批恢复。
- 所有 Tool Call 都会获得配对的 `role=tool` 结果。
- 每轮最多实际执行 3 个工具；超出的调用获得明确的未执行 Observation。
- `tool_search` 找到的工具会提升到本轮候选列表。

### 7.5 Skills 与 Router

- Skill 有激活白名单。
- References 按安全路径加载。
- 实现 SiliconFlow Embedding Router，并提供确定性回退。

### 7.6 Section 与 Graph

- 实现 Section 识别并写入 MySQL。
- Neo4j 写入 `DocumentVersion-HAS_SECTION-Section-HAS_CHUNK-Chunk`。
- 检索结果准确报告 `graph_attempted`、`graph_used`、`graph_degraded`。
- Neo4j 关系查询改为顺序 MATCH，消除笛卡尔积警告。

### 7.7 API

- 增加 Conversation 列表和消息读取接口，返回 Citation。
- 增加 OpenAlex 论文搜索和详情 API。

### 7.8 前端

- 重做 LoginView、NotebooksView、WorkspaceView。
- 新增 PaperSearchView。
- 实现 JWT Refresh。
- 实现 SSE 游标断线续读。
- 增加 Evidence Rail、Run Trace、审批操作和已有 Conversation 复用。
- 修复移动端窄屏品牌字母 N 不显示的问题。

### 7.9 Docker 与运行时修复

- 后端 Dockerfile 复制 `uv.lock` 并执行 `uv sync --frozen --no-dev`。
- 前端 Dockerfile 使用 `npm ci`。
- 为 DeepSeek、SiliconFlow、OpenAlex、Neo4j、Redis 增加资源关闭逻辑。
- Celery Task Wrapper 在关闭 `asyncio.run` 的 Loop 前 dispose SQLAlchemy Async Engine。
- Parser 在无文件名且类型为 octet-stream 时，仅对有效 UTF-8 文本放行。
- 修复 Milvus 2.6 不允许 multi-analyzer BM25 字段开启 `enable_match` 的问题。
- Milvus 查询改用实际主键 `chunk_id`，不再错误使用 `id`。
- 修复 Compose 中失效的 MinIO 镜像标签。

## 8. Docker 代理检查结果

主机环境：

```text
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
ALL_PROXY=socks5://127.0.0.1:7897
```

Docker daemon 报告的代理地址为 `http.docker.internal:3128`，没有单独的 registry mirror。这是 Docker Desktop 把宿主机代理桥接给 daemon 的内部地址，实际镜像拉取和构建已经成功，不要仅因为端口不是 7897 就改坏它。

## 9. OpenCode 接手建议

接手后先做只读检查，不要重建已完成模块：

```powershell
cd "F:\Project Practice\notebook\notebookagent"
docker compose --profile core --profile graph ps
Invoke-RestMethod http://localhost:8001/health
```

如需看日志：

```powershell
docker compose --profile core --profile graph logs --tail 200 api worker frontend
```

如需重新运行质量检查：

```powershell
cd "F:\Project Practice\notebook\notebookagent\backend"
uv run ruff check .
uv run pytest

cd "F:\Project Practice\notebook\notebookagent\frontend"
npm run build
```

继续开发前建议阅读：

```text
NotebookAgent_项目开发指南.md
NotebookAgent_开发方案.md
NotebookAgent_核心闭环设计.md
NotebookAgent_文件结构与代码架构.md
```

下一步最自然的工作不是再次重写第一版，而是从以下事项中选择：

1. 配置一个真实外部 MCP Server，验证远程 Streamable HTTP 或本地 stdio 的生产配置。
2. 增加更大的中英文论文集，做全文自动分窗和 Citation 完整性评测。
3. 建立 `hybrid` 与 `hybrid_graph` 的固定评测集，比较召回率、引用正确率、时延和成本。
4. 做生产安全加固，例如 Secret 管理、非 root Celery、限流、CORS 和备份恢复。
5. 第一版稳定后再设计跨会话长期 Memory、Subagent 或 MoA，不要提前混入当前 Root Agent Loop。

## 10. 关键横向链路

```text
用户登录
→ 打开 Notebook
→ 上传论文
→ Worker 解析正文
→ MySQL 保存事实与 Chunk
→ SiliconFlow 生成 Embedding
→ Milvus 建 Dense + BM25 索引
→ Neo4j 建 Section / Chunk / Entity 图索引
→ 用户发送 Query 或附带全文文章
→ ContextBuilder 做预算、全文装箱或完整分窗
→ Router 选择候选工具
→ DeepSeek 决定直接回答或 Tool Call
→ Registry 校验 Schema / 权限 / 风险
→ Dispatcher 执行原生工具或 MCP
→ ToolObservation 回填
→ 每轮重新预算并压缩 / Checkpoint / 重新装箱
→ 最终答案 + Citation + ContextManifest 通过 SSE 返回前端
```

第一版的核心判断原则仍然是：

```text
候选工具筛选可以由规则、Embedding Router 或未来 JEV 完成
但最终动作由 DeepSeek Tool Calling 决定
所有工具都必须经过 Registry、Schema、权限、审批和 Dispatcher
RAG、Memory、State、Skills、MCP 是不同层，不能混成同一个“上下文”概念
```
