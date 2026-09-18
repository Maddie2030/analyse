SHELL := bash

.PHONY: help start stop status logs build migrate validate test test-quick staging-status rabbitmq-status public-up public-down public-status browser-on browser-off db-backup-status db-backup-now db-snapshot-now catalog-recovery-check catalog-recovery-import android-debug android-test android-apk

help:
	@echo "MReader RC4.84 canonical hybrid commands"
	@echo "  make start              Start Docker Desktop K8s + hybrid stateful Compose"
	@echo "  make stop               Stop the hybrid runtime (local durable volumes preserved)"
	@echo "  make status             Show Compose/Kubernetes/KEDA status"
	@echo "  make logs               Show recent hybrid logs"
	@echo "  make build              Build current hybrid application images"
	@echo "  make migrate            Apply current DB migrations through hybrid stateful Compose"
	@echo "  make validate           Validate current release structure/contracts"
	@echo "  make test               Run full hybrid diagnostic suite"
	@echo "  make test-quick         Run quick hybrid diagnostics"
	@echo "  make public-up          Enable configured public user-plane edges"
	@echo "  make browser-on         Enable optional Chromium scraper worker"

start:
	./hybrid-up.sh
stop:
	./hybrid-down.sh
status:
	./scripts/hybrid/status.sh
logs:
	./scripts/logs.sh all
build:
	./scripts/hybrid/build-images.sh
migrate:
	./scripts/migrate.sh
validate:
	./scripts/validate-current-release.sh
test:
	./test-mreader.sh --full
test-quick:
	./test-mreader.sh --quick
staging-status:
	./scripts/diagnose-scraper-staging.sh
rabbitmq-status:
	./scripts/rabbitmq-status.sh
public-up:
	./scripts/hybrid/public-up.sh both
public-down:
	./scripts/hybrid/public-down.sh
public-status:
	./scripts/hybrid/public-status.sh
browser-on:
	./scripts/scraper-browser.sh enable
browser-off:
	./scripts/scraper-browser.sh disable

db-backup-status:
	./db-backup.sh status
db-backup-now:
	./db-backup.sh daily
db-snapshot-now:
	./db-backup.sh snapshot


catalog-recovery-check:
	@test -n "$(SOURCE)" || (echo "Usage: make catalog-recovery-check SOURCE=/path/to/backup.dump" >&2; exit 2)
	./scripts/recovery/catalog-restore.sh --source "$(SOURCE)" --check

catalog-recovery-import:
	@test -n "$(SOURCE)" || (echo "Usage: make catalog-recovery-import SOURCE=/path/to/backup.dump" >&2; exit 2)
	./scripts/recovery/catalog-restore.sh --source "$(SOURCE)" --import

android-debug:
	cd android && ./gradlew :app:assembleDebug
android-test:
	cd android && ./gradlew :app:testDebugUnitTest
android-apk:
	./build-android-apk.sh
