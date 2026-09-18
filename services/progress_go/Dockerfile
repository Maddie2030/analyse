FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src

# Resolve the dependencies declared in go.mod without running `go mod tidy`
# before the source code exists. `tidy` needs the actual package imports.
COPY services/progress_go/go.mod ./
RUN go mod download

# Copy the complete module, then generate/verify the checksum set against
# the real imports before compiling.
COPY services/progress_go ./
RUN go mod tidy && \
    go mod verify && \
    CGO_ENABLED=0 GOOS=linux go build \
      -trimpath \
      -ldflags="-s -w" \
      -o /out/progress-api \
      ./cmd/api


FROM alpine:3.22.1

RUN apk add --no-cache 'ca-certificates>=20260611' 'wget>=1.25.0' && \
    addgroup -S app && adduser -S -G app app

WORKDIR /app

COPY --from=builder /out/progress-api /app/progress-api

USER app

EXPOSE 8080

ENTRYPOINT ["/app/progress-api"]
