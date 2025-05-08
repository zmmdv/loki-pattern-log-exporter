import os
import re
import time
import yaml
import logging
import requests
import glob
import threading
import urllib.parse
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import defaultdict
from flask import Flask, jsonify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Global state for health check
app_state = {
    'configs_loaded': False,
    'last_check': None,
    'error_count': 0,
    'loki_connected': False,
    'loki_connection_attempts': 0
}

# Configure retry strategy for requests
retry_strategy = Retry(
    total=3,  # number of retries
    backoff_factor=1,  # wait 1, 2, 4 seconds between retries
    status_forcelist=[500, 502, 503, 504]  # HTTP status codes to retry on
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("http://", adapter)
http.mount("https://", adapter)

@dataclass
class LokiConfig:
    endpoint: str = "http://localhost:3100"
    query: str = '{job="default"}'
    pattern: str = ".*"  # Default pattern that matches everything
    interval: str = "1m"  # Default interval of 1 minute
    region_emoji: str = ":earth_americas:"
    region_text: str = "default-region"
    alert_name: str = "PatternMatchFound"  # Custom alert name
    description: str = ""  # Optional description for the alert

@dataclass
class SlackConfig:
    token: str = ""
    channel: str = ""

@dataclass
class Config:
    loki: LokiConfig
    slack: SlackConfig
    name: str  # Added name field to identify different configs

class MessageCache:
    def __init__(self, window_minutes: int = 5):
        self.window_minutes = window_minutes
        self.messages: Dict[str, datetime] = {}

    def add_message(self, message: str):
        self.messages[message] = datetime.now()
        self._cleanup()

    def has_message(self, message: str) -> bool:
        self._cleanup()
        return message in self.messages

    def _cleanup(self):
        cutoff = datetime.now() - timedelta(minutes=self.window_minutes)
        self.messages = {msg: time for msg, time in self.messages.items() if time > cutoff}

def check_loki_connection(endpoint: str) -> bool:
    """Check if Loki endpoint is accessible."""
    try:
        response = http.get(f"{endpoint}/ready", timeout=5)
        response.raise_for_status()
        app_state['loki_connected'] = True
        app_state['loki_connection_attempts'] = 0
        return True
    except Exception as e:
        logger.error(f"Failed to connect to Loki at {endpoint}: {str(e)}")
        app_state['loki_connected'] = False
        app_state['loki_connection_attempts'] += 1
        return False

def wait_for_loki_connection(endpoint: str, max_attempts: int = 10) -> bool:
    """Wait for Loki to become available with exponential backoff."""
    attempt = 0
    while attempt < max_attempts:
        if check_loki_connection(endpoint):
            logger.info("Successfully connected to Loki")
            return True
        
        # Exponential backoff: 2^attempt seconds
        wait_time = min(2 ** attempt, 60)  # Cap at 60 seconds
        logger.info(f"Waiting {wait_time} seconds before next connection attempt...")
        time.sleep(wait_time)
        attempt += 1
    
    logger.error(f"Failed to connect to Loki after {max_attempts} attempts")
    return False

def load_config(config_path: str) -> List[Config]:
    """Load configuration from a YAML file with environment variable support."""
    configs = []
    
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
            
        # Get config name from filename
        config_name = os.path.splitext(os.path.basename(config_path))[0]
            
        # Load Loki config with environment variable fallback
        loki_config = LokiConfig(
            endpoint=os.getenv('LOKI_ENDPOINT', config_data['loki']['endpoint']),
            query=os.getenv('LOKI_QUERY', config_data['loki']['query']).strip(),
            pattern=os.getenv('LOKI_PATTERN', config_data['loki'].get('pattern', '.*')),
            interval=os.getenv('LOKI_INTERVAL', config_data['loki']['interval']),
            region_emoji=os.getenv('REGION_EMOJI', config_data['loki'].get('region_emoji', ':earth_americas:')),
            region_text=os.getenv('REGION_TEXT', config_data['loki'].get('region_text', 'default-region')),
            alert_name=os.getenv('ALERT_NAME', config_data['loki'].get('alert_name', 'PatternMatchFound')),
            description=os.getenv('DESCRIPTION', config_data['loki'].get('description', ''))
        )
            
        # Load Slack config with environment variable fallback
        slack_config = SlackConfig(
            token=os.getenv('SLACK_TOKEN', config_data['slack']['token']),
            channel=os.getenv('SLACK_CHANNEL', config_data['slack']['channel'])
        )
            
        configs.append(Config(
            loki=loki_config,
            slack=slack_config,
            name=config_name
        ))
            
    except Exception as e:
        logger.error(f"Error loading config {config_path}: {str(e)}")
        app_state['error_count'] += 1
    
    return configs

def extract_app_from_query(query: str) -> str:
    """Extract the app name from a Loki query string like {app="my-app"}"""
    match = re.search(r'app\s*=\s*"([^"]+)"', query)
    if match:
        return match.group(1)
    return "unknown"

def send_slack_notification(config: Config, log_entry: tuple, cache: MessageCache):
    """Send notification to Slack if message hasn't been sent recently."""
    timestamp_ns, log_message = log_entry
    if cache.has_message(log_message):
        return
    try:
        # Format timestamp
        ts = datetime.fromtimestamp(int(timestamp_ns) / 1e9).strftime('%Y-%m-%d %H:%M:%S')
        # Extract app name
        app_name = extract_app_from_query(config.loki.query)
        # Use emoji and region text from config
        region_emoji = config.loki.region_emoji
        region_text = config.loki.region_text
        # Format Slack message
        slack_text = (
            f"{region_emoji} *{region_text}* :fire: *{config.loki.alert_name}*\n"
            f"> App: {app_name}\n"
            f"> Timestamp: {ts}\n"
            f"> Message: {log_message}"
        )
        if config.loki.description:
            slack_text += f"\n> Description: {config.loki.description}"
        client = WebClient(token=config.slack.token)
        response = client.chat_postMessage(
            channel=config.slack.channel,
            text=slack_text
        )
        if response['ok']:
            cache.add_message(log_message)
            logger.info(f"Notification sent to Slack for config {config.name}")
    except SlackApiError as e:
        logger.error(f"Error sending Slack notification: {str(e)}")
        app_state['error_count'] += 1

def query_loki(config: Config) -> List[tuple]:
    """Query Loki for logs matching the pattern. Returns list of (timestamp, message) tuples."""
    try:
        # Check Loki connection before querying
        if not app_state['loki_connected']:
            if not wait_for_loki_connection(config.loki.endpoint):
                return []

        # Calculate the time range based on the interval
        current_time = time.time()
        interval_seconds = parse_interval(config.loki.interval)
        
        # Ensure end time is current time and start time is interval seconds before
        end_time = int(current_time * 1e9)  # Current time in nanoseconds
        start_time = int((current_time - interval_seconds) * 1e9)  # Start time in nanoseconds
        
        # Verify timestamps
        if start_time >= end_time:
            logger.error(f"Invalid time range: start={start_time}, end={end_time}")
            return []
        
        # Construct the query with proper encoding
        base_query = config.loki.query.strip()
        if config.loki.pattern != ".*":  # Only add pattern if it's not the default
            # Escape special characters in the pattern
            escaped_pattern = re.escape(config.loki.pattern)
            base_query = f'{base_query} |~ "{escaped_pattern}"'
        
        # Prepare the query parameters with proper timestamp formatting
        query_params = {
            'query': base_query,
            'start': f"{start_time}",  # Use f-string to avoid scientific notation
            'end': f"{end_time}",      # Use f-string to avoid scientific notation
            'limit': '1000'
        }
        
        # Log the actual query for debugging
        logger.debug(f"Loki query: {base_query}")
        logger.debug(f"Query params: {query_params}")
        logger.debug(f"Time range: {datetime.fromtimestamp(current_time - interval_seconds)} to {datetime.fromtimestamp(current_time)}")
        
        # Make the request to Loki
        response = http.get(
            f"{config.loki.endpoint}/loki/api/v1/query_range",
            params=query_params,
            timeout=10
        )
        response.raise_for_status()
        
        # Parse the response
        data = response.json()
        if 'data' not in data or 'result' not in data['data']:
            return []
        
        # Extract log lines as (timestamp, message) tuples
        matching_logs = []
        for stream in data['data']['result']:
            for value in stream['values']:
                log_line = value[1]  # The log message is the second element
                timestamp_ns = value[0]  # The timestamp in nanoseconds
                matching_logs.append((timestamp_ns, log_line))
        
        return matching_logs
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error querying Loki: {str(e)}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response text: {e.response.text}")
        app_state['error_count'] += 1
        app_state['loki_connected'] = False
        return []
    except Exception as e:
        logger.error(f"Unexpected error querying Loki: {str(e)}")
        app_state['error_count'] += 1
        return []

def parse_interval(interval: str) -> int:
    """Parse interval string (e.g., '1m', '5m', '1h') into seconds."""
    unit = interval[-1]
    value = int(interval[:-1])
    
    if unit == 's':
        return value
    elif unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    else:
        raise ValueError(f"Invalid interval unit: {unit}")

@app.route('/health')
def health_check():
    """Health check endpoint for Kubernetes liveness probe."""
    if not app_state['configs_loaded']:
        return jsonify({
            'status': 'error',
            'message': 'No configurations loaded'
        }), 503
    
    if app_state['error_count'] > 10:  # Too many errors
        return jsonify({
            'status': 'error',
            'message': f'Too many errors: {app_state["error_count"]}'
        }), 503
    
    if not app_state['loki_connected']:
        return jsonify({
            'status': 'error',
            'message': 'Loki connection lost',
            'connection_attempts': app_state['loki_connection_attempts']
        }), 503
    
    return jsonify({
        'status': 'healthy',
        'configs_loaded': app_state['configs_loaded'],
        'last_check': app_state['last_check'],
        'error_count': app_state['error_count'],
        'loki_connected': app_state['loki_connected']
    }), 200

def run_flask():
    """Run the Flask application."""
    app.run(host='0.0.0.0', port=8080)

def main():
    # Create configuration directory if it doesn't exist
    config_dir = "/app/configuration"
    os.makedirs(config_dir, exist_ok=True)
    
    # Initialize message cache
    cache = MessageCache()
    
    # Load all configuration files
    config_files = glob.glob(os.path.join(config_dir, "*.yaml"))
    if not config_files:
        logger.error(f"No configuration files found in {config_dir}")
        app_state['configs_loaded'] = False
    else:
        configs = []
        for config_file in config_files:
            configs.extend(load_config(config_file))
        
        if not configs:
            logger.error("No valid configurations loaded")
            app_state['configs_loaded'] = False
        else:
            logger.info(f"Loaded {len(configs)} configuration(s)")
            app_state['configs_loaded'] = True
            
            # Start the main loop in a separate thread
            def run_main_loop():
                while True:
                    for config in configs:
                        try:
                            # Query Loki for matching logs
                            matching_logs = query_loki(config)
                            
                            # Send notifications for each matching log
                            for log_entry in matching_logs:
                                send_slack_notification(config, log_entry, cache)
                                
                        except Exception as e:
                            logger.error(f"Error processing config {config.name}: {str(e)}")
                            app_state['error_count'] += 1
                    
                    # Update last check time
                    app_state['last_check'] = datetime.now().isoformat()
                    
                    # Sleep for the shortest interval among all configs
                    min_interval = min(parse_interval(config.loki.interval) for config in configs)
                    time.sleep(min_interval)
            
            # Start the main loop in a separate thread
            main_thread = threading.Thread(target=run_main_loop, daemon=True)
            main_thread.start()
    
    # Start the Flask application
    run_flask()

if __name__ == "__main__":
    main() 