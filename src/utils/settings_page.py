import streamlit as st
from .db_manager import db_manager
from .db_models import ExchangeAccount

def settings_page():
    st.header("⚙️ 系统设置")
    
    tab_acc, tab_sys = st.tabs(["交易所账户", "系统参数"])
    
    with tab_acc:
        st.subheader("交易所账户管理")
        
        # 1. List Accounts
        session = db_manager.get_session()
        target_uid = st.session_state.get('viewing_user_id', st.session_state.user_id)
        accounts = db_manager.get_exchange_accounts(session, target_uid)
        
        if accounts:
            for acc in accounts:
                with st.expander(f"{acc.alias} ({acc.exchange} - {acc.account_type})", expanded=False):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**ID**: `{acc.id}`")
                        st.write(f"**Exchange**: {acc.exchange}")
                        st.write(f"**Type**: {acc.account_type}")
                        st.write(f"**Created**: {acc.created_at}")
                    with c2:
                        if st.button("🗑️ 删除账户", key=f"del_acc_{acc.id}", type="primary"):
                            try:
                                if db_manager.delete_exchange_account(session, acc.id, target_uid):
                                    st.success("删除成功！")
                                    st.rerun()
                                else:
                                    st.error("删除失败")
                            except Exception as e:
                                st.error(f"Error: {e}")
        else:
            st.info("暂无配置账户")
            
        session.close()
        
        st.divider()
        
        # 2. Add Account
        st.subheader("添加新账户")
        with st.form("add_account_form"):
            alias = st.text_input("账户别名 (Alias)", placeholder="e.g. MyBinanceTest")
            exchange = st.selectbox("交易所", ["binance", "binanceusdm"], index=1)
            acc_type = st.selectbox("账户类型", ["live", "testnet"], index=1)
            api_key = st.text_input("API Key", type="password")
            secret_key = st.text_input("Secret Key", type="password")
            
            submitted = st.form_submit_button("保存配置")
            if submitted:
                if not alias or not api_key or not secret_key:
                    st.error("请填写所有必填字段")
                else:
                    session = db_manager.get_session()
                    try:
                        # Auto-strip keys
                        api_key = api_key.strip()
                        secret_key = secret_key.strip()
                        
                        db_manager.add_exchange_account(
                            session, 
                            target_uid, 
                            alias, 
                            api_key, 
                            secret_key, 
                            account_type=acc_type, 
                            exchange=exchange
                        )
                        session.commit()
                        st.success(f"账户 {alias} 添加成功！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"添加失败: {e}")
                    finally:
                        session.close()

    with tab_sys:
        st.info("系统参数配置功能开发中...")
