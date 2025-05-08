FROM golang:latest AS builder

WORKDIR /app

# Install git for go mod download
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy go mod and sum files
COPY go.mod ./

# Download dependencies
RUN go mod tidy && go mod download

# Copy source code
COPY . .

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -o loki-pattern-exporter

# Final stage
FROM debian:latest

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/loki-pattern-exporter .
COPY --from=builder /app/config.yaml .

# Run as non-root user
RUN useradd -m -u 1000 appuser
USER appuser

ENTRYPOINT ["./loki-pattern-exporter"] 