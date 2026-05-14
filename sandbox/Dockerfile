FROM python:3.11-slim

WORKDIR /workspace

# Install analysis libraries
RUN pip install --no-cache-dir pandas numpy matplotlib seaborn openpyxl

# Create output directory with open permissions
RUN mkdir -p /output && chmod 777 /output

# Set matplotlib to non-interactive backend by default
ENV MPLBACKEND=Agg

# Copy runner
COPY run.py /run.py

ENTRYPOINT ["python", "/run.py"]
