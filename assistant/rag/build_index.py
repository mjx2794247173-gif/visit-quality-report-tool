from rag_service import get_collection

if __name__ == "__main__":
    store = get_collection()
    print(f"RAG 索引完成，共 {store.count()} 个知识片段")
