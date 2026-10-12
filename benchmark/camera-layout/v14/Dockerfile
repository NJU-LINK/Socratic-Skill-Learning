FROM python:3.11-slim

RUN pip install --no-cache-dir pytest==8.4.1

WORKDIR /app
COPY camera_geom.py /app/camera_geom.py
COPY floor_plan.json /app/floor_plan.json
