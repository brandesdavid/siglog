build-pizero:
    docker buildx build --platform linux/arm64 -f apps/pizero2w/Dockerfile -t ghcr.io/brandesdavid/siglog-pi:latest --load apps/pizero2w

push-pizero:
    docker buildx build --platform linux/arm64 -f apps/pizero2w/Dockerfile -t ghcr.io/brandesdavid/siglog-pi:latest --push apps/pizero2w

run-pizero-fake:
    cd apps/pizero2w && docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
