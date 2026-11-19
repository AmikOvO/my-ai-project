# 技能 2 参考答案：自研 MCP 服务 + LangChain 中间件的企业智能客服 RAG 系统

## 一、项目结构

```
two/
├── backend/                 # LangChain 后端 + MCP 服务
│   ├── main.py              # 第 2 题：RAG、Agent、PII / HITL 中间件、FastAPI 接口
│   ├── mcp_server.py        # 第 1 题：FastMCP + stdio，两个文件读取工具
│   ├── data/                # 补充文档（MCP 读取，不进 RAG 库）
│   │   └── mcp_advanced.md
│   ├── rag_source/          # 主知识库（RAG 检索）
│   │   └── mcp_intro.md
│   ├── chroma_db/           # 向量数据库
│   ├── requirements.txt
│   └── test_main.http
└── frontend/                # Vue3 + Element Plus
    ├── src/views/LoginView.vue   # 登录页
    ├── src/views/ChatView.vue    # 聊天页 + 审批卡片
    ├── src/api/request.js
    ├── src/router/index.js
    └── src/stores/user.js
```

## 二、运行方式

后端（先装依赖，Python 3.13）：

```bash
cd two/backend
pip install -r requirements.txt
python main.py            # 控制台依次演示第 2 题各小题
uvicorn main:app --port 8000   # 启动接口服务
```

前端：

```bash
cd two/frontend
npm install
npm run dev               # http://localhost:5173
```

演示账号：`admin / 123456`、`kefu01 / 123456`（不同账号的对话记录互相独立）。

注意：HITL 演示会真实删除 `data/mcp_advanced.md`，演示完需要把文件恢复（内容与 `one/backend/data/mcp_advanced.md` 相同），否则第 5 题读取不到文档。

## 三、题目与代码对照

| 题目 | 实现位置 |
| --- | --- |
| 第 1 题 `list_project_files` | `mcp_server.py`：`Path("data").glob("*.md")`，只返回 md 文件名、不递归 |
| 第 1 题 `read_markdown_file` | `mcp_server.py`：超过 5000 字符截断并追加提示 |
| 第 2 题 1 加载与分割 | `main.py: build_vector_store()`，`TextLoader` + `RecursiveCharacterTextSplitter` |
| 第 2 题 2 向量化与存储 | `main.py: build_vector_store()`，`chromadb.PersistentClient` 写入 `chroma_db` |
| 第 2 题 3 `rag_search_func` | `main.py: rag_search_func()`，结果带 `[来源：RAG向量库 mcp_intro.md]` |
| 第 2 题 4 RAG 优先 | `main.py: chat()`，先问 RAG，只有回答“资料不足”才转 MCP；删除类请求用 `need_mcp()` 关键词直接路由到 MCP（否则 RAG 会自己说“我无法删除文件”，审批永远触发不了） |
| 第 2 题 5 按需调用 MCP | `main.py: run_mcp_turn()`，Agent 自动 `list_project_files` + `read_markdown_file` |
| 第 2 题 6 PII 中间件 | `main.py: pii_middlewares`（手机号 / 身份证号正则 + `mask`）、`log_masked_input` 打印脱敏结果 |
| 第 2 题 6 HITL 中间件 | `main.py: delete_log_file` + `HumanInTheLoopMiddleware` + `InMemorySaver`，`/approve` 恢复执行 |
| 第 3 题 1 聊天页面 | `ChatView.vue`：消息区 + 输入框 + 发送按钮，用户靠左、模型靠右 |
| 第 3 题 2、3 两种提问 | 前端直接提问即可，来源标记由后端返回 |
| 第 3 题 4 审批卡片 | `ChatView.vue` 的 `.approve-card`，批准 / 拒绝分别调 `/approve` |

## 四、接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/login` | 账号密码登录，返回 `user_id`、`name` |
| GET | `/history/{user_id}` | 该账号自己的对话记录 |
| POST | `/chat` | 提问。正常返回 `{"status":"done","answer":...}`；触发高危操作时返回 `{"status":"pending","tool":...,"args":...}` |
| POST | `/approve` | 人工审批，`decision` 取 `approve` / `reject`，恢复被中断的 Agent 并返回最终回答 |

## 五、中间件工作流程

1. 用户提问先经 `PIIMiddleware`：手机号 `13812345678` → `****5678`，身份证号同样只保留后 4 位；模型只看到脱敏后的文本，日志会打印实际输入。
2. 涉及查询敏感数据时，按系统提示词统一回复“抱歉，出于安全合规要求，无法提供相关信息”。
3. 命中 `delete_log_file` 时，`HumanInTheLoopMiddleware` 通过 LangGraph 的 `interrupt` 暂停 Agent，接口把待审批动作返回前端。
4. 前端点“批准”/“拒绝”后调 `/approve`，后端用 `Command(resume={"decisions": [...]})` 在同一个 `thread_id` 上恢复执行：批准则真正删除文件，拒绝则把拒绝结果作为工具消息交回模型。
