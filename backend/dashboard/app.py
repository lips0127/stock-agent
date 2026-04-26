import streamlit as st
from backend.core.database import get_connection
from backend.core.database import authenticate_user
from datetime import date
import pandas as pd
from backend.services.scanner_service import get_high_dividend_stocks_by_concept
from backend.services.stock_service import get_stock_metrics, get_sina_index_spot, get_eastmoney_url

st.set_page_config(page_title="A 股股息率监测系统", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; font-family: 'Segoe UI', sans-serif; }
    section[data-testid="stSidebar"] { background-color: #2c3e50; color: white; }
    section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 { color: #ecf0f1 !important; }
    section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] div, section[data-testid="stSidebar"] p { color: #bdc3c7 !important; font-size: 1.1em; }
    section[data-testid="stSidebar"] .stRadio label { color: #ecf0f1 !important; font-weight: 500; }
    section[data-testid="stSidebar"] hr { background-color: #7f8c8d; }
    div[data-testid="stMetric"] { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #e0e0e0; }
    div[data-testid="stDataFrame"] { background-color: white; padding: 10px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    h1, h2, h3 { color: #2c3e50; font-weight: 600; }
    .stButton>button { background-color: #3498db; color: white; border-radius: 5px; border: none; padding: 0.5rem 1rem; transition: all 0.3s; }
    .stButton>button:hover { background-color: #2980b9; color: white; }
    .stSuccess { background-color: #d4edda; color: #155724; border-left: 5px solid #28a745; }
    .stInfo { background-color: #d1ecf1; color: #0c5460; border-left: 5px solid #17a2b8; }
</style>
""", unsafe_allow_html=True)

@st.dialog("用户登录")
def login_dialog():
    with st.form("login_form_dialog"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submit_button = st.form_submit_button("登 录", use_container_width=True)

    if submit_button:
        if authenticate_user(username, password):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.success("登录成功！")
            st.rerun()
        else:
            st.error("用户名或密码错误")

def login_widget():
    col1, col2 = st.columns([8, 1])
    with col2:
        if not st.session_state.get("authenticated", False):
            if st.button("登录", use_container_width=True):
                login_dialog()
        else:
            if st.button("退出", use_container_width=True):
                st.session_state["authenticated"] = False
                st.session_state["username"] = None
                st.rerun()

def dashboard_page():
    user_name = st.session_state.get('username', '游客')
    st.title(f"仪表盘 | 欢迎, {user_name}")

    st.markdown("### 市场核心指数 (实时)")

    indices_map = {
        "s_sh000001": "上证指数",
        "s_sz399001": "深证成指",
        "s_sz399006": "创业板指",
        "s_sh000688": "科创50",
        "s_sh000012": "国债指数"
    }

    cols = st.columns(len(indices_map))
    for i, (symbol, name) in enumerate(indices_map.items()):
        data = get_sina_index_spot(symbol)
        with cols[i]:
            if data:
                val = data['current']
                pct = data['change_pct']
                st.metric(label=name, value=f"{val:.2f}", delta=f"{pct:.2f}%")
            else:
                st.metric(label=name, value="--", delta="--")

    st.divider()

    today = date.today().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM stock_daily_metrics")
        row = cur.fetchone()
        latest_date = row[0] if row and row[0] else today

        st.markdown(f"### 高股息 Top 20 (数据日期: {latest_date})")

        cur.execute(
            "SELECT * FROM stock_daily_metrics WHERE date = ? ORDER BY dividend_yield DESC LIMIT 20",
            (latest_date,)
        )
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

    if rows:
        data = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            code = row_dict['code']
            data.append({
                "代码": code,
                "名称": row_dict['name'],
                "最新价": row_dict['price'],
                "股息率 (%)": row_dict['dividend_yield'],
                "详情": get_eastmoney_url(code)
            })

        st.dataframe(
            data,
            column_config={
                "最新价": st.column_config.NumberColumn(format="%.2f"),
                "股息率 (%)": st.column_config.NumberColumn(format="%.2f"),
                "详情": st.column_config.LinkColumn(display_text="查看详情")
            },
            hide_index=True,
            use_container_width=True,
            height=600
        )
    else:
        st.info("今日数据尚未更新，请运行后台全量扫描脚本。")


def scanner_page():
    st.title("实时市场扫描")
    st.markdown("""
    本功能将实时扫描 **中证红利指数 (000922)** 的成分股。
    若需查看全市场数据，请访问 **仪表盘**。
    """)

    if st.button("开始实时扫描 (约需 30秒)"):
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            status_text.text("正在获取成分股列表...")
            progress_bar.progress(30)
            data_list = get_high_dividend_stocks_by_concept(limit=100)
            progress_bar.progress(100)
            status_text.text("扫描完成！")

            if data_list:
                for item in data_list:
                    item['详情'] = get_eastmoney_url(item['code'])

                st.success(f"成功扫描到 {len(data_list)} 只股票")
                st.dataframe(
                    data_list,
                    column_config={
                        "code": "代码",
                        "名称": "名称",
                        "price": st.column_config.NumberColumn("最新价", format="%.2f"),
                        "股息率": st.column_config.NumberColumn("股息率 (%)", format="%.2f"),
                        "详情": st.column_config.LinkColumn(display_text="查看详情")
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.warning("扫描未返回数据，请检查网络或稍后再试")
        except Exception as e:
            st.error(f"扫描出错: {e}")

def analysis_page():
    st.title("个股深度分析")

    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("stock_query"):
            symbol = st.text_input("股票代码", max_chars=6, placeholder="例如: 600519")
            submitted = st.form_submit_button("查询", use_container_width=True)

    if submitted and symbol:
        try:
            with st.spinner("正在从交易所获取最新数据..."):
                data = get_stock_metrics(symbol)

            st.markdown("---")

            link = get_eastmoney_url(symbol)
            st.markdown(f"### {data['名称']} ({symbol})")

            res_col1, res_col2, res_col3 = st.columns(3)
            with res_col1:
                st.metric("股票名称", data["名称"])
            with res_col2:
                st.metric("最新价", f"¥ {data['最新价']:.2f}")
            with res_col3:
                st.metric("股息率 (TTM)", f"{data['股息率']}%")

            st.markdown("### 投资建议")
            if data['股息率'] > 5:
                st.success(f"强力推荐：{data['名称']} 的股息率高达 {data['股息率']}%，远超市场平均水平")
            elif data['股息率'] > 3:
                st.info(f"值得关注：{data['名称']} 的股息率为 {data['股息率']}%，具备一定的防守属性")
            else:
                st.warning(f"观察为主：{data['名称']} 的股息率仅为 {data['股息率']}%")

        except Exception as e:
            st.error(f"查询失败: {e}")

def main():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    with st.sidebar:
        st.title("股息助手 Pro")

        if st.session_state.get("authenticated", False):
            st.success(f"{st.session_state.get('username', '')}")
        else:
            st.info("游客模式")

        st.markdown("---")

        page = st.radio(
            "功能导航",
            ["仪表盘", "个股分析", "市场扫描"],
            index=0,
            captions=["市场概览与高股息排行", "单只股票深度查询", "实时抓取市场数据"]
        )

        st.markdown("---")

        if st.session_state.get("authenticated", False):
            if st.button("退出登录", use_container_width=True):
                st.session_state["authenticated"] = False
                st.rerun()
        else:
            if st.button("登录系统", use_container_width=True):
                login_dialog()

    if "仪表盘" in page:
        dashboard_page()
    elif "个股分析" in page:
        if st.session_state.get("authenticated", False):
            analysis_page()
        else:
            st.warning("该功能仅对登录用户开放")
            if st.button("立即登录"):
                login_dialog()
    elif "市场扫描" in page:
        scanner_page()

if __name__ == "__main__":
    main()
