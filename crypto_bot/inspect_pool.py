import requests
API_KEY = "1c31e2f3ca4dafda349a171e8bb9801a"
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
