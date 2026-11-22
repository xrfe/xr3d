FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.lock.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY external/Kiln-main/kiln /app/external/Kiln-main/kiln
COPY external/Kiln-main/LICENSE external/Kiln-main/SKILL.md /app/external/Kiln-main/
RUN python -m backend.install_print_engine
ENV XR3D_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
