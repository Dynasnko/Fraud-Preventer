import sys
import os
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import asyncio
from AllInOneProject.Controller.bridge import agent

async def main():
    print("Testing agent...")
    try:
        resp = await agent.ask("user_123", "這是不是詐騙？")
        print("Response:", resp.response_text)
        print("Status:", resp.status)
        if hasattr(resp, "planner_thought"):
            print("Thought:", resp.planner_thought)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
