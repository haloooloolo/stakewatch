from abc import ABC, abstractmethod

import discord
from web3 import AsyncWeb3
from web3.types import LogReceipt
from web3.contract import AsyncContract
from web3._utils.filters import AsyncLogFilter
from eth_typing import BlockNumber

BLOCK_EXPLORER_URL = 'https://etherscan.io'

class Event(ABC):
    def __init__(self, w3: AsyncWeb3, vault_name: str, vault_contract: AsyncContract, receipt: LogReceipt):
        self.w3: AsyncWeb3 = w3
        self.vault_name: str = vault_name
        self.vault_contract: AsyncContract = vault_contract
        self.block: BlockNumber = receipt["blockNumber"]
        self.tx_idx: int = receipt["transactionIndex"]
        self.tx_hash: str = receipt["transactionHash"].to_0x_hex()
        self.args: dict = receipt.get('args', {})
        
    @staticmethod
    @abstractmethod
    async def get_filter(contract: AsyncContract, from_block: BlockNumber, to_block: BlockNumber) -> AsyncLogFilter:
        pass
    
    @abstractmethod
    async def to_embed(self) -> discord.Embed:
        pass

class DepositEvent(Event):    
    @staticmethod
    async def get_filter(contract: AsyncContract, from_block: BlockNumber, to_block: BlockNumber) -> AsyncLogFilter:
        return await contract.events.Deposited.create_filter(from_block=from_block, to_block=to_block)
    
    async def to_embed(self) -> discord.Embed:
        amount = self.w3.from_wei(self.args["assets"], 'ether')
        sender = self.args["caller"]
        timestamp = (await self.w3.eth.get_block(self.block)).get("timestamp", 0)
        return discord.Embed(
            title='**New Deposit**', 
            color=discord.Color.green(),
            description=(
                f'🏦 [{self.vault_name}]({BLOCK_EXPLORER_URL}/address/{self.vault_contract.address})\n'
                f'💵 **{amount:,.6g} ETH**\n'
                f'🪪 [{sender[:10]}...{sender[-8:]}]({BLOCK_EXPLORER_URL}/address/{sender})\n'
                f'🧾 [{self.tx_hash[:10]}...{self.tx_hash[-8:]}]({BLOCK_EXPLORER_URL}/tx/{self.tx_hash})\n'
                f'🕒 <t:{timestamp}:R>'
            )
        )
        
class ExitEvent(Event):        
    @staticmethod
    async def get_filter(contract: AsyncContract, from_block: BlockNumber, to_block: BlockNumber) -> AsyncLogFilter:
        return await contract.events.ExitQueueEntered.create_filter(from_block=from_block, to_block=to_block)
    
    async def to_embed(self) -> discord.Embed:
        assets = await self.vault_contract.functions.convertToAssets(self.args["shares"]).call(block_identifier=self.block)
        amount = self.w3.from_wei(assets, 'ether')
        sender = self.args["owner"]
        timestamp = (await self.w3.eth.get_block(self.block)).get("timestamp", 0)
        return discord.Embed(
            title='**New Withdrawal**', 
            color=discord.Color.red(),
            description=(
                f'🏦 [{self.vault_name}]({BLOCK_EXPLORER_URL}/address/{self.vault_contract.address})\n'
                f'💵 **-{amount:,.6g} ETH**\n'
                f'🪪 [{sender[:10]}...{sender[-8:]}]({BLOCK_EXPLORER_URL}/address/{sender})\n'
                f'🧾 [{self.tx_hash[:10]}...{self.tx_hash[-8:]}]({BLOCK_EXPLORER_URL}/tx/{self.tx_hash})\n'
                f'🕒 <t:{timestamp}:R>'
            )
        )
