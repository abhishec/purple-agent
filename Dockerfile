FROM public.ecr.aws/docker/library/python:3.12-slim

# Create non-root user (AgentBeats best practice)
RUN useradd -m -u 1000 agentbeats

WORKDIR /app

COPY --chown=agentbeats:agentbeats requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=agentbeats:agentbeats src/ ./src/
COPY --chown=agentbeats:agentbeats main.py .

USER agentbeats

EXPOSE 9010

# AgentBeats-compatible entrypoint: accepts --host, --port, --card-url
ENTRYPOINT ["python", "main.py"]
CMD ["--host", "0.0.0.0", "--port", "9010"]
