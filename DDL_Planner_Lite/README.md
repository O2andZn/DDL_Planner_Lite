# DDL Planner Lite

DDL Planner Lite 是一款面向大学生的轻量级任务与截止日期管理工具，用于管理课程作业、实验报告、考试复习和论文等学习任务。本项目采用 Python、Streamlit 和 SQLite，界面使用自定义 CSS，提供任务管理、每日计划、专注计时和数据统计功能。

> 当前版本已实现任务管理、本地持久化、首页 Dashboard、每日计划、25 分钟番茄钟和数据统计中心。

## 项目结构

```text
DDL_Planner_Lite/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── data/
│   └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── pages/
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── task_manager.py
│   │   ├── daily_plan.py
│   │   └── statistics.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── tasks.py
│   │   ├── daily_plan.py
│   │   ├── focus.py
│   │   ├── data_management.py
│   │   ├── reminders.py
│   │   └── statistics.py
│   └── ui/
│       ├── __init__.py
│       └── navigation.py
├── assets/
│   └── style.css
├── backups/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   ├── test_task_service.py
│   ├── test_focus.py
│   ├── test_daily_plan.py
│   ├── test_statistics.py
│   ├── test_data_management.py
│   └── test_reminders.py
└── logs/
    └── .gitkeep
```

## 环境要求

- Python 3.10 或更高版本
- pip

## 安装依赖

在项目根目录执行：

```bash
python -m venv .venv
```

Windows PowerShell 激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装项目依赖：

```bash
python -m pip install -r requirements.txt
```

## 运行项目

在项目根目录执行：

```bash
streamlit run app.py
```

Streamlit 启动后会在终端显示本地访问地址，通常为 `http://localhost:8501`。

## 数据库

首次启动时，应用会在 `data/ddl_planner.db` 创建 SQLite 数据库和 `tasks` 表。任务截止时间保存在 `due_date` 和 `due_time` 字段；旧任务会迁移为截止日当天 `23:59`。`task_reminders` 表记录已触发的阶段，改动任务截止时间会清除其旧阶段记录；SQLite 使用 Python 标准库，无需单独安装或启动数据库服务。
应用还会创建 `focus_records` 表保存专注会话和状态，不会清空已有任务或专注记录。计时记录包含可空的 `mode`、`planned_duration` 和当前计时段起点字段；升级时旧记录字段保留为空，不推测其模式。
应用会创建 `daily_plan_items` 保存每日计划；任务表的 `completed_at` 用于准确统计完成日期。旧任务的完成时间无法确认时会保留为空，不会使用 `updated_at` 推测。`data_management_logs` 只记录清理类型与数量，不包含任务标题或描述。

任务管理支持创建、搜索与组合筛选、编辑、删除确认和标记完成。分类包含预设选项和自定义名称；每条新任务必须填写名称和截止日期/时间。应用打开时及前台运行期间每分钟，会检查未完成任务的 24 小时、12 小时、3 小时和逾期提醒；同一任务同一阶段只提示一次，可在提醒弹窗中查看任务或稍后关闭。提醒仅在应用内显示，不会在网页关闭时推送。首页显示实时任务统计、完成进度、今日待办和近期截止提醒。关闭应用或重新启动不会清除任务。

今日计划页面可从所有未完成任务中选择一项或多项安排到当天，计划日期与任务截止日期相互独立；支持移除当日计划、完成任务和关联专注目标。番茄钟支持倒计时（15、25、30、45、60 分钟或 1～180 分钟自定义）及不设时限的正计时。计时状态持久化到 SQLite，支持暂停、继续和重置；倒计时完成计入番茄钟次数，正计时结束计入自由专注次数，重置放弃的记录不纳入有效时长统计。

数据统计中心展示真实任务总览、最近 7 天新增/完成任务、分类与优先级分布，以及倒计时和正计时有效专注的累计时长和最近 7 天趋势，并分别展示完成番茄钟与自由专注次数。

专注统计右上角的「清除记录」按钮会在二次确认后清空专注历史；若有正在进行或暂停的番茄钟，则必须先结束或重置计时。清理不会删除任务或每日计划。数据库备份仍可由服务代码创建，当前没有单独的备份管理页面。

界面采用 Pastel Campus 浅色主题，侧边栏可切换到 Midnight Study 深色主题；偏好保存在页面地址参数中，刷新后会继续沿用。各页面共用圆角卡片、柔和色彩和适配主题的图表样式。

## 运行测试

在项目根目录执行：

```bash
python -m unittest discover -s tests -v
```

测试使用独立临时 SQLite 数据库，不会修改 `data/ddl_planner.db`。
