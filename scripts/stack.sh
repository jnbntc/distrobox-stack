#!/usr/bin/env bash
set -eo pipefail

# Separar imágenes rootless de las rootful según la arquitectura del INI
ROOTLESS_IMAGES=("ansible-ops" "gns3-client" "ia-dev" "iot-dev" "media-ops" "pwsh-admin" "re-ops")
ROOTFUL_IMAGES=("net-ops")
REGISTRY="localhost/custom"

build() {
    # 1. Compilar entornos estándar en el storage rootless del usuario (/var/mnt/storage/podman-rootless/...)
    for img in "${ROOTLESS_IMAGES[@]}"; do
        echo "=== [BUILD USER] Construyendo ${REGISTRY}/${img}:latest ==="
        podman build -t "${REGISTRY}/${img}:latest" -f "dockerfiles/Containerfile.${img}" dockerfiles/
    done

    # 2. Compilar entornos de red/auditoría directamente en el storage rootful (/var/mnt/storage/podman-rootful/...)
    for img in "${ROOTFUL_IMAGES[@]}"; do
        echo "=== [BUILD ROOT] Construyendo ${REGISTRY}/${img}:latest ==="
        sudo podman build -t "${REGISTRY}/${img}:latest" -f "dockerfiles/Containerfile.${img}" dockerfiles/
    done
}

deploy() {
    echo "=== [DEPLOY] Ensamblando cajas desde distrobox.ini ==="
    distrobox assemble create --file distrobox.ini
}

recreate() {
    build
    echo "=== [RECREATE] Reemplazando contenedores existentes ==="
    distrobox assemble create --file distrobox.ini --replace
}

clean_images() {
    echo "=== [CLEAN] Eliminando imágenes locales viejas ==="
    podman images -q "${REGISTRY}/*" | xargs -r podman rmi -f 2>/dev/null || true
    sudo podman images -q "${REGISTRY}/*" | xargs -r sudo podman rmi -f 2>/dev/null || true
}

case "$1" in
    build)    build ;;
    deploy)   deploy ;;
    recreate) recreate ;;
    clean)    clean_images ;;
    *)
        echo "Uso: $0 {build|deploy|recreate|clean}"
        exit 1
        ;;
esac
