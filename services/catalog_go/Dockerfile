FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src

# Copy the module definition first for cacheable dependency setup.
COPY services/catalog_go/go.mod ./

# Copy source before `go mod tidy` so Go can resolve the exact packages
# imported by this service and generate the complete go.sum in-container.
COPY services/catalog_go/ ./

# Resolve and verify the module graph inside Docker.
# This removes any dependency on Go being installed on the host.
RUN go mod tidy && \
    go mod verify

# Build a static Linux binary.
RUN CGO_ENABLED=0 GOOS=linux \
    go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /out/catalog-go \
    ./cmd/api


FROM alpine:3.22.1

RUN apk add --no-cache 'ca-certificates>=20260611' && \
    addgroup -S app && \
    adduser -S -G app app

WORKDIR /app

COPY --from=builder /out/catalog-go /app/catalog-go

USER app

EXPOSE 8080

ENTRYPOINT ["/app/catalog-go"]
