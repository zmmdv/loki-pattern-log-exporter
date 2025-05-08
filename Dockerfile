FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install git for go mod download
RUN apk add --no-cache git

# Copy go mod and sum files
COPY go.mod ./

# Download dependencies with specific versions
RUN go mod download && \
    go get github.com/grafana/loki@v2.9.2 && \
    go get github.com/slack-go/slack@v0.12.5 && \
    go get gopkg.in/yaml.v3@v3.0.1

# Copy source code
COPY . .

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -o loki-pattern-exporter

# Final stage
FROM alpine:latest

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/loki-pattern-exporter .
COPY --from=builder /app/config.yaml .

# Run as non-root user
RUN adduser -D -g '' appuser
USER appuser

ENTRYPOINT ["./loki-pattern-exporter"] 