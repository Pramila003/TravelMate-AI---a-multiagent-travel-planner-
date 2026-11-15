import os
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
import certifi
from dotenv import load_dotenv


os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

load_dotenv()

tavily_api_key=os.getenv("TAVILY_API_KEY")

client=MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={tavily_api_key}"
        },
    }
)

async def get_all_tool():
    tools=await client.get_tools()
    for tool in tools:
        print(tool.name)
        
tavily_search_tool=None

async def get_tavily_search_tool():
    global tavily_search_tool
    if tavily_search_tool is not None:
        return
    
    tools=await client.get_tools()
    for tool in tools:
        print(tool.name)
    
    tavily_search_tool = next(
            tool
            for tool in tools
            if tool.name == "tavily_search"
        )


async def tavily_mcp_search(query:str):
    await get_tavily_search_tool()
    result = await tavily_search_tool.ainvoke(
        {
            "query": query
        }
    )
    # return result
    print(result)
    