import asyncio 
from tests.mcp_client_tavily import get_all_tool,tavily_mcp_search

if __name__ =="__main__":
    # asyncio.run(get_all_tool())
    query="Tell me about ai"
    asyncio.run(tavily_mcp_search(query))