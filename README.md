# Loki Pattern Log Exporter

This application monitors Loki logs for specific patterns and sends notifications to Slack when matches are found.

## Prerequisites

- Go 1.21 or later
- Docker
- Kubernetes cluster
- Loki instance
- Slack workspace with a bot token

## Configuration

The application can be configured using either environment variables or a `config.yaml` file. Environment variables take precedence over the config file.

### Environment Variables

```bash
# Loki Configuration
LOKI_ENDPOINT="http://localhost:3100"  # Loki endpoint
LOKI_QUERY='{job="your-job-name"}'    # Loki query
LOKI_PATTERN="error|exception|critical" # Pattern to match
LOKI_INTERVAL="1m"                    # Check interval

# Slack Configuration
SLACK_TOKEN="your-slack-token"         # Slack bot token
SLACK_CHANNEL="your-channel-id"        # Slack channel ID
```

### Config File

Alternatively, you can use a `config.yaml` file with the following structure:

```yaml
loki:
  endpoint: "http://localhost:3100"  # Loki endpoint
  query: '{job="your-job-name"}'    # Loki query
  pattern: "error|exception|critical" # Pattern to match
  interval: "1m"                    # Check interval

slack:
  token: "your-slack-token"         # Slack bot token
  channel: "your-channel-id"        # Slack channel ID
```

## Building with Docker

### Single Architecture Build
```bash
docker build -t loki-pattern-exporter:latest .
```

### Multi-Architecture Build
The Dockerfile supports building for multiple architectures (AMD64, ARM64, and ARM). To build for multiple architectures:

1. Set up Docker buildx:
```bash
docker buildx create --name mybuilder --use
```

2. Build and push for multiple architectures:
```bash
docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t your-registry/loki-pattern-exporter:latest \
  --push .
```

Or build locally for your current architecture:
```bash
docker buildx build --load -t loki-pattern-exporter:latest .
```

## Deploying to Kubernetes

1. Create the Kubernetes secret for Slack credentials:
```bash
# First, encode your Slack token and channel ID in base64
echo -n "your-slack-token" | base64
echo -n "your-channel-id" | base64

# Update the values in k8s/secrets.yaml with the base64 encoded values
```

2. Apply the Kubernetes manifests:
```bash
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/deployment.yaml
```

3. Verify the deployment:
```bash
kubectl get pods -l app=loki-pattern-exporter
```

## Running Locally

### Using Environment Variables
```bash
export LOKI_ENDPOINT="http://localhost:3100"
export LOKI_QUERY='{job="your-job-name"}'
export LOKI_PATTERN="error|exception|critical"
export LOKI_INTERVAL="1m"
export SLACK_TOKEN="your-slack-token"
export SLACK_CHANNEL="your-channel-id"
go run main.go
```

### Using Config File
1. Update the `config.yaml` with your settings
2. Run the application:
```bash
go run main.go
```

## Security Notes

- The application runs as a non-root user in the container
- Sensitive credentials are stored in Kubernetes secrets
- Resource limits are set to prevent resource exhaustion

## Monitoring

The application logs its activities to stdout, which can be collected by your logging infrastructure. 