FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
# requirements.txt 설치 후 torch를 CUDA 버전으로 덮어씀
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --upgrade torch --index-url https://download.pytorch.org/whl/cu124

COPY app/ ./app/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
