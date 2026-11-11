FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.lock.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
ENV XR3D_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
