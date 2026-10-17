.PHONY: help all setup dev-setup fmt clean distclean maintclean pyfmt black usort tests translations

all: setup

help:
		@echo "konsave helper:"
		@echo ""
		@echo " - setup:        User-level setup"
		@echo " - dev-setup:    Development setup"
		@echo " - fmt:          Format the code with pyfmt"
		@echo " - clean:        Remove all pyc files"
		@echo " - distclean:    Remove any eggs/builds"
		@echo " - maintclean:   Remove virtual env and dist files"
		@echo " - translations: Update the GUI .ts files and rebuild the .qm catalogs"
		@echo ""

setup:
		@echo "Setting Up (user)"
		@python3 -m venv .venv
		@(. .venv/bin/activate && \
				pip install -r requirements.txt && \
				python -m pip install --upgrade pip \
		)

dev-setup: setup
		@echo "Setting Up (dev)"
		@@(. .venv/bin/activate && pip install -r requirements_dev.txt)


fmt: black pylint

black:
		@echo " * Running black"
		@black --safe konsave


# TODO: Consider adding this
# usort:
# 		@echo " * Running usort"
# 		@usort format konsave

pylint:
		@echo " * Running pylint"
		@pylint konsave

clean:
		@find . -name "*.pyc" -exec rm -f {} \;
		@find . -name '__pycache__' -type d | xargs rm -fr

distclean: clean
		rm -fr *.egg *.egg-info/ .eggs/ dist/ build/

maintclean: distclean
		rm -fr .venv/

# TODO: Consider adding proper type-checking
# typecheck:
#		 mypy -p yacgtc --strict --no-strict-optional --ignore-missing-imports --install-types
#		 mypy -p tests --no-strict-optional --ignore-missing-imports --install-types

tests:
		python3 -m unittest discover -s tests -t . -v

# GUI texts: extract the strings from the code into the .ts files (keeping the
# existing translations), then compile them. Translate any message left
# "unfinished" in kongui/gui/translations/*.ts before running the tests.
translations:
		@pyside6-lupdate $$(find kongui/gui -name '*.py' | sort) \
				-ts kongui/gui/translations/kongui_en.ts kongui/gui/translations/kongui_pt_BR.ts \
				-no-obsolete -locations none
		@for lang in en pt_BR; do \
				pyside6-lrelease kongui/gui/translations/kongui_$$lang.ts -qm kongui/gui/translations/kongui_$$lang.qm; \
		done
