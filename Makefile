PLUGIN  := geosian
QGIS_PROFILE ?= $(HOME)/.local/share/QGIS/QGIS3/profiles/default
PLUGIN_DIR   := $(QGIS_PROFILE)/python/plugins/$(PLUGIN)
PYTHON  ?= .venv/bin/python
VERSION := $(shell sed -n 's/^version=//p' $(PLUGIN)/metadata.txt)

export QT_QPA_PLATFORM ?= offscreen

.PHONY: help venv test lint package install uninstall clean

help:
	@echo "make venv       Entorno de desarrollo (usa el PyQGIS del sistema)"
	@echo "make test       Batería completa"
	@echo "make lint       Comprobación de estilo"
	@echo "make package    Genera $(PLUGIN)-$(VERSION).zip"
	@echo "make install    Enlaza el complemento en el perfil de QGIS"
	@echo "make uninstall  Quita el enlace"

venv:
	python3 -m venv --system-site-packages .venv
	.venv/bin/pip install -q pytest ruff
	@echo "Listo. PyQGIS se toma del sistema."

test:
	$(PYTHON) -m pytest tests/ -q

lint:
	$(PYTHON) -m ruff check $(PLUGIN) tests || true

package: clean
	@mkdir -p build
	zip -qr build/$(PLUGIN)-$(VERSION).zip $(PLUGIN) \
		-x '*__pycache__*' '*.pyc' '*.pyo'
	@echo "build/$(PLUGIN)-$(VERSION).zip"

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
