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

# Mark the container unhealthy if the web output stops responding or if any
# source hasn't been polled in over 120 seconds (signals a stuck polling loop).
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,json,sys; r=urllib.request.urlopen('http://localhost:8090/health',timeout=5); d=json.load(r); ago=d.get('source_last_polled_ago',{}); sys.exit(0 if not ago or max(ago.values())<120 else 1)"

CMD ["python", "-m", "mediainfo", "--config", "config.yaml"]
