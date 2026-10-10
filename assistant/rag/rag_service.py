from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
DB_PATH = Path(__file__).resolve().parent / "chroma_db"
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
app = FastAPI(title="Quality Bulletin RAG")
collection = None

class Query(BaseModel):
    question: str
    top_k: int = 4

def get_collection():
    global collection
    if collection is not None:
        return collection
    import chromadb
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection = client.get_or_create_collection("quality_bulletin_knowledge", metadata={"hnsw:space": "cosine"})
    if collection.count() == 0:
        chunks, ids, metas = [], [], []
        for file in sorted(KNOWLEDGE.glob("*.md")):
            parts = [part.strip() for part in file.read_text(encoding="utf-8").split("\n#") if part.strip()]
            for index, part in enumerate(parts):
                chunks.append(part); ids.append(f"{file.name}-{index}"); metas.append({"source": file.name})
        if chunks:
            embeddings = model.encode(chunks, normalize_embeddings=True).tolist()
            collection.add(ids=ids, documents=chunks, metadatas=metas, embeddings=embeddings)
    app.state.model = model
    return collection

@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME}

@app.post("/retrieve")
def retrieve(query: Query):
    store = get_collection()
    embedding = app.state.model.encode([query.question], normalize_embeddings=True).tolist()
    result = store.query(query_embeddings=embedding, n_results=max(1, min(query.top_k, 12)))
    docs = result.get("documents", [[]])[0]; metas = result.get("metadatas", [[]])[0]
    return {"results": [{"text": text, "source": meta.get("source", "") if meta else ""} for text, meta in zip(docs, metas)]}
