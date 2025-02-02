import os
import sys
import json
import ta
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))


from utilities.bitget_futures import BitgetFutures

# --- CONFIG ---
params = {
    'symbol': '/USDT:USDT',
    'bitget_symbol': 'SOLUSDT_UMCBL',  # Bitget-specific symbol format
    'timeframe': '1h',
    'margin_mode': 'isolated',
    'balance_fraction': 1,
    'leverage': 3,
    'average_type': 'DCM',
    'average_period': 5,
    'envelopes': [0.07, 0.11, 0.14],
    'stop_loss_pct': 0.4,
    'use_longs': True,
    'use_shorts': True,
}

key_path = 'LiveTradingBots/secret.json'
key_name = 'envelope'
tracker_file = f"LiveTradingBots/code/strategies/envelope/tracker_{params['symbol'].replace('/', '-').replace(':', '-')}.json"
trigger_price_delta = 0.01

# --- AUTHENTICATION ---
print(f"\n{datetime.now().strftime('%H:%M:%S')}: >>> starting execution for {params['symbol']}")
with open(key_path, "r") as f:
    api_setup = json.load(f)[key_name]
bitget = BitgetFutures(api_setup)

# --- TRACKER FILE HANDLING ---
if not os.path.exists(tracker_file):
    with open(tracker_file, 'w') as file:
        json.dump({"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}, file)

def read_tracker():
    with open(tracker_file, 'r') as file:
        return json.load(file)

def update_tracker(data):
    with open(tracker_file, 'w') as file:
        json.dump(data, file)

# --- ORDER MANAGEMENT ---
def cancel_all_orders():
    # Cancel regular orders
    for order in bitget.fetch_open_orders(params['symbol']):
        bitget.cancel_order(order['id'], params['symbol'])
    
    # Cancel trigger orders with Bitget-specific handling
    trigger_orders = bitget.fetch_open_trigger_orders(params['bitget_symbol'])
    long_count = short_count = 0
    for order in trigger_orders:
        if order['info']['planType'] == 'normal_plan':
            if order['side'] == 'buy':
                long_count += 1
            elif order['side'] == 'sell':
                short_count += 1
            bitget.cancel_trigger_order(order['id'], params['bitget_symbol'])
    print(f"{datetime.now().strftime('%H:%M:%S')}: Orders cancelled, {long_count} longs left, {short_count} shorts left")

# --- DATA HANDLING ---
def fetch_and_process_data():
    data = bitget.fetch_recent_ohlcv(params['bitget_symbol'], params['timeframe'], 100).iloc[:-1]
    
    # Calculate indicators
    if params['average_type'] == 'DCM':
        ta_obj = ta.volatility.DonchianChannel(data['high'], data['low'], data['close'], 
                                             window=params['average_period'])
        data['average'] = ta_obj.donchian_channel_mband()
    else:
        raise ValueError(f"Unsupported average type: {params['average_type']}")
    
    # Calculate envelopes
    for i, e in enumerate(params['envelopes']):
        data[f'band_high_{i+1}'] = data['average'] / (1 - e)
        data[f'band_low_{i+1}'] = data['average'] * (1 - e)
    
    print(f"{datetime.now().strftime('%H:%M:%S')}: OHLCV data processed")
    return data

# --- ORDER PLACEMENT WITH ERROR HANDLING ---
def place_order_safely(order_func, **kwargs):
    try:
        response = order_func(**kwargs)
        if 'code' in response and response['code'] != '00000':
            print(f"Order failed: {response['msg']}")
            return None
        return response
    except Exception as e:
        print(f"Order error: {str(e)}")
        return None

# --- STOP LOSS HANDLING ---
def handle_stop_losses():
    tracker = read_tracker()
    closed_orders = bitget.fetch_closed_trigger_orders(params['bitget_symbol'])
    
    if closed_orders and any(o['id'] in tracker['stop_loss_ids'] for o in closed_orders):
        update_tracker({
            "status": "stop_loss_triggered",
            "last_side": tracker['last_side'],
            "stop_loss_ids": []
        })
        print(f"{datetime.now().strftime('%H:%M:%S')}: Stop loss triggered")

# --- POSITION MANAGEMENT ---
def manage_positions(data):
    positions = bitget.fetch_open_positions(params['bitget_symbol'])
    
    if len(positions) > 1:
        positions.sort(key=lambda x: x['timestamp'], reverse=True)
        for pos in positions[1:]:
            place_order_safely(
                bitget.flash_close_position,
                symbol=params['bitget_symbol'],
                side=pos['side']
            )
    
    return positions[0] if positions else None

# --- MAIN LOGIC ---
if __name__ == "__main__":
    try:
        # Initial setup
        cancel_all_orders()
        data = fetch_and_process_data()
        handle_stop_losses()
        position = manage_positions(data)
        
        # Trading logic
        tracker = read_tracker()
        if tracker['status'] != "ok_to_trade":
            current_price = data['close'].iloc[-1]
            resume_price = data['average'].iloc[-1]

            if (tracker['last_side'] == 'long' and current_price >= resume_price) or \
               (tracker['last_side'] == 'short' and current_price <= resume_price):
                update_tracker({"status": "ok_to_trade", "last_side": tracker['last_side']})

        if not position:
            bitget.set_margin_mode(params['bitget_symbol'], params['margin_mode'])
            bitget.set_leverage(params['bitget_symbol'], params['leverage'])

        # Calculate balance
        balance = params['balance_fraction'] * params['leverage'] * bitget.fetch_balance()['USDT']['total']
        print(f"{datetime.now().strftime('%H:%M:%S')}: Trading balance: {balance:.2f} USDT")

        # Order placement logic
        tracker_info = {
            "status": "ok_to_trade",
            "last_side": tracker['last_side'],
            "stop_loss_ids": []
        }

        # Long positions logic
        if params['use_longs'] and (not position or position['side'] == 'long'):
            for i in range(len(params['envelopes'])):
                entry_price = data[f'band_low_{i+1}'].iloc[-1]
                trigger_price = entry_price * (1 + trigger_price_delta)
                amount = balance / len(params['envelopes']) / entry_price

                if amount < bitget.fetch_min_amount_tradable(params['bitget_symbol']):
                    print(f"Skipping long layer {i+1} - insufficient funds")
                    continue

                # Place entry order
                order = place_order_safely(
                    bitget.place_trigger_limit_order,
                    symbol=params['bitget_symbol'],
                    side='buy',
                    amount=amount,
                    trigger_price=trigger_price,
                    price=entry_price,
                    planType='normal_plan'
                )

                if order:
                    # Place exit order
                    place_order_safely(
                        bitget.place_trigger_market_order,
                        symbol=params['bitget_symbol'],
                        side='sell',
                        amount=amount,
                        trigger_price=data['average'].iloc[-1],
                        reduce=True
                    )

                    # Place stop loss
                    sl_order = place_order_safely(
                        bitget.place_trigger_market_order,
                        symbol=params['bitget_symbol'],
                        side='sell',
                        amount=amount,
                        trigger_price=entry_price * (1 - params['stop_loss_pct']),
                        reduce=True
                    )

                    if sl_order and 'data' in sl_order and 'orderId' in sl_order['data']:
                        tracker_info['stop_loss_ids'].append(sl_order['data']['orderId'])

        # Update tracker file
        update_tracker(tracker_info)
        print(f"{datetime.now().strftime('%H:%M:%S')}: Execution completed successfully")

    except Exception as e:
        print(f"{datetime.now().strftime('%H:%M:%S')}: ERROR - {str(e)}")
