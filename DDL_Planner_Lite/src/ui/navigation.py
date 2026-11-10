"""侧边栏导航组件。"""

import streamlit as st


PAGES = ("首页", "任务管理", "今日计划", "数据统计")
PAGE_ICONS = {
    "首页": ":material/home:",
    "任务管理": ":material/checklist:",
    "今日计划": ":material/timer:",
    "数据统计": ":material/insert_chart:",
}


def _save_theme_choice() -> None:
    """将主题偏好写入 URL，便于刷新或复制页面后继续使用。"""
    st.query_params["theme"] = (
        "dark" if st.session_state["theme_toggle"] else "light"
    )


def render_navigation() -> str:
    """渲染侧边栏并返回当前选中的页面名称。"""
    target_page = st.session_state.pop("navigation_target", None)
    if target_page in PAGES:
        st.session_state["main_navigation"] = target_page
    elif st.session_state.get("main_navigation") not in PAGES:
        st.session_state["main_navigation"] = PAGES[0]

    if "theme_toggle" not in st.session_state:
        st.session_state["theme_toggle"] = st.query_params.get("theme") == "dark"

    with st.sidebar:
        st.markdown(
            """
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">
                    <svg viewBox="0 0 48 48" role="img">
                        <path d="M7 16 24 8l17 8-17 8-17-8Z"/>
                        <path d="M14 20v9c5 5 15 5 20 0v-9M41 17v12"/>
                        <path d="M37 33h8"/>
                    </svg>
                </div>
                <div>
                    <div class="brand-name">DDL Planner Lite</div>
                    <div class="brand-subtitle">STUDY BUDDY · 学习搭子</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        selected_page = st.radio(
            "导航",
            PAGES,
            format_func=lambda page: f"{PAGE_ICONS[page]}  {page}",
            key="main_navigation",
            label_visibility="collapsed",
        )
        st.markdown('<div class="sidebar-theme-label">外观</div>', unsafe_allow_html=True)
        st.toggle(
            "Midnight Study 深色主题",
            key="theme_toggle",
            on_change=_save_theme_choice,
        )
        return selected_page
