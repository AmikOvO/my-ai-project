import asyncio
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("项目文件工具")

@mcp.tool()
def list_project_files():
    names = []
    for file in Path("data").glob("*.md"):
        if file.is_file():
            names.append(file.name)
    return names

@mcp.tool()
def read_markdown_file(file_path: str):
    text = Path("data", file_path).read_text(encoding="utf-8")
    if len(text) > 5000:
        return text[:5000] + "文件过长，内容已截断"
    return text


if __name__ == "__main__":
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        print(tool.name, file=sys.stderr)
    mcp.run(transport="stdio")
