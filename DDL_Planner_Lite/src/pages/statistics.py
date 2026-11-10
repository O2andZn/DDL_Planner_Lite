"""数据统计中心。"""

from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

from src import database
from src.services import statistics


_PURPLE = "#a78bce"


def _theme_colors() -> tuple[str, str, str]:
    if st.session_state.get("theme_toggle", False):
        return "#bca3ee", "#f3edf8", "#51495f"
    return _PURPLE, "#51465c", "#e7e0ed"


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    return f"{minutes} 分钟"


def _chart_layout(figure: go.Figure, *, height: int = 340) -> go.Figure:
    _, text_color, grid_color = _theme_colors()
    figure.update_layout(
        height=height,
        margin={"l": 16, "r": 16, "t": 24, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": text_color, "family": "sans-serif"},
        legend={"orientation": "h", "y": 1.12, "x": 0},
    )
    figure.update_xaxes(
        gridcolor=grid_color,
        linecolor=grid_color,
        zerolinecolor=grid_color,
    )
    figure.update_yaxes(
        gridcolor=grid_color,
        linecolor=grid_color,
        zerolinecolor=grid_color,
    )
    return figure


def _render_task_overview(data: dict) -> None:
    st.subheader("任务总览")
    metrics = st.columns(4)
    metrics[0].metric("全部任务", data["total"])
    metrics[1].metric("已完成", data["completed"])
    metrics[2].metric("待完成", data["pending"])
    metrics[3].metric("已逾期", data["overdue"])
    st.progress(data["completion_rate"])
    st.caption(
        f"总体完成率 {data['completion_rate']:.0%} · "
        f"{data['completed']} / {data['total']} 项已完成"
    )


def _render_weekly_tasks(data: dict) -> None:
    st.subheader("最近 7 天任务变化")
    primary, _, _ = _theme_colors()
    days = [day.strftime("%m-%d") for day in data["week_dates"]]
    figure = go.Figure()
    figure.add_bar(
        x=days,
        y=data["weekly_created"],
        name="新增任务",
        marker_color="#e5c4d5" if st.session_state.get("theme_toggle", False) else "#e9dff5",
    )
    figure.add_bar(
        x=days,
        y=data["weekly_completed"],
        name="完成任务",
        marker_color=primary,
    )
    figure.update_layout(
        barmode="group",
        xaxis_title="日期",
        xaxis={"type": "category"},
        yaxis_title="任务数量",
        yaxis={"rangemode": "tozero", "dtick": 1},
    )
    st.plotly_chart(_chart_layout(figure), use_container_width=True)


def _render_category_chart(data: dict) -> None:
    st.subheader("任务分类分布")
    if not data["categories"]:
        st.info("还没有任务分类数据。")
        return
    categories = data["categories"]
    palette = (
        ("#bca3ee", "#ebafcb", "#ebcb85", "#a7dcc3", "#9aa7e6", "#d9b8e4")
        if st.session_state.get("theme_toggle", False)
        else ("#a78bce", "#f3b8cf", "#f5d98e", "#a7dcc3", "#9aa7e6", "#d9b8e4")
    )
    figure = go.Figure(
        data=[
            go.Pie(
                labels=list(categories),
                values=list(categories.values()),
                hole=0.56,
                marker={"colors": [palette[index % len(palette)] for index in range(len(categories))]},
                textinfo="label+percent",
                sort=False,
            )
        ]
    )
    st.plotly_chart(
        _chart_layout(figure, height=360),
        use_container_width=True,
    )


def _render_priority_chart(data: dict) -> None:
    st.subheader("优先级分布")
    priority_order = ("高", "中", "低")
    values = [data["priorities"].get(priority, 0) for priority in priority_order]
    figure = go.Figure(
        data=[
            go.Bar(
                x=list(priority_order),
                y=values,
                marker_color=[
                    "#edb5cf" if item == "高" else "#e7c779" if item == "中" else "#91cdb0"
                    for item in priority_order
                ],
                text=values,
                textposition="outside",
            )
        ]
    )
    figure.update_layout(
        xaxis_title="优先级",
        yaxis_title="任务数量",
        yaxis={"rangemode": "tozero", "dtick": 1},
        showlegend=False,
    )
    st.plotly_chart(_chart_layout(figure, height=300), use_container_width=True)


@st.dialog("确认清除专注记录", width="small")
def _confirm_clear_focus_records() -> None:
    st.warning(
        "即将清除全部历史专注记录。清除后，累计专注时长、"
        "已完成番茄钟数量、专注趋势和最近专注记录都会重置为空。"
    )
    try:
        active_focus = database.get_active_focus_record()
    except database.DatabaseError as error:
        st.error(f"检查当前番茄钟状态失败：{error}")
        active_focus = None
        can_clear = False
    else:
        can_clear = active_focus is None

    if not can_clear:
        st.error("当前有进行中或暂停的番茄钟。请先结束或重置计时，再清除历史记录。")

    cancel_column, confirm_column = st.columns(2)
    if cancel_column.button(
        "取消",
        key="cancel_clear_focus_records",
        width="stretch",
    ):
        st.session_state["show_clear_focus_confirmation"] = False
        st.rerun()

    if confirm_column.button(
        "确认清除",
        key="confirm_clear_focus_records",
        type="primary",
        disabled=not can_clear,
        width="stretch",
    ):
        from src.services import data_management

        try:
            deleted = data_management.clear_focus_history()
        except database.ActiveFocusError as error:
            st.error(str(error))
        except database.DatabaseError as error:
            st.error(f"清除专注记录失败：{error}")
        else:
            st.session_state["show_clear_focus_confirmation"] = False
            st.session_state["focus_records_cleared_message"] = (
                f"已清除 {deleted} 条历史专注记录，统计已更新。"
            )
            st.rerun()


def _render_focus_overview(data: dict) -> None:
    primary, _, _ = _theme_colors()
    title_column, action_column = st.columns((5, 1))
    title_column.subheader("专注统计 Focus Statistics")
    if action_column.button(
        "清除记录",
        key="open_clear_focus_confirmation",
        icon=":material/delete:",
        help="清除全部历史专注记录",
        type="secondary",
    ):
        st.session_state["show_clear_focus_confirmation"] = True
        st.rerun()

    cleared_message = st.session_state.pop("focus_records_cleared_message", None)
    if cleared_message:
        st.success(cleared_message)

    metrics = st.columns(3)
    metrics[0].metric("累计有效专注时长", _format_duration(data["total_focus_seconds"]))
    metrics[1].metric("已完成番茄钟", data["completed_pomodoros"])
    metrics[2].metric("自由专注次数", data["count_up_sessions"])

    if st.session_state.get("show_clear_focus_confirmation"):
        _confirm_clear_focus_records()

    if not data["recent_focus_records"]:
        st.info("还没有已完成的番茄钟记录。完成一段专注后，趋势数据会显示在这里。")
        return

    days = [day.strftime("%m-%d") for day in data["week_dates"]]
    minutes = [seconds / 60 for seconds in data["weekly_focus_seconds"]]
    figure = go.Figure(
        data=[
            go.Scatter(
                x=days,
                y=minutes,
                mode="lines+markers",
                name="专注时长",
                line={"color": primary, "width": 3},
                marker={"color": primary, "size": 8},
                fill="tozeroy",
                fillcolor=(
                    "rgba(188, 163, 238, 0.15)"
                    if st.session_state.get("theme_toggle", False)
                    else "rgba(167, 139, 206, 0.14)"
                ),
            )
        ]
    )
    figure.update_layout(
        xaxis_title="完成日期",
        xaxis={"type": "category"},
        yaxis_title="专注分钟数",
        yaxis={"rangemode": "tozero"},
        showlegend=False,
    )
    st.plotly_chart(_chart_layout(figure), use_container_width=True)

    st.markdown("#### 最近专注记录")
    for record in data["recent_focus_records"]:
        completed_at = datetime.fromisoformat(record["completed_at"])
        mode_label = {
            "countdown": "倒计时",
            "count_up": "自由专注",
        }.get(record.get("mode"), "历史记录")
        st.write(
            f"**{record['task_title']}** · "
            f"{completed_at:%Y-%m-%d %H:%M} 完成 · "
            f"{_format_duration(int(record['duration']))} · "
            f"{mode_label}"
        )


def render_statistics() -> None:
    """从 SQLite 数据渲染任务和专注统计。"""
    st.title("数据统计")
    st.write("回顾任务进度、分类分布和专注习惯。")
    try:
        data = statistics.get_statistics()
    except database.DatabaseError as error:
        st.error(f"读取统计数据失败：{error}")
        return

    _render_task_overview(data)

    task_trend_column, category_column = st.columns((1.2, 1))
    with task_trend_column:
        _render_weekly_tasks(data)
    with category_column:
        _render_category_chart(data)

    _render_priority_chart(data)
    st.divider()
    _render_focus_overview(data)
