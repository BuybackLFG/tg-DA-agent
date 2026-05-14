FROM python:3.11-slim

WORKDIR /workspace

# Install analysis libraries
RUN pip install --no-cache-dir pandas numpy matplotlib seaborn openpyxl

# Copy runner
COPY sandbox/run.py /run.py

ENTRYPOINT ["python", "/run.py"]
