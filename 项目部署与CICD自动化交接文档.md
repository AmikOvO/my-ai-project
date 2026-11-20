# 项目部署与 CI/CD 自动化交接文档

> 更新时间：2026-11-20
> 仓库：`https://github.com/AmikOvO/my-ai-project`（分支 `main`）
> 服务器：阿里云 ECS `47.95.28.173`（华北2，Ubuntu 22.04），部署目录 `/opt/app`

## 一、当前状态

上一轮交接卡在 `docker login` 报 `403 Forbidden`。本轮排查发现：**除了这个 403，代码和镜像构建配置里还有 6 处必然导致后续失败的问题**，已全部修复（详见第二节）。修完之后，整条链路只剩下「ACR 从 GitHub 网络侧不可达」这一个外部因素需要你在控制台处理。

---

## 二、本轮修复清单

| # | 问题 | 后果 | 修复 |
|---|------|------|------|
| 1 | `backend/requirements.txt` 是 **UTF-16LE** 编码（不是 UTF-8） | `pip install -r requirements.txt` 100% 失败：`Invalid requirement: '\x00a\x00i\x00o...'`。这是 403 修好后的**第一个拦路虎** | 转成 UTF-8 + LF，123 个包完整保留 |
| 2 | `frontend/src/api/request.js` 写死 `baseURL: 'http://127.0.0.1:8000'` | 线上用户的浏览器会去请求**自己电脑**的 8000 端口，登录/对话全部挂掉 | 改为 `import.meta.env.VITE_API_BASE \|\| '/api'`，走 nginx 反代 |
| 3 | `timeout: 5000` | 大模型首字生成普遍 >5s，对话必然超时 | 改 120s（nginx 侧同步放到 300s） |
| 4 | 前端 `Dockerfile` 用 `node:18-alpine`，但 `package.json` 要求 `^22.18`，vite 8 不支持 Node 18 | `npm run build` 直接报错 | 换 `node:22-alpine` + `npm ci` |
| 5 | 没有 `.dockerignore` | 本地 Windows 的 `node_modules` 被 `COPY . .` 覆盖进容器，rollup/esbuild 原生模块变体不匹配，报 `Cannot find module @rollup/rollup-linux-x64-gnu` | 新增 `frontend/.dockerignore`、`backend/.dockerignore` |
| 6 | `backend/rag_source/` 被 `.gitignore` 排除；`chroma_db/` 也没进镜像 | CI checkout 出来的代码里**没有 RAG 源文件**，首次 RAG 检索抛 `InvalidCollectionException` → `/chat` 500 | `rag_source` 纳入版本控制；`main.py` 增加 lifespan 启动钩子，向量库为空时自动建库 |
| 7 | 后端 `Dockerfile` 用 `python:3.10-slim`，但依赖是 3.13 环境导出的（`numpy 2.5.4`/`chromadb 1.5.9` 等） | 大概率找不到匹配 wheel 或解析失败 | 换 `python:3.13-slim`；构建时预热 chromadb 默认向量模型，避免 ECS 上首次 embedding 联网下载超时 |
| 8 | `docker-compose.yml` 里 `env_file: .env` | 服务器上 `.env` 一旦不存在，compose 直接报错退出（本地 `.env` 是 0 字节空文件，也没进仓库） | 去掉强依赖，改为可选变量注入 |
| 9 | 部署脚本假设服务器上已有正确版本的 `docker-compose.yml` | 仓库改了 compose 但服务器还是旧的 | 部署时自动 `scp` 覆盖 |
| 10 | 部署时拉取镜像**没有登录**（个人版仓库默认私有） | `docker compose pull` 报 unauthorized/403 | 服务器端部署前先 `docker login` |
| 11 | 镜像只有 `:latest`，无版本号 | 无法回滚 | 同时推送 `:<7位sha>`，compose 支持 `IMAGE_TAG` 指定版本 |
| 12 | 无资源限制 | 2核2G 上前端+后端+chromadb 可能被 OOM Killer 干掉 | 后端 `mem_limit 1300m`、前端 `128m`，日志轮转 10m×3 |

新增文件：
- `.github/workflows/acr-diagnose.yml`：**手动触发**的 ACR 连接诊断（专门解决 403）
- `docker-compose.build.yml`：兜底方案，绕开 ACR 直接在 ECS 上构建
- `.env.example`、`backend/.dockerignore`、`frontend/.dockerignore`

---

## 三、关于 403 Forbidden：一个关键结论

**403 几乎不可能是密码错。** Docker Registry 的语义是：

- 凭证错误 → `401 Unauthorized` / `incorrect username or password`
- 请求被网络层或 ACL 拦截 → `403 Forbidden`

本轮实测（国内网络）：

```
$ curl -i https://registry.cn-beijing.aliyuncs.com/v2/
HTTP/1.1 401 Unauthorized
Www-Authenticate: Bearer realm="https://dockerauth.cn-hangzhou.aliyuncs.com/auth",
                          service="registry.aliyuncs.com:cn-beijing:26842"
```

说明：域名可达、仓库服务正常、通用域名 `registry.cn-beijing.aliyuncs.com` 没有被废弃。

结合「本地同样凭证能登录成功」这一事实，唯一变量就是**请求来源 IP**：GitHub 托管 Runner 在境外（Azure），而你的本地在国内。

因此上一轮交接里的「任务 2（改密码）」「任务 3（改账号名）」「任务 4（RAM 子账号 AccessKey）」**都解决不了 403**——它们解决的是 401。RAM AccessKey 只适合替代固定密码做鉴权，换不掉 IP 白名单。

---

## 四、还剩 3 件事需要你在控制台/本地操作

### 第 1 步（最可能直接解决）关闭 ACR 公网访问控制

阿里云 ACR 控制台 → 选华北2(北京) → 目标实例/命名空间 → 左侧 **访问控制** → 检查 **公网访问入口 / 公网访问控制白名单**：

- 若开启且填了具体 IP → 关闭它，或把白名单改成 `0.0.0.0/0`（GitHub Runner 的 IP 是动态的，逐个放行不可维护）
- 同时确认「仓库属性」不是仅限 VPC 访问

### 第 2 步 用诊断工作流拿到实证

仓库 Actions 页面 → 左侧 **ACR 连接诊断（手动触发）** → Run workflow。

它会打印：Runner 出口 IP、`/v2/` 匿名响应、用你的凭证换 token 的结果、`docker login` 详细输出、以及 SSH 到 ECS 的连通性。判读方式：

- token 接口返回 200 且有 token，但 `docker login` 仍 403 → **确定是 IP/ACL 拦截**，回到第 1 步或走兜底方案
- token 接口返回 401 → 才是凭证问题（此时才需要重置密码 / 换 RAM AccessKey）
- SSH 步骤失败 → 与 ACR 无关，单独查安全组和密钥

### 第 3 步 提交并触发部署

```bash
cd D:/Projects/practice/two
git add -A
git commit -m "fix: 修复镜像构建与前后端联调问题，加固 CI/CD 流水线"
git push origin main
```

push 后流水线顺序：预检 → 登录 ACR → 构建推送 backend/frontend（`latest` + `sha`）→ scp compose → 服务器 pull/up → 冒烟检查。

> 如果第 1 步之后仍 403，最稳的方案是**在 ECS 上装 GitHub self-hosted runner**（构建发生在国内，推送 ACR 走内网 `-vpc` 域名，速度快且不受跨境限制）；
> 更省事的临时方案是第五节「兜底构建」。

---

## 五、兜底方案：完全绕开 ACR

在服务器上执行：

```bash
# 2核2G 构建 chromadb 依赖容易 OOM，先加 swap
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

cd /opt/app
git clone https://github.com/AmikOvO/my-ai-project.git . 2>/dev/null || git pull
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

可用性验证：`curl -I http://127.0.0.1/`、`docker compose ps`。

---

## 六、上线后验收清单

| 检查项 | 命令 / 操作 | 期望 |
|--------|-------------|------|
| 前端可访问 | 浏览器打开 `http://47.95.28.173` | 出现登录页 |
| 后端反代通 | `curl -s http://47.95.28.173/api/` | `{"message":"企业智能客服 RAG 系统"}` |
| 登录 | admin / 123456 | 进入对话页，无 F12 报错 |
| RAG 链路 | 问「stdio transport的优点是什么？」 | 回答带 `[来源：RAG向量库 mcp_intro.md]` |
| RAG 建库日志 | `docker logs my_backend \| head -40` | 出现 `【RAG】向量库就绪，共 N 个文本块` |
| MCP 链路 | 问「MCP协议推荐版本是什么？」 | 回答带 `[来源：MCP ...]` |
| 容器健康 | `docker inspect -f '{{.State.Health.Status}}' my_backend` | `healthy` |

## 七、回滚

```bash
cd /opt/app
IMAGE_TAG=<上一个 7 位 sha> docker compose up -d
# 或
IMAGE_TAG=latest docker compose up -d
```

## 八、已知遗留（不影响本次上线）

1. `backend/main.py` 里 DeepSeek API Key 硬编码（现已支持环境变量覆盖，建议在服务器 `/opt/app/.env` 配 `DEEPSEEK_API_KEY=` 后删掉代码里的默认值）。**该 Key 已进入 Git 历史和公开仓库，建议去 DeepSeek 控制台轮换。**
2. 对话历史/审批现场存在进程内存（`InMemorySaver`），容器重建即丢失；`chat_history.json` 打在镜像里，不可持久化写入。
3. 登录账号明文硬编码（考试演示用）。CORS 为 `allow_origins=["*"]` + `allow_credentials=True`，属于不规范组合。
4. `云端部署项目背景.md` 与本文档内容重复，可删。
