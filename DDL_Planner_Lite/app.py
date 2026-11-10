"""DDL Planner Lite 的 Streamlit 应用入口。"""

from html import escape

import streamlit as st

from src.database import DatabaseError, initialize_database
from src.ui.navigation import render_navigation
from src.services import reminders
from src.pages.daily_plan import render_daily_plan
from src.pages.dashboard import render_dashboard
from src.pages.statistics import render_statistics
from src.pages.task_manager import render_task_manager


PAGE_RENDERERS = {
    "首页": render_dashboard,
    "任务管理": render_task_manager,
    "今日计划": render_daily_plan,
    "数据统计": render_statistics,
}


def load_stylesheet() -> None:
    """加载项目的全局样式。"""
    from src.config import STYLESHEET_PATH

    try:
        stylesheet = STYLESHEET_PATH.read_text(encoding="utf-8")
    except OSError as error:
        st.error(f"无法加载界面样式：{error}")
        return

    st.markdown(f"<style>{stylesheet}</style>", unsafe_allow_html=True)


@st.dialog("DDL 截止提醒", width="large")
def _render_ddl_reminder_dialog() -> None:
    reminder_items = st.session_state.get("ddl_pending_reminders", [])
    if not reminder_items:
        return

    st.write("这些任务即将截止或已经逾期，请安排时间及时处理。")
    labels = {
        "24h": ("24 小时提醒", "ddl-reminder-24h"),
        "12h": ("12 小时提醒", "ddl-reminder-12h"),
        "3h": ("紧急提醒 · 3 小时内", "ddl-reminder-3h"),
        "overdue": ("任务已逾期", "ddl-reminder-overdue"),
    }
    for reminder in reminder_items:
        title, style_class = labels[reminder["reminder_type"]]
        remaining_text = reminders.format_remaining_time(
            reminder["remaining_seconds"]
        )
        st.markdown(
            f"""
            <section class="ddl-reminder {style_class}">
              <div class="ddl-reminder-heading">{title}</div>
              <div class="ddl-reminder-task">{escape(reminder["title"])}</div>
              <div class="ddl-reminder-detail">
                {escape(remaining_text)} · {escape(reminder["priority"])}优先级
                · {escape(reminder["category"])}
              </div>
              <div class="ddl-reminder-deadline">
                截止：{escape(reminder["due_date"])} {escape(reminder["due_time"])}
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    view_column, later_column = st.columns(2)
    if view_column.button(
        "查看任务",
        key="ddl_reminder_view_task",
        type="primary",
        width="stretch",
    ):
        st.session_state["reminder_task_search"] = reminder_items[0]["title"]
        st.session_state["navigation_target"] = "任务管理"
        st.session_state.pop("ddl_pending_reminders", None)
        st.rerun()

    if later_column.button(
        "稍后提醒",
        key="ddl_reminder_later",
        width="stretch",
    ):
        st.session_state.pop("ddl_pending_reminders", None)
        st.rerun()


@st.fragment(run_every="60s")
def _check_and_render_ddl_reminders() -> None:
    try:
        new_reminders = reminders.get_due_reminders()
    except DatabaseError as error:
        st.error(f"检查 DDL 提醒失败：{error}")
        return
    if new_reminders:
        st.session_state.setdefault("ddl_pending_reminders", new_reminders)
    if st.session_state.get("ddl_pending_reminders"):
        _render_ddl_reminder_dialog()


def main() -> None:
    """初始化基础设施并渲染当前页面。"""
    st.set_page_config(
        page_title="DDL Planner Lite",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_stylesheet()
    try:
        initialize_database()
    except DatabaseError as error:
        st.error(f"数据库初始化失败：{error}")
        st.stop()

    selected_page = render_navigation()
    PAGE_RENDERERS[selected_page]()
    _check_and_render_ddl_reminders()


if __name__ == "__main__":
    main()
