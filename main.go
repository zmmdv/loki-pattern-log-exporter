package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"regexp"
	"sync"
	"time"

	"github.com/grafana/loki/pkg/logcli/client"
	"github.com/grafana/loki/pkg/logcli/query"
	"github.com/slack-go/slack"
	"gopkg.in/yaml.v3"
)

// MessageCache represents a cache of recently sent messages
type MessageCache struct {
	messages map[string]time.Time
	mu       sync.RWMutex
	window   time.Duration
}

// NewMessageCache creates a new message cache with the specified time window
func NewMessageCache(window time.Duration) *MessageCache {
	return &MessageCache{
		messages: make(map[string]time.Time),
		window:   window,
	}
}

// Add adds a message to the cache
func (c *MessageCache) Add(message string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.messages[message] = time.Now()
}

// Contains checks if a message is in the cache and not expired
func (c *MessageCache) Contains(message string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	
	if timestamp, exists := c.messages[message]; exists {
		if time.Since(timestamp) < c.window {
			return true
		}
		// Message exists but is expired, remove it
		c.mu.RUnlock()
		c.mu.Lock()
		delete(c.messages, message)
		c.mu.Unlock()
		c.mu.RLock()
	}
	return false
}

// Cleanup removes expired messages from the cache
func (c *MessageCache) Cleanup() {
	c.mu.Lock()
	defer c.mu.Unlock()
	
	now := time.Now()
	for message, timestamp := range c.messages {
		if now.Sub(timestamp) > c.window {
			delete(c.messages, message)
		}
	}
}

type Config struct {
	Loki struct {
		Endpoint string `yaml:"endpoint" env:"LOKI_ENDPOINT"`
		Query    string `yaml:"query" env:"LOKI_QUERY"`
		Pattern  string `yaml:"pattern" env:"LOKI_PATTERN"`
		Interval string `yaml:"interval" env:"LOKI_INTERVAL"`
	} `yaml:"loki"`
	Slack struct {
		Token   string `yaml:"token" env:"SLACK_TOKEN"`
		Channel string `yaml:"channel" env:"SLACK_CHANNEL"`
	} `yaml:"slack"`
}

func loadConfig(path string) (*Config, error) {
	config := &Config{}

	// Set default values
	config.Loki.Endpoint = "http://localhost:3100"
	config.Loki.Query = "{job=\"your-job-name\"}"
	config.Loki.Pattern = "error|exception|critical"
	config.Loki.Interval = "1m"

	// Try to load from config file if it exists
	if _, err := os.Stat(path); err == nil {
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("error reading config file: %v", err)
		}

		err = yaml.Unmarshal(data, config)
		if err != nil {
			return nil, fmt.Errorf("error parsing config file: %v", err)
		}
	}

	// Override with environment variables if they exist
	if env := os.Getenv("LOKI_ENDPOINT"); env != "" {
		config.Loki.Endpoint = env
	}
	if env := os.Getenv("LOKI_QUERY"); env != "" {
		config.Loki.Query = env
	}
	if env := os.Getenv("LOKI_PATTERN"); env != "" {
		config.Loki.Pattern = env
	}
	if env := os.Getenv("LOKI_INTERVAL"); env != "" {
		config.Loki.Interval = env
	}
	if env := os.Getenv("SLACK_TOKEN"); env != "" {
		config.Slack.Token = env
	}
	if env := os.Getenv("SLACK_CHANNEL"); env != "" {
		config.Slack.Channel = env
	}

	// Validate required fields
	if config.Slack.Token == "" {
		return nil, fmt.Errorf("SLACK_TOKEN is required")
	}
	if config.Slack.Channel == "" {
		return nil, fmt.Errorf("SLACK_CHANNEL is required")
	}

	return config, nil
}

func queryLoki(cfg *Config, pattern *regexp.Regexp) ([]string, error) {
	client := client.New(cfg.Loki.Endpoint, nil)
	q := query.NewQuery(cfg.Loki.Query, time.Now().Add(-time.Minute), time.Now(), 0, 0, false, false, false)

	results, err := client.Query(q)
	if err != nil {
		return nil, fmt.Errorf("error querying Loki: %v", err)
	}

	var matches []string
	for _, stream := range results.Data.Result {
		for _, value := range stream.Values {
			if pattern.MatchString(value[1]) {
				matches = append(matches, fmt.Sprintf("Found pattern in log: %s", value[1]))
			}
		}
	}

	return matches, nil
}

func sendSlackNotification(cfg *Config, messages []string, cache *MessageCache) error {
	api := slack.New(cfg.Slack.Token)
	
	for _, msg := range messages {
		// Check if message was recently sent
		if cache.Contains(msg) {
			log.Printf("Skipping duplicate message: %s", msg)
			continue
		}

		_, _, err := api.PostMessage(
			cfg.Slack.Channel,
			slack.MsgOptionText(msg, false),
		)
		if err != nil {
			return fmt.Errorf("error sending Slack message: %v", err)
		}

		// Add message to cache after successful send
		cache.Add(msg)
		log.Printf("Sent message to Slack: %s", msg)
	}
	
	return nil
}

func main() {
	configPath := flag.String("config", "config.yaml", "path to config file")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	pattern, err := regexp.Compile(cfg.Loki.Pattern)
	if err != nil {
		log.Fatalf("Failed to compile pattern: %v", err)
	}

	interval, err := time.ParseDuration(cfg.Loki.Interval)
	if err != nil {
		log.Fatalf("Failed to parse interval: %v", err)
	}

	// Create message cache with 1 hour window
	messageCache := NewMessageCache(1 * time.Hour)

	// Start cache cleanup goroutine
	go func() {
		ticker := time.NewTicker(15 * time.Minute)
		defer ticker.Stop()
		for range ticker.C {
			messageCache.Cleanup()
		}
	}()

	log.Printf("Starting Loki pattern monitor...")
	log.Printf("Monitoring pattern: %s", cfg.Loki.Pattern)
	log.Printf("Check interval: %s", interval)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			matches, err := queryLoki(cfg, pattern)
			if err != nil {
				log.Printf("Error querying Loki: %v", err)
				continue
			}

			if len(matches) > 0 {
				err = sendSlackNotification(cfg, matches, messageCache)
				if err != nil {
					log.Printf("Error sending Slack notification: %v", err)
				}
			}
		}
	}
} 