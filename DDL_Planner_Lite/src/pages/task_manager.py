"""任务管理页面。"""

from datetime import date, datetime, time
from html import escape

import streamlit as st

from src.database import DatabaseError, TaskNotFoundError
from src.services import tasks


_PRIORITY_COLORS = {"高": "priority-high", "中": "priority-medium", "低": "priority-low"}


def _deadline_text(due_date: str | None, due_time: str = "23:59") -> str:
    if not due_date:
        return "未设置截止日期"
    try:
        deadline = datetime.combine(
            date.fromisoformat(due_date),
            time.fromisoformat(due_time or "23:59"),
        ).astimezone()
    except ValueError:
        return f"截止日期：{due_date}"

    current_time = datetime.now().astimezone()
    seconds_left = int((deadline - current_time).total_seconds())
    if seconds_left < 0:
        overdue_seconds = abs(seconds_left)
        overdue_hours, remainder = divmod(overdue_seconds, 3600)
        if overdue_hours:
            return f"已逾期 {overdue_hours} 小时 {remainder // 60} 分钟"
        return "已逾期"
    days_left = (deadline.date() - current_time.date()).days
    if days_left == 0:
        return "今天截止"
    return f"还剩 {days_left} 天"


def _render_task_form() -> None:
    st.subheader("添加任务")
    category = st.selectbox("任务分类", tasks.CATEGORY_OPTIONS, key="add_category_choice")
    custom_category = ""
    if category == tasks.CUSTOM_CATEGORY_OPTION:
        custom_category = st.text_input(
            "自定义分类名称 *",
            placeholder="例如：社团活动",
            key="add_custom_category",
        )

    with st.form("add_task_form", clear_on_submit=True):
        first_row = st.columns((2, 1, 1))
        title = first_row[0].text_input("任务名称 *", placeholder="例如：完成数据结构课程作业")
        due_date = first_row[1].date_input("截止日期 *", value=date.today())
        due_time = first_row[2].time_input(
            "截止时间", value=time(23, 59), step=60
        )

        description = st.text_area("任务描述（选填）", placeholder="补充任务要求或备注")
        priority = st.selectbox("优先级", tasks.PRIORITIES, index=1)

        submitted = st.form_submit_button(
            "添加任务", type="primary", use_container_width=True
        )

    if submitted:
        try:
            tasks.add_task(
                title=title,
                description=description,
                due_date=due_date,
                due_time=due_time,
                priority=priority,
                category=category,
                custom_category=custom_category,
            )
        except tasks.TaskValidationError as error:
            st.error(str(error))
        except DatabaseError as error:
            st.error(f"保存任务失败：{error}")
        else:
            st.success("任务已添加。")
            st.rerun()


def _render_task_card(task: dict) -> None:
    task_id = task["id"]
    with st.container(border=True):
        title_text = escape(task["title"])
        if task["status"] == "已完成":
            st.markdown(
                f'<div class="task-title task-title-completed">{title_text}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="task-title">{title_text}</div>',
                unsafe_allow_html=True,
            )

        heading = st.columns((5, 1))
        priority_class = _PRIORITY_COLORS.get(task["priority"], "priority-medium")
        heading[0].markdown(
            f'<span class="task-badge {priority_class}">'
            f'{escape(task["priority"])}优先级</span> '
            f'<span class="task-badge">{escape(task["category"])}</span>',
            unsafe_allow_html=True,
        )
        status_class = "status-completed" if task["status"] == "已完成" else "status-pending"
        heading[1].markdown(
            f'<span class="task-badge {status_class}">{escape(task["status"])}</span>',
            unsafe_allow_html=True,
        )
        deadline = _deadline_text(task["due_date"], task.get("due_time") or "23:59")
        deadline_class = (
            "task-deadline-overdue"
            if deadline.startswith("已逾期")
            else "task-deadline-today"
            if deadline == "今天截止"
            else ""
        )
        st.markdown(
            f'<div class="task-deadline {deadline_class}">'
            f'截止日期：{escape(task["due_date"] or "未设置")} '
            f'{escape(task.get("due_time") or "23:59")} · '
            f'{escape(deadline)}</div>',
            unsafe_allow_html=True,
        )
        if task["description"]:
            st.write(task["description"])

        actions = st.columns((1, 1, 3))
        if task["status"] == "待完成" and actions[0].button(
            "标记完成", key=f"complete_{task_id}", use_container_width=True
        ):
            try:
                tasks.complete_task(task_id)
            except (DatabaseError, TaskNotFoundError) as error:
                st.error(f"更新任务状态失败：{error}")
            else:
                st.toast("任务已完成。")
                st.rerun()

        with actions[1].expander("编辑"):
            try:
                current_due_date = date.fromisoformat(task["due_date"])
            except (TypeError, ValueError):
                current_due_date = date.today()
            try:
                current_due_time = time.fromisoformat(task.get("due_time") or "23:59")
            except (TypeError, ValueError):
                current_due_time = time(23, 59)

            initial_category = (
                task["category"]
                if task["category"] in tasks.PRESET_CATEGORIES
                else tasks.CUSTOM_CATEGORY_OPTION
            )
            category_choice = st.selectbox(
                "任务分类",
                tasks.CATEGORY_OPTIONS,
                index=tasks.CATEGORY_OPTIONS.index(initial_category),
                key=f"edit_category_{task_id}",
            )
            custom_category = ""
            if category_choice == tasks.CUSTOM_CATEGORY_OPTION:
                custom_category = st.text_input(
                    "自定义分类名称 *",
                    value=task["category"],
                    key=f"edit_custom_category_{task_id}",
                )

            with st.form(f"edit_task_form_{task_id}"):
                edit_title = st.text_input(
                    "任务名称 *", value=task["title"], key=f"edit_title_{task_id}"
                )
                edit_description = st.text_area(
                    "任务描述",
                    value=task["description"],
                    key=f"edit_description_{task_id}",
                )
                edit_due_date = st.date_input(
                    "截止日期 *",
                    value=current_due_date,
                    key=f"edit_due_date_{task_id}",
                )
                edit_due_time = st.time_input(
                    "截止时间",
                    value=current_due_time,
                    step=60,
                    key=f"edit_due_time_{task_id}",
                )
                edit_priority = st.selectbox(
                    "优先级",
                    tasks.PRIORITIES,
                    index=tasks.PRIORITIES.index(task["priority"])
                    if task["priority"] in tasks.PRIORITIES
                    else 1,
                    key=f"edit_priority_{task_id}",
                )
                edit_submitted = st.form_submit_button("保存修改", type="primary")

            if edit_submitted:
                try:
                    tasks.edit_task(
                        task_id,
                        title=edit_title,
                        description=edit_description,
                        due_date=edit_due_date,
                        due_time=edit_due_time,
                        priority=edit_priority,
                        category=category_choice,
                        custom_category=custom_category,
                    )
                except tasks.TaskValidationError as error:
                    st.error(str(error))
                except (DatabaseError, TaskNotFoundError) as error:
                    st.error(f"保存修改失败：{error}")
                else:
                    st.success("任务已更新。")
                    st.rerun()

        if actions[2].checkbox(
            "确认删除此任务", key=f"confirm_delete_{task_id}"
        ):
            if st.button(
                "删除任务",
                key=f"delete_{task_id}",
                type="secondary",
            ):
                try:
                    tasks.remove_task(task_id)
                except (DatabaseError, TaskNotFoundError) as error:
                    st.error(f"删除任务失败：{error}")
                else:
                    st.success("任务已删除。")
                    st.rerun()


def render_task_manager() -> None:
    """渲染任务统计、创建表单、筛选器和任务列表。"""
    st.title("任务管理")
    st.write("集中管理课程作业、实验报告、考试复习和论文等任务。")

    try:
        all_tasks = tasks.get_tasks()
    except DatabaseError as error:
        st.error(f"读取任务失败：{error}")
        return

    today = datetime.now().astimezone()
    total = len(all_tasks)
    completed = sum(task["status"] == "已完成" for task in all_tasks)
    pending = total - completed
    overdue = sum(
        task["status"] == "待完成"
        and task["due_date"] is not None
        and datetime.combine(
            date.fromisoformat(task["due_date"]),
            time.fromisoformat(task.get("due_time") or "23:59"),
        ).astimezone()
        < today
        for task in all_tasks
    )

    stat_columns = st.columns(4)
    stat_columns[0].metric("任务总数", total)
    stat_columns[1].metric("待完成", pending)
    stat_columns[2].metric("已完成", completed)
    stat_columns[3].metric("已逾期", overdue)

    st.divider()
    _render_task_form()

    st.divider()
    st.subheader("任务列表")
    available_categories = ["全部"] + list(
        dict.fromkeys(task["category"] for task in all_tasks)
    )
    filter_columns = st.columns((2, 1, 1, 1))
    pending_search = st.session_state.pop("reminder_task_search", None)
    if pending_search is not None:
        st.session_state["task_search"] = pending_search
    keyword = filter_columns[0].text_input(
        "搜索任务名称",
        placeholder="输入关键词",
        key="task_search",
    )
    selected_status = filter_columns[1].selectbox(
        "任务状态", ("全部", *tasks.STATUSES)
    )
    selected_priority = filter_columns[2].selectbox(
        "优先级", ("全部", *tasks.PRIORITIES)
    )
    selected_category = filter_columns[3].selectbox("任务分类", available_categories)

    try:
        visible_tasks = tasks.get_tasks(
            status=None if selected_status == "全部" else selected_status,
            priority=None if selected_priority == "全部" else selected_priority,
            category=None if selected_category == "全部" else selected_category,
            keyword=keyword,
        )
    except (DatabaseError, tasks.TaskValidationError) as error:
        st.error(f"筛选任务失败：{error}")
        return

    if not visible_tasks:
        st.info("没有符合条件的任务。你可以先添加一个任务。")
        return

    for task in visible_tasks:
        _render_task_card(task)
