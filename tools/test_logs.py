# -*- coding: utf-8 -*-
"""日志清理逻辑单元测试：验证按 id 精确删除、其余日志与任务数据不受影响。

用法：py test_logs.py
"""
import datetime
import importlib.util
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(APP_DIR, "server.py")

spec = importlib.util.spec_from_file_location("taskboard_server", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, ("| " + str(extra)) if extra else "")


def make_log(log_id, log_type, at, changes=None, snapshot=None):
    log = {"id": log_id, "at": at, "taskId": "task-x", "taskTitle": "T", "type": log_type}
    if changes:
        log["changes"] = changes
    if snapshot:
        log["snapshot"] = snapshot
    return log


def iso(days_ago, hours=0):
    t = datetime.datetime.now().astimezone() - datetime.timedelta(days=days_ago, hours=hours)
    return t.isoformat(timespec="seconds")


def build_data():
    return {
        "version": 1,
        "statuses": ["待处理"],
        "tasks": [{"id": "task-x", "title": "T", "status": "待处理", "archived": False}],
        "logs": [
            make_log("v1", "view", iso(0, 3)),
            make_log("v2", "view", iso(3)),
            make_log("v3", "view", iso(40)),
            make_log("u1", "update", iso(2),
                     changes=[{"field": "title", "from": "旧标题甲", "to": "新标题乙"}]),
            make_log("c1", "create", iso(0, 1), snapshot={"title": "示例任务", "status": "待处理"}),
            make_log("a1", "archive", iso(0, 2)),
            make_log("d1", "delete", iso(0, 2), snapshot={"title": "已删任务"}),
            make_log("bad", "view", "不是时间"),  # 时间异常：按 id 清理时与其他日志同等对待
        ],
    }


def ids(data):
    return [l["id"] for l in data["logs"]]


# 1. 按 id 清理子集（模拟“类型=查看”的筛选结果）：只删命中，其余原样保留
data = build_data()
removed = server.remove_logs_by_ids(data, ["v1", "v2", "v3", "bad"])
check("按 id 清理子集：删除条数=4", removed == 4, removed)
check("按 id 清理子集：目标全部删除", not ({"v1", "v2", "v3", "bad"} & set(ids(data))), ids(data))
check("按 id 清理子集：其余日志保留", set(ids(data)) == {"u1", "c1", "a1", "d1"}, ids(data))
check("按 id 清理子集：变更前后值原样保留",
      any(l["id"] == "u1" and l["changes"][0]["from"] == "旧标题甲" for l in data["logs"]),
      ids(data))

# 2. 按 id 清理单条（模拟“类型+时间+关键词”组合筛选结果）
data = build_data()
removed = server.remove_logs_by_ids(data, ["u1"])
check("按 id 清理单条：删除 1 条", removed == 1, removed)
check("按 id 清理单条：仅该条被删", "u1" not in ids(data) and len(data["logs"]) == 7, ids(data))

# 3. 全量清理（模拟“无筛选条件”的当前列表 = 全部日志）
data = build_data()
all_ids = ids(data)
removed = server.remove_logs_by_ids(data, all_ids)
check("全量清理：删除条数=全部", removed == len(all_ids) and data["logs"] == [],
      (removed, data["logs"]))

# 4. 安全性：id 不存在时不删除任何日志
data = build_data()
removed = server.remove_logs_by_ids(data, ["no-such-1", "no-such-2"])
check("不存在的 id：删除 0 条且数据不变", removed == 0 and len(data["logs"]) == 8,
      (removed, len(data["logs"])))

# 5. 边界：空集合 / None 不做任何删除
data = build_data()
r1 = server.remove_logs_by_ids(data, [])
r2 = server.remove_logs_by_ids(data, None)
check("空集合 / None：删除 0 条且数据不变",
      r1 == 0 and r2 == 0 and len(data["logs"]) == 8, (r1, r2, len(data["logs"])))

# 6. 边界：重复 id 只删除一次、计数不重复
data = build_data()
removed = server.remove_logs_by_ids(data, ["v1", "v1", "v1"])
check("重复 id：删除条数按实际计（1）", removed == 1 and "v1" not in ids(data),
      (removed, ids(data)))

# 7. 任务与状态数据不受影响
data = build_data()
server.remove_logs_by_ids(data, ["v1", "c1"])
check("清理日志不影响任务与状态",
      len(data["tasks"]) == 1 and data["tasks"][0]["id"] == "task-x"
      and data["statuses"] == ["待处理"],
      (data["tasks"], data["statuses"]))

print()
print("单元测试完成：通过 %d 项，失败 %d 项" % (passed, failed))
sys.exit(1 if failed else 0)
