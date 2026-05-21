FROM python:3.13-slim

# matplotlib needs a font; dejavu is what its default ships against
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
        "matplotlib>=3.10,<4" \
        "pandas>=2.2,<4" \
        "numpy>=2,<3" \
        "scipy>=1.13,<2" \
        "seaborn>=0.13,<0.14"

COPY analyze.py _render_pdf.py make_report.sh entrypoint.sh /app/
RUN chmod +x /app/make_report.sh /app/entrypoint.sh

# /data is the volume mount point: it holds input.csv and receives outputs
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--pdf"]
