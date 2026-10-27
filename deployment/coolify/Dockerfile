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
CMD ["python", "scripts/dashboard.py"]
