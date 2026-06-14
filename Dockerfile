FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pixoo_media ./pixoo_media

# Match the default first-user uid/gid (1000) on most Linux hosts so files
# written to bind-mounted volumes (cache/, logs/) are owned by that user.
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app
USER app

EXPOSE 8090

CMD ["python", "-m", "pixoo_media", "--config", "config.yaml"]
