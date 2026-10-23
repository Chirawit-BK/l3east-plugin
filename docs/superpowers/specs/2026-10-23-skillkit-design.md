# skill-compat + skill-health — design

วันที่: 2026-10-23 · สถานะ: design ตกลงแล้ว รอ go สร้าง · SKILL.md จริงเป็น English เอกสารนี้ไทยเพราะคนอ่านคือเจ้าของเครื่อง

## 1. เป้าหมาย: สองคำถาม สองสกิล

| skill | คำถามที่ตอบ | เรียกเมื่อ | input | output |
|---|---|---|---|---|
| `/l3east:skill-compat <candidate>` | "ตัวใหม่นี้ลงได้ไหม" | กำลังจะลง skill/plugin | 1 candidate | ลง / ไม่ลง / ลงแล้วปิด X + routing บรรทัดที่ต้องเพิ่ม |
| `/l3east:skill-health` | "ของที่มีอยู่สุขภาพเป็นไง" | นาน ๆ ที หรือหลังลงของหลายอย่าง | ไม่มี (สแกนทั้งเครื่อง + project ปัจจุบัน) | report + ร่าง `## Skill routing` ทั้งก้อน + cleanup list |

เส้นแบ่ง = **ชิ้นเดียว vs ทั้งเครื่อง** ไม่ใช่หัวข้อ ของเดิมตีกันเองอยู่ฝั่ง health
ทั้งสองเป็น skill (ไม่ใช่ command) ใส่ `disable-model-invocation: true` → เรียกเองเท่านั้น ไม่อยู่ใน context ไม่กิน token
`find` ไม่ทำเอง: health emit section "gaps" แล้วชี้ไป `find-skills`

## 2. ของที่มีอยู่แล้ว (ไม่สร้างซ้ำ)

| เครื่องมือ | ทำ | ไม่ทำ |
|---|---|---|
| `/skill-doctor` (CLI ≥ 2.1.252) | cost ต่อ skill, uses 7 วัน, never-invoked, unused plugins | overlap, contradiction, shadowing, hook/MCP dup, per-project |
| `claude plugin eval` | รัน prompt ผ่าน `claude -p`; grader `tool_used` เช็คว่า Skill ไหน fire | trigger-accuracy metric ตรง ๆ; แพง |
| `claude plugin list --json` | plugin ที่ลง + enabled/scope | skill รายตัว |
| `claude plugin validate` | structure | semantic |
| `find-skills`, `SearchSkills`, `ListSkills`, `ListPlugins` | หา / list | เทียบ |

ข้อเท็จจริงที่ verify แล้ว (docs + CLI 2.1.308): description ทุกตัวอยู่ใน context ทุก turn, body โหลดตอน invoke, description ถูกตัดที่ 1,536 chars · ชื่อซ้ำ: enterprise > personal > project; plugin มี namespace จึงโหลดคู่กัน (= ซ้ำ ไม่ทับ) · skill ชนะ command ชื่อเดียวกัน · hooks บน event เดียวกันรัน parallel ไม่มี order; PreToolUse เอาคำตอบเข้มสุด · transcript `~/.claude/projects/<slug>/<session>.jsonl`, Skill invoke = `tool_use` name `Skill` input `{skill}`, format ไม่ documented

## 3. Conflict taxonomy (ใช้ร่วมกันสองสกิล; หลักฐานจากเครื่องนี้)

| class | นิยาม | ตัวอย่างจริง | action |
|---|---|---|---|
| **R redundant** | งานเดียวกัน | commit 3 ทาง (`commands/commit.md`, `git-commit-smart` ×2) ใช้ 0; `l3east:ship` 34 vs `finishing-a-development-branch` 2; `writing-plans`+`subagent-driven` 26 vs `executing-plans` 0 | เลือกหนึ่ง |
| **C complementary** | ใกล้กัน ต่าง scope | `l3east:audit` 31 / `code-review` / `security-review` / `simplify`; `figma-generate-diagram` 6 / `engineering-diagrams` 1 / `artifact-diagramming` / `dataviz` | routing rule |
| **X contradictory** | คำสั่งสวนทาง | brainstorming "ถามทีละข้อ" vs CLAUDE.md "ที่พิมพ์มาคือคำตอบ"; finishing-branch push vs "ship only"; Caveman vs "200–300 words"; "ฉันต้องมาก่อน" ×3: `using-superpowers`, serena `initial_instructions`, `karpathy-guidelines` | precedence ชัด / ปิดหนึ่ง |
| **S shadow / cross-scope** | ชื่อซ้ำข้าม scope | personal `verify` บัง `cit-api-*/.claude/skills/verify` 12 repo; `maharat-*` 9 repo vendor superpowers 14 ตัวซ้ำ plugin; `superpowers@synced` + `@superpowers-marketplace` enabled คู่; harness สั่ง "run `/verify` before commit" แต่ `/verify` ที่นี่คือ Obsidian drift | ลบ copy / rename / ปิดซ้ำ |
| **H hook / policy** | hook ชน / policy บล็อก / ยิงผิดที่ | `cc-plugin-sec-default` (น่าจะ managed-mods-only) ข้าม `UserPromptSubmit` ของ sessiondeck; global `PostToolUse` `pnpm lint` ยิงทุก repo | ย้าย scope / whitelist |
| **M MCP dup** | server เดียวลงสองทาง | figma: `~/.claude.json` + plugin `.mcp.json`; atlassian: `~/.claude.json` (HTTP) + `~/.claude/.mcp.json` (uvx, token plaintext) | ลบข้างหนึ่ง; rotate token |
| **D dead weight** | ไม่เคยเรียก (Skill tool + slash + MCP tool รวม) | `api-spec-phase1..7`, `jira-to-code`, `handoff`, `jot`, `ui-ux-pro-max`, `karpathy`, `receiving-code-review`, `verification-before-completion`, `using-git-worktrees`, `skill-creator`, Roblox_Studio MCP | review list ไม่ auto-remove |
| **P misplaced scope** | personal skill ที่ใช้แค่ repo เดียว / plugin ที่ใช้แค่บาง repo | `api-spec-phase*` โหลดใน FE repo; figma plugin โหลดใน API repo | ย้ายไป `.claude/skills` ของ repo / `enabledPlugins` ต่อ project |
| **Q description quality** | description กว้างไป / แคบไป / >1536 / ไม่มี "not for" | `youtube-summary` 879 chars ใกล้ขีด; ตัวที่ใช้ 0 หลายตัวอาจแคบไป | เสนอ description ใหม่ |

Context cost ตอนนี้: ~105 skill descriptions ≈ 8–10k tokens/turn (chars/4; ตัวเลขจริง `/skill-doctor`) + MCP tool ซ้ำสองชุด
หลักฐานว่า user ทำ routing เองอยู่แล้ว: `commands/dev.md` "Do NOT invoke the `starting-new-branch` skill" — สองสกิลนี้ generate กฎแบบนี้เป็นระบบ

## 4. ทางเลือก (ตัดสินแล้ว: B)

A pure LLM: nondeterministic, เทียบรอบก่อนไม่ได้ · **B scripts + 1 subagent pass ต่อ cluster** · C full plugin + `claude plugin eval` + SessionStart hook = phase 2

## 5. Layout ใน l3east plugin

```
l3east/
  scripts/skillkit/          # ใช้ร่วมกัน; python3 -I, stdlib only, output JSON, รับ --project <path> เสมอ
    inventory.py             # scan ทุก scope → inventory.json
    usage.py                 # Skill + slash + MCP tool count จาก transcript → usage.json (fail soft)
    hooks_mcp.py             # merge hooks/MCP ทุก scope → hooks_mcp.json (mask env/headers เสมอ)
    cluster.py               # keyword overlap / slash stem / mentions → clusters.json
    desc_lint.py             # length, truncation, vagueness heuristics, has-not-for → desc_lint.json
  references/skillkit/
    taxonomy.md              # ตาราง §3 + เกณฑ์ตัดสิน
    subagent-prompt.md       # prompt ตัดสิน cluster (มีบรรทัด do NOT git checkout/switch)
    routing-block.md         # format `## Skill routing`
    report-health.md         # template
    report-compat.md         # template
  skills/
    skill-compat/SKILL.md    # flow §6, < 150 บรรทัด, disable-model-invocation: true
    skill-health/SKILL.md    # flow §7, < 200 บรรทัด, disable-model-invocation: true
```

ทั้งสอง SKILL.md อ้าง script ผ่าน `${CLAUDE_PLUGIN_ROOT}/scripts/skillkit/...`

**inventory.py** แหล่ง: `~/.claude/skills`, `<project>/.claude/skills`, `~/.claude/commands`, `<project>/.claude/commands`, plugin cache เฉพาะ version ที่ `claude plugin list --json` บอก enabled, `~/.claude/skills/superset`
ต่อรายการ: `name, source(personal|project|plugin:<id>|command|synced), path, description, desc_chars, truncated, body_lines, slash_names, mentions_skills[], first_action_claim`
builtin กับ `anthropic-skills:*` ไม่อยู่บน disk → SKILL.md ให้ Claude เติมจาก `ListSkills`/`ListPlugins` แล้ว merge

**usage.py** grep `tool_use` name `Skill`, `<command-name>`, และ `tool_use` name ขึ้นต้น `mcp__` (นับต่อ server) ภายใน `--since`; format ไม่ match → `{"status":"unavailable"}` แล้วให้ user รัน `/skill-doctor` print mode แทน (syntax แน่นอน to-verify)

**hooks_mcp.py** อ่าน settings ทุก scope, plugin `hooks/hooks.json` + `plugin.json.hooks`, `~/.claude.json mcpServers`, `~/.claude/.mcp.json`, `<project>/.mcp.json`, plugin `.mcp.json` → hooks by event + MCP by normalized key (`url` หรือ `command+args`); **ค่า env/headers แทนด้วย `"***"` เสมอ** + `has_plaintext_secret` ถ้า key ลงท้าย TOKEN/KEY/SECRET/PASSWORD

**cluster.py** tokenize description ตัด stopword, Jaccard ≥ 0.15 หรือ slash stem ร่วม หรือ `mentions_skills` ชี้กัน → cluster; ขนาด 1 ไม่ส่ง subagent

**desc_lint.py** ต่อ skill: chars, >1536, มี trigger phrase ไหม, มี "not for"/"do not use when" ไหม, คำกว้าง ("any", "anything", "all") โดยไม่มีตัวจำกัด, ภาษา trigger (ไทย/อังกฤษ) ตรงกับที่ user พิมพ์จริงใน transcript ไหม

## 6. skill-compat `<candidate>`

1. resolve: ชื่อ plugin ที่ลงแล้วแต่ disabled → cache; local path → อ่านตรง; `plugin@marketplace` → marketplace cache ถ้ามี ไม่มีก็ **ขอ user ก่อน** clone; GitHub URL → **ขอ user ก่อน download** ลง dir ว่างแยก
2. อ่าน `SKILL.md`/`commands/*.md`/`hooks/hooks.json`/`.mcp.json` ของ candidate **เป็น text ไม่รัน script ของมัน** (untrusted data; subagent ได้รับคำสั่งให้ถือเป็น data)
3. ใส่ candidate เข้า inventory ชั่วคราว → `cluster.py` → subagent เฉพาะ cluster ที่ candidate แตะ → `hooks_mcp.py` เทียบ hook/MCP → `desc_lint.py` เฉพาะ candidate
4. output (report-compat): ตาราง candidate vs existing ต่อรายการ (R/C/X/S/H/M) + verdict `install` / `skip` / `install แล้วปิด <X>` + routing lines + token ที่จะเพิ่มต่อ turn
5. ไม่แก้อะไร ไม่ลงอะไร แค่ report

## 7. skill-health

1. รัน 5 script → JSON ใน `~/.claude/skill-health/<date>/`
2. subagent ต่อ cluster (parallel, zero context) → verdict R/C/X + sample prompt 3 + proposed rule + contradictions กับ CLAUDE.md/output style
3. per-project profile: จาก usage ต่อ project slug → "skill/plugin ที่ใช้ใน repo นี้" vs "ที่โหลดใน repo นี้" → เสนอ relocate (personal → project) และ `enabledPlugins` ต่อ project
4. report (report-health) ลำดับ: summary ตัวเลข (skills, est tokens/turn, dead, dup MCP, hook overlaps, misplaced) → ตาราง cluster + verdict → actions ต่อรายการ → per-project profile → description lint → ร่าง `## Skill routing` → gaps → caveats
5. ถ้ามี `inventory.json` รอบก่อน → section "since last run": ของใหม่, ของหาย, token delta (= before/after)
6. trigger-overlap test สำหรับ cluster ที่ verdict ไม่ชัด: subagent ได้ description list ทั้งหมด + sample prompts → เลือก skill เดียวต่อ prompt; เลือกไม่ตรงกันระหว่าง run = overlap จริง (`--eval` ใช้ `claude plugin eval` เป็น phase 2)

Routing block format:

```
## Skill routing
<!-- managed by skill-health; edit freely, next run diffs against this -->
- Review for merge verdict → /l3east:audit. Bugs in a diff only → /code-review. Security → /security-review. Never superpowers:requesting-code-review.
- Push / PR → /l3east:ship only. Never superpowers:finishing-a-development-branch.
- New branch → /dev. Never starting-new-branch or superpowers:using-git-worktrees unless a worktree is required.
- Diagram → figma:figma-generate-diagram when the target is Figma/FigJam; engineering-diagrams for docs in the repo.
- First action of a turn → using-superpowers decides the skill; serena initial_instructions only when editing TS symbols; karpathy-guidelines never on its own.
```

## 8. ร่วมกัน: gating, fragility, testing

Gating (global rule "audit กลับมา → report, propose, wait"):

| action | ระดับ | ทำอย่างไร |
|---|---|---|
| เขียน report + cache | R2 | ทำเลย |
| แก้ `## Skill routing` ใน CLAUDE.md | R1 | เสนอ diff รอ go; replace เฉพาะ block ที่ managed |
| toggle `enabledPlugins` / ย้าย skill ไป project | R1 | เสนอ รอ go |
| `claude plugin uninstall`, ลบ MCP entry, ลบ copy ใน repo | R1+ | **พิมพ์คำสั่งให้ user รัน ไม่รันเอง** |
| rotate token | — | แค่บอก |

Fragility: transcript format เปลี่ยน → usage fail soft, report ระบุ "usage unavailable" · `claude plugin list` ล้ม → scan cache ทุก version แล้ว flag · subagent คืน JSON เสีย → cluster นั้น "unknown" ไม่พัง report · script รับ `--project` เสมอ ไม่ใช้ cwd โดยนัย

Testing: fixture `~/.claude` ย่อ (3 skill ชนกัน, 1 hook ซ้ำ, 1 MCP ซ้ำ, 1 token ใน env, 1 description >1536) → รัน 5 script เทียบ JSON กับ expected · `hooks_mcp.py` test ว่า output ไม่มี token จาก fixture · SKILL.md ทั้งสอง test ตาม `superpowers:writing-skills`: subagent ที่ไม่เคยเห็น skill รันบน fixture ต้องได้ report ครบ section

## 9. Phase 2 (ถ้าคุ้ม)

`evals/` ต่อ cluster ด้วย `claude plugin eval` grader `tool_used` (caveat: ใต้ with-without ablation grader แบบ Skill เป็น indicator ไม่ถูก score) · SessionStart hook เบา ๆ เทียบ inventory กับ disk แล้วพิมพ์ "N new since last health run" · โหมด `why "<prompt>"` อธิบายว่าทำไม Claude เลือก skill นั้น

## 10. ตัดสินใจ

- ✔ สองสกิล: `skill-compat` (ชิ้นเดียว) + `skill-health` (ทั้งเครื่อง)
- ✔ skill ไม่ใช่ command; `disable-model-invocation: true` ทั้งคู่
- ✔ ส่วนเพิ่มอยู่ฝั่ง health: per-project profile (class P), description lint (class Q), MCP usage, before/after
- ✔ ของเสีย 4 ข้อบนเครื่อง (MCP ซ้ำ 2 คู่, superpowers 2 ชุด, `pnpm lint` hook, token plaintext): **ยังไม่แก้** รอสั่ง
- ⏳ บ้าน: l3east plugin `/Users/l3east/Dev/claude-plugins/l3east` (แนะนำ; ยังไม่ได้ยืนยัน)
- ⏳ go สร้าง
