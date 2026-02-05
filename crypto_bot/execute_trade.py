import time
from web3 import Web3
from eth_account import Account
import config

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

ROUTER_ABI = [
    {"inputs": [{"components": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint24", "name": "fee", "type": "uint24"}, {"internalType": "address", "name": "recipient", "type": "address"}, {"internalType": "uint256", "name": "deadline", "type": "uint256"}, {"internalType": "uint256", "name": "amountIn", "type": "uint256"}, {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"}, {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}], "internalType": "struct ISwapRouter.ExactInputSingleParams", "name": "params", "type": "tuple"}], "name": "exactInputSingle", "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}], "stateMutability": "payable", "type": "function"}
]

class Trader:
    def __init__(self, rpc_url, private_key):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)
        self.router = self.w3.eth.contract(address=config.ROUTER, abi=ROUTER_ABI)

    def get_balance(self, token_address):
        token = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return token.functions.balanceOf(self.account.address).call()

    def get_decimals(self, token_address):
        token = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return token.functions.decimals().call()

    def approve_if_needed(self, token_address, spender, amount):
        token = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        current_allowance = token.functions.allowance(self.account.address, spender).call()
        if current_allowance < amount:
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            tx = token.functions.approve(spender, 2**256 - 1).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gas': 100000,
                'maxFeePerGas': self.w3.eth.gas_price,
                'maxPriorityFeePerGas': self.w3.eth.max_priority_fee
            })
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            return self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return None

    def swap(self, token_in, token_out, amount_in, fee=500, expected_price=None):
        """
        expected_price: price in USDC per Asset (e.g. ~0.1 for WPOL, ~2500 for WETH)
        """
        self.approve_if_needed(token_in, config.ROUTER, amount_in)

        amount_out_min = 0
        if expected_price:
            d_in = self.get_decimals(token_in)
            d_out = self.get_decimals(token_out)
            if token_in == config.USDC: # BUY
                expected_amount_out = (amount_in * (10**d_out) / (10**d_in)) / expected_price
            else: # SELL
                expected_amount_out = (amount_in * (10**d_out) / (10**d_in)) * expected_price

            amount_out_min = int(expected_amount_out * (1 - config.SLIPPAGE_TOLERANCE))

        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": fee,
            "recipient": self.account.address,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in,
            "amountOutMinimum": amount_out_min,
            "sqrtPriceLimitX96": 0
        }

        nonce = self.w3.eth.get_transaction_count(self.account.address)
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            'from': self.account.address,
            'nonce': nonce,
            'gas': 300000,
            'maxFeePerGas': self.w3.eth.gas_price,
            'maxPriorityFeePerGas': self.w3.eth.max_priority_fee
        })
        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)
