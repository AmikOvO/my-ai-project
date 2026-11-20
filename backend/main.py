import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import chromadb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    PIIMiddleware,
    wrap_model_call,
)
from langchain_community.document_loaders import TextLoader
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

# 1. DeepSeek api key 一律从环境变量读取（服务器 /opt/app/.env），代码里不再保留明文
#    原因：硬编码的 Key 会随仓库公开泄露，被他人盗用产生费用
if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
    print(
        "【警告】未配置 DEEPSEEK_API_KEY。"
        "请在服务器 /opt/app/.env 中写入 DEEPSEEK_API_KEY=sk-xxx 后执行 docker compose up -d。"
    )

DATA_DIR = Path("data")
HISTORY_FILE = Path("chat_history.json")

# 登录账号（考试演示用，真实项目应存数据库并加密）
USERS = {
    "admin": {"password": "123456", "name": "管理员"},
    "kefu01": {"password": "123456", "name": "客服一号"},
}


def ensure_rag_ready():
    """容器里 chroma_db 是空的（已被 .gitignore 排除），启动时自动建库。

    否则第一次 RAG 检索会抛 InvalidCollectionException 直接 500。
    """
    try:
        client = chromadb.PersistentClient(path="chroma_db")
        collection = client.get_or_create_collection("mcp_intro")
        if collection.count() == 0:
            print("【RAG】向量库为空，开始构建…")
            build_vector_store()
        print("【RAG】向量库就绪，共", collection.count(), "个文本块")
    except Exception as exc:  # 兜底：初始化失败也不能让整个服务起不来
        print("【RAG】向量库初始化失败，RAG 检索将降级：", repr(exc))


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_rag_ready()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "企业智能客服 RAG 系统"}


# ---------- 第 2 题 1、2：文档加载、分割与向量化 ----------
def build_vector_store():
    loader = TextLoader("rag_source/mcp_intro.md", encoding="utf-8")
    docs = loader.load()
    print("【1】TextLoader 读取到的原文：\n", docs[0].page_content)

    splitter = RecursiveCharacterTextSplitter(chunk_size=180, chunk_overlap=0)
    chunks = splitter.split_documents(docs)
    for chunk in chunks:
        print("\n--- 文本块 ---")
        print(chunk.page_content)

    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_or_create_collection("mcp_intro")
    for number, chunk in enumerate(chunks, start=1):
        collection.upsert(ids=[str(number)], documents=[chunk.page_content])
    print("\n【2】向量数据库里有", collection.count(), "个文本块")


# ----------  【3】 RAG 检索函数 ----------
def rag_search_func(question):
    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_collection("mcp_intro")
    result = collection.query(query_texts=[question], n_results=2)
    passages = result["documents"][0]
    return "[来源：RAG向量库 mcp_intro.md]\n" + "\n\n".join(passages)


# ---------- 【6】 PII 中间件 ----------
# 内置类型只有 email/credit_card/ip/mac_address/url，手机号与身份证号用正则自定义。
# strategy="mask" 会把 13812345678 变成 ****5678，模型只能看到脱敏后的内容。
pii_middlewares = [
    PIIMiddleware(
        "phone_number",
        detector=r"1[3-9]\d{9}",
        strategy="mask",
        apply_to_input=True,
    ),
    PIIMiddleware(
        "id_card",
        detector=r"\d{17}[\dXx]",
        strategy="mask",
        apply_to_input=True,
    ),
]


# 自定义中间件：打印 PII 处理之后模型真正收到的输入
@wrap_model_call
async def log_masked_input(request, handler):
    last = request.messages[-1] if request.messages else None
    # 只有检测到敏感信息被脱敏时才打印，避免正常对话刷屏
    if isinstance(last, HumanMessage) and "****" in str(last.content):
        print("【PII】模型收到的已是脱敏内容：", last.content)
    return await handler(request)


SENSITIVE_RULE = (
    "如果用户提供了手机号、身份证号并要求查询订单、账号等敏感数据，"
    "只回答：抱歉，出于安全合规要求，无法提供相关信息。"
)

# ---------- 【4】 RAG 优先策略 ----------
# 删除/修改文件这类“要动手”的请求，RAG 里不可能有答案，直接交给带工具的 Agent，
# 否则无限问答模型会自己编“我无法删除文件”，审批流程永远触发不了。
TOOL_INTENT = re.compile(r"删除|删掉|移除|清空|delete", re.IGNORECASE)


def need_mcp(question):
    return bool(TOOL_INTENT.search(question))


async def answer_from_rag(question, history):
    search_question = question
    # 追问可能只说“它”，检索时带上同一用户上一轮的问题。
    if history:
        previous_question = history[-2]["content"]
        search_question = previous_question + "\n" + question
    passages = rag_search_func(search_question)
    agent = create_agent(
        model=ChatDeepSeek(model="deepseek-flash"),
        tools=[],
        system_prompt=(
            "用对话历史理解问题中的指代。"
            "只根据下面的资料回答，并保留资料里的来源标记。"
            "资料不足时，只输出“资料不足”。"
            "如果用户要求删除、修改文件或执行任何操作，也只输出“资料不足”，不要说自己做不到。"
            + SENSITIVE_RULE
            + f"\n资料：\n{passages}"
        ),
        middleware=[*pii_middlewares, log_masked_input],
    )
    messages = history + [{"role": "user", "content": question}]
    result = await agent.ainvoke({"messages": messages})
    return result["messages"][-1].content


# ---------- 【6】 高危操作工具 ----------
@tool
def delete_log_file(file_name: str) -> str:
    """删除 data 目录下的指定文件。调用后系统会自动发起人工审批，直接调用即可，无需向用户确认。"""
    target = DATA_DIR / Path(file_name).name
    if not target.exists():
        return f"文件不存在：{target.name}"
    target.unlink()
    return f"已删除文件：{target.name}"


async def get_mcp_tools():
    client = MultiServerMCPClient({
        "files": {
            "command": sys.executable,
            "args": ["mcp_server.py"],
            "transport": "stdio",
        }
    })
    return await client.get_tools()


# ----------  【5】 + 【6】：MCP Agent 与中间件 ----------
_mcp_agent = None
# HITL 需要 checkpointer 保存中断现场，同一 thread_id 才能恢复执行
_memory = InMemorySaver()

MCP_SYSTEM_PROMPT = (
    "你是企业智能客服，可以读取 data 目录里的补充文档。"
    "先调用 list_project_files 查看文件名，再调用 read_markdown_file 读取需要的文件，"
    "根据读到的内容回答，并在结尾标注 [来源：MCP 文件名]。"
    "用户要求删除 data 目录下的文件时，必须立刻调用 delete_log_file 并把文件名作为参数，"
    "不要去询问用户是否确认，也不要解释审批流程，系统会自动处理人工审批。"
    "只回答当前问题，不要评价之前的回答。" + SENSITIVE_RULE
)


async def get_mcp_agent():
    global _mcp_agent
    if _mcp_agent is None:
        tools = await get_mcp_tools()
        _mcp_agent = create_agent(
            model=ChatDeepSeek(
                model="deepseek-flash",
                extra_body={"thinking": {"type": "disabled"}},
            ),
            tools=[*tools, delete_log_file],
            system_prompt=MCP_SYSTEM_PROMPT,
            middleware=[
                *pii_middlewares,
                log_masked_input,
                # 只有删除文件需要审批，读取类工具直接放行
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "delete_log_file": {"allowed_decisions": ["approve", "reject"]},
                    },
                ),
            ],
            checkpointer=_memory,
        )
    return _mcp_agent


def thread_config(user_id):
    # 同一个用户共用一个 thread，Agent 的记忆（对话上下文）就存在这里
    return {"configurable": {"thread_id": f"mcp-{user_id}"}}


def read_interrupt(result):
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None
    return interrupts[0].value


async def run_mcp_turn(user_id, question):
    agent = await get_mcp_agent()
    # 多轮对话的记忆：同一用户复用同一个 thread_id，历史消息保存在 checkpointer 里，
    # 所以这里只传本轮问题，模型仍能结合上文理解“它”“这个文件”等指代。
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config=thread_config(user_id),
    )
    hitl = read_interrupt(result)
    if hitl:
        action = hitl["action_requests"][0]
        print(f"【HITL】已中断，等待人工审批：{action['name']} {action['args']}")
        return {"status": "pending", "tool": action["name"], "args": action["args"]}
    return {"status": "done", "answer": result["messages"][-1].content}


async def resume_mcp_turn(user_id, decision):
    agent = await get_mcp_agent()
    result = await agent.ainvoke(
        Command(resume={"decisions": [decision]}),
        config=thread_config(user_id),
    )
    return result["messages"][-1].content


# ---------- 对话记录 ----------
user_histories = (
    json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
)
# 待审批的高危操作：user_id -> 提问内容
pending_actions = {}


def save_histories():
    HISTORY_FILE.write_text(
        json.dumps(user_histories, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember(user_id, question, answer):
    history = user_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    save_histories()


async def chat(user_id, question):
    # 还有未处理的高危操作时，先让用户完成审批，避免中断现场被新提问覆盖
    if user_id in pending_actions:
        return {"status": "pending_approval", "answer": "请先处理待审批的删除操作"}
    history = user_histories.setdefault(user_id, [])
    if need_mcp(question):
        print("检测到文件操作请求，直接交给 MCP Agent")
        result = await run_mcp_turn(user_id, question)
    else:
        answer = await answer_from_rag(question, history)
        if not answer.strip().startswith("资料不足"):
            print("使用 RAG 回答")
            remember(user_id, question, answer)
            return {"status": "done", "answer": answer}
        print("RAG 资料不足，转 MCP Agent")
        result = await run_mcp_turn(user_id, question)
    if result["status"] == "pending":
        pending_actions[user_id] = question
        return result
    remember(user_id, question, result["answer"])
    return result


async def approve(user_id, decision):
    if decision not in ("approve", "reject"):
        return {"status": "done", "answer": "无效的审批结果"}
    if user_id not in pending_actions:
        return {"status": "done", "answer": "当前没有待审批的操作"}
    reply = (
        {"type": "approve"}
        if decision == "approve"
        else {"type": "reject", "message": "用户拒绝了该删除操作，请勿重试。"}
    )
    answer = await resume_mcp_turn(user_id, reply)
    question = pending_actions.pop(user_id)
    remember(user_id, question, answer)
    return {"status": "done", "answer": answer}


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    user_id: str
    question: str


class ApproveRequest(BaseModel):
    user_id: str
    decision: str


@app.post("/login")
def login_api(body: LoginRequest):
    user = USERS.get(body.username)
    if not user or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"user_id": body.username, "name": user["name"]}


@app.get("/history/{user_id}")
def history_api(user_id: str):
    # 不同账号只返回自己的对话记录
    return {"messages": user_histories.get(user_id, [])}


def friendly_error(exc: Exception) -> str:
    """把大模型侧的错误翻译成用户能看懂的一句话，避免前端只显示 500。"""
    text = repr(exc)
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return "服务未配置 DEEPSEEK_API_KEY，请在服务器 /opt/app/.env 中配置后重启容器。"
    if "Insufficient Balance" in text or "402" in text:
        return "模型服务调用失败：DeepSeek 账户余额不足（402），请充值或更换 API Key。"
    if "401" in text or "Unauthorized" in text or "invalid_api_key" in text:
        return "模型服务调用失败：DeepSeek API Key 无效（401），请检查 DEEPSEEK_API_KEY 配置。"
    if "Timeout" in text or "timed out" in text:
        return "模型服务调用超时，请稍后重试。"
    return f"模型服务调用失败：{type(exc).__name__}"


@app.post("/chat")
async def chat_api(body: ChatRequest):
    try:
        return await chat(body.user_id, body.question)
    except Exception as exc:  # 模型侧异常不能裸奔成 500
        print("【chat】调用失败：", repr(exc))
        return {"status": "error", "answer": friendly_error(exc)}


@app.post("/approve")
async def approve_api(body: ApproveRequest):
    try:
        return await approve(body.user_id, body.decision)
    except Exception as exc:
        print("【approve】调用失败：", repr(exc))
        return {"status": "error", "answer": friendly_error(exc)}


# ---------- 控制台演示：对应试卷第 2 题各小题 ----------
async def demo():
    print("========== 第 2 题 1、2、3：加载 / 分割 / 向量化 ==========")
    build_vector_store()

    print("\n========== 第 2 题 3：RAG 检索函数 ==========")
    print(rag_search_func("stdio transport的优点是什么？"))

    print("\n========== 第 2 题 4：RAG 优先（不调用 MCP） ==========")
    print(await chat("admin", "stdio transport的优点是什么？"))

    print("\n========== 第 2 题 5：RAG 不足时调用 MCP ==========")
    print(await chat("admin", "MCP协议推荐版本是什么？"))

    print("\n========== 第 2 题 6：PII 脱敏 ==========")
    print(await chat("kefu01", "我的手机号是13812345678，帮我查下订单"))

    print("\n========== 第 2 题 6：HITL 拒绝 ==========")
    await chat("kefu01", "帮我删除 mcp_advanced.md 文件")
    print(await approve("kefu01", "reject"))

    print("\n========== 第 2 题 6：HITL 批准 ==========")
    await chat("kefu01", "帮我删除 mcp_advanced.md 文件")
    print(await approve("kefu01", "approve"))
    print("提示：演示删除后，需要把 data/mcp_advanced.md 恢复，否则第 5 题会读不到文件。")


if __name__ == "__main__":
    asyncio.run(demo())
