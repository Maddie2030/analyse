FROM mcr.microsoft.com/playwright:v1.62.0-noble@sha256:baed2032d533817f3dbe6425de795788430ba345e819a1201337009ba17c9d07
WORKDIR /workspace/tests/browser
COPY tests/browser/package.json ./package.json
RUN npm install --no-audit --no-fund
COPY tests/browser/ ./
# Runtime tests must never try to repair missing dependencies from npm.
ENV npm_config_offline=true
ENTRYPOINT []
CMD ["./node_modules/.bin/playwright", "test", "--config=playwright.config.mjs"]
