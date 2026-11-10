"""首页 Dashboard。"""

from datetime import date, datetime
from html import escape
from random import choice

import streamlit as st

from src.database import DatabaseError, TaskNotFoundError
from src.services import daily_plan, tasks


_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_MOTIVATION = (
    "把大目标拆成小步骤，今天完成一点也很棒。",
    "专注当下的一件事，进步就会慢慢累积。",
    "计划让努力更有方向，行动让目标更近一步。",
    "不必一次做到完美，先开始就是很好的进度。",
    "给今天的自己一个小目标，然后安心完成它。",
)
_PRIORITY_COLORS = {"高": "priority-high", "中": "priority-medium", "低": "priority-low"}
_METRIC_ICONS = {
    "all": '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H20a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5.5A1.5 1.5 0 0 1 4 18.5z"/><path d="M8 4v16M11 8h6M11 12h6"/>',
    "pending": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "completed": '<path d="m5 12 4 4L19 6"/><circle cx="12" cy="12" r="9"/>',
    "overdue": '<path d="M12 9v4m0 4h.01"/><path d="m10.3 3.9-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3.1l-8-14a2 2 0 0 0-3.4 0Z"/>',
}
_MOCHI = """
<svg class="mochi-illustration" viewBox="0 0 220 190" role="img" aria-label="戴着薰衣草围巾的 Mochi 小猫">
  <ellipse cx="110" cy="170" rx="70" ry="10" fill="#8067a8" opacity=".12"/>
  <path d="M55 86 48 37c-1-8 8-13 14-8l34 25m69 32 8-49c1-8-8-13-14-8l-34 25" fill="#fffdf8" stroke="#76677f" stroke-width="4" stroke-linejoin="round"/>
  <path d="m57 55 25 14m80-14-25 14" stroke="#f3b8cf" stroke-width="8" stroke-linecap="round"/>
  <path d="M45 105c0-36 29-65 65-65s65 29 65 65v31c0 20-16 36-36 36H81c-20 0-36-16-36-36z" fill="#fffdf8" stroke="#76677f" stroke-width="4"/>
  <path d="M78 104c7-8 17-8 24 0m16 0c7-8 17-8 24 0" fill="none" stroke="#51465c" stroke-width="4" stroke-linecap="round"/>
  <path d="m104 119 6 5 6-5" fill="#f3b8cf" stroke="#51465c" stroke-width="2" stroke-linejoin="round"/>
  <path d="M82 130c5 5 10 5 15 0m26 0c5 5 10 5 15 0" fill="none" stroke="#f0a8bd" stroke-width="4" stroke-linecap="round"/>
  <path d="M61 148c20-12 77-12 98 0l-7 23H68z" fill="#bca3ee" stroke="#76677f" stroke-width="3" stroke-linejoin="round"/>
  <path d="m109 149 14 9-14 16-14-16z" fill="#a78bce" stroke="#76677f" stroke-width="2" stroke-linejoin="round"/>
  <path d="m35 78 5-9m145 9 5-9M31 113h-9m167 0h9" stroke="#e5b7c8" stroke-width="3" stroke-linecap="round"/>
</svg>
"""


def _render_task(
    task: dict, *, section: str, due_label: str, action_scope: str
) -> None:
    with st.container(border=True):
        st.markdown(f"**{escape(task['title'])}**")
        priority_class = _PRIORITY_COLORS.get(task["priority"], "priority-medium")
        st.markdown(
            f'<span class="task-badge {priority_class}">'
            f'{escape(task["priority"])}优先级</span> '
            f'<span class="task-badge">{escape(task["category"])}</span> '
            f'<span class="task-badge {section}">{escape(due_label)}</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"截止日期：{task['due_date']}")

        if task["status"] == "待完成" and st.button(
            "标记完成",
            key=f"dashboard_complete_{action_scope}_{task['id']}",
            use_container_width=False,
        ):
            try:
                tasks.complete_task(task["id"])
            except (DatabaseError, TaskNotFoundError) as error:
                st.error(f"更新任务状态失败：{error}")
            else:
                st.toast("任务已完成。")
                st.rerun()


def _render_welcome_banner(
    today: date, completion_rate: float, completed_today: int, planned_today: int
) -> None:
    hour = datetime.now().hour
    greeting = "早上好" if hour < 12 else "下午好" if hour < 18 else "晚上好"
    weekday = _WEEKDAYS[today.weekday()]
    motivation = choice(_MOTIVATION)
    completion = completion_rate
    st.markdown(
        f"""
        <section class="welcome-banner">
          <div class="welcome-copy">
            <div class="eyebrow">DDL PLANNER LITE <span>✦</span> STUDY BUDDY</div>
            <h1>{greeting}，今天也一起加油！</h1>
            <p class="welcome-date">{today:%Y年%m月%d日} · {weekday}</p>
            <p class="welcome-motivation">{escape(motivation)}</p>
            <div class="welcome-progress-label">
              <span>今日计划 · {completed_today}/{planned_today} 项完成</span>
              <strong>{completion:.0%}</strong>
            </div>
            <div class="welcome-progress-track">
              <span style="width:{completion:.0%}"></span>
            </div>
          </div>
          <div class="welcome-art">{_MOCHI}</div>
          <div class="welcome-sparkle sparkle-one">✦</div>
          <div class="welcome-sparkle sparkle-two">✧</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_metric_cards(data: dict) -> None:
    metrics = (
        ("all", "全部任务", data["total"], "收进清单的每个小目标", "lavender"),
        ("pending", "待完成", data["pending"], "一步一步，不用着急", "pink"),
        ("completed", "已完成", data["completed"], "为今天的努力点赞", "mint"),
        ("overdue", "已逾期", data["overdue"], "先处理最重要的一项", "butter"),
    )
    columns = st.columns(4, gap="medium")
    for column, (icon, label, value, note, tone) in zip(columns, metrics):
        column.markdown(
            f"""
            <div class="dashboard-metric metric-{tone}">
              <div class="metric-heading">
                <span>{label}</span>
                <span class="metric-icon">
                  <svg viewBox="0 0 24 24" aria-hidden="true">{_METRIC_ICONS[icon]}</svg>
                </span>
              </div>
              <div class="metric-number">{value}</div>
              <div class="metric-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_today_tasks(today_tasks: list[dict]) -> None:
    st.subheader("今日待办")
    if not today_tasks:
        st.info("今天没有待完成任务，安排一些休息时间吧。")
        return
    for task in today_tasks:
        _render_task(
            task,
            section="deadline-today",
            due_label="今天截止",
            action_scope="today",
        )


def _render_deadline_reminders(data: dict, today: date) -> None:
    st.subheader("近期 DDL 提醒")

    overdue_tasks = data["overdue_tasks"]
    if overdue_tasks:
        st.markdown("**已逾期**")
        for task in overdue_tasks:
            overdue_days = (today - date.fromisoformat(task["due_date"])).days
            _render_task(
                task,
                section="deadline-overdue",
                due_label=f"已逾期 {overdue_days} 天",
                action_scope="overdue",
            )

    upcoming_tasks = data["upcoming_tasks"]
    if upcoming_tasks:
        st.markdown("**未来 7 天**")
        for task in upcoming_tasks:
            days_left = (date.fromisoformat(task["due_date"]) - today).days
            if days_left == 0:
                due_label, section = "今天截止", "deadline-today"
            elif days_left == 1:
                due_label, section = "明天截止", "deadline-tomorrow"
            else:
                due_label, section = f"还剩 {days_left} 天", "deadline-normal"
            _render_task(
                task,
                section=section,
                due_label=due_label,
                action_scope="upcoming",
            )
    elif not overdue_tasks:
        st.info("未来 7 天内没有即将截止的任务。")


def _navigate_to_task_manager() -> None:
    st.session_state["navigation_target"] = "任务管理"


def render_dashboard() -> None:
    """从真实任务数据渲染欢迎信息、统计和截止提醒。"""
    today = date.today()
    try:
        data = tasks.get_dashboard_data(today=today)
        planned_today = daily_plan.get_planned_tasks(today)
    except DatabaseError as error:
        st.error(f"读取首页任务数据失败：{error}")
        return

    completed_today = sum(item["status"] == "已完成" for item in planned_today)
    today_progress = completed_today / len(planned_today) if planned_today else 0.0
    _render_welcome_banner(today, today_progress, completed_today, len(planned_today))
    _render_metric_cards(data)

    st.caption(
        f"完成率 {data['completion_rate']:.0%} · "
        f"{data['completed']} / {data['total']} 项已完成"
    )

    _render_today_tasks(data["today_tasks"])
    _render_deadline_reminders(data, today)

    st.subheader("快捷操作")
    actions = st.columns(2)
    actions[0].button(
        "＋ 添加新任务",
        type="primary",
        use_container_width=True,
        on_click=_navigate_to_task_manager,
    )
    actions[1].button(
        "查看全部任务",
        use_container_width=True,
        on_click=_navigate_to_task_manager,
    )
