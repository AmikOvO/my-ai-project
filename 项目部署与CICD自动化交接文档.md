# 项目部署与 CI/CD 自动化交接文档

> 更新时间：2026-11-20
> 仓库：`https://github.com/AmikOvO/my-ai-project`（分支 `main`）
> 服务器：阿里云 ECS `47.95.28.173`（华北2，Ubuntu 22.04，2核1.7G），部署目录 `/opt/app`
> **线上地址：http://47.95.28.173（已可访问，容器 healthy）**

---

## 一、当前状态：已上线 ✅

| 项 | 状态 |
|----|------|
| 前端页面 | ✅ `http://47.95.28.173` 200 |
| 前后端联调 `/api` | ✅ 200，返回 `{"message":"企业智能客服 RAG 系统"}` |
| 登录接口 | ✅ 200（admin/123456） |
| RAG 向量库 | ✅ 启动时自动建库，日志 `【RAG】向量库就绪，共 4 个文本块` |
| 容器健康 | ✅ backend / frontend 均 healthy |
| CI/CD | ✅ push 到 main 自动部署成功（GitHub Actions 绿色） |
| 大模型对话 | ❌ **DeepSeek 账户余额不足（402 Insufficient Balance）**，需充值或换 Key |

> 最后一步只差钱：接口链路已全部打通，模型侧返回 402。见第五节如何换 Key。

**部署方式已从「GitHub 构建 + ACR」改为「GitHub 传源码 + ECS 本地构建」**，原因见第三节。

---

## 二、本轮修复清单（14 项，全部已验证）

| # | 问题 | 后果 | 修复 |
|---|------|------|------|
| 1 | `backend/requirements.txt` 是 **UTF-16LE** 编码 | `pip install` 100% 失败：`Invalid requirement: '\x00a\x00i\x00o...'` | 转 UTF-8 + LF |
| 2 | `requirements.txt` 含 **`pywin32==312`**（Windows 专属包，来自本地 pip freeze） | Linux 镜像构建报 `No matching distribution found for pywin32==312` | 移除（本次实测就卡在这里） |
| 3 | 前端 `baseURL: 'http://127.0.0.1:8000'` 写死 | 线上用户浏览器去请求**自己电脑**的 8000 端口，登录/对话全挂 | 改为 `/api`，由 nginx 反代；vite 增加 dev 代理 |
| 4 | axios `timeout: 5000` | 大模型首字普遍 >5s，对话必然超时 | 120s（nginx 提高到 300s） |
| 5 | 前端镜像 `node:18` 但 `engines ^22.18` + vite 8 | `npm run build` 报错 | 换 `node:22-alpine` + `npm ci` |
| 6 | 缺 `.dockerignore` | Windows 的 `node_modules` 覆盖进容器，原生模块变体不匹配 | 新增前后端 `.dockerignore` |
| 7 | 后端镜像 `python:3.10`，依赖却是 3.13 环境导出 | wheel 不匹配 | 换 `python:3.13-slim` |
| 8 | `rag_source/` 被 `.gitignore` 排除 | 镜像里没有 RAG 源文件 | 纳入版本控制 |
| 9 | `chroma_db/` 不在镜像，首次 RAG 查询必 500 | `InvalidCollectionException` | `main.py` 增加 lifespan 启动钩子自动建库 |
| 10 | chromadb 首次 embedding 要联网下载 ONNX 模型，国内 ECS 拉不动 | RAG 不可用 | 模型（88MB）预先放在 `/opt/app/chroma-model`，以只读卷挂进容器 |
| 11 | `compose` 里 `env_file: .env` | 服务器缺 `.env` 时 compose 直接退出（本地 `.env` 是 0 字节） | 去掉强依赖，改可选变量注入 |
| 12 | 部署链路依赖服务器上手工存在的 compose 文件，而 `/opt/app` 实际是**空的** | 即使 ACR 通了，`docker compose pull` 也会报没有配置文件 | 部署时自动同步源码/compose |
| 13 | 模型侧异常直接抛 500 | 前端只显示「请求失败」 | 后端捕获并返回可读原因（402/401/超时） |
| 14 | CI 打包 `tar` 输出到仓库目录内 | tar 读到自己，退出码 1，流水线直接失败 | 归档写到 `/tmp` |
| 15 | 构建步骤 `command_timeout: 30m` | 2核机首次构建（1.3GB 依赖）需 >30 分钟，被中断 | 放宽到 60m，并拆成「构建」「启动」两步 |

新增文件：`.github/workflows/deploy-on-ecs.yml`、`.github/workflows/acr-diagnose.yml`、`docker-compose.build.yml`、`.env.example`、`.gitattributes`、前后端 `.dockerignore`。

---

## 三、关于 403 Forbidden：结论已有实证

原始报错：`login attempt to https://registry.cn-beijing.aliyuncs.com/v2/ failed with status: 403 Forbidden`

上一轮的猜测（改密码、改账号名、RAM AccessKey）**方向都是错的**——它们解决的是 401，不是 403。

本轮用流水线自动抓取到的实证：

```
token_http=200 | 凭证有效，登录被网络层拦截
realm=https://dockerauth.cn-hangzhou.aliyuncs.com/auth
service=registry.aliyuncs.com:cn-beijing:26842
resp={"access_token":"***...            ← 阿里云鉴权服务已签发 token
```

也就是说：**用户名密码完全正确、鉴权服务也认了、token 都发下来了**，但拿着 token 访问 registry 时被拒。这只能是网络层/访问控制层面的拦截（GitHub 托管 Runner 在境外，其动态 IP 被 ACR 的公网访问控制挡掉，或该个人版实例不允许境外直连）。

因此本项目改为 **ECS 本地构建**，彻底绕开这条跨境链路：
- 优点：不再依赖 ACR，构建走国内网络（阿里云 PyPI 源 + npmmirror），镜像层缓存在服务器上，改了代码二次构建只要 1-2 分钟
- 代价：构建占用 ECS 的 CPU/内存（首次约 25 分钟；期间站点会略慢）

如果以后仍想用 ACR 方案（比如买了国内 self-hosted runner），把 `.github/workflows/deploy.yml` 的 `on: workflow_dispatch` 改回 `push: branches: [main]` 即可，那个工作流已经写好并在诊断中验证过预检/重试逻辑。

**补充：ACR 上的镜像仓库可以改回私有了。** 11/19 曾把 `amiko-project/backend`、`amiko-project/frontend` 设为「公开」来绕 403，但公开/私有与 403 无关（403 是公网访问控制/IP 层）。
现在的自动部署完全不经过 ACR，备用 ACR 工作流的 push 和服务器 pull 都带了 `docker login`，所以改私有不影响任何链路。
建议：ACR 控制台 → 制品仓库 → 操作列点「置为私有」；
若这两个仓库里推送过 11/20 之前的镜像（当时 Key 还硬编码在 `main.py`），镜像层里带着旧 Key，公开期间可被匿名拉取 —— 建议一并删除这些旧镜像。

---

## 四、现在的部署方式

```
本地 git push → GitHub Actions
   ├─ 打包源码（排除 .git / node_modules / dist）→ scp 到 /opt/app
   ├─ SSH 执行 docker compose -f docker-compose.yml -f docker-compose.build.yml build
   ├─ docker compose up -d
   └─ 冒烟检查（首页 200 / /api 200 / 容器健康 / 打印后端日志）
```

服务器目录结构：

```
/opt/app
├── backend/  frontend/  .github/        # 每次部署覆盖
├── docker-compose.yml                   # 生产编排（镜像名 + 资源限制）
├── docker-compose.build.yml             # 覆盖层：改为本地构建 + 国内 PyPI 源
└── chroma-model/all-MiniLM-L6-v2/onnx/  # 向量模型（88MB，一次性上传，不进仓库）
```

> `chroma-model` 不在仓库里，也不随部署覆盖。若误删，执行
> `scp -r ~/.cache/chroma/onnx_models/all-MiniLM-L6-v2 deployer@47.95.28.173:/opt/app/chroma-model/`
> 重新上传（模型已在本地缓存）。

手动部署一次（不等 CI）：

```bash
ssh deployer@47.95.28.173
cd /opt/app
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

---

## 五、如何恢复对话功能（DeepSeek 余额）

两种都行：

**A. 给原 Key 充值**（最简单）— 到 DeepSeek 控制台充值后立即生效，无需重启。

**B. 换一个新 Key**（不用重新打镜像）：

```bash
ssh deployer@47.95.28.173
cd /opt/app
echo 'DEEPSEEK_API_KEY=sk-你的新key' > .env     # compose 会自动读取该文件做变量替换
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d
docker exec my_backend printenv DEEPSEEK_API_KEY   # 确认已注入
```

> 代码中**已删除硬编码 Key**，只认环境变量；服务器 `/opt/app/.env` 已写入当前 Key（600 权限，不进仓库）。
> 切记：该 Key 此前明文提交在 **GitHub 公开仓库**（`AmikOvO/my-ai-project`，2026-11-20 10:37 由提交 `84adb6e 公开仓库` 转为 public）里，
> **必须去 DeepSeek 控制台轮换**，否则任何人都能拿它刷额度。注意：这里说的是 GitHub 仓库，与阿里云 ACR 的仓库可见性无关。

---

## 六、上线验收结果

| 检查项 | 实际结果 |
|--------|----------|
| `curl http://47.95.28.173/` | 200 |
| `curl http://47.95.28.173/api/` | 200 `{"message":"企业智能客服 RAG 系统"}` |
| `POST /api/login` admin/123456 | 200 `{"user_id":"admin","name":"管理员"}` |
| `POST /api/chat` RAG 问句 | 200，返回「DeepSeek 余额不足」可读提示（链路已通，卡在额度） |
| `docker inspect my_backend` | `healthy` |
| 后端启动日志 | `【RAG】向量库就绪，共 4 个文本块` |

余额恢复后，再按试卷题目问一遍即可：
- 「stdio transport的优点是什么？」→ 应带 `[来源：RAG向量库 mcp_intro.md]`
- 「MCP协议推荐版本是什么？」→ 应走 MCP 工具，带 `[来源：MCP ...]`
- 「帮我删除 mcp_advanced.md」→ 应触发人工审批

---

## 七、回滚 / 重跑

```bash
# 回滚到某个提交并重新部署
git revert <sha> && git push origin main     # 触发自动部署

# 或在服务器上直接重建（不动代码）
cd /opt/app && docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

查看失败原因：Actions 页面 → 运行记录 → 「ECS 构建失败」注解里会直接带构建日志末尾；也可 `ssh deployer@47.95.28.173 'tail -50 /tmp/build.log'`。

---

## 八、已知遗留（不影响本次上线）

1. **DeepSeek 余额不足**（唯一功能阻塞，见第五节）。
2. 早期版本把 API Key 明文写在 `main.py` 并提交进了 **GitHub 公开仓库** —— 本轮已从代码移除并改为 `.env` 注入，但**历史提交里仍然存在**，务必轮换 Key。
3. 对话历史与审批现场存在进程内存（`InMemorySaver`），容器重启即丢失；`chat_history.json` 打在镜像里，写入不持久。
4. 登录账号明文硬编码（考试演示用）；CORS 为 `allow_origins=["*"]` + `allow_credentials=True`，属不规范组合。
5. `云端部署项目背景.md` 与本文档重复，可删。
6. 后端镜像 1.38GB，主要来自 chromadb + onnxruntime + langchain；如需瘦身可考虑多阶段构建或换轻量 embedding 方案。
