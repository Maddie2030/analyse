FROM mreader/api-tests:1.3.0-rc4.84

WORKDIR /repo
COPY tests/diagnostics /repo/tests/diagnostics
COPY scripts/diagnostics /repo/scripts/diagnostics
ENTRYPOINT ["python", "-u", "/repo/tests/diagnostics/runner.py"]
