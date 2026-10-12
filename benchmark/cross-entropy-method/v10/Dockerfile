FROM ghcr.io/laude-institute/t-bench/python-3-13:20250620

WORKDIR /app
RUN python3 -m pip install --no-cache-dir \
    "numpy==2.2.6" \
    "pytest==8.4.1" \
    "setuptools==80.9.0" \
    "wheel==0.45.1"

COPY pyproject.toml /app/
COPY cross_entropy_method /app/cross_entropy_method

RUN python3 -m pip install --no-cache-dir --no-deps --no-build-isolation -e .
