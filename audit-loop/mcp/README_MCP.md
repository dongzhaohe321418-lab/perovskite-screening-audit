# science-audit-loop MCP server

本地 stdio MCP server，让 **Claude Science** 在每次 session 收尾时与本机的科学审计流水线
（scienceRepo → Tier-0 checks → Codex 审计 → controller → disposition）交互。

- server: `audit-loop/mcp/audit_mcp_server.py`
- 协议: JSON-RPC 2.0 over stdio，newline-delimited，手写实现（不依赖任何 MCP SDK）
- serverInfo: `{"name": "science-audit-loop", "version": "1.1.0"}`
- 依赖: 只用 stdlib + `audit-loop/.venv` 里已有的 `yaml` / `fastapi` / `httpx` / `jsonschema`
- 七个 tool: `audit_status`、`get_pending_review`、`submit_disposition`、`request_audit`、
  `acknowledge_escalation`、`notify_pi`、`check_action`

> `check_action`（1.1 新增）让 controller 的 fail-closed 准入闸门 `POST /actions/check`
> 第一次变得**可达**：在此之前系统里没有任何东西调用过该端点，MCP server 甚至不持有
> `ACTION_API_TOKEN`，闸门形同虚设。**诚实的边界**：它在调用点是**建议性**的
> （advisory）—— 可达、且每次咨询都记账，但**不是** enforcement：不调用它的 caller
> 不会被它拦住。把它说成"强制"就等于把当初那个缺陷换个说法留下来。

---

## 1. 注册片段 / registration

### 1.1 标准 MCP client（`mcpServers` 配置块）

任何支持标准 stdio MCP server 的 client 都用这一段。全部路径都是绝对路径，
所以 server 与 client 的工作目录无关：

```json
{
  "mcpServers": {
    "science-audit-loop": {
      "command": "/Users/ericdong/Desktop/perovskite-project/audit-loop/.venv/bin/python",
      "args": [
        "/Users/ericdong/Desktop/perovskite-project/audit-loop/mcp/audit_mcp_server.py"
      ]
    }
  }
}
```

放置位置（按 client 选一个）：

| client | 配置文件 |
| --- | --- |
| Claude Science / Claude Desktop（macOS） | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Code（项目级） | `<project>/.mcp.json`，同样的 `mcpServers` 结构 |

改完配置需要重启 client（stdio server 在 client 启动时才 spawn）。

### 1.2 Claude Code CLI 一行注册

```bash
claude mcp add-json science-audit-loop '{
  "command": "/Users/ericdong/Desktop/perovskite-project/audit-loop/.venv/bin/python",
  "args": ["/Users/ericdong/Desktop/perovskite-project/audit-loop/mcp/audit_mcp_server.py"]
}'
```

### 1.3 指向另一份 config（可选）

默认读 `audit-loop/orchestrator/config.yaml`。要换一份（例如 selftest 用的 scratch config），
加 `--config`，或设环境变量 `AUDIT_LOOP_CONFIG`：

```json
{
  "mcpServers": {
    "science-audit-loop": {
      "command": "/Users/ericdong/Desktop/perovskite-project/audit-loop/.venv/bin/python",
      "args": [
        "/Users/ericdong/Desktop/perovskite-project/audit-loop/mcp/audit_mcp_server.py",
        "--config",
        "/path/to/orchestrator/config.yaml"
      ]
    }
  }
}
```

`--config` 优先于 `AUDIT_LOOP_CONFIG`，后者优先于默认路径。

### 1.4 手动验证注册是否可用

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| /Users/ericdong/Desktop/perovskite-project/audit-loop/.venv/bin/python \
  /Users/ericdong/Desktop/perovskite-project/audit-loop/mcp/audit_mcp_server.py 2>/dev/null
```

应当得到两行 JSON：`initialize` 的 result，以及 7 个 tool 的列表。
（stderr 是日志，stdout 只有协议 JSON。）

---

## 2. 前置条件 / prerequisites

1. `audit-loop/.venv` 存在，且装了 `fastapi` / `httpx` / `jsonschema` / `PyYAML` 以及
   editable 安装的 `science-audit-controller`。
2. `audit-loop/orchestrator/config.yaml` 存在，`paths.*` 指向真实位置；
   `project.project_id` 非空（`check_action` 用它构造请求）。
3. `install.sh` 已经跑过，生成了 `paths.secrets_env`（默认 `audit-loop/state/secrets.env`，
   `KEY=VALUE` 每行一条）：`GITHUB_WEBHOOK_SECRET`、`ACTION_API_TOKEN`、
   `CLAUDE_API_TOKEN`、`CONTROLLER_READ_TOKEN`。`PI_APPROVAL_TOKEN` **不在**这个文件里，
   它单独放在 `state/pi_token.env`，没有任何自动化进程加载。

### 2.1 本 server 持有哪些 token / least privilege

`SECRET_KEYS` 是本 server 会读取并注入进程内 controller 的 key 集合。1.1 起是**两个**：

| key | 用途 | 为什么是正当的 |
| --- | --- | --- |
| `CLAUDE_API_TOKEN` | `POST /claude/dispositions` | 处置通道：对已经写在自己头上的 findings 表态 |
| `ACTION_API_TOKEN` | `POST /actions/check` | 闸门咨询通道：问"这个高风险动作被允许吗"。**问 ≠ 判**：该端点只读策略状态并返回 ALLOW/DENY，无法创建或放宽任何 authorization |

仍然**故意不持有**：

- `PI_APPROVAL_TOKEN` —— 对应 `POST /authorizations` 与 `POST /admin/quarantine-event`。
  执行者若能自己签发批准、或把针对自己的 blocker 事件隔离掉，two-key 规则当场塌掉。
  它连 `secrets.env` 都不在（见上）。
- `CONTROLLER_READ_TOKEN` —— 本 server 从不使用。

缺 token 的端点返回 503，这是**预期姿态**，不是配置错误。

**secrets.env 缺失/不全时的行为**：`initialize` 与 `tools/list` 照常工作；`audit_status` 也
照常渲染，并把缺失的 key 名字列出来（只报告 key 在不在，**从不**打印值）；真正需要该
token 的 tool 返回 `isError: true` 的配置错误 —— `submit_disposition` 说
`secrets.env has no CLAUDE_API_TOKEN`，`check_action` 说
`secrets.env has no ACTION_API_TOKEN — run install.sh first (<path>)`。

---

## 3. Tools

所有 tool 都返回 `{"content": [{"type": "text", "text": "..."}], "isError": <bool>}`。
失败一律是 `isError: true` + 可读的文字说明，**不是** JSON-RPC error —— 这样 caller
可以自我纠正后重试。

### 3.1 `audit_status`

无参数。一次调用拿到全貌，session 收尾时先调它。

输出包含：

- config 路径、`project_id`、`science_branch`、scienceRepo 的 HEAD（12 位前缀）与当前分支；
- 最近最多 8 个 cycle：`cycle_id`、`science_commit` 12 位前缀、`status`、FINAL 时的
  `decision`、`disposition_status`；
- pending review 的数量与 `cycle_id` 列表；
- escalation：OPEN / ACKNOWLEDGED 计数，以及每条 OPEN 的 `escalation_id` / `finding_id` /
  `cycle_ids` / `opened_at`；
- **gate consultations**：`state/action_ledger.jsonl` 里最近 5 条 `check_action` 记录
  （时间、decision、action、截断到 64 字符的 reason codes）；一条都没有时明确说
  `none recorded`；
- 初始化状态：`secrets.env`、state dir、controller state、spool 队列长度。

只读；不写任何文件。controller state 不存在时按空处理。

样例（scratch fixture）：

```
AUDIT LOOP STATUS  (2026-07-30T08:40:08+00:00)
config: /Users/ericdong/Desktop/perovskite-project/audit-loop/orchestrator/config.yaml
project: perovskite-screening   science_branch: main
science repo: /Users/ericdong/Desktop/perovskite-project/scienceRepo  HEAD=81fd505e71b8 (branch main)

Cycles: 1 total, showing most recent 1
  cycle_id      commit        status                 decision            disposition
  CYCLE-000001  81fd505e71b8  CODEX_TASK_CREATED     -                   NOT_STARTED

Pending reviews: 0
Escalations: 0 OPEN, 0 ACKNOWLEDGED (0 total)

Gate consultations (check_action): 2 recorded, showing last 2
  2026-07-30T13:50:10.481890+00:00 DENY   submit_production_job      ACTIVE_BLOCKER_F-001, ACTIVE_BLOCKER_F-002, ACTIVE_BLOCKER_F-...
  2026-07-30T13:52:34.445107+00:00 DENY   submit_production_job      ACTIVE_BLOCKER_F-001, ACTIVE_BLOCKER_F-002, ACTIVE_BLOCKER_F-...
  ledger: /Users/ericdong/Desktop/perovskite-project/audit-loop/state/action_ledger.jsonl

Initialization:
  secrets.env:      present, all 2 keys set
  state dir:        present  (/Users/ericdong/Desktop/perovskite-project/audit-loop/state)
  controller state: present (1 cycles)
  spool:            present, 0 queued event(s)
```

### 3.2 `get_pending_review`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `cycle_id` | string，`^CYCLE-[0-9]{6}$` | 否 | 指定某个 cycle；省略则取**最旧**的一条 |

返回一段文本，依次是：

1. header：`cycle_id`、`audit_report_id`、`report_sha256`、`science_commit`、`decision`、
   `finding_ids`、`created_at`、`report_path`、`result_path`、队列长度；
2. `audit_report.md` 的**全文**（超过 200,000 字符才截断，并明确标注）;
3. `audit_result.json` 的全文；
4. "How to respond / 如何回覆" 说明段：六个 disposition 取值的含义、`fix_commit` 的
   iff 规则、必须逐字回抄 `report_sha256`、以及"绝不能声称 finding 已 closed"。

队列为空时返回一句正常说明（`isError: false`），不算错误。
指定的 `cycle_id` 不在队列里时返回 `isError: true`，并列出实际可用的 `cycle_id`。
只读。

> pending review 由 orchestrator 在 cycle 进入 FINAL 时写入
> `<state_dir>/pending_reviews/CYCLE-XXXXXX.json`。本 server 从不自己创建它。

### 3.3 `submit_disposition`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `disposition` | object | 是 | `claude_disposition` 对象，**原样**转发给 controller |

行为：以 `Authorization: Bearer <CLAUDE_API_TOKEN>` POST 到 controller 的
`/claude/dispositions`。controller 是唯一的校验者；本 server 绝不修改 disposition 的内容
（scratch 测试里断言过：controller state 里记下的 `dispositions[cycle_id]` 与提交的对象逐字相等）。

`disposition` 的形状：

```json
{
  "cycle_id": "CYCLE-000001",
  "audit_report_id": "AR-CYCLE-000001-0001",
  "report_sha256_confirmed": true,
  "report_sha256": "<64-hex，逐字回抄 get_pending_review 给出的值>",
  "findings": [
    {"finding_id": "F-EVD-001", "disposition": "ACCEPT_AND_STOP", "evidence": "..."},
    {"finding_id": "F-DOC-002", "disposition": "ACCEPT_AND_FIX", "fix_commit": "<40-hex>"}
  ]
}
```

规则（由 controller 强制，写在这里方便一次做对）：

- `findings` 必须对该 cycle 的每个 `finding_id` 给出**恰好一个**条目，不缺、不多、不重复；
- `disposition` ∈ `{ACCEPT_AND_FIX, ACCEPT_AND_STOP, DISAGREE_WITH_EVIDENCE,
  NEED_PI_DECISION, DEFER_WITH_CAVEAT, PASS_NO_ACTION}`；
- `fix_commit` **当且仅当** `ACCEPT_AND_FIX` 时出现：完整 40 位 sha，必须是一个新的
  science commit，且以被审计的 `science_commit` 为祖先（先提交修复，再引用其 sha）；
- `report_sha256` 必须与 FINAL 报告一致，`report_sha256_confirmed` 必须为 `true`；
- 不允许出现 `closed` 字段 —— 关闭 finding 只能由下一轮 re-audit 验证后由 controller 完成。

成功（`valid: true`）时本 server 做三件事：

1. 把 `<state_dir>/pending_reviews/<cycle_id>.json` 移到
   `<state_dir>/pending_reviews/recorded/`（目录按需创建）；
2. 写一条 spool 事件 `{"type": "disposition_recorded", "cycle_id": "...", "source": "mcp"}`；
3. 返回成功文本 + controller 的 `errors` 列表（成功时通常是空）。

被拒（`valid: false`）时返回 `isError: true`，正文是 controller 的 error 列表**原文**，
并明确说明"什么都没记录、pending review 没有移动"。据此修正后重新提交即可。例如：

```
submit_disposition failed: controller REJECTED the disposition (valid=false).
Errors verbatim from the controller:
  - audit report ID does not match
  - confirmed report SHA-256 does not match the FINAL report
  - missing finding dispositions: ['F-DOC-002']
Correct the disposition and call submit_disposition again. Nothing was recorded and no state was moved.
```

> controller app 是**懒加载**的：只有第一次调用 `submit_disposition` 时才会
> `sys.path.insert(controller_root)` → `from app.main import create_app` → 用
> `fastapi.testclient.TestClient` 在进程内 POST。启动时不 import，所以 controller 有问题
> 也不影响 `initialize` / `tools/list`。进程内使用的环境变量：`SCIENCE_REPO_PATH`、
> `AUDIT_REPO_PATH`、`PROJECT_CONFIG_PATH`、`CONTROLLER_STATE_PATH` 加全部 secrets。

### 3.4 `request_audit`

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `reason` | string，非空 | 是 | — | 触发原因；写进 spool 事件，并传给 `make_audit_request.py` |
| `regenerate_manifest` | boolean | 否 | `true` | 是否先重新生成 evidence manifest |

流程：

1. `regenerate_manifest=true`：以子进程运行
   `<venv_python> <audit_loop_root>/orchestrator/make_audit_request.py --repo <science_repo> --reason <reason>`，
   取 stdout **最后一行**作为新的 HEAD sha。脚本非 0 退出时，返回它的 stderr 作为 tool 错误。
   `regenerate_manifest=false`：直接 `git -C <science_repo> rev-parse HEAD`。
2. 校验 sha 是 40 位 hex，并且在 science 分支上：
   `git merge-base --is-ancestor <sha> refs/heads/<science_branch>`（等于 branch head 也算通过）。
   不在分支上就报错并说明只有该分支的 commit 才能被审计。
3. 写 spool 事件 `{"type": "science_commit", "sha": "<40hex>", "source": "mcp", "reason": "..."}`。
4. 返回 sha + `audit queued; the orchestrator will pick it up.`

本 server 只读 scienceRepo（`rev-parse` / `merge-base`）。真正会写 repo 的只有
`make_audit_request.py`，那是 orchestrator 自己的脚本。

样例输出：

```
manifest NOT regenerated (regenerate_manifest=false); using current HEAD
science_commit: cc32ba33989caec2eddff928dd961a823d2aab63
branch check:   OK (branch head)
spool event:    evt-20260730T083959349882Z-72865-2.json
reason:         end-of-session audit
audit queued; the orchestrator will pick it up.
```

### 3.5 `acknowledge_escalation`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `escalation_id` | string，非空 | 是 | `audit_status` 里列出的 id |
| `resolution_note` | string，非空 | 是 | 处理说明，原样存档 |

把 `<state_dir>/escalations.json` 里对应条目改成
`status: "ACKNOWLEDGED"` + `resolution_note` + `acknowledged_at`（UTC ISO8601）+
`acknowledged_by: "mcp"`。读-改-写全程持 `fcntl.flock`（锁文件 `escalations.json.lock`），
写入用 tmp + `os.replace` 原子替换。

失败情形：`escalation_id` 未知（错误信息里列出已知 id）、或该条已经是 `ACKNOWLEDGED`
（错误信息里带上原有的时间与 note）。

**Acknowledge ≠ 关闭 finding**：它只记录"人已经做出决定"。

### 3.6 `notify_pi`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `subject` | string，非空 | 是 | 通知副标题，保留前 200 字符 |
| `body` | string，非空 | 是 | 通知正文，保留前 1000 字符 |

这是**人为介入**通道。做两件事：

1. macOS 桌面通知：
   `subprocess.run(["osascript", "-e", 'display notification "<body>" with title "Audit Loop" subtitle "<subject>"'])`。
   文本经过 AppleScript 字符串转义（`\` `"` 换行 制表 都转义），**从不**经过 shell 插值。
2. 向 `<state_dir>/logs/notifications.log` **追加**一行（单次 `O_APPEND` 写）：

   ```
   <utc-iso>\tsource=mcp\tstatus=<sent|osascript>\tsubject=<单行化 subject>\tbody=<单行化 body>
   ```

osascript 失败（headless、通知权限被关等）视为**非致命**：日志照写，tool 仍返回
`isError: false`，只在文本里标注 `macOS notification: osascript failed (non-fatal): ...`。
日志写不进去才算 tool 失败 —— 那是唯一不能丢的那一份记录。

### 3.7 `check_action`（1.1 新增：准入闸门咨询）

在做**任何高风险动作之前**先问 controller 的 fail-closed policy engine
（`POST /actions/check`）：允许还是不允许。

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `action` | string，非空 | 是 | — | 要做的动作名，如 `submit_production_job`、`publish_claim` |
| `science_commit` | string，`^[a-fA-F0-9]{40}$` | 否 | science repo 当前 HEAD | 该动作所依据的完整 40 位 sha |
| `manifest_sha256` | string，`^[a-fA-F0-9]{64}$` | 否 | 该 commit 上 `.audit/audit_request.json` 里的 `evidence_manifest_sha256` | 证据清单哈希 |
| `intent` | string，非空 | 否 | — | 一行说明你即将做什么；原样记进 ledger |

`action` **故意不是 enum**：引擎必须看到你真正想做的那个名字，认不出就 DENY。

**高风险动作**（`app/policy_engine.py` 的 `HIGH_RISK_ACTIONS`）：
`submit_production_job`、`stop_production_job`、`publish_claim`、`change_locked_protocol`、
`exclude_scientific_data`、`increase_budget`、`operate_instrument`。
低风险白名单：`run_unit_tests`、`run_local_analysis`、`read_results`、
`generate_report_draft`。**两者之外的任何名字一律 DENY（`UNKNOWN_ACTION`）** —— 这就是
fail-closed 的默认，不是 bug。

流程：

1. 解析默认值：`git -C <science_repo> rev-parse HEAD`；
   `git -C <science_repo> show <sha>:.audit/audit_request.json` → `evidence_manifest_sha256`。
   **解析不出来就报错，绝不猜哈希**：commit 上没有 `.audit/audit_request.json`、JSON 坏了、
   没有该字段、字段不是 64 位 hex、sha 不在 repo 里 —— 每一种都返回 `isError: true` 且
   点名缺的到底是什么，并附一句 `no hash was guessed`。猜一个近似的 manifest 哈希会
   悄悄废掉 `MANIFEST_MISMATCH` 这条检查。
2. 以 `Authorization: Bearer <ACTION_API_TOKEN>` POST
   `{project_id, actor: "claude_science", action, science_commit, manifest_sha256}`
   到进程内 controller 的 `/actions/check`。`project_id` 取自 `config.yaml` 的
   `project.project_id`；`actor` 恒为 `claude_science`（引擎的 allow-list 只有它）。
3. 向 `<state_dir>/action_ledger.jsonl` **追加**一行 JSON（单次 `O_APPEND` 写；
   append-only 的账本不做 tmp+replace 重写）：

   ```json
   {"action": "submit_production_job", "decision": "DENY",
    "intent": "…", "manifest_sha256": "…", "reason_codes": ["…"],
    "science_commit": "…", "source": "mcp", "timestamp": "<utc-iso>"}
   ```

4. 返回**可读文本**（不是 JSON dump）。

**返回约定**：ALLOW 与 DENY 都是 `isError: false` —— DENY 是闸门正常工作的答案，不是
tool 故障。只有"没拿到答案"（参数非法、默认值解析失败、缺 token、controller 报错）才是
`isError: true`；这种情况下文本会说明**没有决定就等于不被允许，"没有 DENY" 不是 ALLOW**。
若确实打到了 controller 但没拿到决定，ledger 里会多一条 `decision: "ERROR"` 且带
`error` 字段的记录 —— 失败的咨询同样留痕。

**DENY** 的正文以 `STOP — the policy gate returned DENY. Do NOT perform this action.` 开头，
然后逐条列出 controller 原样返回的 reason code 加一行中文/英文白话解释。覆盖的 code
（字符串取自 `app/policy_engine.py`，不是编出来的）：

| reason code | 一句话含义 |
| --- | --- |
| `UNKNOWN_PROJECT` | 送出的 `project_id` 不是 controller 配置里的项目 |
| `ACTOR_NOT_ALLOWED` | actor 不在引擎 allow-list 上 |
| `BLOCKER_STATE_INCONSISTENT` | blocker 事件日志归约不出一致状态，引擎 fail-closed，等人修 |
| `UNKNOWN_ACTION` | 引擎不认识这个动作名 → 默认拒绝（不要为了绕过它去编名字） |
| `ACTIVE_BLOCKER_<finding_id>` | 该 finding 仍是 OPEN blocking，且 scope 覆盖本动作；只有修复→re-audit→`FINDING_VERIFIED_CLOSED` 才能解除 |
| `NO_FINAL_AUDIT_FOR_COMMIT` | 这个 commit 没有任何 audit cycle 走到 FINAL |
| `MANIFEST_MISMATCH` | 给的 manifest 哈希 ≠ 该 commit 的 FINAL 审计记录的那个 |
| `AUDIT_DECISION_NOT_PERMISSIVE` | FINAL 审计的 decision 不是 `PASS` / `PASS_WITH_CAVEATS` |
| `POLICY_APPROVAL_REQUIRED` | 没有 `policy_approved=true` 的未过期 authorization |
| `BUDGET_APPROVAL_REQUIRED` | 没有 `budget_approved=true` 的未过期 authorization |
| `PI_APPROVAL_REQUIRED` | 没有 `pi_approved=true` 的未过期 authorization；只有 PI 能签发，本 server 不持有 `PI_APPROVAL_TOKEN`，所以你**自己解不开**，要用 `notify_pi` 去问 |

authorization 的匹配是**逐字**的：actor + action + science_commit + manifest_sha256 四项
全等，且 `expires_at` 未过期。

**ALLOW** 的正文会指名这次放行所依据的 FINAL cycle 与 commit，并写明这是"**仅**针对
**这一个** action、**这一个** commit、**这一份** manifest 的一次授权"，不外延到别的动作、
之后的 commit 或更大的范围。若该 commit 根本没有 FINAL cycle（引擎把这个动作归为
低风险直接放行），文本会**照实说**这次 ALLOW 不依赖任何审计，别当成"审计批准过"。

**它是什么、不是什么（必须照抄的边界）**：tool description 与每一次 ALLOW/DENY 正文都
带这句话 ——

> check_action is ADVISORY AT THE POINT OF CALL. The controller's fail-closed policy engine
> makes the decision and this consultation is now on record in the append-only ledger — but
> nothing here mechanically prevents an action. A caller that simply never calls check_action
> is not stopped by it. Reachable and logged, not enforced.

外部审计当初的结论是"**够不着的闸门等于没有闸门**"。1.1 修的是"够不着"和"没留痕"，
不是"不可绕过"。把它描述成 enforcement 就是换个说法把原缺陷留下来。

DENY 实例（真实 state，`submit_production_job` @ HEAD，节选）：

```
STOP — the policy gate returned DENY. Do NOT perform this action.

action:          submit_production_job
actor:           claude_science
project_id:      perovskite-screening
science_commit:  81fd505e71b8bde5faab169cb4c42b791f656949   [default: HEAD of …/scienceRepo]
manifest_sha256: c546b4176ddf115ec90f5daf88ee8cece8a91e15d504d3b16b08307d402c5db4   [default: evidence_manifest_sha256 in .audit/audit_request.json @ commit]
intent:          live smoke test of the admission gate; no job will be submitted
asked at:        2026-07-30T13:52:34.445107+00:00

Reason codes verbatim from the controller, each with a one-line gloss:
  - ACTIVE_BLOCKER_F-001
      finding F-001 is an OPEN blocking finding whose blocked_scopes cover this action; …
  …
  - AUDIT_DECISION_NOT_PERMISSIVE
      the FINAL audit for this commit decided something other than PASS or PASS_WITH_CAVEATS …
  - PI_APPROVAL_REQUIRED
      … Only the PI can create one (POST /authorizations with PI_APPROVAL_TOKEN); this server
      deliberately does not hold that token …

What to do now:
  * Do not retry with different arguments to hunt for an ALLOW, …
```

---

## 4. 典型 session 收尾流程

```
audit_status
        ├─ pending reviews > 0 ──► get_pending_review
        │                              └─► 读完整报告 ──► submit_disposition
        │                                        ├─ valid:true  → 完成（事件已入 spool）
        │                                        └─ valid:false → 按 errors 修正后重提
        ├─ 有 NEED_PI_DECISION / 被 block 住 ──► notify_pi
        ├─ 有 OPEN escalation 且已有人拍板 ──► acknowledge_escalation
        └─ 本 session 改动了 scienceRepo ──► request_audit(reason="...")

任何高风险动作之前（提交生产任务、发布结论、改锁定协议、排除数据、加预算、操作仪器）：

        check_action(action="...", intent="...")
                ├─ DENY  ──► 停手；按 reason code 修根因，或 notify_pi 找 PI
                └─ ALLOW ──► 只做这一个动作、只在这个 commit 上做一次，然后重新问
```

对 `ACCEPT_AND_FIX`：**先**在 scienceRepo 提交修复、拿到新 sha，**再**把该 sha 作为
`fix_commit` 提交 disposition。

---

## 5. 状态文件契约 / state contract

state 的所有者是 orchestrator；本 server 只按下表读写。所有写操作原子化
（tmp + `os.replace`），所有读操作容忍文件缺失或损坏（损坏只记 stderr，不抛异常）。

| 路径 | 本 server 的动作 |
| --- | --- |
| `<state_dir>/spool/evt-<utcstamp>-<pid>-<n>.json` | **写**。单个 JSON 对象；先写 `.evt-*.tmp`（点号前缀，不会被 `evt-*.json` glob 命中）再 `os.replace`，orchestrator 永远看不到半截文件。事件类型只有 `science_commit` 与 `disposition_recorded`。 |
| `<state_dir>/pending_reviews/CYCLE-XXXXXX.json` | **读**；disposition 成功后**移动**到 `recorded/`。从不创建、从不修改内容。 |
| `<state_dir>/escalations.json` | **读-改-写**（flock + 原子替换），只改被 acknowledge 的那一条。 |
| `<state_dir>/controller/state.json` | `audit_status` 只读（缺失按空处理）；`submit_disposition` 通过 controller 自己的 `JsonStorage` 间接写入。 |
| `<state_dir>/logs/notifications.log` | **追加**一行。 |
| `<state_dir>/action_ledger.jsonl` | **追加**一行（每次 `check_action` 一条）。append-only：单次 `O_APPEND` 写，**从不**用 tmp+replace 重写整个文件，也从不删改既有行。`audit_status` 只读它的最后几行。 |

**绝不触碰**：`scienceRepo` 与 `auditRepo` 的工作区内容（只跑 `rev-parse` / `merge-base`
这类只读 git 命令）。

---

## 6. 协议细节 / protocol notes

- `initialize` → `{"protocolVersion": <回抄 client 请求的版本，缺省 "2025-06-18">,
  "capabilities": {"tools": {}}, "serverInfo": {"name": "science-audit-loop", "version": "1.1.0"}}`
- `notifications/initialized` 及任何其它 notification（无 `id` 的消息）→ 不回任何东西。
- `tools/list` → `{"tools": [...]}`，每个都有 `name` / `description` / `inputSchema`
  （JSON Schema，Draft 2020-12，已用 `jsonschema.check_schema` 验证）。
- `tools/call` → `{"content":[{"type":"text","text":"..."}],"isError":<bool>}`。
- `ping` → `{}`（额外实现的便利方法，MCP 标准的一部分）。
- 未知 **method** → JSON-RPC error `-32601`。
- 未知 **tool 名** → `isError: true` 的文本（列出可用 tool），不是协议错误 ——
  让 caller 能自己改对。
- 非法 JSON 输入 → `-32700`，主循环继续。JSON-RPC batch（数组）不支持 → `-32600`。
- 任何异常都被逐消息捕获：tool 内部异常 → `isError: true`；handler 异常 → `-32603`。
  主循环不会因为一条消息而退出。
- **stdout 只有协议 JSON 行**。启动时 server 把真实 stdout 存到私有句柄，然后把
  `sys.stdout` 指向 stderr —— 任何第三方库（fastapi / httpx / controller）的 `print`
  都不可能污染协议流。日志全部走 stderr，格式
  `[<utc>] science-audit-loop: <message>`。

---

## 7. 故障排查 / troubleshooting

| 现象 | 处理 |
| --- | --- |
| client 里看不到这个 server | 检查 `command` 指向的是 `audit-loop/.venv/bin/python`（不是系统 python），并重启 client。 |
| 所有 tool 都报 `configuration error — config not found` | `--config` 路径错了，或 `config.yaml` 不在 `<audit_loop_root>/orchestrator/` 下。 |
| `submit_disposition` 报 `secrets.env missing` | 先跑 `install.sh` 生成 `state/secrets.env`。 |
| `submit_disposition` 报 `HTTP 401` | `secrets.env` 里的 `CLAUDE_API_TOKEN` 与 controller 进程用的不一致。 |
| `submit_disposition` 报 `unknown or non-FINAL cycle` | 该 cycle 在 controller state 里还没到 FINAL；先看 `audit_status`。 |
| `request_audit` 报 `make_audit_request.py not found` | orchestrator 还没装好；临时可用 `regenerate_manifest=false`。 |
| `request_audit` 报 `is not on branch main` | 当前 HEAD 不在 science 分支上；先 merge / checkout 回该分支。 |
| 看不到桌面通知 | `notify_pi` 的文本里会写明 osascript 的失败原因；`notifications.log` 里始终有记录。 |
| `check_action` 报 `secrets.env has no ACTION_API_TOKEN` | `install.sh` 没跑过，或该 key 被清空了。`initialize`/`tools/list`/`audit_status` 不受影响。 |
| `check_action` 报 `cannot resolve the default manifest_sha256` | 该 commit 上没有 `.audit/audit_request.json`（先跑 `request_audit` 生成），或那个 sha 不属于这个 repo。想手动指定就显式传 `manifest_sha256`——**不要**随便填一个凑数的哈希。 |
| `check_action` 报 `HTTP 401` / `HTTP 503` | 401：`secrets.env` 的 `ACTION_API_TOKEN` 与 controller 用的不一致；503：controller 进程没配 `ACTION_API_TOKEN`。两种都**不是** ALLOW。 |
| `check_action` 一直 DENY 且带 `ACTIVE_BLOCKER_*` | 有 OPEN 的 blocking finding。只有"提交修复 → re-audit → controller 记下 `FINDING_VERIFIED_CLOSED`"才解除，自己声称修好了不算。 |
| 想看 server 日志 | 全在 stderr。client 通常会落盘（Claude Desktop: `~/Library/Logs/Claude/mcp*.log`）。 |

---

## 8. 自测 / self-test

server 是纯 stdio 进程，可以直接用管道驱动。已验证过的端到端测试覆盖：
`initialize` 握手（含版本回抄与缺省）、`tools/list` 的 7 个 tool 与 schema 合法性
（`jsonschema.Draft202012Validator.check_schema`）、
未知 method / 未知 tool、`audit_status` 渲染、`get_pending_review` 全文嵌入、
`submit_disposition` 的拒绝路径（controller error 列表原文）与接受路径
（pending review 移动 + spool 事件 + controller 里逐字记录）、`request_audit` 的
`regenerate_manifest=false` 路径与非分支 commit 拒绝、`acknowledge_escalation` 往返与
重复确认拒绝、`notify_pi` 的日志行、secrets.env 缺失时 `initialize`/`tools/list`/`audit_status`
仍可用，以及 stdout 全程只有 JSON-RPC 行。

`check_action` 另外验证过（scratch tree，56/56 通过）：高风险动作在没有 FINAL 审计时
DENY 且带 `NO_FINAL_AUDIT_FOR_COMMIT` 并**恰好**写一行 ledger；未知动作名 DENY 且带
`UNKNOWN_ACTION`（确认不是 ALLOW）；只给 `action` 时默认值确实取到 HEAD 与
`.audit/audit_request.json` 里的 manifest 哈希；commit 上没有 `.audit/audit_request.json`
（以及有文件但缺 `evidence_manifest_sha256` 字段）时返回点名的错误、**不写** ledger、
不编哈希；低风险动作 ALLOW 时照实说明"不依赖任何审计 cycle"；有 FINAL PASS cycle +
未过期完整 authorization 时 ALLOW 并指名该 cycle；`secrets.env` 缺 `ACTION_API_TOKEN` 时
给出配置错误而 `initialize`/`tools/list` 照常。

真实 config 上只做过只读冒烟：`check_action(action="submit_production_job")` → DENY
（`ACTIVE_BLOCKER_F-001/002/003/004/006`、`AUDIT_DECISION_NOT_PERMISSIVE`、
`POLICY_/BUDGET_/PI_APPROVAL_REQUIRED`），除了它自己该写的那一行 ledger 之外，
`state/` 没有任何其它文件被新增或改动。

跑自测的方式：复制一份 `config.yaml` 到 scratch 目录、把 `paths.*` 改到 scratch
（scratch state_dir + scratch git repos + 假的 `secrets.env` + 假的
`controller/state.json` + 假的 `pending_reviews/*.json`），然后用 `--config` 指向它。
**不要**用真实 config 跑写操作类的 tool。
