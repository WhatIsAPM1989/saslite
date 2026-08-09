VENV := .venv
PYTHON := $(VENV)/bin/python
WORKDIR ?= .work
LOCAL_PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: install test run version

install:
	$(PYTHON) -m pip install -e .

test:
	PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m unittest discover -s tests -v

run:
	@test -n "$(PROGRAM)" || (echo "Usage: make run PROGRAM=/path/to/program.sas [WORKDIR=/path/to/work]"; exit 2)
	PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m saslite --workdir "$(WORKDIR)" "$(PROGRAM)"

version:
	PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m saslite --version
