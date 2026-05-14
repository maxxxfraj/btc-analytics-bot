import asyncio
import requests
import pandas as pd
import pandas_ta as ta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

import os
from dotenv import load_dotenv

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
        result = {}
        price = float(requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        ).json()['price'])

        url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
        res = requests.get(url, timeout=5).json()
        binance_oi = float(res['openInterest']) * price / 1_000_000_000

        url_bybit = "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1h&limit=1"
        res_bybit = requests.get(url_bybit, timeout=5).json()
        bybit_oi = float(res_bybit['result']['list'][0]['openInterest']) * price / 1_000_000_000

        url_okx = "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP"
        res_okx = requests.get(url_okx, timeout=5).json()
        okx_oi = float(res_okx['data'][0]['oiCcy']) * price / 1_000_000_000

        total = binance_oi + bybit_oi + okx_oi
        result = {'binance': binance_oi, 'bybit': bybit_oi, 'okx': okx_oi, 'total': total}

        url_hist = "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25"
        hist = requests.get(url_hist, timeout=5).json()
        if len(hist) >= 25:
            oi_now = float(hist[-1]['sumOpenInterest'])
            oi_24h = float(hist[0]['sumOpenInterest'])
            result['change_24h'] = ((oi_now - oi_24h) / oi_24h) * 100
        else:
            result['change_24h'] = None

        return result
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

def get_coinbase_android_rank():
    try:
        # Google Play топ фінансових додатків
        url = "https://play.google.com/store/apps/collection/cluster?clp=ogooCAEqAggIMiQKHmNvbS5jb2luYmFzZS5hbmRyb2lkLmNvaW5iYXNlEAEYAw%3D%3D&hl=en&gl=us"
        # Використовуємо RSS Google Play топ Finance
        rss_url = "https://play.google.com/store/apps/collection/topselling_free?hl=en&gl=us"

        # Альтернатива — iTunes-стиль пошук через Google Play API
        search_url = "https://itunes.apple.com/lookup?bundleId=com.coinbase.android&country=us"
        res = requests.get(search_url, timeout=5).json()

        # Google Play топ через публічний endpoint
        gplay_url = "https://play.google.com/store/apps/top/chart?hl=en&gl=US&cat=FINANCE&num=200"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(gplay_url, headers=headers, timeout=5)

        # Парсимо позицію Coinbase
        content = r.text.lower()
        apps_list = content.split('com.coinbase.android')
        if len(apps_list) > 1:
            # Рахуємо скільки додатків перед Coinbase
            before = content[:content.find('com.coinbase.android')]
            rank = before.count('market://details?id=') + 1
            return rank
        return None
    except:
        return None

def get_coinbase_gplay_rank():
    """Отримує рейтинг Coinbase в Google Play Finance через RSS"""
    try:
        url = "https://androidrank.org/application/coinbase-buy-bitcoin-ether/com.coinbase.android"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, headers=headers, timeout=5)
        content = res.text

        # Шукаємо рейтинг у Finance
        if 'Finance' in content and '#' in content:
            idx = content.find('Top Finance')
            if idx > 0:
                snippet = content[idx:idx+50]
                import re
                match = re.search(r'#(\d+)', snippet)
                if match:
                    return int(match.group(1))
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
        android_rank = get_coinbase_gplay_rank()
        oi_data = get_open_interest()

        current_price = df['close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        ma50 = df['MA50'].iloc[-1]
        ma200 = df['MA200'].iloc[-1]

        resistance = df['high'].tail(14).max()
        support = df['low'].tail(14).min()

        bull_pct, neutral_pct, bear_pct = calculate_forecast(current_price, ma50, rsi, fund_rate)

        price_icon = "🟢" if pct_24 > 0 else "🔴"
        rsi_status = "перекуплений 🔴" if rsi > 70 else "перепроданий 🟢" if rsi < 30 else "нейтр. ⚪️"
        ma_status = "🟢 Бичий" if current_price > ma50 else "🔴 Ведмежий"
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

            f"📊 *RSI Інтрадей*\n"
            f"5m:  {rsi_label(rsi_intraday['5m'])}\n"
            f"15m: {rsi_label(rsi_intraday['15m'])}\n"
            f"1h:  {rsi_label(rsi_intraday['1h'])}\n\n"

            f"💸 *Funding (BTC)*\n"
            f"Зараз: {fund_rate:+.4f}% ({fund_status})\n\n"

            + oi_text +

            f"📱 *Coinbase App Store*\n"
            f"iOS Finance:  {rank_emoji(ios_rank)}\n"
            f"Android Finance: {rank_emoji(android_rank)}\n\n"

            f"🎯 *Прогноз напрямку (24-72ч)*\n"
            f"🟢 ↑ Вверх:   {bull_pct}%\n"
            f"⚪️ → Боковик: {neutral_pct}%\n"
            f"🔴 ↓ Вниз:    {bear_pct}%\n"
        )

        await msg.edit_text(text, parse_mode="Markdown")

    except Exception as e:
        await msg.edit_text(f"❌ Помилка: {e}")

async def main():
    print("Бот запущений! Напишіть йому /dash")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())