FROM python:3.12.10-slim

WORKDIR /app
COPY apps /app/apps
COPY services/eye /app/services/eye
COPY services/face /app/services/face

RUN pip install --no-cache-dir \
    "eyetrax==0.4.0" "mediapipe==1.0.0" "numpy==1.26.4" \
    "opencv-python-headless==4.11.0.86" "starlette>=0.37,<1" \
    "uvicorn[standard]>=0.30,<1" /app/services/face

ENV PYTHONPATH=/app/services/eye/src:/app
CMD ["python", "-m", "mcm_eye.worker"]
