FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src

COPY services/outbox_relay/go.mod services/outbox_relay/go.sum ./
RUN go mod download

COPY services/outbox_relay ./
RUN go mod tidy && \
    go mod verify && \
    CGO_ENABLED=0 GOOS=linux go build \
      -trimpath \
      -ldflags="-s -w" \
      -o /out/outbox-relay \
      ./cmd/relay


FROM alpine:3.22.1

RUN apk add --no-cache 'ca-certificates>=20260611' 'wget>=1.25.0' && \
    addgroup -S app && adduser -S -G app app

WORKDIR /app
COPY --from=builder /out/outbox-relay /app/outbox-relay
USER app

EXPOSE 8080
ENTRYPOINT ["/app/outbox-relay"]
