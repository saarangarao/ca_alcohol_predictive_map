# Convenience wrappers. Run inside the activated virtual environment.
PY ?= python

.PHONY: all test heavy

all:            ## full rebuild: tests, then raw -> clean -> features -> queries -> clusters -> model -> figures
	$(PY) run_all.py

test:           ## unit tests only
	$(PY) -m pytest -q

heavy:          ## full rebuild plus the optional bigger-model experiment
	$(PY) run_all.py --with-heavy
