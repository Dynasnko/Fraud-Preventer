import sys
import os
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import asyncio
from AllInOneProject.Controller.bridge import agent

def my_callback(step_type, detail):
    print(f"  [CALLBACK] {step_type}: {detail}")

async def main():
    uid = "full_flow_test_001"
    
    # Round 1: 初始問題（會被 interrupt）
    print("=== Round 1: 初始問題 ===")
    resp1 = await agent.ask(uid, "有人說可以幫我投資保證獲利，透過Line聯繫我，要我匯款5萬到他的帳戶，這是詐騙嗎？", on_step=my_callback)
    print(f"Status: {resp1.status}")
    print(f"Response: {resp1.response_text[:200]}")
    
    if resp1.status == "interrupted":
        # Round 2: 回覆追問（走完整 planner → worker → synthesizer）
        print("\n=== Round 2: 補充資訊 ===")
        resp2 = await agent.ask(uid, "事件發生在昨天，對方自稱是投資老師王先生，透過Line聯繫，要求我透過ATM匯款5萬元", is_reply=True, on_step=my_callback)
        print(f"Status: {resp2.status}")
        print(f"Response: {resp2.response_text[:500]}")
    else:
        print(f"(未觸發 interrupt，直接完成)")

if __name__ == "__main__":
    asyncio.run(main())
