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
`decision=BLOCK` 时 finding 必须带 `blocked_scopes`(对应 controller 高风险动作名),
高风险动作走 `/actions/check` 默认 DENY。

### 循环终止(宪法 §3.4)

- 幂等:同 (commit, trigger, evidence hash) 只建一个 cycle;重复投递直接吸收。
- 限速:`limits.max_cycles_per_hour`(默认 4),超出的事件留在 spool,launchd 每 15 分钟重试。
- 升级:同一 finding 跨 `escalate_after_unresolved_cycles`(默认 3)个 FINAL cycle 未验证关闭
  → `ESCALATE_TO_PI`,通知你,记入 `state/escalations.json`;Claude Science 可经 MCP
  `acknowledge_escalation` 记录你的裁决。
- `PASS` 不自动触发提交,`BLOCK` 不自动触发昂贵修复——都只触发 disposition(§3.5)。

## 目录

| 路径 | 作用 |
|---|---|
| `rulebook/` | 宪法(逐字)+ 机器可解析规则索引 `AUDIT_RULEBOOK.md`(31 条 R-* 规则,从属宪法)+ 两个 lock 文件 |
| `checks/` | Tier-0 确定性检查(9 项 C-* 检查,stdlib+yaml,无 LLM) |
| `orchestrator/` | `orchestrator.py`(调度核心)、`make_audit_request.py`(代 Claude Science 重生成 `.audit/`)、`config.yaml`、`projects.yaml` |
| `mcp/` | Claude Science 的 local MCP server(6 个工具,注册方法见 `mcp/README_MCP.md`) |
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

测试 48 → 50 全绿(新增未知动作拒绝、非后代 fix_commit 拒绝两条回归)。

## 已知边界(有意为之/待办)

- controller 事件日志无修复接口:一条异常事件会永久 fail-closed(设计取向是安全而非可用);
  本地单写者下可达路径已很窄。出现时删 `state/controller/state.json` 前先备份并通知 PI。
- GitHub 接线(2026-07-30):auditRepo → `dongzhaohe321418-lab/perovskite-screening-audit`
  (private),每次 FINAL 后自动 push;scienceRepo 以 GitHub 为真相源,每轮 pass fetch,
  仅 fast-forward 同步并自动触发新 head 审计,发散/脏树只通知 PI 不动仓库
  (`config.yaml` 的 `sync:` 开关)。建议在 GitHub 给 audit 分支加保护规则。
- Tier-0 `C-TEST-001`(clean-clone 跑仓库自测)默认关闭,`checks/checks.yaml` 打开。
- `claude` CLI 的 npm 原生二进制未签名被 macOS SIGKILL;闭环用 MCP 不依赖它,如需修复:
  `npm reinstall -g @anthropic-ai/claude-code`。
