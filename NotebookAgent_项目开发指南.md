# NotebookAgent 项目开发指南

> 目标：从当前第一版代码出发，按横向数据流理解和验收网页版论文研究Agent。每一步都回答“为什么做 → 哪些文件 → 文件职责 → 数据怎么流 → 怎么验收”。

## 先记住一条主线

```text
上传论文
→ Celery解析、分块、Embedding、图索引
→ 用户提交Query与全文附件
→ Context Builder装箱或完整分窗
→ DeepSeek决定直接回答或Tool Call
→ Registry校验、审批、执行
→ Observation回填下一轮
→ Evidence/Citation回答
→ SSE展示并保存Checkpoint
```

## 第1步：配置与Docker基础

### 为什么做

模型密钥、数据库地址和上下文窗口不能散落在代码里。先统一配置，后面的API、Worker和容器才会使用同一套参数。

### 涉及哪些文件

```text
.env.example
backend/app/core/config.py
docker-compose.yml
backend/Dockerfile
frontend/Dockerfile
frontend/nginx.conf
```

### 每个文件负责什么

- `.env.example`：列出DeepSeek、SiliconFlow、MySQL、Redis、Milvus、Neo4j配置；真实密钥复制到`.env`。
- `config.py`：Pydantic Settings读取环境变量，并计算有效输入预算。
- `docker-compose.yml`：编排core服务和可选graph Profile。
- 两个Dockerfile：分别构建FastAPI/Celery运行镜像和Vue静态站点。
- `nginx.conf`：将`/api`与`/mcp`转发到FastAPI。

第一版以Docker为唯一承诺运行方式：`.env`中的`mysql/redis/milvus/neo4j`主机名和`/app/...`配置路径是容器内路径，不要求同一份配置直接在Windows宿主机启动后端。

### 横向数据流

```text
.env
→ Settings
→ FastAPI / Celery / Provider / Retrieval共享

浏览器
→ Nginx :3000
→ /api 或 /mcp
→ FastAPI :8001
```

### 完成后怎么验收

```powershell
Copy-Item .env.example .env
docker compose --profile core --profile graph config --quiet
```

命令应退出0；`.env`不能提交版本库。

## 第2步：认证、Notebook与MySQL真相源

### 为什么做

研究资料必须属于确定用户和Notebook。权限边界先建立，Tool和MCP才不会跨Notebook读取。

### 涉及哪些文件

```text
backend/app/models.py
backend/app/schemas.py
backend/app/core/database.py
backend/app/core/security.py
backend/app/api/auth.py
backend/app/api/notebooks.py
backend/app/api/conversations.py
```

### 每个文件负责什么

- `models.py`：定义User、Notebook、DocumentVersion、Chunk、Conversation、AgentRun、Evidence、Citation等表。
- `schemas.py`：校验注册、登录、Run和审批参数。
- `database.py`：只提供异步SQLAlchemy Session。
- `security.py`：scrypt密码哈希和JWT签发/解析。
- `auth.py`：注册、登录、刷新令牌。
- `notebooks.py`：Notebook CRUD、资料列表和上传。
- `conversations.py`：创建对话和`summary/full/off`资源状态。

### 横向数据流

```text
注册/登录 → JWT
JWT → get_current_user
→ Notebook.owner_id校验
→ Document.notebook_id校验
→ 才允许读取或运行Agent
```

### 完成后怎么验收

- A用户不能读取B用户Notebook。
- 密码列中没有明文。
- MySQL保存完整原文的字段使用LONGTEXT，不受普通TEXT约64KB限制。
- 第一版表中不存在长期Memory、Subagent或MoA模型。

## 第3步：论文上传、解析与分块

### 为什么做

模型不能直接理解PDF二进制。必须先提取文本，同时保留页码和字符范围，后续引用才可回链。

### 涉及哪些文件

```text
backend/app/api/notebooks.py
backend/app/ingestion/parser.py
backend/app/ingestion/chunker.py
backend/app/ingestion/profile.py
backend/app/prompts/profile.py
backend/app/ingestion/tasks.py
backend/app/celery_app.py
```

### 每个文件负责什么

- 上传接口保存原始文件并创建`IngestionJob`。
- `parser.py`提取PDF文本层或读取TXT/MD，生成页码范围；multipart丢失文件名且标为`application/octet-stream`时，仅对可解码UTF-8正文做安全回退。
- `chunker.py`按段落优先切片，保存`char_start/end`和`page_start/end`。
- `chunker.py`同时识别Section；Neo4j写入`DocumentVersion → Section → Chunk`结构。
- `profile.py`+`prompts/profile.py`：抽取标题/作者/年份/关键词/摘要/研究地区等原始信息，并用DeepSeek生成结构化概要（一句话、数据与方法、结果与结论、创新与不足），写入`document_profiles`与论文画像向量；摘要缺失标记`generated`。
- `tasks.py`：Milvus写入后立即把文档标`ready`，再投递独立`build_graph_index`任务建图；图任务失败只记`graph_status=failed`，不影响文档可用。前端资料行显示「处理中 / 图谱构建中 / 可检索 / 图谱失败」，图完成或失败时弹出非阻塞提示。
- `tasks.py`执行异步摄取、写MySQL和索引；Celery每次`asyncio.run`结束前释放异步数据库连接池，避免下一任务复用旧事件循环连接。
- `celery_app.py`连接Redis队列，启用重试和晚确认。

### 横向数据流

```text
UploadFile
→ 文件存储
→ DocumentVersion.pending
→ Celery ingest_document
→ ParsedDocument
→ ChunkDraft
→ MySQL full_text + chunks
```

### 完成后怎么验收

- 文本PDF状态最终为`ready`。
- 扫描PDF没有文本层时明确报需要OCR，不生成空索引。
- 首Chunk从0开始，末Chunk到全文结尾，每个Chunk有来源版本和页码。

## 第4步：Milvus混合检索与Neo4j GraphRAG

### 为什么做

Dense适合语义近似，BM25适合术语和精确词，Neo4j适合“方法—数据集—指标—论文”的关系问题。三者互补，但最终都必须回到MySQL原文Chunk。

### 涉及哪些文件

```text
backend/app/providers/siliconflow.py
backend/app/retrieval/milvus.py
backend/app/retrieval/neo4j_store.py
backend/app/retrieval/fusion.py
backend/app/retrieval/service.py
backend/app/ingestion/graph_extract.py
```

### 每个文件负责什么

- `siliconflow.py`：BGE-M3 Embedding和bge-reranker-v2-m3重排。
- `milvus.py`：1024维Dense字段、内置BM25 Sparse字段与混合检索；Milvus 2.6的multi-analyzer字段不同时开启`enable_match`，并按真实主键名`chunk_id`解析搜索命中。
- `neo4j_store.py`：节点约束、有证据关系写入和1～2跳扩展。
- `fusion.py`：RRF去重融合。
- `service.py`：实现四种`retrieval_mode`和图故障降级。
- `graph_extract.py`：图抽取入口；每条关系绑定当前证据Chunk。

### 横向数据流

```text
query → BGE-M3向量
→ 文档层: 在论文画像(标题+关键词+完整摘要+结构化概要)中筛选Top10论文
→ Chunk层: 候选论文内 Milvus Dense Top30 + BM25 Top30
→ 可选Neo4j chunk_id
→ RRF
→ SiliconFlow Rerank
→ 带document_id/chunk_id/section/page的Evidence
```

### 完成后怎么验收

- `hybrid`和`hybrid_graph`分别可评测。
- 相同Chunk不会重复返回，`sources`记录命中来源。
- Neo4j关闭时仍能回答，并返回`graph_degraded=true`。
- 图关系没有有效`evidence_chunk_ids`时不能进入最终Evidence。

## 第5步：论文级Query上下文

### 为什么做

当前附件是用户明确要求处理的材料，不能先变成Top-K，也不能只处理开头。物理窗口不够时，Runtime要完整分窗而不是静默截断。

### 涉及哪些文件

```text
backend/app/agent/types.py
backend/app/agent/context_builder.py
backend/app/prompts/agent.py
backend/tests/test_context_builder.py
```

### 每个文件负责什么

- `types.py`：`QueryEnvelope、AttachmentPayload、AttachmentWindow、ContextManifest`。
- `context_builder.py`：动态预算、单消息全文装箱、连续分窗和每层Token估算。
- `prompts/agent.py`：集中保存Root、全文/窗口、引用映射和汇总Prompt Builder。
- 测试：验证预算内全文、95%阈值分窗、中文窗口不超预算、超窗无空洞、每窗重复原始任务。

### 横向数据流

```text
原始Query + 附件ID/指令
→ 从MySQL读取active DocumentVersion.full_text
→ 估算有效输入预算
→ single packet 或 N个window packets
→ DeepSeek逐包处理
→ 汇总所有窗口结论
```

### 完成后怎么验收

```powershell
Set-Location backend
uv run pytest tests/test_context_builder.py -q
```

关键断言：拼接所有窗口正文必须与原文完全相同，相邻`char_end == 下一窗char_start`。

## 第6步：Tool Registry、Router与六个业务工具

### 为什么做

模型只能提议调用工具；是否存在、参数是否合法、能否执行必须由后端决定。工具增多后不能每轮塞入全部Schema。

### 涉及哪些文件

```text
backend/app/agent/router.py
backend/app/tools/registry.py
backend/app/tools/native.py
```

### 每个文件负责什么

- `router.py`：定义可被JEV替换的`RouterProvider`，默认使用SiliconFlow Embedding筛选最多12个候选，失败时确定性降级。
- `registry.py`：保存工具摘要、完整Schema、风险、参数校验和Dispatcher。
- `native.py`：六个业务工具与三个Harness工具的参数模型和处理器。

### 横向数据流

```text
短Tool Catalog
→ RouterProvider.select_tools
→ 最多12个完整Schema
→ DeepSeek tool_call
→ Registry校验
→ Dispatcher
→ ToolObservation
```

### 完成后怎么验收

- 不存在的工具返回`tool_not_found`。
- 参数错误返回`invalid_arguments`。
- 每轮Schema数量不超过12。
- `tool_search`命中的工具会被提升到下一轮候选前部，不会因12个上限再次被截掉。
- JEV只能替换候选选择，不能直接执行工具。

## 第7步：Root Agent Loop、SSE与Checkpoint

### 为什么做

一次LLM调用只是聊天；能够在工具结果后继续思考、暂停审批、断线续读和恢复，才是完整Agent Runtime。

### 涉及哪些文件

```text
backend/app/providers/deepseek.py
backend/app/agent/runtime.py
backend/app/agent/events.py
backend/app/agent/tasks.py
backend/app/api/agent_runs.py
```

### 每个文件负责什么

- `deepseek.py`：解析流式文本和碎片化Tool Call参数。
- `runtime.py`：最多10轮Root Loop、全文窗口汇总；每轮调用`ContextCompactor`按0.6/0.75重估并压缩上下文，多Tool Call逐个配对Observation，审批后从`pending_batch`继续；结束时把与LLM同构的消息写入`run_transcripts`，`_history`按会话拼接最近若干Run的transcript。
- `events.py`：RunEvent写MySQL，同时尽力发布Redis。
- `tasks.py`：Celery执行Agent Run。
- `agent_runs.py`：创建、SSE、Manifest、取消、重试和审批API。

### 横向数据流

```text
POST Run → Celery
→ context packets
→ DeepSeek
→ tool_calls
→ Observation
→ Checkpoint
→ 下一轮
→ final answer
→ SSE run_completed
```

### 完成后怎么验收

- SSE断开后可用`Last-Event-ID`续读。
- 写工具暂停为`waiting_approval`。
- 拒绝后ToolCall状态为rejected且无外部调用。
- Run完成后有最终Message、RunEvent和Checkpoint。
- 一次返回多个Tool Call时，每个调用都有对应`role=tool`消息；超过单轮3个的调用明确标为未执行。

## 第8步：MCP Client与Server

### 为什么做

MCP让新工具通过配置接入，也让外部Agent复用NotebookAgent的只读研究能力，但两边都必须经过同一权限边界。

### 涉及哪些文件

```text
config/mcp_servers.yaml
config/mcp_expose.yaml
backend/app/mcp_runtime/client_manager.py
backend/app/mcp_runtime/server.py
backend/app/api/runtime_config.py
```

### 每个文件负责什么

- `mcp_servers.yaml`：外部Server、transport、环境变量密钥、白名单和默认风险。
- `mcp_expose.yaml`：NotebookAgent向外暴露的只读工具白名单。
- Client Manager：环境变量展开、stdio/Streamable HTTP、发现、调用、资源读取。
- Server：`POST /mcp`工具实现；调用前解码令牌并校验Notebook所有权。
- Runtime API：查看、测试和Reload。

### 横向数据流

```text
Reload → MCP capability discovery
→ mcp.server.tool短目录
→ DeepSeek选择
→ 风险检查/审批
→ MCP call
→ ToolObservation
```

### 完成后怎么验收

- YAML中没有真实密钥。
- 新Server Reload后可发现且命名无冲突。
- 未声明风险的工具按write审批。
- `/mcp`携带A用户令牌时不能读取B用户Notebook。

## 第9步：配置式Skills

### 为什么做

Skill是可复用工作方法，不应全部常驻系统提示词，也不应借声明工具来扩大权限。

### 涉及哪些文件

```text
config/skills.yaml
skills/literature-review/SKILL.md
backend/app/skills/catalog.py
```

### 每个文件负责什么

- `skills.yaml`：根目录和启用ID。
- `SKILL.md`：Frontmatter元数据、允许工具和完整研究指令。
- `catalog.py`：校验重复ID、描述、版本和未知工具，按需加载正文，并安全解析不能逃出Skill目录的`references/`静态资料。

### 横向数据流

```text
启动/Reload
→ 扫描SKILL.md
→ System只放短摘要
→ DeepSeek调用load_skill
→ 返回正文
→ allowed_tools ∩ 用户权限
```

### 完成后怎么验收

- 修改配置Reload后新Skill可见。
- 未调用`load_skill`前完整正文不进入上下文。
- Skill声明未知工具时Reload失败。
- Skill不能获得用户原本没有的工具权限。

## 第10步：Vue研究工作台

### 为什么做

后端能力需要一个可观察界面：用户要看到资料状态、选择全文附件、Agent实时输出和审批请求。

### 涉及哪些文件

```text
frontend/src/api.ts
frontend/src/views/LoginView.vue
frontend/src/views/NotebooksView.vue
frontend/src/views/WorkspaceView.vue
frontend/src/views/PaperSearchView.vue
frontend/src/style.css
```

### 每个文件负责什么

- `api.ts`：Axios JWT和fetch SSE解析。
- `LoginView`：注册/登录。
- `NotebooksView`：创建和进入Notebook。
- `WorkspaceView`：上传、全文附件选择、恢复已有对话、发送Query、实时Run轨迹、审批和Evidence Rail。
- `PaperSearchView`：检索OpenAlex元数据、查看详情并把选中的论文信息带入研究对话。
- `style.css`：统一研究型视觉语言、三栏工作台、移动端重排、可见焦点和减少动态效果偏好。

### 横向数据流

```text
用户勾选ready文档
→ attachment_ids + instructions
→ 创建Run
→ fetch SSE
→ text_delta / tool_call / approval_required / run_completed
→ 页面更新
```

### 完成后怎么验收

```powershell
Set-Location frontend
npm install
npm run build
```

构建应生成`dist/`且TypeScript无错误。

## 第11步：总验收与运行顺序

### 为什么做

单元模块通过不代表完整链路可用。最后必须区分“代码级验证”和“需要真实密钥/容器的集成验证”。

### 涉及哪些文件

```text
backend/tests/
docker-compose.yml
Makefile
```

### 每个文件负责什么

- 测试目录覆盖分窗、路由、Skill权限、RRF、摄取范围和认证。
- Compose启动MySQL、Redis、Milvus依赖、Neo4j、API、Worker和前端。
- Makefile提供`test / lint / up / up-graph`。

### 横向数据流

```text
静态检查与单测
→ 前端生产构建
→ Compose语法检查
→ core Profile冒烟
→ core + graph真实密钥端到端
```

### 完成后怎么验收

```powershell
docker compose --profile core --profile graph config --quiet
docker compose --profile core --profile graph up -d --build
docker compose --profile core --profile graph ps
```

静态检查和20项自动化测试属于开发验收；正式运行只依赖Docker镜像，不要求宿主机安装Python或Node。

最终人工链路：

```text
注册登录
→ 创建Notebook
→ 上传论文并等待ready
→ 确认Milvus与Neo4j索引
→ 勾选论文作为全文附件
→ 提交研究Query
→ 观察Tool Call / Skill / GraphRAG
→ 如有写MCP工具完成审批
→ 得到带页码或文本范围引用的回答
→ 查询ContextManifest确认全文覆盖
```

另外检查`http://localhost:3000`三个主场景：登录/注册、Notebook研究对话、论文搜索；检查`http://localhost:8001/health`返回健康状态。

## 第一版完成与后续边界

当前第一版代码已经包含Root Agent、全文分窗、混合检索、Neo4j、MCP、Skills、审批、Checkpoint、SSE和Docker结构。长期Memory、Subagent、MoA、CLI仍是后续独立功能，不能为了“看起来完整”提前混入当前闭环。
