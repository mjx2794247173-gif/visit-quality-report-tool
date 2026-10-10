FROM node:24-bookworm-slim

WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
  && rm -rf /var/lib/apt/lists/*

COPY rag/requirements.txt /app/rag/requirements.txt
RUN python3 -m venv /opt/rag-venv \
  && /opt/rag-venv/bin/pip install --no-cache-dir -r /app/rag/requirements.txt

COPY knowledge /app/knowledge
COPY rag /app/rag
RUN /opt/rag-venv/bin/python /app/rag/build_index.py

COPY server /app/server
COPY index.html /app/index.html

ENV PATH="/opt/rag-venv/bin:$PATH"
ENV NODE_ENV=production
EXPOSE 8787
CMD ["sh", "-c", "python -m uvicorn rag.rag_service:app --host 127.0.0.1 --port 8790 & exec node server/server.mjs"]
