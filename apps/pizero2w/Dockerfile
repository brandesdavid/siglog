FROM debian:bookworm-slim AS dump1090-build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    git \
    pkg-config \
    librtlsdr-dev \
    libusb-1.0-0-dev \
    libncurses-dev \
    && rm -rf /var/lib/apt/lists/*

ARG DUMP1090_VERSION=v9.0
RUN git clone --depth 1 --branch "${DUMP1090_VERSION}" \
        https://github.com/flightaware/dump1090.git /src/dump1090 \
    && cd /src/dump1090 \
    && make RTLSDR=yes BLADERF=no HACKRF=no LIMESDR=no SOAPYSDR=no CPUFEATURES=no \
    && strip dump1090

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV GPS_DEVICE=/dev/ttyAMA0
ENV GPS_BAUD=9600
ENV DUMP1090_JSON=/app/data/dump1090/aircraft.json

RUN apt-get update && apt-get install -y --no-install-recommends \
    librtlsdr0 \
    libusb-1.0-0 \
    libncurses6 \
    gpsd \
    python3 \
    python3-gps \
    python3-flask \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dump1090-build /src/dump1090/dump1090 /usr/bin/dump1090-fa

COPY api/ /app/api/
COPY config/supervisord.conf /etc/supervisor/conf.d/siglog.conf
COPY config/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/data/dump1090

WORKDIR /app

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
