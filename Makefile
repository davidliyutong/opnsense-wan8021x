# Single entry point for the wan8021x plugin and its test environment.
# Host requirements: docker (with compose), git, /dev/kvm.

include env/versions.env
export

HOST_UID	!= id -u
HOST_GID	!= id -g
export HOST_UID HOST_GID

COMPOSE		= docker compose -f env/compose.yml --env-file env/versions.env
VM_RUN		= $(COMPOSE) run --rm --no-deps --entrypoint /usr/local/sbin/vm-entrypoint vm
DEV		= $(COMPOSE) run --rm --no-deps dev
# act runs the workflows in a job container capped like a GitHub-hosted
# ubuntu-latest runner for private repositories (2 CPU, 8 GB RAM, no swap).
# Disk (14 GB there) cannot be capped with overlay2; see docs/testenv.md.
ACT_LIMITS	= --cpus=2 --memory=8g --memory-swap=8g
ACT		= act -P ubuntu-latest=wan8021x/act:local --pull=false \
		  --artifact-server-path .cache/act/artifacts \
		  --container-options "$(ACT_LIMITS) --device /dev/kvm"
BASE		= images/base-$(OPNSENSE_VERSION).qcow2
GOLDEN		= vm/golden.qcow2
PLUGIN		= net/wan8021x

.PHONY: help tools image golden reset up down restart logs console ssh shell \
	deploy remove package lint lint-local ci-local test check status clean

help:
	@echo "tools     build the local docker images (qemu, authenticator, dev tools)"
	@echo "image     download + verify the OPNsense nano image, convert to qcow2"
	@echo "golden    provision a golden VM disk (serial-console automation)"
	@echo "reset     throw away the VM state: new overlay on top of golden"
	@echo "up/down   start/stop VM + authenticator"
	@echo "console   attach to the VM serial console (ctrl-] to quit)"
	@echo "ssh       ssh into the VM as root"
	@echo "deploy    install the plugin from this tree into the VM"
	@echo "package   build os-wan8021x pkg inside the VM into .cache/pkg"
	@echo "lint      style checks in the dev container + upstream make lint in the VM"
	@echo "lint-local  only the dev container checks (what CI runs on every push)"
	@echo "test      end-to-end tests against the running VM (TESTARGS=... for pytest)"
	@echo "check     lint + fresh VM + deploy + all tests"
	@echo "ci-local  run the GitHub workflows with act under runner limits (ACTARGS=\"-j lint\")"

tools:
	$(COMPOSE) --profile tools build

.cache/images/$(OPNSENSE_IMAGE):
	mkdir -p .cache/images
	curl -fL -o $@.part $(OPNSENSE_MIRROR)/$(OPNSENSE_VERSION)/$(OPNSENSE_IMAGE)
	mv $@.part $@

.cache/$(BASE): .cache/images/$(OPNSENSE_IMAGE)
	$(VM_RUN) prepare-base

image: .cache/$(BASE)

.cache/$(GOLDEN): .cache/$(BASE)
	$(COMPOSE) down
	$(VM_RUN) overlay $(BASE) $(GOLDEN).tmp
	VM_DISK=$(GOLDEN).tmp $(COMPOSE) up -d vm
	$(DEV) python3 env/provision/bootstrap.py
	timeout 300 docker wait $$($(COMPOSE) ps -aq vm)
	$(COMPOSE) down
	mv .cache/$(GOLDEN).tmp .cache/$(GOLDEN)

golden: .cache/$(GOLDEN)

reset: .cache/$(GOLDEN)
	$(COMPOSE) down
	$(VM_RUN) overlay $(GOLDEN) vm/overlay.qcow2
	$(COMPOSE) up -d
	$(DEV) python3 tools/vmctl.py wait

up: .cache/$(GOLDEN)
	@test -f .cache/vm/overlay.qcow2 || $(VM_RUN) overlay $(GOLDEN) vm/overlay.qcow2
	$(COMPOSE) up -d
	$(DEV) python3 tools/vmctl.py wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

console:
	$(DEV) socat -,raw,echo=0,escape=0x1d UNIX-CONNECT:/src/.cache/run/serial.sock

ssh:
	@tools/bin/vm-ssh

shell:
	$(DEV) bash

deploy:
	$(DEV) python3 tools/vmctl.py deploy $(PLUGIN)

remove:
	$(DEV) python3 tools/vmctl.py remove $(PLUGIN)

package:
	$(DEV) python3 tools/vmctl.py package $(PLUGIN)

status:
	$(COMPOSE) ps
	$(COMPOSE) exec auth authctl status

lint: lint-local
	$(DEV) python3 tools/vmctl.py lint $(PLUGIN)

lint-local:
	$(DEV) tools/lint.sh $(PLUGIN)

test:
	$(DEV) python3 -m pytest -v tests/e2e $(TESTARGS)

check: lint reset deploy test

ci-local:
	docker build -q --build-arg ACT_IMAGE=$(ACT_IMAGE) -t wan8021x/act:local env/act
	$(ACT) push -W .github/workflows/ci.yml $(ACTARGS)

clean: down
	rm -rf .cache/vm .cache/run .cache/auth
