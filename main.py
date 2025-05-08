import os
import re
import time
import yaml
import logging
import requests
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class LokiConfig:
    endpoint: str
    query: str
    pattern: str
    interval: str

@dataclass
class SlackConfig:
    token: str
    channel: str

@dataclass
class Config:
    loki: LokiConfig
    slack: SlackConfig

class MessageCache:
    def __init__(self, window_seconds: int = 300):  # 5 minutes default window
        self.messages: Dict[str, datetime] = {}
        self.window = timedelta(seconds=window_seconds)

    def add(self, message: str) -> None:
        self.messages[message] = datetime.now()

    def contains(self, message: str) -> bool:
        if message in self.messages:
            if datetime.now() - self.messages[message] < self.window:
                return True
            # Message exists but is expired, remove it
            del self.messages[message]
        return False

    def cleanup(self) -> None:
        now = datetime.now()
        expired = [msg for msg, timestamp in self.messages.items() 
                  if now - timestamp > self.window]
        for msg in expired:
            del self.messages[msg]

def load_config(config_path: str) -> Config:
    # Default values
    config = Config(
        loki=LokiConfig(
            endpoint="http://localhost:3100",
            query='{job="your-job-name"}',
            pattern="error|exception|critical",
            interval="1m"
        ),
        slack=SlackConfig(
            token="",
            channel=""
        )
    )

    # Load from config file if it exists
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            yaml_config = yaml.safe_load(f)
            
            if 'loki' in yaml_config:
                loki_config = yaml_config['loki']
                config.loki.endpoint = loki_config.get('endpoint', config.loki.endpoint)
                config.loki.query = loki_config.get('query', config.loki.query)
                config.loki.pattern = loki_config.get('pattern', config.loki.pattern)
                config.loki.interval = loki_config.get('interval', config.loki.interval)
            
            if 'slack' in yaml_config:
                slack_config = yaml_config['slack']
                config.slack.token = slack_config.get('token', config.slack.token)
                config.slack.channel = slack_config.get('channel', config.slack.channel)

    # Override with environment variables
    config.loki.endpoint = os.getenv('LOKI_ENDPOINT', config.loki.endpoint)
    config.loki.query = os.getenv('LOKI_QUERY', config.loki.query)
    config.loki.pattern = os.getenv('LOKI_PATTERN', config.loki.pattern)
    config.loki.interval = os.getenv('LOKI_INTERVAL', config.loki.interval)
    config.slack.token = os.getenv('SLACK_TOKEN', config.slack.token)
    config.slack.channel = os.getenv('SLACK_CHANNEL', config.slack.channel)

    # Validate required fields
    if not config.slack.token:
        raise ValueError("SLACK_TOKEN is required")
    if not config.slack.channel:
        raise ValueError("SLACK_CHANNEL is required")

    return config

def query_loki(config: Config, pattern: re.Pattern) -> List[str]:
    # Calculate time range
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=1)  # Default to 1 minute window
    
    # Convert to nanoseconds for Loki
    start_ns = int(start_time.timestamp() * 1e9)
    end_ns = int(end_time.timestamp() * 1e9)

    # Prepare query parameters
    params = {
        'query': config.loki.query,
        'start': start_ns,
        'end': end_ns,
        'limit': 1000
    }

    try:
        response = requests.get(f"{config.loki.endpoint}/loki/api/v1/query_range", params=params)
        response.raise_for_status()
        data = response.json()

        matches = []
        for result in data.get('data', {}).get('result', []):
            for value in result.get('values', []):
                if pattern.search(value[1]):
                    matches.append(f"Found pattern in log: {value[1]}")

        return matches
    except requests.exceptions.RequestException as e:
        logger.error(f"Error querying Loki: {e}")
        return []

def send_slack_notification(config: Config, messages: List[str], cache: MessageCache) -> None:
    client = WebClient(token=config.slack.token)
    
    for msg in messages:
        if cache.contains(msg):
            logger.info(f"Skipping duplicate message: {msg}")
            continue

        try:
            response = client.chat_postMessage(
                channel=config.slack.channel,
                text=msg
            )
            cache.add(msg)
            logger.info(f"Sent message to Slack: {msg}")
        except SlackApiError as e:
            logger.error(f"Error sending Slack message: {e}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Loki Pattern Log Exporter')
    parser.add_argument('--config', default='config.yaml', help='path to config file')
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        pattern = re.compile(config.loki.pattern)
        cache = MessageCache()

        while True:
            matches = query_loki(config, pattern)
            if matches:
                send_slack_notification(config, matches, cache)
            
            # Parse interval (e.g., "1m", "5m", "1h")
            interval_str = config.loki.interval
            if interval_str.endswith('m'):
                interval = int(interval_str[:-1]) * 60
            elif interval_str.endswith('h'):
                interval = int(interval_str[:-1]) * 3600
            else:
                interval = int(interval_str)
            
            time.sleep(interval)
            cache.cleanup()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main() 