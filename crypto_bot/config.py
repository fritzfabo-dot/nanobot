import os

# API Keys and URLs
SUBGRAPH_API_KEY = os.getenv("SUBGRAPH_API_KEY", "1c31e2f3ca4dafda349a171e8bb9801a")
SUBGRAPH_ID = "3hCPRGf4z88VC5rsBKU5AA9FBBq5nF3jbKJG7VZCbhjm"
ENDPOINT = f"https://gateway-arbitrum.network.thegraph.com/api/{SUBGRAPH_API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Addresses (Polygon)
USDC = "0x3C499c542cEF5E3811e1192ce70d8cC03d5c3359"
WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

# Bot Configuration
POOLS = [
    "0xb6e57ed85c4c9dbfef2a68711e9d6f36c56e0fcb",  # WPOL/USDC
    "0xa4d8c89f0c20efbe54cba9e7e7a7e509056228d9",  # USDC/WETH
]
ASSETS = ["WPOL", "WETH"]

# Risk Management
USDC_PER_TRADE_PERCENT = 0.5 # Use 50% of available USDC per trade
SLIPPAGE_TOLERANCE = 0.01   # 1% slippage protection
