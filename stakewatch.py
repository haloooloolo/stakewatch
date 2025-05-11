import os
import json
import logging
import argparse
from typing import Any, Optional

import discord
from discord.ext import tasks, commands

from web3 import Web3
from web3.contract import Contract
from eth_typing import BlockNumber

logging.basicConfig(format='%(levelname)5s %(asctime)s [%(name)s] %(message)s')
logging.getLogger().setLevel('INFO')
logger = logging.getLogger('StakeWatch')

BLOCK_EXPLORER_URL = 'https://etherscan.io'

class StakeWatch(commands.Cog):
    def __init__(self, bot: commands.Bot, cl_args: argparse.Namespace):
        self.bot = bot
        self.w3 = Web3(Web3.HTTPProvider(cl_args.rpc))
        self.vaults = self._get_vaults()
        self.state = {
            'last_block': 22319339
        } | (self._load_state() or {})
        self._channel_id = cl_args.channel
        self.batch_size = cl_args.batch_size
        self.channel = None
        self.fetch_events.start()
        
    def _get_vaults(self) -> dict[str, Contract]:
        with open('res/vault.abi.json', 'r') as f:
            abi = f.read()
        vault_addresses = {
            'Private Vault': '0xB266274F55e784689e97b7E363B0666d92e6305B'
        }
        return {name: self.w3.eth.contract(address=addr, abi=abi) for name, addr in vault_addresses.items()}
                
    def _load_state(self) -> Optional[dict[str, Any]]:
        try:
            with open('res/state.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning('State file not found')
            return None
        
    def _save_state(self, state: dict[str, Any]):
        with open('res/state.json', 'w') as f:
            json.dump(state, f, indent=4)
                
    def cog_unload(self):
        self.fetch_events.cancel()
        
    def on_ready(self):
        logger.info(f'Logged in as {self.bot.user}')
        
    @tasks.loop(seconds=30)
    async def fetch_events(self):
        from_block = self.state['last_block'] + 1
        to_block = min(self.w3.eth.block_number, from_block + self.batch_size - 1)
        
        if to_block < from_block:
            logger.warning('No new blocks to process')
            return

        logger.info(f'Fetching events in [{from_block}, {to_block}]')
        
        embeds: list[tuple[BlockNumber, discord.Embed]] = []
        embeds += self.get_deposit_events(from_block, to_block)
        embeds += self.get_exit_events(from_block, to_block)
                
        for block_id, embed in sorted(embeds):
            await self.channel.send(embed=embed)
        
        self.state['last_block'] = to_block
        self._save_state(self.state)
        
    @fetch_events.before_loop
    async def setup(self):
        await self.bot.wait_until_ready()
        self.channel = await self.bot.fetch_channel(self._channel_id)
            
    def get_deposit_events(self, from_block: BlockNumber, to_block: BlockNumber) -> list[tuple[BlockNumber, discord.Embed]]:
        embeds = []
        for vault_name, vault_contract in self.vaults.items():
            event_filter = vault_contract.events.Deposited.create_filter(from_block=from_block, to_block=to_block) 
            for event in event_filter.get_all_entries():
                logger.debug(f'New deposit event: {vault_name}: {event}')
                amount = self.w3.from_wei(event.args.assets, 'ether')
                sender = event.args.caller
                tx_hash = '0x' + event.transactionHash.hex()
                block_number = event.blockNumber
                timestamp = self.w3.eth.get_block(block_number).timestamp
                embed = discord.Embed(
                    title='**New Deposit**', 
                    color=discord.Color.green(),
                    description=(
                        f'🏦 [{vault_name}]({BLOCK_EXPLORER_URL}/address/{vault_contract.address})\n'
                        f'💵 **{amount:,.6g} ETH**\n'
                        f'🪪 [{sender[:10]}...{sender[-8:]}]({BLOCK_EXPLORER_URL}/address/{sender})\n'
                        f'🧾 [{tx_hash[:10]}...{tx_hash[-8:]}]({BLOCK_EXPLORER_URL}/tx/{tx_hash})\n'
                        f'🕒 <t:{timestamp}:R>'
                    )
                )
                embeds.append((block_number, embed))
        return embeds
    
    def get_exit_events(self, from_block: BlockNumber, to_block: BlockNumber) -> list[tuple[BlockNumber, discord.Embed]]:
        embeds = []
        for vault_name, vault_contract in self.vaults.items():
            event_filter = vault_contract.events.ExitQueueEntered.create_filter(from_block=from_block, to_block=to_block) 
            for event in event_filter.get_all_entries():
                logger.debug(f'New withdrawal event: {vault_name}: {event}')
                assets = vault_contract.functions.convertToAssets(event.args.shares).call(block_identifier=event.blockNumber)
                amount = self.w3.from_wei(assets, 'ether')
                sender = event.args.owner
                tx_hash = '0x' + event.transactionHash.hex()
                block_number = event.blockNumber
                timestamp = self.w3.eth.get_block(block_number).timestamp
                embed = discord.Embed(
                    title='**New Withdrawal**', 
                    color=discord.Color.red(),
                    description=(
                        f'🏦 [{vault_name}]({BLOCK_EXPLORER_URL}/address/{vault_contract.address})\n'
                        f'💵 **-{amount:,.6g} ETH**\n'
                        f'🪪 [{sender[:10]}...{sender[-8:]}]({BLOCK_EXPLORER_URL}/address/{sender})\n'
                        f'🧾 [{tx_hash[:10]}...{tx_hash[-8:]}]({BLOCK_EXPLORER_URL}/tx/0x{tx_hash})\n'
                        f'🕒 <t:{timestamp}:R>'
                    )
                )
                embeds.append((block_number, embed))
        return embeds
        
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='stakewatch')
    parser.add_argument('-r', '--rpc', type=str, help='Ethereum RPC URL', required=True)
    parser.add_argument('-c', '--channel', type=int, help='Discord event channel I.', required=True)
    parser.add_argument('--batch-size', type=int, help='Maximum number of blocks to process in one request', default=10_000)
    return parser.parse_args()

bot = commands.Bot(intents=discord.Intents.none(), command_prefix=())

@bot.event
async def setup_hook():
    args = parse_args()
    cog = StakeWatch(bot, args)
    await bot.add_cog(cog)
    
token = os.getenv('DISCORD_TOKEN')
bot.run(token)
