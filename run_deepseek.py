import os
import sys
from datetime import datetime, timedelta

# Set proxy for yfinance (Clash Verge - 糖果云)
os.environ['http_proxy'] = 'http://127.0.0.1:7897'
os.environ['https_proxy'] = 'http://127.0.0.1:7897'

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Parse command line arguments
ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
date = sys.argv[2] if len(sys.argv) > 2 else datetime.now().strftime("%Y-%m-%d")

# Create a custom config - use DeepSeek
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-chat"
config["quick_think_llm"] = "deepseek-chat"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["output_language"] = "Chinese"

# Configure data vendors (yfinance, no extra API keys needed)
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# Run analysis
print("=" * 60)
print(f"TradingAgents - DeepSeek Chat - {ticker} Analysis ({date})")
print("=" * 60)

_, decision = ta.propagate(ticker, date)
print("\n" + "=" * 60)
print("FINAL DECISION:")
print("=" * 60)
print(decision)
