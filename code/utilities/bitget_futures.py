import ccxt
import time
import pandas as pd
from typing import Any, Optional, Dict, List

class BitgetFutures:
    def _init_(self, api_setup: Optional[Dict[str, Any]] = None) -> None:
        self.symbol_mapping = {
            'SOL/USDT:USDT': 'SOLUSDT_UMCBL',
            # Add more symbol mappings as needed
        }
        
        if api_setup is None:
            self.session = ccxt.bitget({'options': {'defaultType': 'future'}})
        else:
            api_setup.setdefault("options", {"defaultType": "future"})
            self.session = ccxt.bitget(api_setup)

        self.markets = self.session.load_markets()

    def _convert_symbol(self, symbol: str) -> str:
        """Convert CCXT symbol to Bitget-specific symbol"""
        return self.symbol_mapping.get(symbol, symbol)

    def _get_bitget_side(self, side: str, position_side: str = None) -> str:
        """Convert generic side to Bitget-specific side"""
        if position_side == 'long':
            return 'close_long' if side == 'sell' else 'open_long'
        elif position_side == 'short':
            return 'close_short' if side == 'buy' else 'open_short'
        return side

    def fetch_min_amount_tradable(self, symbol: str) -> float:
        bitget_symbol = self._convert_symbol(symbol)
        return self.markets[bitget_symbol]['limits']['amount']['min']

    def fetch_open_trigger_orders(self, symbol: str) -> List[Dict[str, Any]]:
        bitget_symbol = self._convert_symbol(symbol)
        return self.session.fetch_open_orders(bitget_symbol, params={'stop': True})

    def cancel_trigger_order(self, id: str, symbol: str) -> Dict[str, Any]:
        bitget_symbol = self._convert_symbol(symbol)
        return self.session.cancel_order(id, bitget_symbol, params={'stop': True})

    def fetch_open_positions(self, symbol: str) -> List[Dict[str, Any]]:
        bitget_symbol = self._convert_symbol(symbol)
        positions = self.session.fetch_positions(
            [bitget_symbol], 
            params={'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
        )
        return [p for p in positions if float(p['contracts']) > 0]

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, 
                                  trigger_price: float, reduce: bool = False, 
                                  print_error: bool = False) -> Optional[Dict[str, Any]]:
        try:
            bitget_symbol = self._convert_symbol(symbol)
            position_side = 'long' if side == 'sell' else 'short'
            bitget_side = self._get_bitget_side(side, position_side)

            params = {
                'triggerPrice': self.price_to_precision(bitget_symbol, trigger_price),
                'planType': 'normal_plan',
                'reduceOnly': reduce,
                'triggerType': 'market_price',
                'marginCoin': 'USDT'
            }

            return self.session.create_order(
                symbol=bitget_symbol,
                type='market',
                side=bitget_side,
                amount=self.amount_to_precision(bitget_symbol, amount),
                params=params
            )
        except Exception as err:
            if print_error:
                print(f"Trigger Market Order Error: {err}")
            return None

    def place_trigger_limit_order(self, symbol: str, side: str, amount: float, 
                                 trigger_price: float, price: float, 
                                 reduce: bool = False, print_error: bool = False) -> Optional[Dict[str, Any]]:
        try:
            bitget_symbol = self._convert_symbol(symbol)
            position_side = 'long' if side == 'buy' else 'short'
            bitget_side = self._get_bitget_side(side, position_side)

            params = {
                'triggerPrice': self.price_to_precision(bitget_symbol, trigger_price),
                'executePrice': self.price_to_precision(bitget_symbol, price),
                'planType': 'normal_plan',
                'reduceOnly': reduce,
                'triggerType': 'market_price',
                'marginCoin': 'USDT'
            }

            return self.session.create_order(
                symbol=bitget_symbol,
                type='limit',
                side=bitget_side,
                amount=self.amount_to_precision(bitget_symbol, amount),
                price=self.price_to_precision(bitget_symbol, price),
                params=params
            )
        except Exception as err:
            if print_error:
                print(f"Trigger Limit Order Error: {err}")
            return None

    # Keep other methods but add symbol conversion where needed
    def fetch_recent_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        bitget_symbol = self._convert_symbol(symbol)
        # ... rest of the method remains the same but use bitget_symbol ...

    def set_leverage(self, symbol: str, margin_mode: str = 'isolated', leverage: int = 1) -> None:
        bitget_symbol = self._convert_symbol(symbol)
        # ... rest of the method remains the same but use bitget_symbol ...