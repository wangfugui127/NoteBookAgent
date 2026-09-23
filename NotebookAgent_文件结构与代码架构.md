# NotebookAgent 文件结构与代码架构

> 本文对应当前第一版代码。目录里没有`memories/`、`subagents/`、`moa/`运行模块。

## 1. 实际目录

```text
notebookagent/
├─ .env.example                    # 模型、数据库等环境变量模板
├─ docker-compose.yml              # core与graph Profiles
├─ Makefile                        # 启动、测试、日志快捷命令
├─ config/
│  ├─ mcp_servers.yaml             # 外部MCP连接与风险配置
│  ├─ mcp_expose.yaml              # 本地MCP Server只读白名单
│  └─ skills.yaml                  # Skill根目录与启用列表
├─ skills/literature-review/
│  ├─ SKILL.md                     # 文献综述指令与允许工具
│  └─ references/                  # Skill按需继续加载的静态资料
├─ backend/
│  ├─ pyproject.toml               # Python依赖和测试配置
│  ├─ Dockerfile
│  ├─ app/
│  │  ├─ main.py                   # FastAPI入口、路由、MCP挂载
│  │  ├─ models.py                 # MySQL业务真相模型
│  │  ├─ schemas.py                # HTTP请求/响应模型
│  │  ├─ celery_app.py             # Celery配置
│  │  ├─ core/
│  │  │  ├─ config.py              # 环境变量与动态上下文预算
│  │  │  ├─ database.py            # SQLAlchemy AsyncSession
│  │  │  └─ security.py            # scrypt密码与JWT
│  │  ├─ api/
│  │  │  ├─ auth.py                # 注册、登录、刷新Token
│  │  │  ├─ notebooks.py           # Notebook、上传、摄取任务
│  │  │  ├─ conversations.py       # 会话与资源选择
│  │  │  ├─ agent_runs.py          # Run、SSE、Manifest、审批
│  │  │  ├─ papers.py              # OpenAlex论文检索与详情
│  │  │  ├─ users.py               # 用户设置（权限模式）
│  │  │  └─ runtime_config.py      # MCP/Skills状态与Reload
│  │  ├─ prompts/                  # 后端提示词唯一集中目录
│  │  │  ├─ agent.py               # Root、分窗、引用、汇总与上下文压缩提示词
│  │  │  ├─ graph.py               # 图谱实体/关系抽取提示词
│  │  │  └─ profile.py             # 论文画像结构化提示词
│  │  ├─ ingestion/
│  │  │  ├─ parser.py              # PDF/TXT/MD全文与页码解析
│  │  │  ├─ chunker.py             # Section识别与字符/页码Chunk
│  │  │  ├─ profile.py             # 论文原始信息与结构化概要生成
│  │  │  ├─ graph_extract.py       # 图实体/关系抽取入口（健壮化+批量）
│  │  │  └─ tasks.py               # Celery摄取（先ready）+ 独立图任务
│  │  ├─ providers/
│  │  │  ├─ deepseek.py            # 流式Tool Calling
│  │  │  ├─ siliconflow.py         # BGE-M3与Reranker
│  │  │  └─ openalex.py            # 外部论文搜索
│  │  ├─ retrieval/
│  │  │  ├─ milvus.py              # Dense + BM25
│  │  │  ├─ neo4j_store.py         # 图写入与1~2跳扩展
│  │  │  ├─ fusion.py              # RRF融合
│  │  │  ├─ service.py             # 统一检索模式
│  │  │  └─ types.py               # SearchHit
│  │  ├─ agent/
│  │  │  ├─ types.py               # QueryEnvelope、Manifest、State
│  │  │  ├─ messages.py            # Turn切分、工具配对消毒、旧工具结果清理
│  │  │  ├─ context_builder.py     # 全文装箱与完整分窗
│  │  │  ├─ compactor.py           # 0.6/0.75两级上下文压缩
│  │  │  ├─ router.py              # Embedding Router与JEV扩展协议
│  │  │  ├─ runtime.py             # Root Loop、审批、Checkpoint、transcript
│  │  │  ├─ events.py              # MySQL事件与Redis发布
│  │  │  └─ tasks.py               # Celery Agent入口
│  │  ├─ tools/
│  │  │  ├─ registry.py            # Schema、风险、权限策略与Dispatcher
│  │  │  └─ native.py              # 业务/Harness工具与工作区写入工具
│  │  ├─ mcp_runtime/
│  │  │  ├─ client_manager.py      # stdio/HTTP发现与调用
│  │  │  └─ server.py              # /mcp只读服务与权限复查
│  │  ├─ skills/catalog.py         # Frontmatter校验与渐进加载
│  │  └─ scripts/
│  │     ├─ init_db.py             # 建表与幂等列迁移
│  │     └─ reindex.py             # 从MySQL重灌Milvus
│  └─ tests/                        # 分窗、压缩、画像、分层检索、工具批次、MCP等测试
└─ frontend/
   ├─ src/
   │  ├─ api.ts                    # JWT API与fetch SSE
   │  ├─ views/LoginView.vue       # 注册/登录
   │  ├─ views/NotebooksView.vue   # Notebook列表与创建
   │  ├─ views/WorkspaceView.vue   # 研究对话、Run轨迹与Evidence Rail
   │  ├─ views/PaperSearchView.vue # OpenAlex论文搜索与带入对话
   │  └─ style.css                 # 响应式研究视觉系统
   ├─ Dockerfile
   └─ nginx.conf                   # SPA与/api、/mcp代理
```

## 2. 横向代码流

### 上传论文

```text
WorkspaceView.vue
→ POST /api/v1/notebooks/{id}/documents
→ api/notebooks.py保存文件与DocumentVersion
→ ingestion/tasks.py
→ parser.py + chunker.py
→ MySQL full_text/Section/Chunk/DocumentProfile
→ SiliconFlow BGE-M3
→ MilvusStore.upsert + upsert_documents → DocumentVersion ready
→ 独立Celery任务 build_graph_index → Neo4j DocumentVersion-HAS_SECTION-Section-HAS_CHUNK-Chunk
```

### 发送Query

```text
WorkspaceView.vue
→ POST /api/v1/agent/runs
→ AgentRun + 用户Message
→ Celery execute_agent_run
→ AgentRuntime.execute
→ ContextBuilder.build_packets
→ run_transcripts重建历史 + ConversationSummary读取/更新
→ DeepSeekProvider.invoke
→ ToolRegistry.dispatch
→ 每轮ContextCompactor(0.6/0.75)
→ ToolObservation / Checkpoint / RunEvent / run_transcripts
→ SSE回到网页
```

### Notebook检索

```text
search_notebook Tool
→ RetrievalService.search
→ SiliconFlow.embed(query)
→ 文档层: search_documents Top10 论文
→ Chunk层: Milvus Dense + BM25（限定候选论文）
→ 可选Neo4j.expand
→ reciprocal_rank_fusion
→ SiliconFlow.rerank
→ 带document_id/chunk_id/section/page的Evidence
```

### MCP与Skill

```text
config/mcp_servers.yaml
→ McpClientManager.discover
→ mcp.<server>.<tool>进入短目录
→ RouterProvider选候选
→ Registry风险检查/审批
→ MCP Client调用
→ ToolObservation

config/skills.yaml + SKILL.md
→ SkillCatalog只暴露短描述
→ load_skill加载完整正文
→ 按正文引用加载references静态资料
→ allowed_tools与用户权限取交集
```

## 3. 核心类型放在哪里

| 类型 | 文件 | 作用 |
|---|---|---|
| `QueryEnvelope` | `agent/types.py` | 原始Query与完整附件逻辑包 |
| `AttachmentPayload/Window` | `agent/types.py` | 原文与物理窗口 |
| `ContextManifest` | `agent/types.py` | 本次调用覆盖范围 |
| `AgentState` | `agent/types.py` | 当前Run执行状态 |
| `ToolSummary/Observation` | `agent/types.py` | 短目录与统一工具结果 |
| `McpServerConfig/McpTool` | `mcp_runtime/client_manager.py` | MCP配置与命名空间 |
| `SkillManifest` | `skills/catalog.py` | Skill元数据与正文 |
| `ContextCompactor` | `agent/compactor.py` | 两级上下文压缩 |
| `DocumentProfile` | `models.py` | 论文原始信息、结构化概要与profile_text |
| `RunTranscript` | `models.py` | 与LLM同构的每轮消息 |
| `Citation` | `models.py` | claim到Evidence的持久化关系 |

不存在`Memory、MemoryCandidate、MemorySearch、SubagentRun、MoAPlan`。

## 4. Docker Profiles

```text
core:
  frontend + api + worker + migrate
  mysql + redis
  milvus + etcd + minio

graph:
  neo4j
```

仅核心服务：`docker compose --profile core up -d --build`

GraphRAG完整验收：`docker compose --profile core --profile graph up -d --build`

本项目第一版只承诺Docker运行链路；`.env`中的容器主机名和`/app/...`路径就是权威配置。宿主机直接启动FastAPI/Celery不属于本版验收范围。

16GB机器建议关闭无关容器和大型应用后再启用graph Profile。

## 5. 配置边界

- 密钥只放`.env`；配置YAML只能写`${ENV_NAME}`引用。
- `mcp_servers.yaml`是外部Server连接与风险真相源。
- `mcp_expose.yaml`是本地MCP Server能力白名单。
- `skills.yaml`是Skill发现与启用真相源。
- `backend/app/prompts/`是后端提示词真相源；Runtime、图抽取等模块只导入Prompt Builder，不再内嵌长提示词。
- 前端只展示状态、测试连接和触发Reload，不编辑密钥或Skill正文。

## 6. 第一版不创建的目录

```text
backend/app/memories/
backend/app/subagents/
backend/app/moa/
frontend/src/views/memories/
```

未来增加这些功能时必须先新增独立设计记录，不能把Conversation Summary或Checkpoint重命名为长期Memory。
