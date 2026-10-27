PLUGIN  := geosian
# QGIS 3 y QGIS 4 guardan el perfil en carpetas distintas (QGIS3/, QGIS4/).
# Se pregunta la versión al PyQGIS instalado; si no responde, se asume la 3.
QGIS_MAJOR   ?= $(shell python3 -c 'from qgis.core import Qgis; print(Qgis.versionInt() // 10000)' 2>/dev/null || echo 3)
QGIS_PROFILE ?= $(HOME)/.local/share/QGIS/QGIS$(QGIS_MAJOR)/profiles/default
PLUGIN_DIR   := $(QGIS_PROFILE)/python/plugins/$(PLUGIN)
PYTHON  ?= .venv/bin/python
BUILD   ?= $(CURDIR)/build
VERSION := $(shell sed -n 's/^version=//p' $(PLUGIN)/metadata.txt)
# `make package SERVIDOR=https://api.devel.greencitycontrol.com` fija el servidor en el
# paquete (ver geosian/core/servidor.py) y lo dice en el nombre del zip.
SERVIDOR ?=
SUFIJO := $(if $(SERVIDOR),-$(subst .,-,$(patsubst https://%,%,$(SERVIDOR))),)

export QT_QPA_PLATFORM ?= offscreen

.PHONY: help venv test lint package install uninstall clean

help:
	@echo "make venv       Entorno de desarrollo (usa el PyQGIS del sistema)"
	@echo "make test       Batería completa"
	@echo "make lint       Comprobación de estilo"
	@echo "make package    Genera $(PLUGIN)-$(VERSION).zip"
	@echo "make package SERVIDOR=https://api.devel.greencitycontrol.com   Con el servidor fijado"
	@echo "make install    Enlaza el complemento en el perfil de QGIS"
	@echo "make uninstall  Quita el enlace"

venv:
	python3 -m venv --system-site-packages .venv
	.venv/bin/pip install -q pytest ruff
	@echo "Listo. PyQGIS se toma del sistema."

test:
	$(PYTHON) -m pytest tests/ -q

lint:
	$(PYTHON) -m ruff check $(PLUGIN) tests

# Solo lo versionado de $(PLUGIN)/ (nada de cachés ni restos locales) y la
# licencia dentro, que el repositorio de complementos de QGIS la exige.
package:
	@rm -rf $(BUILD)/$(PLUGIN) $(BUILD)/$(PLUGIN)-$(VERSION).zip
	@mkdir -p $(BUILD)/$(PLUGIN)
	git ls-files -z $(PLUGIN) | xargs -0 -I{} cp --parents {} $(BUILD)/
	cp LICENSE $(BUILD)/$(PLUGIN)/LICENSE
ifdef SERVIDOR
	sed -i 's|^SERVIDOR_FIJO = ""$$|SERVIDOR_FIJO = "$(SERVIDOR)"|' $(BUILD)/$(PLUGIN)/core/servidor.py
	@grep -q '^SERVIDOR_FIJO = "$(SERVIDOR)"$$' $(BUILD)/$(PLUGIN)/core/servidor.py || { echo "No se pudo fijar el servidor" >&2; exit 1; }
endif
ifneq (,$(findstring .devel.,$(SERVIDOR)))
	sed -i -e 's|^name=GreenCityControl$$|name=GreenCityControl DEVEL (pruebas)|' -e 's|^description=|description=VERSIÓN DE PRUEBAS, conectada a devel. |' $(BUILD)/$(PLUGIN)/metadata.txt
	@grep -q '^name=GreenCityControl DEVEL (pruebas)$$' $(BUILD)/$(PLUGIN)/metadata.txt || { echo "No se pudo marcar el paquete de devel" >&2; exit 1; }
endif
	cd $(BUILD) && zip -qr $(PLUGIN)-$(VERSION)$(SUFIJO).zip $(PLUGIN)
	@rm -rf $(BUILD)/$(PLUGIN)
	@echo "$(BUILD)/$(PLUGIN)-$(VERSION)$(SUFIJO).zip"

install:
	@mkdir -p $(dir $(PLUGIN_DIR))
	@rm -rf $(PLUGIN_DIR)
	ln -s $(CURDIR)/$(PLUGIN) $(PLUGIN_DIR)
	@echo "Enlazado en $(PLUGIN_DIR)"
	@echo "Actívalo en QGIS: Complementos > Administrar e instalar complementos."

uninstall:
	@rm -rf $(PLUGIN_DIR)
	@echo "Quitado de $(PLUGIN_DIR)"

clean:
	@rm -rf build
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	@find . -name '*.py[co]' -delete
