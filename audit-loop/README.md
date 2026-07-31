# audit-loop — 本地自动审计闭环

`scienceRepo`(Claude Science 执行)→ Codex 只读审计 → `auditRepo`(不可变审计工件)→
Claude Science 逐条 disposition → 修复 commit → 再审计 → PI 只在升级时介入。

宪法:[`rulebook/CODEX_AUDIT_WORKFLOW.md`](rulebook/CODEX_AUDIT_WORKFLOW.md)(v1.1,逐字导入,
sha256 记录于 `rulebook/constitution.lock.json`)。本目录所有组件只是它 §3.5 "loop controller"
和 §17 各角色模板的机械实现;冲突时以宪法为准。

## 架构(全本地,无常驻服务)

```
scienceRepo 每次 commit(main)
   └─ .git/hooks/post-commit ──写──▶ state/spool/evt-*.json
                                        │ launchd WatchPaths(com.ericdong.audit-loop)
                                        ▼
                            orchestrator.py(单次 pass,flock 防并发)
   1. 通过内嵌 science-audit-controller 建立 cycle(固定 commit,幂等键)
   2. Tier-0 确定性检查 checks/deterministic_checks.py ──▶ check_report.json(机器真相)
   3. codex exec(workspace-write 沙箱,worktree 只读,宪法+规则索引+Tier-0 报告入 prompt)
   4. 校验四件套工件 → 以 controller 身份 commit 进 auditRepo(Codex 本身永不 push,§1.2)
   5. controller 全量校验(HMAC webhook、树对比、schema、manifest 哈希)→ FINAL
   6. state/pending_reviews/CYCLE-*.json + macOS 通知
                                        │
                Claude Science(会话末,经 local MCP:mcp/audit_mcp_server.py)
   get_pending_review → submit_disposition(逐 finding;controller 校验 fix_commit
   必须存在且是被审计 commit 的后代)→ 新 commit 触发下一轮
                                        │
   同一 finding 连续 N=3 个 FINAL cycle 未关闭 ──▶ ESCALATE_TO_PI(macOS 通知 + escalations.json)
```

### 反同源偏差(Tier-0 机器真相)

Codex 与 Claude Science 可能共享盲区,所以哈希解析、路径存在性、JSON 严格性、空提交、
SUPERSEDED banner、跨文档状态矛盾等全部由 **无 LLM 的脚本** 先行判定
(`checks/deterministic_checks.py`,配置在 `checks/checks.yaml`)。审计 prompt 明确:
Codex 不得与 Tier-0 结果矛盾,引用其失败必须带 `check_id`;Codex 独立发现的 HARD 缺陷
必须附可复现命令并提议新的 `C-*` 检查——这是把 LLM 发现固化成机器检查的棘轮。

### 硬性失败 vs 软性意见

宪法 §12:只有 `CRITICAL/HIGH` 是阻断级;`MEDIUM/LOW/INFO` 记录、不阻断。
`decision=BLOCK` 时 finding 必须带 `blocked_scopes`(对应 controller 高风险动作名)。

### 准入闸门的真实强度(不要说成 enforcement)

高风险动作走 `/actions/check`,默认 DENY:需要该 commit 上恰好一份放行的 FINAL 审计、
manifest 相符、无适用 blocker、且 PI 授权未过期。Claude Science 经 MCP 的 `check_action`
咨询它,每次咨询写入 append-only 的 `state/action_ledger.jsonl`。

**它在调用点是建议性的,不是机械不可绕过的**:不调用它的 caller 不会被它拦住。
一次外部审计指出,一个行为者够不着的闸门等于没有闸门——我们此前正是如此(端点存在、
零调用者、MCP 连 token 都没有)。现在闸门**可达且每次咨询可审计**,这是真实的进步;
但要做到机械强制,必须把咨询装进动作本身(例如 HPC 提交脚本先查 `/actions/check`),
那一步尚未做。这两件事不可混为一谈。

### 循环终止(宪法 §3.4)

- 幂等:同 (commit, trigger, evidence hash) 只建一个 cycle;重复投递直接吸收。
- 限速:`limits.max_cycles_per_hour`(默认 4),超出的事件留在 spool,launchd 每 15 分钟重试。
- 升级即暂停,**三个独立触发器**——任一命中即 `ESCALATE_TO_PI`,记入
  `state/escalations.json`,并**停止对新提交的自动复审**,直到经 MCP
  `acknowledge_escalation` 由你放行:
  1. **轮次**:同一 finding 跨 `escalate_after_unresolved_cycles`(默认 3)个 FINAL cycle 未关闭。
  2. **时间**:blocking finding 开启超过 `stalled_finding_hours`(默认 24)仍无验证关闭。
  3. **争议**:处置为 `DISAGREE_WITH_EVIDENCE` 或 `NEED_PI_DECISION` —— 审计者与执行者
     各执一词本来就是人该裁决的,不该让两个 agent 互相磨。

  只有轮次一个维度是不够的:被反驳且此后不再提交的 finding 不产生新周期,计数器永不前进,
  于是它无限期阻断生产而无人被通知。那不是无限循环,是**静默死锁**——更难发现。
- `PASS` 不自动触发提交,`BLOCK` 不自动触发昂贵修复——都只触发 disposition(§3.5)。

## 目录

| 路径 | 作用 |
|---|---|
| `rulebook/` | 宪法(逐字)+ 机器可解析规则索引 `AUDIT_RULEBOOK.md`(31 条 R-* 规则,从属宪法)+ 两个 lock 文件 |
| `checks/` | Tier-0 确定性检查(12 项 C-* 检查,stdlib+yaml,无 LLM) |
| `orchestrator/` | `orchestrator.py`(调度核心)、`make_audit_request.py`(代 Claude Science 重生成 `.audit/`)、`config.yaml`、`projects.yaml` |
| `mcp/` | Claude Science 的 local MCP server(7 个工具,含准入闸门 `check_action`;注册方法见 `mcp/README_MCP.md`) |
| `mutation_test.py` | 对抗性测试:注入已知缺陷,跑真实审计,看是否被抓到 |
| `hooks/` `launchd/` `install.sh` | 触发装置;`selftest.py` 在 scratch 克隆里跑全链路 |
| `state/` | spool、cycles、worktrees、pending_reviews、controller state、secrets.env(600)、日志 |

## 日常操作

```bash
# 状态一览(或让 Claude Science 调 MCP 的 audit_status)
tail -20 /Users/ericdong/Desktop/perovskite-project/audit-loop/state/logs/launchd.out.log

# 手动触发一轮(等价于 Claude Science commit)
python3 - <<'EOF'
import json, subprocess, datetime
sha = subprocess.run(["git","-C","/Users/ericdong/Desktop/perovskite-project/scienceRepo","rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
open(f"/Users/ericdong/Desktop/perovskite-project/audit-loop/state/spool/evt-{stamp}-{sha}.json","w").write(json.dumps({"type":"science_commit","sha":sha,"source":"manual"}))
EOF

# 全链路自测(scratch 克隆,不碰生产)
/Users/ericdong/Desktop/perovskite-project/audit-loop/.venv/bin/python selftest.py

# 停用 / 启用
launchctl bootout gui/$(id -u)/com.ericdong.audit-loop
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ericdong.audit-loop.plist
```

## 对 science-audit-controller 的修复(本次)

1. `policy_engine.py`:未知 action 由 fail-open ALLOW 改为 DENY `UNKNOWN_ACTION`(引入显式
   `LOW_RISK_ACTIONS` 白名单)——修复"README 声称默认 DENY 但代码对任意未知动作放行"。
2. `report_validator.py`:`ACCEPT_AND_FIX` 的 `fix_commit` 现在必须是被审计 commit 的后代
   (原先任意旧 commit 也能当修复)。
3. `github_client.py`:本地模式按原始字节读 blob(原先 `text=True` 换行归一化会使
   报告哈希不等于 git blob)。
4. `pyproject.toml`:`jsonschema[format-nongpl]`,`format: date-time` 校验从静默失效变为生效。
5. `webhook.py`:`audit_branch` 缺省容错。

另有 PI 认证的事件隔离修复路径(`POST /admin/quarantine-event`)、`parent_report_sha256`
回执链,以及回执必须绑定策略包。测试 48 → 64 全绿。

## 验证强度分级(不要越级引用)

一次外部审计对同类系统的批评是:把"有审计日志"说成"由不变量保证的闭环受控系统"是逻辑越级。
本项目的证据按强度分开陈述,不合并:

| 强度 | 内容 |
|---|---|
| **机械证明** | controller 66 个单元测试 + 编排器 10 个单元测试;Tier-0 12 项检查在真实仓库上确定性可复现;干净克隆在陌生路径 install + 全套测试通过 |
| **模拟端到端** | `selftest.py` 全链路 4/4,但 Codex 由 `--simulate-codex` 桩替代 |
| **真实审计** | 6 轮真实 Codex 审计,每轮 ~316 万 input tokens |
| **完整闭环** | **2026-07-31 走通一整圈**:CYCLE-000001 判 BLOCK/7 findings → 逐条 disposition → 单个 fix commit `bfece650` → CYCLE-000002 独立复审 → **F-001/002/003/004/007 五条验证关闭**,Tier-0 hard_fail 4→0。关闭由 controller 的 finding 生命周期校验强制,不是自我声明。 |
| **仍未验证** | 高风险动作的机械强制:`check_action` 可达且每次咨询入账,但调用点仍是建议性的——把咨询装进动作本身尚未做。 |

其他必须随结论一同引用的限制:

- **Tier-0 覆盖率 12/27**:规则手册声明 27 个 `C-*`,已实现 11 个;其余 15 条规则纯靠 LLM 判断。
- **`severity_floors` 是事后拟合的**:下限依据真实审计观测到的评级设定,是策略选择而非独立验证。
- **假阳性率数据极弱**:`C-INJECT-001` / `C-NUM-001` 各只在一棵树上验证过无假阳性,n=1 几乎不排除任何东西。
- **doctor 会显示 active blockers**:此前有 active blocker 时它仍报 "Idle",这违反我们
  自己的 `R-GRD-001`(会撒谎的守卫比没有守卫更糟)。现在阻断中必然显示,并区分
  "Stalled"(无待办但仍在阻断)与 "Idle"(真的什么都没有)。
- **执行来源部分自述**:回执已绑定策略包(宪法/规则手册/检查器哈希)、模型标识与
  `prompt_sha256`(编排器比对本轮实际下发的提示词),`provider` 字段可选记录;但仍无
  provider request ID 或独立 attestation,成本台账靠 cwd 匹配会话文件。
- **覆盖是自述的**:回执必须申报 `coverage`(绑定本轮 evidence manifest、正整数
  `paths_examined`、method),编排器校验其绑定;但**没有任何东西独立核实审计者真的读过那些路径**。
  这挡住了"什么都没看的空 PASS",挡不住夸大的覆盖声明。
- **策略包绑定的执行位置**:在编排器提交工件前校验。当前架构下 Codex 从不 push,编排器即闸门,
  故此处足够;若将来允许 Codex 身份直接推送审计仓,该校验必须移入 controller。

## 已知边界(有意为之/待办)

- controller 事件日志的修复需 PI 介入:异常事件由 `POST /admin/quarantine-event`
  (仅 `PI_APPROVAL_TOKEN`)隔离,append-only、从不删除事件;`GET /events` 列出可隔离的哈希。
- GitHub 接线(2026-07-30):auditRepo → `dongzhaohe321418-lab/perovskite-screening-audit`
  (private),每次 FINAL 后自动 push;scienceRepo 以 GitHub 为真相源,每轮 pass fetch,
  但**审计只读 `state/science-mirror.git` 镜像,绝不写 live 仓**;发散只通知 PI。
  两仓均为 public,audit 分支已启用保护(禁强推/禁删除/强制线性历史)。
- Tier-0 `C-TEST-001`(clean-clone 跑仓库自测)默认关闭,`checks/checks.yaml` 打开。
- `claude` CLI 的 npm 原生二进制未签名被 macOS SIGKILL;闭环用 MCP 不依赖它,如需修复:
  `npm reinstall -g @anthropic-ai/claude-code`。
