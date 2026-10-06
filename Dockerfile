FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 FLASK_APP=wsgi.py
WORKDIR /srv

# Python packages. Three ways to get them (the build picks automatically):
#  1. a folder named "wheels" next to this file (downloaded once on your own PC) -> installed offline, no internet needed
#  2. PIP_INDEX_URL set to a different package mirror (useful if pypi.org is slow or blocked on your network)
#  3. the normal pypi.org download, with long timeouts, retries and a cache so a re-run resumes
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt wheels* /tmp/pkg/
RUN --mount=type=cache,target=/root/.cache/pip sh -c '\
    if ls /tmp/pkg/*.whl >/dev/null 2>&1; then \
        echo "Installing from the local wheels folder (offline)"; \
        pip install --no-index --find-links /tmp/pkg -r /tmp/pkg/requirements.txt; \
    else \
        pip install --index-url "$PIP_INDEX_URL" --default-timeout=120 --retries 10 -r /tmp/pkg/requirements.txt; \
    fi && rm -rf /tmp/pkg'

COPY . .
RUN useradd -m appuser && mkdir -p /srv/uploads && chown -R appuser /srv
USER appuser

EXPOSE 8000
# One gevent worker per container handles thousands of idle websockets.
# Scale by running MORE CONTAINERS (ECS tasks), not more workers.
CMD ["gunicorn", "-k", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", \
     "-w", "1", "--worker-connections", "3000", "-b", "0.0.0.0:8000", \
     "--timeout", "120", "--graceful-timeout", "30", "wsgi:app"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1
