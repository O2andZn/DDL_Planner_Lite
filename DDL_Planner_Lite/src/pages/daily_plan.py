"""今日任务清单、番茄钟和专注统计。"""

from datetime import date, datetime
from html import escape

import streamlit as st

from src import database
from src.services import daily_plan, focus, tasks


_MOTIVATION = (
    "专注眼前这一小步，今天的计划就会更近一点。",
    "给自己一段安静的时间，把重要的事做好。",
    "每一次专注，都是在为目标积累进度。",
)
_PRIORITY_COLORS = {"高": "priority-high", "中": "priority-medium", "低": "priority-low"}
_STATUS_LABELS = {
    "running": "进行中",
    "paused": "已暂停",
    "completed": "已完成",
    "abandoned": "未完成",
}
_TIMER_MOCHI = """
<svg viewBox="0 0 64 54" aria-hidden="true">
  <path d="m8 23-3-16c0-3 3-5 5-3l11 9m22 10 3-16c0-3-3-5-5-3L30 15" fill="#fffdf8" stroke="#76677f" stroke-width="2.5" stroke-linejoin="round"/>
  <path d="m9 15 8 4m30-4-8 4" stroke="#f3b8cf" stroke-width="4" stroke-linecap="round"/>
  <path d="M7 32c0-13 10-23 25-23s25 10 25 23v6c0 8-7 14-15 14H22C14 52 7 46 7 38z" fill="#fffdf8" stroke="#76677f" stroke-width="2.5"/>
  <path d="M20 30c2-3 5-3 7 0m10 0c2-3 5-3 7 0" fill="none" stroke="#51465c" stroke-width="2.5" stroke-linecap="round"/>
  <path d="m29 36 3 2 3-2" fill="#f3b8cf" stroke="#51465c" stroke-width="1.5" stroke-linejoin="round"/>
  <path d="M24 43c2 2 4 2 6 0m4 0c2 2 4 2 6 0" fill="none" stroke="#f0a8bd" stroke-width="2" stroke-linecap="round"/>
</svg>
"""


def _format_duration(seconds: int) -> str:
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    if minutes:
        return f"{minutes} 分 {remaining_seconds:02d} 秒"
    return f"{remaining_seconds} 秒"


def _format_clock(seconds: int) -> str:
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _task_selector(pending_tasks: list[dict], active: dict | None) -> int | None:
    st.markdown("#### 当前专注目标")
    task_map = {task["id"]: task for task in pending_tasks}
    options: list[int | None] = [None, *task_map]
    key = "daily_focus_task_id"
    if st.session_state.get(key) not in options:
        st.session_state[key] = None

    return st.selectbox(
        "选择一个待完成任务，也可以使用自由专注",
        options,
        format_func=lambda task_id: (
            "自由专注（不关联任务）"
            if task_id is None
            else task_map[task_id]["title"]
        ),
        key=key,
        disabled=active is not None,
        label_visibility="collapsed",
    )


def _render_today_tasks(today_tasks: list[dict], active: dict | None) -> None:
    st.subheader("今日任务清单")
    if not today_tasks:
        st.info("今天没有待完成任务。你仍然可以从其他待完成任务中选择专注目标。")
        return

    for task in today_tasks:
        with st.container(border=True):
            st.markdown(f"**{task['title']}**")
            priority_class = _PRIORITY_COLORS.get(
                task["priority"], "priority-medium"
            )
            status_class = (
                "status-completed"
                if task["status"] == "已完成"
                else "status-pending"
            )
            st.markdown(
                f'<span class="task-badge {priority_class}">'
                f'{escape(task["priority"])}优先级</span> '
                f'<span class="task-badge">{escape(task["category"])}</span> '
                f'<span class="task-badge {status_class}">'
                f'{escape(task["status"])}</span>'
                + (
                    '<span class="task-badge focus-target-chip">正在专注</span>'
                    if active is not None and active["task_id"] == task["id"]
                    else ""
                ),
                unsafe_allow_html=True,
            )
            st.caption(f"最终截止日期：{task['due_date'] or '未设置'}")

            action_columns = st.columns((1, 1))
            if task["status"] == "待完成" and action_columns[0].button(
                "设为专注目标",
                key=f"daily_select_task_{task['id']}",
                disabled=active is not None,
                use_container_width=True,
            ):
                st.session_state["daily_focus_task_id"] = task["id"]
                st.rerun()

            if task["status"] == "待完成" and action_columns[1].button(
                "标记完成",
                key=f"daily_complete_task_{task['id']}",
                disabled=active is not None and active["task_id"] == task["id"],
                use_container_width=True,
            ):
                try:
                    tasks.complete_task(task["id"])
                except (database.DatabaseError, database.TaskNotFoundError) as error:
                    st.error(f"更新任务状态失败：{error}")
                else:
                    st.toast("任务已完成。")
                    st.rerun()

            if action_columns[1].button(
                "从今日计划移除",
                key=f"daily_remove_task_{task['plan_item_id']}",
                use_container_width=True,
            ):
                try:
                    daily_plan.remove_task(task["plan_item_id"], task["plan_date"])
                except (database.DatabaseError, database.TaskNotFoundError) as error:
                    st.error(f"移除计划任务失败：{error}")
                else:
                    st.toast("已从今日计划移除，原任务仍保留在任务库中。")
                    st.rerun()


def _render_add_tasks_area(today: date) -> None:
    st.subheader("安排今日任务")
    try:
        available_tasks = daily_plan.get_available_tasks(today)
    except database.DatabaseError as error:
        st.error(f"读取可安排任务失败：{error}")
        return

    if not available_tasks:
        st.info("没有可加入的待完成任务。已完成或已安排的任务不会重复显示。")
        return

    task_map = {task["id"]: task for task in available_tasks}
    selected_task_ids = st.multiselect(
        "从任务库选择一个或多个未完成任务",
        options=list(task_map),
        format_func=lambda task_id: (
            f"{task_map[task_id]['title']} · 截止 "
            f"{task_map[task_id]['due_date'] or '未设置'}"
        ),
        key="daily_plan_add_selection",
    )
    if st.button(
        "添加到今日计划",
        key="daily_plan_add_button",
        type="primary",
        disabled=not selected_task_ids,
    ):
        try:
            added_count = daily_plan.add_tasks(selected_task_ids, today)
        except (database.DatabaseError, database.TaskNotFoundError) as error:
            st.error(f"添加到今日计划失败：{error}")
        else:
            st.success(f"已添加 {added_count} 项任务到今日计划。")
            st.session_state.pop("daily_focus_task_id", None)
            st.rerun()

def _render_focus_timer(selected_task_id: int | None) -> None:
    try:
        completed_now = focus.complete_expired_focus()
        active = focus.get_active_focus()
    except database.DatabaseError as error:
        st.error(f"读取专注计时失败：{error}")
        return

    st.subheader("番茄钟")
    if "focus_planned_minutes" not in st.session_state:
        st.session_state["focus_planned_minutes"] = 25
    if "focus_custom_minutes" not in st.session_state:
        st.session_state["focus_custom_minutes"] = 25
    if active is not None:
        timer_mode = active.get("mode") or "countdown"
        st.session_state["focus_timer_mode"] = timer_mode
    elif st.session_state.get("focus_timer_mode") not in ("countdown", "count_up"):
        st.session_state["focus_timer_mode"] = "countdown"

    timer_mode = st.radio(
        "计时模式",
        options=("countdown", "count_up"),
        format_func=lambda mode: (
            "倒计时 Countdown" if mode == "countdown" else "正计时 Count Up"
        ),
        key="focus_timer_mode",
        horizontal=True,
        disabled=active is not None,
    )
    if active is None and timer_mode == "countdown":
        choices = ("15分钟", "25分钟", "30分钟", "45分钟", "60分钟", "自定义")
        if st.session_state.get("focus_duration_choice") not in choices:
            st.session_state["focus_duration_choice"] = "25分钟"
        selected_duration = st.selectbox(
            "专注时长",
            choices,
            key="focus_duration_choice",
            label_visibility="collapsed",
        )
        quick_minutes = {
            "15分钟": 15,
            "25分钟": 25,
            "30分钟": 30,
            "45分钟": 45,
            "60分钟": 60,
        }
        if selected_duration in quick_minutes:
            st.session_state["focus_planned_minutes"] = quick_minutes[selected_duration]
        else:
            custom_minutes = st.number_input(
                "自定义时长（1～180 分钟）",
                min_value=1,
                max_value=180,
                step=1,
                key="focus_custom_minutes",
            )
            if st.button("应用自定义时长", key="focus_apply_custom_duration"):
                try:
                    focus.validate_countdown_minutes(custom_minutes)
                except focus.FocusTimerError as error:
                    st.error(str(error))
                else:
                    st.session_state["focus_planned_minutes"] = custom_minutes
                    st.toast(f"倒计时已设置为 {custom_minutes} 分钟。")
                    st.rerun()
        st.caption(
            f"当前倒计时：{st.session_state['focus_planned_minutes']} 分钟"
        )
    elif active is None:
        st.info("自由专注，没有时间限制，按照自己的节奏完成任务。")

    if active is not None:
        task_title = active["task_title"]
        timer_status = active["status"]
        is_count_up = timer_mode == "count_up"
        if is_count_up:
            timer_value = focus.get_elapsed_seconds(active)
            planned_duration = None
        else:
            try:
                timer_value = focus.get_remaining_seconds(active)
            except (TypeError, ValueError) as error:
                st.error(f"读取计时状态失败：{error}")
                return
            planned_duration = active.get("planned_duration") or (
                int(active["duration"]) + int(active["remaining_seconds"])
            )
    else:
        try:
            selected_task = (
                database.get_task(selected_task_id) if selected_task_id else None
            )
        except database.DatabaseError as error:
            st.error(f"读取专注目标失败：{error}")
            return
        task_title = selected_task["title"] if selected_task else "自由专注"
        timer_status = "idle"
        is_count_up = timer_mode == "count_up"
        planned_duration = (
            None
            if is_count_up
            else int(st.session_state["focus_planned_minutes"]) * 60
        )
        timer_value = 0 if is_count_up else (planned_duration or 0)

    st.markdown(f"**当前目标：{task_title}**")
    if active is not None:
        elapsed = focus.get_elapsed_seconds(active)
        if is_count_up:
            progress = (elapsed % 60) / 60
            st.caption(
                "自由专注进行中 · 任务选择已锁定"
                if timer_status == "running"
                else "自由专注已暂停 · 继续后从累计时间恢复"
            )
        elif timer_status == "running":
            progress = elapsed / max(1, planned_duration or 1)
            st.caption("专注进行中 · 任务选择已锁定")
        else:
            progress = elapsed / max(1, planned_duration or 1)
            st.caption("计时已暂停 · 继续后从剩余时间开始")
    elif is_count_up:
        progress = 0.0
        st.caption("自由专注 · 任务选择会在计时开始后锁定")
    else:
        progress = 0.0
        st.caption(f"准备好后开始一段 {planned_duration // 60} 分钟的专注")

    progress = min(1.0, max(0.0, progress))
    ring_mode_class = "pomodoro-count-up" if is_count_up else "pomodoro-countdown"
    st.markdown(
        f"""
        <div class="pomodoro-stage">
          <div class="pomodoro-ring pomodoro-{timer_status} {ring_mode_class}"
               style="--timer-angle:{progress * 360:.1f}deg">
            <div class="pomodoro-face">
              <div class="pomodoro-mochi">{_TIMER_MOCHI}</div>
              <div class="pomodoro-clock">{_format_clock(timer_value)}</div>
              <div class="pomodoro-clock-label">
                {"自由专注" if is_count_up else f"倒计时 · {planned_duration // 60} 分钟"}
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if completed_now is not None:
        st.session_state["focus_just_completed"] = True
    if st.session_state.pop("focus_just_completed", False):
        st.success("专注已完成并保存，时长统计已更新。")

    controls = st.columns(3)
    try:
        if active is None:
            if controls[0].button(
                "开始专注",
                key="focus_start",
                type="primary",
                use_container_width=True,
            ):
                focus.start_focus(
                    selected_task_id,
                    mode=timer_mode,
                    planned_duration_seconds=(
                        planned_duration if timer_mode == "countdown" else None
                    ),
                )
                st.rerun()
        elif timer_status == "running":
            if controls[0].button(
                "暂停",
                key="focus_pause",
                use_container_width=True,
            ):
                focus.pause_focus()
                st.rerun()
        elif controls[0].button(
            "继续",
            key="focus_resume",
            type="primary",
            use_container_width=True,
        ):
            focus.resume_focus()
            st.rerun()

        if active is not None and timer_mode == "count_up" and controls[1].button(
            "结束并保存",
            key="focus_finish_count_up",
            type="primary",
            use_container_width=True,
        ):
            focus.finish_count_up_focus()
            st.session_state["focus_just_completed"] = True
            st.rerun()

        reset_column = controls[2] if timer_mode == "count_up" else controls[1]
        if active is not None and reset_column.button(
            "重置 / 放弃",
            key="focus_reset",
            use_container_width=True,
        ):
            focus.reset_focus()
            st.toast("本次计时已放弃，不计入有效专注统计。")
            st.rerun()
    except focus.FocusTimerError as error:
        st.error(str(error))
    except database.DatabaseError as error:
        st.error(f"保存专注状态失败：{error}")


def _render_completion_action(stats: dict) -> None:
    record = stats["recent_record"]
    if record is None or record["status"] != "completed" or not record["task_id"]:
        return

    try:
        task = database.get_task(record["task_id"])
    except database.DatabaseError as error:
        st.error(f"读取关联任务失败：{error}")
        return
    if task is None or task["status"] != "待完成":
        return

    st.info(
        f"刚刚完成了「{record['task_title']}」的一段专注。"
        "番茄钟完成不代表任务已全部完成，请按实际进度决定是否标记任务完成。"
    )
    if st.button(
        "将关联任务标记为完成",
        key=f"focus_complete_task_{record['id']}",
    ):
        try:
            tasks.complete_task(record["task_id"])
        except (database.DatabaseError, database.TaskNotFoundError) as error:
            st.error(f"更新任务状态失败：{error}")
        else:
            st.success("关联任务已标记为完成。")
            st.rerun()


def _render_focus_statistics(today: date) -> None:
    st.subheader("今日专注统计")
    try:
        stats = focus.get_today_focus_stats(today=today)
    except database.DatabaseError as error:
        st.error(f"读取今日专注统计失败：{error}")
        return

    metrics = st.columns(3)
    metrics[0].metric("今日专注时长", _format_duration(stats["total_seconds"]))
    metrics[1].metric("已完成番茄钟", stats["completed_pomodoros"])
    metrics[2].metric("自由专注次数", stats["count_up_sessions"])

    _render_completion_action(stats)

    if not stats["records"]:
        st.info("今天还没有专注记录，开始第一段专注后数据会显示在这里。")
        return

    task_column, recent_column = st.columns(2)
    with task_column:
        st.markdown("#### 按任务统计")
        for item in stats["task_totals"]:
            st.write(
                f"**{item['task_title']}** · "
                f"{_format_duration(int(item['duration']))} · "
                f"{item['completed_pomodoros']} 个完整番茄钟 · "
                f"{item['count_up_sessions']} 次自由专注"
            )

    with recent_column:
        st.markdown("#### 最近一次专注")
        record = stats["recent_record"]
        started = datetime.fromisoformat(record["started_at"])
        st.write(f"**{record['task_title']}**")
        st.caption(
            f"{started:%H:%M} 开始 · "
            f"{_format_duration(record['actual_duration'])} · "
            f"{_STATUS_LABELS[record['status']]}"
        )


@st.fragment(run_every="1s")
def _render_daily_plan_content() -> None:
    today = date.today()
    st.title("今日计划")
    st.caption(f"{today:%Y年%m月%d日} · {_MOTIVATION[today.toordinal() % len(_MOTIVATION)]}")

    try:
        planned_tasks = daily_plan.get_planned_tasks(today)
    except database.DatabaseError as error:
        st.error(f"读取今日计划失败：{error}")
        return

    try:
        active = focus.get_active_focus()
    except database.DatabaseError as error:
        st.error(f"读取专注计时失败：{error}")
        return

    _render_add_tasks_area(today)
    pending_planned_tasks = [
        task for task in planned_tasks if task["status"] == "待完成"
    ]

    task_column, timer_column = st.columns((1.1, 1), gap="large")
    with task_column:
        _render_today_tasks(planned_tasks, active)
    with timer_column:
        pending_planned_map = {task["id"]: task for task in pending_planned_tasks}
        selected_task_id = _task_selector(pending_planned_tasks, active)
        if selected_task_id is not None:
            st.caption(f"已选择：{pending_planned_map[selected_task_id]['title']}")
        _render_focus_timer(selected_task_id)

    st.divider()
    _render_focus_statistics(today)


def render_daily_plan() -> None:
    """渲染带每秒定时刷新的今日计划页面。"""
    _render_daily_plan_content()
