# 技能来源与可选依赖

仓库只包含项目自己的 `mathm-latex-writing` 适配技能。公开源码不包含本机其他技能、私有写作资料、论文语料、上传材料或 Codex 安装记录。

可选功能：

| 技能 | 功能 |
|---|---|
| nature-writing + nature-shared | 科研章节写作规则 |
| nature-polishing + nature-shared | 科研润色规则 |
| nature-figure | 可选图片源码、字号及碰撞审查工具 |
| hwb-problem-translator / hwb-modeling-ideas / hwb-model-dictionary | HWB 读题流程 |
| hwb-abstract-checker / hwb-model-solution-checker / hwb-reference-appendix-checker | HWB 论文审查 |

取得相应技能的使用许可后，可使用 scripts/import_skills.py 从自己的目录导入，或设置 MATHM_SKILLS_DIR。不要将忽略规则移除后误上传本机全部技能。

用户最初选用的公开 HWB 来源为 [xieyouxixi/hwb-math-modeling-skills](https://github.com/xieyouxixi/hwb-math-modeling-skills)。本机 Nature 技能不在本仓库重新分发，需自行提供。科研写作方法的另一个公开参考为 [K-Dense scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)，不是本项目自动安装的依赖。

第三方规则不代表当年赛事或目标期刊的现行官方要求；以用户提供的适用规范为准。测试目录中的规则文件是路由测试桩，不是真实技能。
