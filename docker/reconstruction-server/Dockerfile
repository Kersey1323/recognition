FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python -m pip install --no-cache-dir -r csrcqsf/biz/railwayparts/reconstruction_server/requirements.txt

CMD ["python", "csrcqsf/biz/railwayparts/reconstruction_server/api.py", "--host", "0.0.0.0", "--port", "8000"]
