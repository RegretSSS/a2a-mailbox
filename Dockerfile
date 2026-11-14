FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir 'fastmcp>=4,<5'
COPY common/ /app/common/
COPY mcp/ /app/mcp/
COPY hub/ /app/hub/
ENV A2A_MAILBOX_ROOT=/data/mailbox
VOLUME ["/data"]
ENTRYPOINT ["python3", "/app/mcp/mailbox_mcp.py"]
