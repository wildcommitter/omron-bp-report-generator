# syntax=docker/dockerfile:1
# Stage 1 — build the omblepy-rs Rust binary.
FROM docker.io/library/rust:1-slim-bookworm AS rust-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libdbus-1-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY omblepy-rs/ omblepy-rs/
RUN cd omblepy-rs && cargo build --release \
    && cp target/release/omblepy-rs /omblepy-rs

# Stage 2 — Python runtime that produces the report.
FROM python:3.13-slim

# matplotlib needs a font (dejavu is the default); libdbus + bluez are
# what omblepy-rs's bluer dep links against at runtime so the daemon can
# reach the host's BlueZ over the bind-mounted /run/dbus socket.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libdbus-1-3 \
        bluez \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
        "matplotlib>=3.10,<4" \
        "pandas>=2.2,<4" \
        "numpy>=2,<3" \
        "scipy>=1.13,<2" \
        "seaborn>=0.13,<0.14" \
        "csvkit>=2,<3"

COPY analyze.py _render_pdf.py bp_utils.py make_report.sh entrypoint.sh \
     omron_merge.sh /app/
COPY --from=rust-builder /omblepy-rs /app/omblepy-rs
RUN chmod +x /app/make_report.sh /app/entrypoint.sh /app/omron_merge.sh \
             /app/omblepy-rs

# /data is the volume mount point: it holds input.csv and receives outputs
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--pdf"]
