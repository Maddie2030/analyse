FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src
COPY services/realtime_go/go.mod ./
RUN go mod download
COPY services/realtime_go ./
RUN go mod tidy && go mod verify && \
    go test ./... && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/realtime-go ./cmd/realtime

FROM alpine:3.22.1
RUN apk add --no-cache 'ca-certificates>=20260611' 'wget>=1.25.0' && \
    addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder /out/realtime-go /app/realtime-go
USER app
EXPOSE 8080
ENTRYPOINT ["/app/realtime-go"]
