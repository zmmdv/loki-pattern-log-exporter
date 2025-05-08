# Loki Pattern Log Exporter

A Python application that monitors Loki logs for specific patterns and sends notifications to Slack when matches are found.

## Features

- Queries Loki logs using the HTTP API
- Supports regex pattern matching in logs
- Sends notifications to Slack
- Prevents duplicate notifications within a time window
- Configurable through YAML config file and environment variables
- Docker support

## Prerequisites

- Python 3.11 or higher
- Access to a Loki instance
- Slack workspace and bot token

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd loki-pattern-log-exporter
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

Create a `config.yaml` file with the following structure:

```yaml
loki:
  endpoint: "http://localhost:3100"  # Loki server endpoint
  query: '{job="your-job-name"}'    # Loki query
  pattern: "error|exception|critical"  # Regex pattern to match
  interval: "1m"                    # Check interval (e.g., "1m", "5m", "1h")

slack:
  token: "${SLACK_TOKEN}"           # Slack bot token
  channel: "${SLACK_CHANNEL}"       # Slack channel ID
```

You can also set these values using environment variables:
- `LOKI_ENDPOINT`
- `LOKI_QUERY`
- `LOKI_PATTERN`
- `LOKI_INTERVAL`
- `SLACK_TOKEN`
- `SLACK_CHANNEL`

## Usage

### Running Locally

```bash
python main.py --config config.yaml
```

### Running with Docker

1. Build the Docker image:
```bash
docker build -t loki-pattern-exporter .
```

2. Run the container:
```bash
docker run -e SLACK_TOKEN=your-token \
           -e SLACK_CHANNEL=your-channel \
           -e LOKI_ENDPOINT=http://your-loki:3100 \
           loki-pattern-exporter
```

## Development

The application is structured as follows:

- `main.py`: Main application code
- `requirements.txt`: Python dependencies
- `config.yaml`: Configuration file
- `Dockerfile`: Docker configuration

### Key Components

1. **MessageCache**: Prevents duplicate notifications within a configurable time window
2. **Loki Query**: Uses Loki's HTTP API to query logs
3. **Slack Integration**: Sends notifications using the Slack SDK
4. **Configuration**: Supports both YAML and environment variables

## License

[Your License]

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request 