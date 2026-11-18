import math
import requests
import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="Калькулятор позиции", layout="centered")
st.title("Калькулятор позиции", anchor=False)

# ---------- Тумблер выбора рынка ----------

market = st.toggle("Торговать американские акции (NASDAQ/NYSE)", value=False)

if market:
    market_type = "usa"
else:
    market_type = "moex"

# ============================================================
# ФУНКЦИИ ДЛЯ MOEX
# ============================================================

@st.cache_data(ttl=600)
def load_stocks():
    url = (
        "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/"
        "securities.json?iss.meta=off&iss.only=securities"
        "&securities.columns=SECID,SHORTNAME,LOTSIZE"
    )
    try:
        r = requests.get(url, timeout=15)
        block = r.json().get("securities", {})
        cols = block.get("columns", [])
        data = block.get("data", [])
        idx = {name: i for i, name in enumerate(cols)}
        result = []
        for row in data:
            secid = row[idx["SECID"]]
            name = row[idx["SHORTNAME"]] or secid
            lotsize = row[idx["LOTSIZE"]] or 1
            result.append((secid, name, int(lotsize)))
        return result
    except Exception:
        return []

@st.cache_data(ttl=600)
def load_futures():
    url = (
        "https://iss.moex.com/iss/engines/futures/markets/forts/boards/RFUD/"
        "securities.json?iss.meta=off&iss.only=securities"
        "&securities.columns=SECID,SHORTNAME,STEPPRICE"
    )
    try:
        r = requests.get(url, timeout=15)
        block = r.json().get("securities", {})
        cols = block.get("columns", [])
        data = block.get("data", [])
        idx = {name: i for i, name in enumerate(cols)}
        result = []
        for row in data:
            secid = row[idx["SECID"]]
            name = row[idx["SHORTNAME"]] or secid
            stepprice = row[idx["STEPPRICE"]]
            if stepprice:
                result.append((secid, name, float(stepprice)))
        return result
    except Exception:
        return []

# ============================================================
# ФУНКЦИИ ДЛЯ USA
# ============================================================

@st.cache_data(ttl=86400)
def load_all_us_tickers():
    """Читает локальные файлы nasdaqlisted.txt и otherlisted.txt из репозитория."""
    tickers = []
    
    files = {
        "NASDAQ": "nasdaqlisted.txt",
        "OTHER": "otherlisted.txt"
    }
    
    for source, filename in files.items():
        try:
            df = pd.read_csv(filename, sep="|")
            df = df[~df.iloc[:, 0].astype(str).str.contains("File Creation Time")]
            
            if source == "NASDAQ":
                if "ETF" in df.columns:
                    df = df[df["ETF"] == "N"]
                for _, row in df.iterrows():
                    tickers.append(f"{row['Symbol']} — {row['Security Name']}")
            else:
                if "ETF" in df.columns:
                    df = df[df["ETF"] == "N"]
                for _, row in df.iterrows():
                    tickers.append(f"{row['ACT Symbol']} — {row['Security Name']}")
                    
        except FileNotFoundError:
            st.error(f"Файл {filename} не найден в корне проекта.")
        except Exception as e:
            st.warning(f"Ошибка при чтении {filename}: {e}")
            
    tickers.sort()
    return tickers

@st.cache_data(ttl=60)
def get_us_price(ticker):
    """Получить текущую цену американской акции через yfinance."""
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.get("lastPrice") or stock.fast_info.get("regularMarketPrice")
        if price:
            return float(price)
        hist = stock.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None
    except Exception:
        return None

# ============================================================
# UI: MOEX
# ============================================================

if market_type == "moex":
    stocks = load_stocks()
    futures = load_futures()

    options = []

    for secid, name, lotsize in stocks:
        options.append({
            "label": f"{secid} — {name} (акция)",
            "secid": secid,
            "type": "stock",
            "lotsize": lotsize,
        })

    for secid, name, stepprice in futures:
        options.append({
            "label": f"{secid} — {name} (фьючерс)",
            "secid": secid,
            "type": "futures",
            "step_price": stepprice,
        })

    options.sort(key=lambda x: x["label"])
    labels = [o["label"] for o in options]

    selected_label = st.selectbox(
        "Выберите тикер",
        options=labels if labels else ["— список недоступен —"],
        index=None,
        placeholder="Choose an option",
        help="Список подгружается с MOEX ISS и кэшируется на 10 минут.",
    )
    selected = next((o for o in options if o["label"] == selected_label), None)

    with st.form("calc_moex"):
        st.markdown("Параметры расчёта", anchors=False)

        stop_rub = st.number_input("Размер стопа, ₽", min_value=0.01, value=1000.0, step=100.0)

        if selected and selected["type"] == "futures":
            ticks = st.number_input("Стоп в тиках", min_value=1, value=10, step=1)
            rub_to_stop = None
            lotsize = None
        elif selected and selected["type"] == "stock":
            rub_to_stop = st.number_input(
                "Рублей до стопа",
                min_value=0.01,
                value=0.37,
                step=0.01,
                format="%.2f",
                help="Разница между ценой покупки и ценой стопа в рублях (на 1 бумагу)",
            )
            lotsize = selected["lotsize"]
            st.caption(f"Размер лота: {lotsize}")
        else:
            ticks = st.number_input("Стоп в тиках", min_value=1, value=10, step=1)
            rub_to_stop = None
            lotsize = None
        submitted = st.form_submit_button("Рассчитать", use_container_width=True)

    if submitted:
        if selected is None:
            st.warning("Для начала выберите тикер из списка выше.")
        elif selected["type"] == "futures":
            step_price = selected["step_price"]
            if step_price and step_price > 0:
                st.success(f"Инструмент: **{selected['label']}** · шаг цены = **{step_price} ₽**")
                qty_raw = stop_rub / (ticks * step_price)
                qty = math.floor(qty_raw)

                st.metric("Количество контрактов", f"{qty}")
                st.caption(f"Точное значение до округления: {qty_raw:.4f}")

                if qty < 1:
                    st.warning("Размер стопа слишком мал — округлённое количество меньше 1.")

                with st.expander("Показать расчёт"):
                    st.write("**Формула:** `qty = stop_rub / (ticks × step_price)`")
                    st.write(f"`qty = {stop_rub} / ({ticks} × {step_price}) = {qty_raw:.4f} → {qty}`")
            else:
                st.error("Шаг цены не определён в базе MOEX.")
                
        elif selected["type"] == "stock":
            if rub_to_stop <= 0:
                st.error("Значение «Рублей до стопа» должно быть положительным.")
            else:
                qty_lots_raw = stop_rub / (rub_to_stop * lotsize)
                qty_lots = math.floor(qty_lots_raw)
                qty_shares = qty_lots * lotsize

                st.success(f"Инструмент: **{selected['label']}** · лот = **{lotsize}**")
                st.metric("Количество лотов", f"{qty_lots}")
                st.caption(f"Количество бумаг: {qty_shares}")

                if qty_lots < 1:
                    st.warning("Размер стопа слишком мал — округлённое количество лотов меньше 1.")

                with st.expander("Показать расчёт"):
                    st.write("**Формула:** `qty_lots = stop_rub / (rub_to_stop × lotsize)`")
                    st.write(f"`qty_lots = {stop_rub} / ({rub_to_stop:.2f} × {lotsize}) = {qty_lots_raw:.4f} → {qty_lots}`")
                    st.write(f"`qty_shares = {qty_lots} × {lotsize} = {qty_shares}`")

# ============================================================
# UI: USA
# ============================================================

else:  # market_type == "usa"
    with st.spinner("Загружаем список акций NASDAQ и NYSE..."):
        all_us_tickers = load_all_us_tickers()

    if not all_us_tickers:
        st.error("Не удалось загрузить список тикеров. Проверьте наличие файлов nasdaqlisted.txt и otherlisted.txt в репозитории.")
        st.stop()

    selected_us_label = st.selectbox(
        "Выберите тикер (NASDAQ/NYSE)",
        options=all_us_tickers,
        index=None,
        placeholder="Начните вводить тикер (например, AAPL)...",
        help="Список содержит все акции с NYSE и NASDAQ. Начните вводить буквы для фильтрации."
    )

    ticker_clean = selected_us_label.split(" — ")[0] if selected_us_label else None

    # Вызываем функцию, которой не хватало
    if ticker_clean:
        current_price = get_us_price(ticker_clean)
        if current_price:
            st.caption(f"Текущая цена **{ticker_clean}**: ${current_price:.2f}")
        else:
            st.caption(f"Не удалось получить цену для **{ticker_clean}**. Проверьте правильность тикера.")

    with st.form("calc_usa"):
        st.markdown("Параметры расчёта", anchors=False)

        stop_usd = st.number_input("Размер стопа, $", min_value=0.01, value=1000.0, step=100.0)
        usd_to_stop = st.number_input(
            "Долларов до стопа",
            min_value=0.01,
            value=1.00,
            step=0.01,
            format="%.2f",
            help="Разница между ценой покупки и ценой стопа в долларах (на 1 акцию)",
        )

        submitted_usa = st.form_submit_button("Рассчитать", use_container_width=True)

    if submitted_usa:
        if not ticker_clean:
            st.warning("Для начала выберите тикер из списка выше.")
        elif usd_to_stop <= 0:
            st.error("Значение «Долларов до стопа» должно быть положительным.")
        else:
            qty_raw = stop_usd / usd_to_stop
            qty = math.floor(qty_raw)

            st.success(f"Инструмент: **{ticker_clean}** (NASDAQ/NYSE) · лот = 1")
            st.metric("Количество акций", f"{qty}")

            if qty < 1:
                st.warning("Размер стопа слишком мал — округлённое количество меньше 1.")

            with st.expander("Показать расчёт"):
                st.write("**Формула:** `qty = stop_usd / usd_to_stop`")
                st.write(f"`qty = {stop_usd} / {usd_to_stop:.2f} = {qty_raw:.4f} → {qty}`")
