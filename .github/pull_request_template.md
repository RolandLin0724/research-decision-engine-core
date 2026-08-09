# Summary / 摘要

<!-- Explain the change and its rationale. / 请说明改动及其理由。 -->

## Related issue / 关联 Issue

Issue: <!-- Add a link when applicable. / 适用时添加链接。 -->

## Change classification / 变更分类

- [ ] Bug fix / Bug 修复
- [ ] Documentation / 文档
- [ ] Test / 测试
- [ ] Portability / 可移植性
- [ ] Performance / 性能
- [ ] Packaging or release / Packaging 或 release
- [ ] Public API, schema, or storage change requiring explicit review /
      需要显式评审的 public API、schema 或 storage 变更
- [ ] Other / 其他

## Contract impact / 合同影响

Explain every affected area; write "None / 无" only when there is no impact. /
请说明每个受影响范围；仅在确无影响时填写“None / 无”。

- Public API / Public API:
- RunSpec or RunBundle / RunSpec 或 RunBundle:
- Replay / Replay:
- SQLite / SQLite:
- Adapters or policies / Adapters 或 policies:
- Packaging or sdist / Packaging 或 sdist:
- Privacy or security / Privacy 或 security:
- Bilingual documentation / 双语文档:

## Verification / 验证

Complete every applicable item. Mark an item `N/A` only beside a written
explanation. / 请完成每个适用项目。只有在旁边写明理由时，才可将项目标记为
`N/A`。

- [ ] Lock check / lock 检查: `uv lock --check`
- [ ] Locked environment sync / 锁定环境同步: `uv sync --locked`
- [ ] Ruff format: `uv run ruff format --check .`
- [ ] Ruff lint: `uv run ruff check .`
- [ ] mypy: `uv run mypy .`
- [ ] Full pytest / 完整 pytest: `uv run pytest`
- [ ] Core release checker / Core release checker:
      `uv run python -m research_decision_engine.core_release_check`
- [ ] Build / 构建: `uv build`
- [ ] Relevant Windows and Linux evidence / 相关 Windows 和 Linux 证据

Exact commands run and results / 实际运行的精确 commands 与结果:

## Privacy and provenance / 隐私与来源

- [ ] No secret, token, or credential is included. / 未包含 secret、token 或
      credential。
- [ ] No private email or unintended legal identity is included. / 未包含私人电子邮箱
      或非有意公开的法律身份。
- [ ] No unredacted local absolute path is included. / 未包含未脱敏的本地绝对路径。
- [ ] No private database or RunBundle is included. / 未包含私人数据库或 RunBundle。
- [ ] No raw audit or recovery evidence is included. / 未包含原始 audit 或 recovery
      evidence。
- [ ] All third-party material has provenance and a compatible license. /
      所有 third-party material 都有来源说明和兼容的 license。
- [ ] No build, cache, or virtual-environment artifact is committed. / 未提交 build、
      cache 或 virtual-environment artifact。

## Compatibility / 兼容性

Explain every change to a public contract, including migration or compatibility
evidence. / 请说明每一项 public-contract change，包括 migration 或
compatibility evidence。

## Documentation / 文档

Describe the documentation impact. Where applicable, confirm that corresponding
English and Simplified Chinese updates have the same meaning. / 请说明文档影响；适用
时，请确认相应的英文和简体中文更新语义一致。
