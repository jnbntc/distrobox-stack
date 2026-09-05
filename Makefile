# Orquestador del Stack Distrobox en Fedora Atomic
.PHONY: all build deploy clean-images recreate

all: build deploy

# Delega la lógica de compilación y orquestación al script en bash
# para soportar unificación de contexto rootful/rootless de manera segura.

build:
	@./scripts/stack.sh build

deploy:
	@./scripts/stack.sh deploy

recreate:
	@./scripts/stack.sh recreate

clean-images:
	@./scripts/stack.sh clean

pull:
	@./scripts/stack.sh pull
