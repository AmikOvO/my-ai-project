# MCP 高级特性 

Streamable HTTP支持会话隔离，支持多客户端并发连接。 stdio模式不支持多客户端，每次连接需要新建子进程，资源开销更大。 MCP协议版本 0.3.0 起正式推荐Streamable HTTP作为远程传输方案。