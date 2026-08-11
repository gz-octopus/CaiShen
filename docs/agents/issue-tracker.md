# Issue tracker: GitHub

CaiShen 的 issue 和规格以 GitHub issue 形式存放。所有操作使用 `gh` CLI。

## 约定

- **创建 issue**: `gh issue create --title "..." --body "..."`。多行 body 用 heredoc。
- **读取 issue**: `gh issue view <number> --comments`,用 `jq` 过滤评论并同时获取标签。
- **列出 issue**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`,配合 `--label` 和 `--state` 过滤。
- **评论 issue**: `gh issue comment <number> --body "..."`
- **打/撤标签**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**: `gh issue close <number> --comment "..."`

仓库从 `git remote -v` 推断 —— `gh` 在 clone 内运行时会自动处理。

## 是否把 PR 当作分流入口

**PR 作为请求入口:否。** _(若本仓库把外部 PR 当作功能请求,改成 `yes`;`/triage` 会读取该标记。)_

设为 `yes` 时,PR 与 issue 走同一套标签和状态,使用 `gh pr` 等价命令:

- **读取 PR**: `gh pr view <number> --comments` + `gh pr diff <number>` 获取 diff。
- **列出待分流的外部 PR**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`,只保留 `authorAssociation` 为 `CONTRIBUTOR` / `FIRST_TIME_CONTRIBUTOR` / `NONE`(去掉 `OWNER` / `MEMBER` / `COLLABORATOR`)。
- **评论 / 打标签 / 关闭**: `gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共享同一套编号,裸 `#42` 可能是任一 —— 用 `gh pr view 42` 解析,失败再 `gh issue view 42`。

## 技能说"发布到 issue tracker"时

创建一个 GitHub issue。

## 技能说"获取相关 ticket"时

运行 `gh issue view <number> --comments`。

## Wayfinding 操作

供 `/wayfinder` 使用。**map** 是一个带 `wayfinder:map` 标签的 issue,子 issue 作为 ticket。

- **Map**: 单个 issue,标签 `wayfinder:map`,body 存放 Notes / Decisions-so-far / Fog。`gh issue create --label wayfinder:map`。
- **子 ticket**: 作为 map 的 GitHub sub-issue 链接的 issue(`gh api` 调用 sub-issues endpoint)。sub-issue 不可用时,把子项写进 map body 的 task list,并在子项 body 顶部加 `Part of #<map>`。标签:`wayfinder:<type>`(`research`/`prototype`/`grilling`/`task`)。认领后 ticket 分配给负责的开发者。
- **阻塞**: GitHub 原生 issue 依赖 —— 规范的、UI 可见的表示。用 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` 加边,其中 `<blocker-db-id>` 是阻塞项的数字 **database id**(`gh api repos/<owner>/<repo>/issues/<n> --jq .id`,_不是_ `#number` 或 `node_id`)。GitHub 报告 `issue_dependencies_summary.blocked_by`(仅开放阻塞项 —— 实时门)。依赖不可用时,回退为在子项 body 顶部加 `Blocked by: #<n>, #<n>`。所有阻塞项关闭后 ticket 解除阻塞。
- **前沿查询**: 列出 map 的开放子项(`gh issue list --state open`,按 map 的 sub-issues / task list 限定),去掉有开放阻塞项(`issue_dependencies_summary.blocked_by > 0`,或 `Blocked by` 行里有开放 issue)或已分配人的;按 map 顺序取第一个。
- **认领**: `gh issue edit <n> --add-assignee @me` —— 本次会话的第一次写入。
- **解决**: `gh issue comment <n> --body "<answer>"`,然后 `gh issue close <n>`,再把上下文指针(gist + 链接)追加到 map 的 Decisions-so-far。
