XARGS := $(if $(shell echo | xargs -r 2>/dev/null && echo 1), xargs -r, xargs)
GIT_DIFF := git diff --name-only --cached --diff-filter=dt


.PHONY: commit
commit:
	$(GIT_DIFF) -- '*.py' | $(XARGS) isort --check-only --diff
	$(GIT_DIFF) -- '*.py' | $(XARGS) flake8


.PHONY: lint
lint:
	isort --diff HeifImagePlugin.py ./tests
	flake8 HeifImagePlugin.py ./tests


.PHONY: test
test:
	pytest --cov=.


ARCH ?= amd64
STACK ?= system
PILLOW ?= latest
LIBHEIF_UC_VERSION ?= 1.21.2-62f1b8c-1a671c7


.PHONY: dockerignore
dockerignore:
	@git status -s --ignored | sed -n 's/^!! /\//p' > .dockerignore
	@printf "%s\n" "/.git*" >> .dockerignore


.PHONY: docker_build
docker_build: dockerignore
	docker build --platform=linux/${ARCH} \
		--build-arg STACK=${STACK} \
		--build-arg PILLOW=${PILLOW} \
		--build-arg LIBHEIF_UC_VERSION=${LIBHEIF_UC_VERSION} \
		-t heif-image-plugin:latest .


.PHONY: docker_shell
docker_shell: docker_build
	docker run --platform=linux/${ARCH} --rm -it -v .:/src heif-image-plugin:latest
