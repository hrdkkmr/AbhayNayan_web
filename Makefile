.PHONY: run test package android

run:
	./scripts/run_local.sh

test:
	./scripts/verify_all.sh

package:
	python3 scripts/package_release.py

android:
	cd android && ./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug
