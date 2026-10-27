FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AES_STATE_DIR=/var/lib/aes-agent-engineering-system

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin aes \
    && mkdir -p /app /var/lib/aes-agent-engineering-system \
    && chown -R aes:aes /app /var/lib/aes-agent-engineering-system

WORKDIR /app
# Official Anthropic SDK for the Claude provider; other providers use stdlib HTTP.
RUN pip install --no-cache-dir anthropic==1.13.0
COPY --chown=aes:aes scripts/ /app/scripts/
COPY --chown=aes:aes research/sources.json /app/research/sources.json

USER aes
EXPOSE 8080
# Lets Coolify keep the old container serving until the new one answers, so redeploys cause no downtime.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3   CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT') or os.environ.get('AES_DASHBOARD_PORT') or '8080'; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz', timeout=4).status == 200 else 1)"
CMD ["python", "scripts/dashboard.py"]
