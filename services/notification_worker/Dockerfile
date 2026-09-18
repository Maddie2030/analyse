FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src
COPY services/notification_worker/go.mod services/notification_worker/go.sum ./
RUN go mod download
COPY services/notification_worker ./
RUN go mod tidy && go mod verify && \
    go test ./... && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/notification-worker ./cmd/worker

FROM alpine:3.22.1
RUN apk add --no-cache 'ca-certificates>=20260611' 'wget>=1.25.0' && \
    addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder /out/notification-worker /app/notification-worker
USER app
EXPOSE 8080
ENTRYPOINT ["/app/notification-worker"]
