FROM debian:bookworm-slim AS dump1090-build

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
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

FROM debian:bookworm-slim AS os-deps

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    librtlsdr0 \
    rtl-sdr \
    libusb-1.0-0 \
    libncurses6 \
    gpsd \
    python3 \
    python3-pip \
    python3-gps \
    python3-flask \
    supervisor \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM os-deps AS python-deps

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages -r /tmp/requirements.txt

FROM python-deps AS noaa-apt

ARG NOAA_APT_VERSION=1.4.1
RUN curl -fsSL -o /tmp/noaa-apt.zip \
      "https://github.com/martinber/noaa-apt/releases/download/v${NOAA_APT_VERSION}/noaa-apt-${NOAA_APT_VERSION}-aarch64-linux-gnu-nogui.zip" \
    && unzip -j /tmp/noaa-apt.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/noaa-apt \
    && rm /tmp/noaa-apt.zip

FROM noaa-apt

ENV GPS_DEVICE=/dev/ttyAMA0
ENV GPS_BAUD=9600
ENV DUMP1090_JSON=/app/data/dump1090/aircraft.json

COPY --from=dump1090-build /src/dump1090/dump1090 /usr/bin/dump1090-fa
COPY api/ /app/api/
COPY config/supervisord.conf /etc/supervisor/conf.d/siglog.conf
COPY config/supervisord-no-gps.conf /etc/supervisor/conf.d/siglog-no-gps.conf
COPY config/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/data/dump1090

WORKDIR /app

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
