from abc import ABC, abstractmethod
from typing import cast

import discord
from web3 import AsyncWeb3
from web3.types import LogReceipt
from web3.contract import AsyncContract
from web3.contract.async_contract import AsyncContractEvent
from eth_typing import BlockNumber, HexStr

EL_EXPLORER_URL = 'https://etherscan.io'
CL_EXPLORER_URL = 'https:/beaconcha.in'

class Event(ABC):
    def __init__(self, w3: AsyncWeb3, vault_name: str, vault_contract: AsyncContract, receipts: list[LogReceipt]):
        self.w3: AsyncWeb3 = w3
        self.vault_name: str = vault_name
        self.vault_contract: AsyncContract = vault_contract
        self.block: BlockNumber = receipts[0]['blockNumber']
        self.tx_idx: int = receipts[0]['transactionIndex']
        self.tx_hash: HexStr = cast(HexStr, receipts[0]['transactionHash'].to_0x_hex())
        self.args: list[dict] = [receipt.get('args', {}) for receipt in receipts]
        
    @staticmethod
    @abstractmethod
    def get_contract_event(contract: AsyncContract) -> AsyncContractEvent:
        pass
    
    @abstractmethod
    async def to_embed(self) -> discord.Embed:
        pass

class Deposit(Event):    
    @staticmethod
    def get_contract_event(contract: AsyncContract) -> AsyncContractEvent:
        return contract.events.Deposited
    
    async def to_embed(self) -> discord.Embed:
        amount = self.w3.from_wei(sum(args['assets'] for args in self.args), 'ether')
        sender = self.args[0]['caller']
        timestamp = (await self.w3.eth.get_block(self.block)).get('timestamp', 0)
        return discord.Embed(
            title='**New Deposit**', 
            color=discord.Color.green(),
            description=(
                f'🏦 [{self.vault_name}]({EL_EXPLORER_URL}/address/{self.vault_contract.address})\n'
                f'💵 **{amount:,.6g} ETH**\n'
                f'🪪 [{sender[:10]}...{sender[-8:]}]({EL_EXPLORER_URL}/address/{sender})\n'
                f'🧾 [{self.tx_hash[:10]}...{self.tx_hash[-8:]}]({EL_EXPLORER_URL}/tx/{self.tx_hash})\n'
                f'🕒 <t:{timestamp}:R>'
            )
        )
        
class ExitRequest(Event):        
    @staticmethod
    def get_contract_event(contract: AsyncContract) -> AsyncContractEvent:
        return contract.events.ExitQueueEntered
    
    async def to_embed(self) -> discord.Embed:
        shares = sum(args['shares'] for args in self.args)
        assets = await self.vault_contract.functions.convertToAssets(shares).call(block_identifier=self.block)
        amount = self.w3.from_wei(assets, 'ether')
        sender = self.args[0]['owner']
        timestamp = (await self.w3.eth.get_block(self.block)).get('timestamp', 0)
        return discord.Embed(
            title='**New Withdrawal**', 
            color=discord.Color.red(),
            description=(
                f'🏦 [{self.vault_name}]({EL_EXPLORER_URL}/address/{self.vault_contract.address})\n'
                f'💵 **-{amount:,.6g} ETH**\n'
                f'🪪 [{sender[:10]}...{sender[-8:]}]({EL_EXPLORER_URL}/address/{sender})\n'
                f'🧾 [{self.tx_hash[:10]}...{self.tx_hash[-8:]}]({EL_EXPLORER_URL}/tx/{self.tx_hash})\n'
                f'🕒 <t:{timestamp}:R>'
            )
        )
        
class ValidatorRegistration(Event):        
    @staticmethod
    def get_contract_event(contract: AsyncContract) -> AsyncContractEvent:
        return contract.events.ValidatorRegistered
    
    async def to_embed(self) -> discord.Embed:
        pubkeys = ['0x' + args['publicKey'].hex() for args in self.args]
        timestamp = (await self.w3.eth.get_block(self.block)).get('timestamp', 0)
        validator_lines = "\n".join(f"📡 [{pubkey[:10]}...{pubkey[-8:]}]({CL_EXPLORER_URL}/validator/{pubkey})" for pubkey in pubkeys)
        return discord.Embed(
            title='**New Validator**' if (len(pubkeys) == 1) else '**New Validators**', 
            color=discord.Color.blue(),
            description=(
                f'🏦 [{self.vault_name}]({EL_EXPLORER_URL}/address/{self.vault_contract.address})\n'
                f'{validator_lines}\n'
                f'🧾 [{self.tx_hash[:10]}...{self.tx_hash[-8:]}]({EL_EXPLORER_URL}/tx/{self.tx_hash})\n'
                f'🕒 <t:{timestamp}:R>'
            )
        )
