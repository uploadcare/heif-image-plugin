.PHONY: clean lint commit check docker_build docker_shell

xargs=$(if $(shell xargs -r </dev/null 2>/dev/null && echo 1), xargs -r, xargs)

clean:
	find . -type f \( -name \*.pyc -o -name \*.pyo \) -delete
	find . -type d -name __pycache__ -print0 | $(xargs) -0 rm -rf

lint: clean
	isort --diff HeifImagePlugin.py ./tests
	flake8 HeifImagePlugin.py ./tests

GIT_DIFF=git diff --name-only --cached --diff-filter=dt
commit:
	${GIT_DIFF} -- '*.py' | $(xargs) isort --diff
	${GIT_DIFF} -- '*.py' | $(xargs) flake8

check: clean
	pytest --cov=. --cov-report=xml tests

docker_build:
	docker build --platform=linux/amd64 -t heif-image-plugin:latest .

docker_shell: docker_build
	docker run --platform=linux/amd64 --rm -it -v .:/src heif-image-plugin:latest

.PHONY: install-pillow-latest
install-pillow-latest:
	pip install .[test] \
		git+https://github.com/uploadcare/pyheif.git@v0.8.0-transforms#egg=pyheif

.PHONY: install-pillow-prod
install-pillow-prod:
	pip install .[test] \
		./pip-stubs/pillow \
		git+https://github.com/uploadcare/pillow-simd.git@simd/9.5-png-truncated#egg=pillow-simd \
		git+https://github.com/uploadcare/pyheif.git@v0.8.0-transforms#egg=pyheif
