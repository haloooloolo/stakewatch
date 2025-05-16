import os
import json
import logging
import argparse
from operator import attrgetter
from typing import Any, Optional, TypeVar, cast

import discord
from discord.abc import Messageable
from discord.ext import tasks, commands

from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3._utils.filters import AsyncLogFilter
from eth_typing import BlockNumber

from events import Event, Deposit, ExitRequest, ValidatorRegistration

logging.basicConfig(format='%(levelname)5s %(asctime)s [%(name)s] %(message)s')
logging.getLogger().setLevel('INFO')
logger = logging.getLogger('StakeWatch')

E = TypeVar('E', bound=Event)

class StakeWatch(commands.Cog):
    def __init__(self, bot: commands.Bot, cl_args: argparse.Namespace):
        self.bot = bot
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(cl_args.rpc))
        self.vaults = self._get_vaults()
        self.state: dict[str, Any] = {
            'last_block': 22319339
        } | (self._load_state() or {})
        self.cl_args = cl_args
        self.event_channel: Messageable = Messageable()
        self.error_channel: Optional[Messageable] = None
        self.fetch_events.start()
        
    def _get_vaults(self) -> dict[str, AsyncContract]:
        with open('res/vaults.json', 'r') as f:
            vault_addresses = json.load(f)
        with open('res/vault.abi.json', 'r') as f:
            abi = f.read()
        return {name: self.w3.eth.contract(address=addr, abi=abi) for name, addr in vault_addresses.items()}
                
    def _load_state(self) -> Optional[dict[str, Any]]:
        try:
            with open('res/state.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning('State file not found')
            return None
        
    def _save_state(self, state: dict[str, Any]) -> None:
        with open('res/state.json', 'w') as f:
            json.dump(state, f, indent=4)
                
    async def cog_unload(self) -> None:
        self.fetch_events.cancel()
        
    def on_ready(self) -> None:
        logger.info(f'Logged in as {self.bot.user}')
        
    @tasks.loop(seconds=30)
    async def fetch_events(self) -> None:
        from_block = self.state['last_block'] + 1
        latest_block = await self.w3.eth.block_number
        to_block = min(latest_block, from_block + self.cl_args.batch_size - 1)
        
        if to_block < from_block:
            logger.warning('No new blocks to process')
            return

        logger.info(f'Fetching events in [{from_block}, {to_block}]')
        
        events: list[Event] = []
        events += await self._get_events_in_range(Deposit, from_block, to_block)
        events += await self._get_events_in_range(ExitRequest, from_block, to_block)
        events += await self._get_events_in_range(ValidatorRegistration, from_block, to_block)
                
        for event in sorted(events, key=attrgetter('block', 'tx_idx')):
            embed = await event.to_embed()
            vault_balance = await self.w3.eth.get_balance(event.vault_contract.address, block_identifier=event.block)
            embed.set_footer(text=f'Vault Balance: {self.w3.from_wei(vault_balance, "ether"):.2f} ETH')
            await self.event_channel.send(embed=embed)
        
        self.state['last_block'] = to_block
        self._save_state(self.state)
        
    async def _get_events_in_range(self, event_type: type[E], from_block: BlockNumber, to_block: BlockNumber) -> list[E]:
        events: list[E] = []
        for vault_name, vault_contract in self.vaults.items():
            log_filter: AsyncLogFilter = await event_type.get_contract_event(vault_contract).create_filter(from_block=from_block, to_block=to_block)
            
            events_by_tx = {}
            for receipt in await log_filter.get_all_entries():
                logger.info(f'New event: {vault_name}: {receipt}')
                if receipt['transactionHash'] not in events_by_tx:
                    events_by_tx[receipt['transactionHash']] = []
                events_by_tx[receipt['transactionHash']].append(receipt)
                
            for tx_hash, receipts in events_by_tx.items():
                event = event_type(self.w3, vault_name, vault_contract, receipts)
                events.append(event)
                
        return events
        
    @fetch_events.before_loop
    async def setup(self) -> None:
        await self.bot.wait_until_ready()
        self.event_channel = cast(Messageable, await self.bot.fetch_channel(self.cl_args.channel))
        if self.cl_args.errors:
            self.error_channel = cast(Messageable, await self.bot.fetch_channel(self.cl_args.errors))
            
    @fetch_events.error
    async def on_error(self, error: BaseException) -> None:
        logger.exception('Failed to process events')
        if self.error_channel:
            await self.error_channel.send(str(error))
    
        
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='stakewatch')
    parser.add_argument('-r', '--rpc', type=str, help='Ethereum RPC URL', required=True)
    parser.add_argument('-c', '--channel', type=int, help='Discord channel ID for events', required=True)
    parser.add_argument('-e', '--errors', type=int, help='Discord channel ID for events', required=False)
    parser.add_argument('--batch-size', type=int, help='Maximum number of processed blocks per iteration', default=10_000)
    return parser.parse_args()


def main():  
    args = parse_args()
    if not (token := os.getenv('DISCORD_TOKEN')):
        raise ValueError('DISCORD_TOKEN environment variable not set')
    
    bot = commands.Bot(intents=discord.Intents.none(), command_prefix=())
    
    @bot.event
    async def setup_hook():
        cog = StakeWatch(bot, args)
        await bot.add_cog(cog)
    
    bot.run(token)
    
    
if __name__ == '__main__':
    main()
