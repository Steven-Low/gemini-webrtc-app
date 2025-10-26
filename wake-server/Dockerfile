# ---- Base image ----
FROM python:3.11-slim

# ---- Set work directory ----
WORKDIR /app

# ---- Install dependencies ----
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
 
# ---- IMPORTANT: openwakeword require downloading core models during runtime ----
RUN python3 - <<EOF
from openwakeword.utils import download_models
download_models()
EOF

RUN mkdir -p /app/models

# ---- Copy app and model ----
COPY wake_server.py .
COPY ok_nabu.onnx .

# ---- Environment ----
ENV WAKE_WORD_MODEL="ok_nabu.onnx"
ENV WAKE_HOST=0.0.0.0
ENV WAKE_PORT=12201

# ---- Expose port and start ----
EXPOSE 12201
CMD ["uvicorn", "wake_server:app", "--host", "0.0.0.0", "--port", "12201"]
