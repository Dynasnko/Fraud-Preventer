import threading

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from AllInOneProject.Agent.tools.tools import sync_165_data_on_startup, analyze_scam_database
from AllInOneProject.Agent.tools.sync_law_data import sync_law_data_on_startup
from AllInOneProject.Agent.tools.data_analysis_tools import compute_statistics, generate_chart
from AllInOneProject.Model.state import MultiState
from AllInOneProject.Agent.rag_builder import MultiAgentRAGBuilder
from AllInOneProject.Agent import HumanRequirementNode, PlannerNode, WorkerNode, SynthesizerNode, ComposerNode

def build_chat_flow() -> StateGraph:
    #詐騙案例資料同步
    try:
        sync_165_data_on_startup()
    except Exception as e:
        print(f"⚠️ 資料同步工具發生未預期錯誤，略過同步: {e}")

    #法規資料庫同步
    try:
        sync_law_data_on_startup()
    except Exception as e:
        print(f"⚠️ 法規資料同步發生未預期錯誤，略過同步: {e}")
    
    rag = MultiAgentRAGBuilder()
    rag.ensure_example_data()
    config = rag.build_or_load()
    worker_map = config["worker_map"]
    stores = config["stores"]
    merged_store = config.get("merged_store")

    # 大型 FAISS 索引（防詐騙專家、_merged）延遲載入以加速啟動，這裡另外在背景
    # 執行緒預熱，避免啟動後第一個剛好用到它們的真實對話要等索引反序列化。
    # 一次只暖一個：索引若與 SQLite 筆數不符會觸發從頭重建（百萬筆規模時需要數 GB
    # 記憶體），若多個大型 store 同時重建會疊加記憶體用量，曾在 OOM 下被系統核心
    # kill 掉整個 process（啟動後看起來像是自動停止）。改成單一背景執行緒依序暖。
    _stores_to_warm = [
        _store for _store in list(stores.values()) + [merged_store]
        if _store is not None and hasattr(_store, "warm")
    ]

    def _warm_all(warm_stores):
        for _store in warm_stores:
            try:
                _store.warm()
            except Exception as e:
                print(f"⚠️ [Warm] 索引預熱失敗，略過: {e}")

    if _stores_to_warm:
        threading.Thread(target=_warm_all, args=(_stores_to_warm,), daemon=True).start()

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    requirement = HumanRequirementNode("requirement", llm=llm)
    planner = PlannerNode("planner", llm=llm, worker_map=worker_map)
    synthesizer = SynthesizerNode("synthesizer", llm=llm)
    composer = ComposerNode("composer", llm=llm, worker_map=worker_map)

    builder = StateGraph(MultiState)
    builder.add_node("requirement", requirement.execute)
    builder.add_node("planner", planner.execute)
    builder.add_node("synthesizer", synthesizer.execute)
    builder.add_node("composer", composer.execute)

    _SCAM_WORKER_ID = "worker_防詐騙專家"
    _DATA_ANALYST_WORKER_ID = "worker_數據分析專家"
    for wid, db in stores.items():
        if wid == _SCAM_WORKER_ID:
            tools = [analyze_scam_database]
        elif wid == _DATA_ANALYST_WORKER_ID:
            tools = [analyze_scam_database, compute_statistics, generate_chart]
        else:
            tools = []
        node = WorkerNode(wid, llm=llm, db=db, tools=tools,
                          description=worker_map.get(wid, ""))
        builder.add_node(wid, node.execute)

    internet_node = WorkerNode("internet_search", llm=llm, db=merged_store)
    builder.add_node("internet_search", internet_node.execute)

    builder.add_edge(START, "requirement")
    builder.add_edge("requirement", "planner")

    def route_workers(state: MultiState):
        tasks = state.get("variables", {}).get("tasks_to_execute", [])
        if not tasks: return "synthesizer"
        return [t["worker_id"] for t in tasks]

    valid_destinations = list(worker_map.keys()) + ["internet_search", "synthesizer"]
    builder.add_conditional_edges("planner", route_workers, valid_destinations)

    for wid in worker_map.keys():
        builder.add_edge(wid, "composer")
    builder.add_edge("internet_search", "composer")

    def route_composer(state: MultiState):
        variables = state.get("variables", {})
        if variables.get("composer_decision", "pass") != "retry":
            return "synthesizer"
        tasks = variables.get("tasks_to_execute", [])
        if not tasks:
            return "synthesizer"
        return [t["worker_id"] for t in tasks]

    valid_composer_destinations = list(worker_map.keys()) + ["internet_search", "synthesizer"]
    builder.add_conditional_edges("composer", route_composer, valid_composer_destinations)

    builder.add_edge("synthesizer", END)

    return builder.compile(checkpointer=MemorySaver())
