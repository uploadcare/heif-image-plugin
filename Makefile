.PHONY: clean lint commit check

xargs=$(if $(shell xargs -r </dev/null 2>/dev/null && echo 1), xargs -r, xargs)

clean:
	find . -type f \( -name \*.pyc -o -name \*.pyo \) -delete
	find . -type d -name __pycache__ -print0 | $(xargs) -0 rm -rf

lint: clean
	isort --diff HeifImagePlugin.py ./tests
	pycodestyle HeifImagePlugin.py ./tests
	flake8 HeifImagePlugin.py ./tests

GIT_DIFF=git diff --name-only --cached --diff-filter=dt
commit:
	${GIT_DIFF} -- '*.py' | $(xargs) isort --diff
	${GIT_DIFF} -- '*.py' | $(xargs) pycodestyle
	${GIT_DIFF} -- '*.py' | $(xargs) flake8

check: clean
	pytest --cov=. --cov-report=xml tests


.PHONY: install-pyheif-latest-pillow-latest install-pyheif-latest-pillow-prod

install-pyheif-latest-pillow-latest:
	pip install --use-deprecated=legacy-resolver .[test]

install-pyheif-latest-pillow-prod:
	sudo apt install --no-install-recommends -y libjpeg-dev
	pip install --use-deprecated=legacy-resolver .[test] \
		-e git+https://github.com/uploadcare/pillow-simd.git@simd/6.0-cmyk16bit#egg=pillow


.PHONY: install-pyheif-prod-pillow-latest install-pyheif-prod-pillow-prod

install-pyheif-prod-pillow-latest:
	pip install --use-deprecated=legacy-resolver .[test] \
		-e git+https://github.com/uploadcare/pyheif.git@0.6.1-prod#egg=pyheif

install-pyheif-prod-pillow-prod:
	sudo apt install --no-install-recommends -y libjpeg-dev
	pip install --use-deprecated=legacy-resolver .[test] \
		-e git+https://github.com/uploadcare/pillow-simd.git@simd/6.0-cmyk16bit#egg=pillow \
		-e git+https://github.com/uploadcare/pyheif.git@0.6.1-prod#egg=pyheif
