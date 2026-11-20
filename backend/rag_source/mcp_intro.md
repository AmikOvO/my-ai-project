# MCP传输协议介绍
MCP 即 Model Context Protocol，是标准化LLM工具调用协议。

## stdio transport
本地子进程通信模式。MCP Server作为子进程启动，通过标准输入输出收发JSON消息。
优点：部署简单、不需要端口、本地安全隔离；缺点：只能本机调用，不支持跨机器访问。
适合：Claude Code本地插件。

## streamable http transport
新一代网络传输方案，单统一端点/mcp，支持SSE流式+普通POST请求。
优点：支持远程跨机器、容器、多客户端并发；缺点：需要网络、需要鉴权。
替代旧版独立SSE transport。

## SSE（旧版，已逐步废弃）
老版本MCP网络方案，双端点设计，一个POST发请求，一个SSE长连接接收返回。
新项目不推荐使用。