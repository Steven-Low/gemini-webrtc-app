# ---- Base image ----
FROM python:3.11-slim

# ---- Set work directory ----
WORKDIR /app

# ---- Install dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Copy app and default model ----
COPY wake_server.py .
COPY models /models

# ---- Environment ----
ENV WAKE_WORD_MODEL="ok_nabu.onnx"
ENV WAKE_HOST=0.0.0.0
ENV WAKE_PORT=12201

# ---- Expose port and start ----
EXPOSE 12201
CMD ["python", "wake_server.py"]
