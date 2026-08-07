VENV := .venv
PYTHON := $(VENV)/bin/python
SASLITE := $(VENV)/bin/saslite
WORKDIR ?= .work

.PHONY: install test run version

install:
	$(PYTHON) -m pip install -e .

test:
	$(PYTHON) -m unittest discover -s tests -v

run:
	@test -n "$(PROGRAM)" || (echo "Usage: make run PROGRAM=/path/to/program.sas [WORKDIR=/path/to/work]"; exit 2)
	$(SASLITE) --workdir "$(WORKDIR)" "$(PROGRAM)"

version:
	$(SASLITE) --version
