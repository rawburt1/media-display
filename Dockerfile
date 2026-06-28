FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mediainfo ./mediainfo

# Match the default first-user uid/gid (1000) on most Linux hosts so files
# written to bind-mounted volumes (cache/, logs/) are owned by that user.
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app
USER app

EXPOSE 8090

# Liveness check: the process is alive and Flask is serving requests.
# Uses /health/live (always returns 200 OK as long as the app is running)
# rather than /health (readiness: reports per-source/output status), so
# external-source failures (Apple TV offline, Plex unreachable, etc.) do
# not trigger container restarts. Requires outputs.web (or outputs.config /
# outputs.info / outputs.feed / outputs.video) to be enabled in config.yaml;
# if no HTTP output is active there is no listener on any port and this
# check will fail — disable it in that case with HEALTHCHECK NONE in a
# docker-compose.yml override.
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health/live', timeout=5)"

CMD ["python", "-m", "mediainfo", "--config", "config.yaml"]
