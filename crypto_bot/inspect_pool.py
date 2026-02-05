import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SUBGRAPH_API_KEY")
SUBGRAPH_ID = "3hCPRGf4z88VC5rsBKU5AA9FBBq5nF3jbKJG7VZCbhjm"
ENDPOINT = f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

QUERY = """
query {
  pool(id: "0xb6e57ed85c4c9dbfef2a68711e9d6f36c56e0fcb") {
    token0 { symbol id }
    token1 { symbol id }
  }
}
"""

resp = requests.post(ENDPOINT, json={"query": QUERY})
print(resp.json())
