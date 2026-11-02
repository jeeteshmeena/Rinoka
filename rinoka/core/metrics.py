from prometheus_client import Counter, Gauge

EventCount = Counter(
    "rinoka_event_count",
    "Number of events being processed",
    labelnames=["type"],
)
SpamPredictionStat = Counter(
    "rinoka_spam_prediction_stat",
    "Number of spam prediction event",
    labelnames=["status"],
)
MessageStat = Counter(
    "rinoka_message_stat",
    "Number of message",
    labelnames=["type"],
)
CommandCount = Counter("rinoka_command_stats", "Number of coomand", labelnames=["name"])
UnhandledError = Counter("rinoka_unhandled_error", "Number of unhandled error", labelnames=["type"])

EventLatencySecond = Gauge(
    "rinoka_event_latency",
    "Latency of event processed",
    labelnames=["type"],
    unit="second",
)
CommandLatencySecond = Gauge(
    "rinoka_command_latency",
    "Latency of command processed",
    labelnames=["name"],
    unit="second",
)
