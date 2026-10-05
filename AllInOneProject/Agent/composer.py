import json
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, SystemMessage
from AllInOneProject.Agent.base_node import AgentNode
from AllInOneProject.Model.state import MultiState

_NEGATIVE_PHRASES = ("查無", "找不到", "無相關", "查不到", "無資料")

class ComposerNode(AgentNode):
    def __init__(self, node_id: str, llm: Any, worker_map: Dict[str, str]):
        self.worker_map = worker_map
        super().__init__(node_id, llm=llm)

    def _get_local_instructions(self) -> str:
        return ""

    def _is_insufficient(self, results: List[Dict]) -> bool:
        insufficient = False
        for r in results:
            wid = r.get("worker_id", "?")
            score = r.get("confidence_score", 1.0)
            missing = (r.get("missing_info") or "").strip()
            content = r.get("content", "")
            neg_hit = next((p for p in _NEGATIVE_PHRASES if p in content), None)

            grounding = r.get("grounding") or {}

            reasons = []
            # 依據等級由系統檢查引用得出（見 worker.assess_grounding），比 LLM 自評的分數可靠
            if grounding.get("level") == "ungrounded":
                reasons.append(f"無依據（{grounding.get('reason', '')}）")
            if score < 0.5:
                reasons.append(f"confidence_score={score:.2f} < 0.5")
            if missing:
                reasons.append(f"missing_info=「{missing[:60]}」")
            if neg_hit:
                reasons.append(f"content 含否定詞「{neg_hit}」")

            if reasons:
                print(f"   ⚠️  [{wid}] 品質不足 → {' | '.join(reasons)}")
                insufficient = True
            else:
                print(f"   ✅ [{wid}] 品質通過（依據={grounding.get('level', '?')}，score={score:.2f}，無 missing_info，無否定詞）")
        return insufficient

    def _fix_worker_id(self, raw_id: str, valid_ids: set) -> str | None:
        """Return corrected ID or None if invalid."""
        if raw_id in valid_ids:
            return raw_id
        potential = f"worker_{raw_id}"
        if potential in valid_ids:
            return potential
        return None

    def execute(self, state: MultiState) -> Dict[str, Any]:
        variables = state.get("variables", {})
        retry_count = variables.get("retry_count", 0)
        worker_results = state.get("worker_results", [])

        print(f"\n--- [Composer] 評估中（第 {retry_count + 1} 輪）---")

        # 強制放行條件
        if retry_count >= 2:
            print("   ✅ [Composer] 已達最大重試次數，強制放行")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": "達最大重試次數"}}

        if not worker_results:
            print("   ✅ [Composer] 無 worker 結果，強制放行")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": "無 worker 結果"}}

        # 快速判斷：所有結果都夠好 → 不必呼叫 LLM
        print(f"   🔍 [Composer] 快速品質檢查（{len(worker_results)} 個 worker）：")
        if not self._is_insufficient(worker_results):
            print("   ✅ [Composer] 全部通過，直接放行（不呼叫 LLM）")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": "所有 worker 結果品質足夠"}}

        # 呼叫 LLM 進行深度評估並生成精煉查詢
        results_summary = json.dumps(
            [
                {
                    "worker_id": r.get("worker_id"),
                    "confidence_score": r.get("confidence_score"),
                    "grounding": {
                        "level": (r.get("grounding") or {}).get("level"),
                        "reason": (r.get("grounding") or {}).get("reason"),
                    },
                    "missing_info": r.get("missing_info"),
                    "content_preview": (r.get("content") or "")[:300],
                }
                for r in worker_results
            ],
            ensure_ascii=False,
            indent=2,
        )

        system_msg = SystemMessage(content=(
            "你是一個 AI 品質評估員，負責評估多個 Worker 的回答是否足夠回應使用者需求。\n"
            "請輸出嚴格符合以下 JSON 格式的結果（不要有任何額外文字）：\n"
            "{\n"
            '  "is_sufficient": true 或 false,\n'
            '  "reasoning": "評估理由（繁體中文）",\n'
            '  "refined_tasks": [\n'
            '    {"worker_id": "worker_XXX", "query": "精煉後查詢", "reasoning": "補強理由"}\n'
            "  ]\n"
            "}\n"
            "若 is_sufficient 為 true，refined_tasks 可為空陣列。\n"
            "只針對信心不足或缺少資訊的 Worker 生成精煉任務。\n"
            "grounding.level 為系統檢查引用後的依據等級（grounded 有依據 / partial 部分依據 / ungrounded 無依據），"
            "比 confidence_score（模型自評）更可靠；ungrounded 代表回答缺乏可驗證的參考資料支持。"
        ))

        human_msg = HumanMessage(content=(
            f"【Worker 評估摘要】\n{results_summary}\n\n"
            "請評估以上回答是否足夠，若不足請提供精煉後的查詢策略。"
        ))

        print("   🤖 [Composer] 呼叫 LLM 進行深度評估...")
        raw = self._invoke_and_parse_json([system_msg, human_msg])

        # LLM 解析失敗 → 放行
        if not raw:
            print("   ⚠️ [Composer] LLM 解析失敗，強制放行")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": "LLM 解析失敗"}}

        is_sufficient = raw.get("is_sufficient", True)
        reasoning = raw.get("reasoning", "")
        refined_tasks_raw = raw.get("refined_tasks", [])

        print(f"   📊 [Composer] LLM 評估結果：is_sufficient={is_sufficient}")
        print(f"      reasoning : {reasoning}")
        if refined_tasks_raw:
            print(f"      refined_tasks ({len(refined_tasks_raw)} 筆)：")
            for t in refined_tasks_raw:
                print(f"        - [{t.get('worker_id')}] {t.get('query', '')[:80]}")

        if is_sufficient:
            print("   ✅ [Composer] LLM 判定足夠，放行")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": reasoning}}

        # 修正 worker_id
        valid_ids = set(self.worker_map.keys()) | {"internet_search"}
        refined_tasks = []
        for t in refined_tasks_raw:
            raw_id = (t.get("worker_id") or "").strip()
            fixed_id = self._fix_worker_id(raw_id, valid_ids)
            if fixed_id is None:
                print(f"   ⚠️ [Composer] 無效 worker_id 跳過: {raw_id}")
                continue
            refined_tasks.append({
                "worker_id": fixed_id,
                "query": t.get("query", ""),
                "reasoning": t.get("reasoning", ""),
            })

        # 清理後無有效任務 → 放行
        if not refined_tasks:
            print("   ✅ [Composer] 精煉任務清理後為空，強制放行")
            return {"variables": {"composer_decision": "pass", "composer_reasoning": "無有效精煉任務"}}

        print(f"   🔄 [Composer] 觸發重試（retry_count: {retry_count} → {retry_count + 1}），精煉任務：")
        for t in refined_tasks:
            print(f"      - [{t['worker_id']}] {t['query'][:80]}")
        return {
            "worker_results": "RESET",
            "variables": {
                "tasks_to_execute": refined_tasks,
                "retry_count": retry_count + 1,
                "composer_decision": "retry",
                "composer_reasoning": reasoning,
            },
        }
