SHELL := /bin/bash
.DEFAULT_GOAL := download

PYTHON ?= python3
SHA ?= $(shell git rev-parse HEAD)
VERSION := $(shell git show "$(SHA):pyproject.toml" | $(PYTHON) -c 'import sys, tomllib; print(tomllib.loads(sys.stdin.read())["project"]["version"])')

.PHONY: download prepare upload
download:
	@set -euo pipefail; \
	test -n "$(VERSION)"; \
	sha=$$(git rev-parse "$(SHA)^{commit}"); \
	printf 'Downloading dists for %s (%.7s)\n' "$(VERSION)" "$$sha"; \
	mkdir -p "$(VERSION)"; \
	gh api --paginate 'repos/{owner}/{repo}/actions/artifacts?per_page=100' \
		--jq ".artifacts[] | select(.workflow_run.head_sha == \"$$sha\") | [.id, .name, .size_in_bytes] | @tsv" | \
	awk -F '\t' '!seen[$$2]++' | \
	while IFS=$$'\t' read -r artifact name size; do \
		case "$$name" in \
			heif_image_plugin-$(VERSION)-*-manylinux_*.whl|heif_image_plugin-$(VERSION)-*-musllinux_*.whl|heif_image_plugin-$(VERSION)-*_universal2.whl) ;; \
			*) continue ;; \
		esac; \
		if [ -e "$(VERSION)/$$name" ]; then \
			if [ "$$(wc -c < "$(VERSION)/$$name")" -ne "$$size" ]; then \
				printf 'stopped (size mismatch): %s\n' "$$name" >&2; \
				exit 1; \
			fi; \
			printf 'skipped (already exists): %s\n' "$$name"; \
			continue; \
		fi; \
		temporary=$$(mktemp "$(VERSION)/.download.XXXXXX"); \
		trap 'rm -f "$$temporary"' EXIT; \
		gh api "repos/{owner}/{repo}/actions/artifacts/$$artifact/zip" > "$$temporary"; \
		if [ "$$(wc -c < "$$temporary")" -ne "$$size" ]; then \
			printf 'stopped (downloaded file size mismatch): %s\n' "$$name" >&2; \
			exit 1; \
		fi; \
		mv "$$temporary" "$(VERSION)/$$name"; \
		trap - EXIT; \
		printf 'downloaded: %s\n' "$$name"; \
	done

prepare: download
	@set -euo pipefail; \
	source=$$(mktemp -d); \
	trap 'rm -rf "$$source"' EXIT; \
	git -C .. archive "$(SHA)" | tar -x -C "$$source"; \
	printf 'Building sdist for %s\n' "$(VERSION)"; \
	if ! $(PYTHON) -m build --sdist --outdir "$(VERSION)" "$$source" > "$$source/build.log" 2>&1; then \
		cat "$$source/build.log" >&2; \
		exit 1; \
	fi
	@$(PYTHON) -m twine check --strict "$(VERSION)"/*.whl "$(VERSION)"/*.tar.gz

upload:
	@$(PYTHON) -m twine check --strict "$(VERSION)"/*.whl "$(VERSION)"/*.tar.gz
	@$(PYTHON) -m twine upload "$(VERSION)"/*.whl "$(VERSION)"/*.tar.gz
