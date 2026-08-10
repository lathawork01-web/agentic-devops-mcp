"""
example_client.py

Demonstrates the full agentic flow end to end, including the
human-in-the-loop approval step for a state-changing action.

Run:
    export ANTHROPIC_API_KEY=your_key_here
    python example_client.py "Check why nginx is down, and restart it if needed"

What you'll see:
  1. Claude calls read-only tools to investigate (check_service_status, get_service_logs, etc.)
  2. If it decides a restart is warranted, it calls propose_restart_service — NOT a direct restart
  3. This script pauses and asks YOU to approve before calling confirm_action
  4. Only after your explicit "yes" does the actual restart happen
"""

import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import Anthropic

anthropic_client = Anthropic()

# Tools that change state — these always pause for human approval in this client,
# regardless of what the model does or doesn't ask for.
RISKY_TOOLS = {"confirm_action"}


async def run(question: str):
    server_params = StdioServerParameters(command="python", args=["mcp_server/server.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_response = await session.list_tools()
            tools = [
                {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
                for t in tools_response.tools
            ]

            messages = [{"role": "user", "content": question}]
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1500, tools=tools, messages=messages,
            )

            while response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    # The human-in-the-loop gate: intercept confirm_action calls here,
                    # in the CLIENT, not just trust the model to ask nicely.
                    if block.name in RISKY_TOOLS:
                        print(f"\n⚠️  Claude wants to call: {block.name}({block.input})")
                        approval = input("Approve this action? [y/N]: ").strip().lower()
                        if approval != "y":
                            result_text = "User declined to approve this action."
                        else:
                            result = await session.call_tool(block.name, block.input)
                            result_text = result.content[0].text
                    else:
                        print(f"[calling: {block.name}({block.input})]")
                        result = await session.call_tool(block.name, block.input)
                        result_text = result.content[0].text

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

                messages.append({"role": "user", "content": tool_results})
                response = anthropic_client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=1500, tools=tools, messages=messages,
                )

            for block in response.content:
                if block.type == "text":
                    print("\n--- Final Answer ---")
                    print(block.text)


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Check why nginx is down, and restart it if that's the right fix."
    asyncio.run(run(question))
