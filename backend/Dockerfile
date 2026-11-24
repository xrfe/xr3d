FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake calculix-ccx libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock.txt backend/requirements.upstream.txt /app/backend/
RUN python -m venv /opt/xr3d-env
ENV PATH=/opt/xr3d-env/bin:$PATH
RUN python -m pip install --no-cache-dir -r backend/requirements.lock.txt && python -m pip check
COPY backend /app/backend
ENV XR3D_DATA_DIR=/data
EXPOSE 8000
CMD ["/opt/xr3d-env/bin/python", "-m", "backend.serve", "--host", "0.0.0.0", "--port", "8000"]
