# Orquestador del Stack Distrobox en Fedora Atomic
.PHONY: all build deploy clean-images recreate pull

# Flujo normal del host: sincronizar imágenes publicadas y crear faltantes.
all: pull deploy

# Build local sólo para desarrollo/pruebas. No se usa automáticamente en deploy.
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
