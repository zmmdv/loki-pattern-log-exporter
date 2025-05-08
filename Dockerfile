# syntax=docker/dockerfile:1.4
FROM --platform=$BUILDPLATFORM golang:1.21-alpine AS builder

ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETARCH
ARG TARGETVARIANT

WORKDIR /app

# Install git for go mod download
RUN apk add --no-cache git

# Copy go mod and sum files
COPY go.mod ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Set build arguments based on target platform
RUN case ${TARGETARCH} in \
    "amd64") \
        GOARCH=amd64 \
        ;; \
    "arm64") \
        GOARCH=arm64 \
        ;; \
    "arm") \
        GOARCH=arm \
        GOARM=${TARGETVARIANT#v} \
        ;; \
    *) \
        echo "Unsupported architecture: ${TARGETARCH}" && exit 1 \
        ;; \
    esac && \
    CGO_ENABLED=0 GOOS=linux GOARCH=${GOARCH} GOARM=${GOARM:-} go build -o loki-pattern-exporter

# Final stage
FROM --platform=$TARGETPLATFORM alpine:latest

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/loki-pattern-exporter .
COPY --from=builder /app/config.yaml .

# Run as non-root user
RUN adduser -D -g '' appuser
USER appuser

ENTRYPOINT ["./loki-pattern-exporter"] 