FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PHOTO_ROOT=/photos DATA_DIR=/data PORT=8090 TZ=Asia/Shanghai

RUN apt-get update \
 && apt-get install -y --no-install-recommends libimage-exiftool-perl fonts-noto-cjk tini \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY app/ /app/
WORKDIR /app
VOLUME ["/data"]
EXPOSE 8090
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "serve.py"]
