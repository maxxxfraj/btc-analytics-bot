import asyncio
import requests
import pandas as pd
import pandas_ta as ta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

import os
from dotenv import load_dotenv
from aiohttp import web

load_dotenv() # Завантажує дані з .env
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

def get_btc_ta_data():
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=250"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        'time','open','high','low','close','volume',
        'close_time','qav','num_trades','taker_base_vol','taker_quote_vol','ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['MA50'] = ta.sma(df['close'], length=50)
    df['MA200'] = ta.sma(df['close'], length=200)
    return df

def get_btc_extra_data():
    url_24h = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
    res_24h = requests.get(url_24h).json()
    pct_24 = float(res_24h['priceChangePercent'])
    high_24 = float(res_24h['highPrice'])
    low_24 = float(res_24h['lowPrice'])
    vol_m = float(res_24h['quoteVolume']) / 1_000_000

    url_funding = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    res_funding = requests.get(url_funding).json()
    fund_rate = float(res_funding['lastFundingRate']) * 100

    return pct_24, high_24, low_24, vol_m, fund_rate

def get_rsi_intraday():
    result = {}
    for interval, limit in [("5m", 20), ("15m", 20), ("1h", 50)]:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
        data = requests.get(url).json()
        df = pd.DataFrame(data, columns=[
            'time','open','high','low','close','volume',
            'ct','qv','trades','tb','tq','ignore'
        ])
        df['close'] = df['close'].astype(float)
        rsi = ta.rsi(df['close'], length=14).iloc[-1]
        result[interval] = rsi
    return result

def get_open_interest():
    try:
        price = float(requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=5
        ).json()['price'])

        res = requests.get("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT", timeout=5).json()
        binance_oi = float(res['openInterest']) * price / 1_000_000_000

        res_bybit = requests.get(
            "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1h&limit=1",
            timeout=5
        ).json()
        bybit_oi = float(res_bybit['result']['list'][0]['openInterest']) * price / 1_000_000_000

        res_okx = requests.get(
            "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP",
            timeout=5
        ).json()
        okx_oi = float(res_okx['data'][0]['oiCcy']) * price / 1_000_000_000

        total = binance_oi + bybit_oi + okx_oi
        result = {'binance': binance_oi, 'bybit': bybit_oi, 'okx': okx_oi, 'total': total}

        hist = requests.get(
            "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25",
            timeout=5
        ).json()
        if len(hist) >= 25:
            oi_now = float(hist[-1]['sumOpenInterest'])
            oi_24h = float(hist[0]['sumOpenInterest'])
            result['change_24h'] = ((oi_now - oi_24h) / oi_24h) * 100
        else:
            result['change_24h'] = None

        return result
    except:
        return None

def get_channel_30d(df):
    try:
        df30 = df.tail(30)
        high_30 = df30['high'].max()
        low_30  = df30['low'].min()
        price   = df['close'].iloc[-1]

        channel_range = high_30 - low_30
        position = (price - low_30) / channel_range

        if position <= 0.33:
            zone_text = "нижня третина (зона відскоку)"
            zone_emoji = "🟢"
        elif position <= 0.66:
            zone_text = "середина каналу"
            zone_emoji = "⚪️"
        else:
            zone_text = "верхня третина (зона опору)"
            zone_emoji = "🔴"

        first_close = df30['close'].iloc[0]
        last_close  = df30['close'].iloc[-1]
        slope_pct   = ((last_close - first_close) / first_close) * 100

        if slope_pct > 5:
            trend_text = "🟢 висхідний"
        elif slope_pct < -5:
            trend_text = "🔴 низхідний"
        else:
            trend_text = "⚪️ плоский"

        return {
            'high': high_30, 'low': low_30,
            'position_pct': position * 100,
            'zone_text': zone_text, 'zone_emoji': zone_emoji,
            'slope_pct': slope_pct, 'trend_text': trend_text
        }
    except:
        return None

def get_hashrate_difficulty():
    try:
        res_hash = requests.get(
            "https://mempool.space/api/v1/mining/hashrate/1m", timeout=8
        ).json()
        current_hashrate = res_hash['currentHashrate'] / 1e18

        hashrates = res_hash.get('hashrates', [])
        if len(hashrates) >= 30:
            avg_30d = sum(h['avgHashrate'] for h in hashrates[-30:]) / 30 / 1e18
            hash_change = ((current_hashrate - avg_30d) / avg_30d) * 100
        else:
            avg_30d = current_hashrate
            hash_change = 0

        hash_emoji = "🟢" if hash_change > 0 else "🔴"

        res_diff = requests.get(
            "https://mempool.space/api/v1/difficulty-adjustment", timeout=8
        ).json()
        current_diff = res_diff['currentDifficulty'] / 1e12
        diff_change  = res_diff['difficultyChange']
        blocks_until = res_diff['remainingBlocks']
        days_until   = round(blocks_until * 10 / 60 / 24, 1)
        diff_emoji   = "🟢" if diff_change > 0 else "🔴"

        return {
            'hashrate': current_hashrate, 'hash_change': hash_change, 'hash_emoji': hash_emoji,
            'difficulty': current_diff, 'diff_change': diff_change,
            'diff_emoji': diff_emoji, 'days_until': days_until
        }
    except:
        return None

def get_coinbase_premium():
    try:
        binance_price = float(requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5
        ).json()['price'])

        coinbase_price = float(requests.get(
            "https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=5
        ).json()['data']['amount'])

        premium_pct = ((coinbase_price - binance_price) / binance_price) * 100

        if premium_pct > 0.1:
            emoji = "🟢"
            status = "американський попит"
        elif premium_pct < -0.1:
            emoji = "🔴"
            status = "дисконт"
        else:
            emoji = "⚪️"
            status = "нейтральний"

        return {'premium_pct': premium_pct, 'emoji': emoji, 'status': status}
    except:
        return None

def get_fear_greed():
    """Fear & Greed Index — сьогодні, вчора, тиждень тому"""
    try:
        res = requests.get(
            "https://api.alternative.me/fng/?limit=8",
            timeout=5
        ).json()

        data = res['data']

        today     = data[0]
        yesterday = data[1]
        week_ago  = data[7]

        def fg_emoji(value):
            v = int(value)
            if v <= 25:
                return "😱"   # Extreme Fear
            elif v <= 45:
                return "😨"   # Fear
            elif v <= 55:
                return "😐"   # Neutral
            elif v <= 75:
                return "😏"   # Greed
            else:
                return "🤑"   # Extreme Greed

        def fg_color(value):
            v = int(value)
            if v <= 25:
                return "🔴"
            elif v <= 45:
                return "🟠"
            elif v <= 55:
                return "⚪️"
            elif v <= 75:
                return "🟡"
            else:
                return "🟢"

        return {
            'today_value':      int(today['value']),
            'today_label':      today['value_classification'],
            'today_emoji':      fg_emoji(today['value']),
            'today_color':      fg_color(today['value']),
            'yesterday_value':  int(yesterday['value']),
            'yesterday_label':  yesterday['value_classification'],
            'week_value':       int(week_ago['value']),
            'week_label':       week_ago['value_classification'],
        }
    except:
        return None

def get_coinbase_ios_rank():
    try:
        url = "https://itunes.apple.com/us/rss/topfreeapplications/limit=200/genre=6015/json"
        res = requests.get(url, timeout=5).json()
        apps = res['feed']['entry']
        for i, app in enumerate(apps):
            if 'coinbase' in app['im:name']['label'].lower():
                return i + 1
        return None
    except:
        return None

def rank_emoji(rank):
    if rank is None:
        return "⚪️ н/д"
    if rank <= 10:
        return f"🟢 #{rank}"
    elif rank <= 50:
        return f"🟡 #{rank}"
    else:
        return f"🔴 #{rank}"

def rsi_label(rsi):
    if rsi >= 70:
        return f"{rsi:.0f} 🔴 перекуплений"
    elif rsi <= 30:
        return f"{rsi:.0f} 🟢 перепроданий"
    else:
        return f"{rsi:.0f} ⚪️ нейтр."

def calculate_forecast(current_price, ma50, rsi, fund_rate):
    bull_score = 0
    bear_score = 0
    neutral_score = 40

    if current_price > ma50:
        bull_score += 25
    else:
        bear_score += 25

    if rsi > 65:
        bear_score += 30
    elif rsi < 35:
        bull_score += 30
    else:
        neutral_score += 20

    if fund_rate > 0.01:
        bear_score += 15
    elif fund_rate < 0:
        bull_score += 15

    total = bull_score + bear_score + neutral_score
    bull_pct = int((bull_score / total) * 100)
    bear_pct = int((bear_score / total) * 100)
    neutral_pct = 100 - bull_pct - bear_pct

    return bull_pct, neutral_pct, bear_pct

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привіт, бос! 🫡 Напиши команду /dash")

@dp.message(Command("dash"))
async def cmd_dash(message: types.Message):
    msg = await message.answer("🔄 Аналізую ринок, рахую ймовірності...")

    try:
        df = get_btc_ta_data()
        pct_24, high_24, low_24, vol_m, fund_rate = get_btc_extra_data()
        rsi_intraday = get_rsi_intraday()
        ios_rank = get_coinbase_ios_rank()
        oi_data = get_open_interest()
        channel = get_channel_30d(df)
        onchain = get_hashrate_difficulty()
        cb_premium = get_coinbase_premium()
        fg = get_fear_greed()

        current_price = df['close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        ma50 = df['MA50'].iloc[-1]
        ma200 = df['MA200'].iloc[-1]

        resistance = df['high'].tail(14).max()
        support = df['low'].tail(14).min()

        bull_pct, neutral_pct, bear_pct = calculate_forecast(current_price, ma50, rsi, fund_rate)

        price_icon  = "🟢" if pct_24 > 0 else "🔴"
        rsi_status  = "перекуплений 🔴" if rsi > 70 else "перепроданий 🟢" if rsi < 30 else "нейтр. ⚪️"
        ma_status   = "🟢 Бичий" if current_price > ma50 else "🔴 Ведмежий"
        fund_status = "🔴 перегрів лонгів" if fund_rate > 0.01 else "🟢 перегрів шортів" if fund_rate < 0 else "⚪️ нейтральний"

        # OI блок
        if oi_data:
            binance_pct = int(oi_data['binance'] / oi_data['total'] * 100)
            bybit_pct   = int(oi_data['bybit']   / oi_data['total'] * 100)
            okx_pct     = int(oi_data['okx']     / oi_data['total'] * 100)
            if oi_data['change_24h'] is not None:
                ch = oi_data['change_24h']
                oi_ch_emoji = "🟢" if ch > 2 else "🔴" if ch < -2 else "⚪️"
                oi_change_text = f"{oi_ch_emoji} {ch:+.1f}% за 24h"
            else:
                oi_change_text = ""
            oi_text = (
                f"📊 *OI (BTC, агрегат)*\n"
                f"Binance: ${oi_data['binance']:.2f}B ({binance_pct}%)\n"
                f"Bybit:   ${oi_data['bybit']:.2f}B ({bybit_pct}%)\n"
                f"OKX:     ${oi_data['okx']:.2f}B ({okx_pct}%)\n"
                f"Total:   ${oi_data['total']:.2f}B  {oi_change_text}\n\n"
            )
        else:
            oi_text = "📊 *OI:* дані недоступні\n\n"

        # Канал 30d
        if channel:
            channel_text = (
                f"📉 *Канал (30d)*\n"
                f"Тренд: {channel['trend_text']} ({channel['slope_pct']:+.1f}%)\n"
                f"Верх: ${channel['high']:,.0f}  Низ: ${channel['low']:,.0f}\n"
                f"Позиція: {channel['zone_emoji']} {channel['position_pct']:.0f}% — {channel['zone_text']}\n\n"
            )
        else:
            channel_text = ""

        # Hashrate + Difficulty
        if onchain:
            onchain_text = (
                f"🔧 *Fundamentals (BTC)*\n"
                f"⚡️ Hashrate: {onchain['hashrate']:.0f} EH/s  "
                f"{onchain['hash_emoji']} {onchain['hash_change']:+.1f}% до 30d avg\n"
                f"🔧 Difficulty: {onchain['difficulty']:.1f}T  "
                f"{onchain['diff_emoji']} {onchain['diff_change']:+.2f}% через {onchain['days_until']}d\n\n"
            )
        else:
            onchain_text = ""

        # Coinbase Premium
        if cb_premium:
            cb_prem_text = (
                f"🇺🇸 Coinbase prem: {cb_premium['emoji']} {cb_premium['premium_pct']:+.3f}%  "
                f"{cb_premium['status']}\n\n"
            )
        else:
            cb_prem_text = ""

        # Fear & Greed
        if fg:
            # Зміна порівняно з вчора
            delta = fg['today_value'] - fg['yesterday_value']
            delta_text = f"{delta:+d} до вчора" if delta != 0 else "без змін"
            delta_emoji = "🟢" if delta > 0 else "🔴" if delta < 0 else "⚪️"

            fg_text = (
                f"😱 *Fear & Greed Index*\n"
                f"Зараз:   {fg['today_color']} {fg['today_value']} — {fg['today_label']} {fg['today_emoji']}\n"
                f"Вчора:   {fg['yesterday_value']} — {fg['yesterday_label']}\n"
                f"7d тому: {fg['week_value']} — {fg['week_label']}\n"
                f"Зміна:   {delta_emoji} {delta_text}\n\n"
            )
        else:
            fg_text = ""

        text = (
            f"📊 🟠 *BTC Dashboard Pro*\n\n"

            f"💰 *Ціна:* ${current_price:,.2f} ({price_icon} {pct_24:+.2f}% 24h)\n"
            f"24h: L ${low_24:,.2f}  H ${high_24:,.2f}\n"
            f"Об'єм 24h: ${vol_m:,.1f}M\n"
            f"Опір (14d): 🔴 ${resistance:,.0f}\n"
            f"Підтримка (14d): 🟢 ${support:,.0f}\n\n"

            f"📐 *TA — Індикатори*\n"
            f"Тренд (D): {ma_status}\n"
            f"MA50: ${ma50:,.0f} | MA200: ${ma200:,.0f}\n"
            f"RSI 1D: {rsi:.0f}  {rsi_status}\n\n"

            + channel_text +

            f"📊 *RSI Інтрадей*\n"
            f"5m:  {rsi_label(rsi_intraday['5m'])}\n"
            f"15m: {rsi_label(rsi_intraday['15m'])}\n"
            f"1h:  {rsi_label(rsi_intraday['1h'])}\n\n"

            f"💸 *Funding (BTC)*\n"
            f"Зараз: {fund_rate:+.4f}% ({fund_status})\n\n"

            + oi_text
            + onchain_text
            + cb_prem_text
            + fg_text +

            f"📱 *Coinbase App Store (US)*\n"
            f"iOS Finance: {rank_emoji(ios_rank)}\n\n"

            f"🎯 *Прогноз напрямку (24-72ч)*\n"
            f"🟢 ↑ Вверх:   {bull_pct}%\n"
            f"⚪️ → Боковик: {neutral_pct}%\n"
            f"🔴 ↓ Вниз:    {bear_pct}%\n"
        )

        await msg.edit_text(text, parse_mode="Markdown")

    except Exception as e:
        await msg.edit_text(f"❌ Помилка: {e}")

async def handle(request):
    return web.Response(text="I am alive!")

async def main():
    # Веб-сервер для Render
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"Бот і веб-сервер запущені на порту {port}!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
