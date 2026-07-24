# Orquestador del Stack Distrobox en Fedora Atomic
.PHONY: all build deploy clean-images recreate

# Lista de contenedores basada en los sufijos de tus Containerfiles
IMAGES := ia-dev iot-dev media-ops net-ops pwsh-admin
REGISTRY := localhost/custom

all: build deploy

# 1. Compilar todas las imágenes en paralelo o de forma secuencial
build:
	@for img in $(IMAGES); do \
		echo "=== [BUILD] Construyendo $(REGISTRY)/$$img:latest ==="; \
		podman build -t $(REGISTRY)/$$img:latest -f dockerfiles/Containerfile.$$img dockerfiles/ || exit 1; \
	done

# 2. Desplegar o actualizar todas las cajas del INI (pedirá sudo automáticamente para net-ops)
deploy:
	@echo "=== [DEPLOY] Ensamblando cajas desde distrobox.ini ==="
	distrobox assemble create --file distrobox.ini

# 3. Forzar reconstrucción y reemplazo total (Disaster Recovery o cambios drásticos)
recreate: build
	@echo "=== [RECREATE] Reemplazando contenedores existentes ==="
	distrobox assemble create --file distrobox.ini --replace

# 4. Limpiar caché de imágenes locales antiguas
clean-images:
	podman rmi -f $$(podman images -q $(REGISTRY)/*) 2>/dev/null || true

