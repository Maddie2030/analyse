FROM golang:1.25.0-alpine3.22 AS builder

WORKDIR /src

COPY services/reader_go/go.mod ./
COPY services/reader_go/ ./

RUN go mod tidy && go mod verify

RUN CGO_ENABLED=0 GOOS=linux \
    go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /out/reader-go \
    ./cmd/api

FROM alpine:3.22.1

RUN apk add --no-cache 'ca-certificates>=20260611' 'wget>=1.25.0' && \
    addgroup -S app && \
    adduser -S -G app app

WORKDIR /app

COPY --from=builder /out/reader-go /app/reader-go

USER app

EXPOSE 8080

ENTRYPOINT ["/app/reader-go"]
