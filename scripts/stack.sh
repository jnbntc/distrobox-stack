#!/usr/bin/env bash
set -eo pipefail

ROOTLESS_IMAGES=("ia-dev" "iot-dev" "media-ops" "pwsh-admin" "re-ops" "book-ops" "gns3-client")
ROOTFUL_IMAGES=("net-ops")
REGISTRY="localhost/custom"
REMOTE_REGISTRY="ghcr.io/jnbntc"

ACTION=$1
shift 1 2>/dev/null || true
TARGETS=("$@")

# Filtro de intersección: Cruza los contenedores solicitados contra el array nativo
filter_targets() {
    local base_array=("$@")
    if [ ${#TARGETS[@]} -eq 0 ]; then
        echo "${base_array[@]}"
    else
        for t in "${TARGETS[@]}"; do
            for a in "${base_array[@]}"; do
                [[ "$t" == "$a" ]] && echo "$a"
            done
        done
    fi
}

build() {
    for img in $(filter_targets "${ROOTLESS_IMAGES[@]}"); do
        echo "=== [BUILD USER] Construyendo ${REGISTRY}/${img}:latest ==="
        podman build -t "${REGISTRY}/${img}:latest" -f "dockerfiles/Containerfile.${img}" dockerfiles/
    done

    for img in $(filter_targets "${ROOTFUL_IMAGES[@]}"); do
        echo "=== [BUILD ROOT] Construyendo ${REGISTRY}/${img}:latest ==="
        sudo podman build -t "${REGISTRY}/${img}:latest" -f "dockerfiles/Containerfile.${img}" dockerfiles/
    done
}

pull_images() {
    for img in $(filter_targets "${ROOTLESS_IMAGES[@]}"); do
        echo "-> Sincronizando (Rootless): ${img}"
        podman pull "${REMOTE_REGISTRY}/${img}:latest"
    done

    for img in $(filter_targets "${ROOTFUL_IMAGES[@]}"); do
        echo "-> Sincronizando (Rootful): ${img}"
        sudo podman pull "${REMOTE_REGISTRY}/${img}:latest"
    done
}

deploy() {
    echo "=== [DEPLOY] Ensamblando contenedores faltantes desde distrobox.ini ==="
    distrobox assemble create --file distrobox.ini
}

recreate() {
    build
    echo "=== [RECREATE] Reemplazando infra existente ==="
    distrobox assemble create --file distrobox.ini --replace
}

clean_images() {
    echo "=== [CLEAN] Purgando blobs OCI huérfanos ==="
    podman images -q "${REGISTRY}/*" | xargs -r podman rmi -f 2>/dev/null || true
    sudo podman images -q "${REGISTRY}/*" | xargs -r sudo podman rmi -f 2>/dev/null || true
}

case "$ACTION" in
    build)    build ;;
    pull)     pull_images ;;
    deploy)   deploy ;;
    recreate) recreate ;;
    clean)    clean_images ;;
    *)
        echo "Uso: $0 {build|pull|deploy|recreate|clean} [contenedor1 contenedor2 ...]"
        exit 1
        ;;
esac
