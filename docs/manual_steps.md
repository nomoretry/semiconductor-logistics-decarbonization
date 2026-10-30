# 需要你操作的部分

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

当前不需要填写人工意见、重新运行API、发送密钥或租用GPU。8条真实数量抽取和16条真实澄清审核均已完成并归档。

## 合并本轮代码

1. 打开仓库的`Pull requests`，进入本轮同起点PPO与双语研究说明的PR。
2. 查看`Files changed`和实验结果；等待`Python offline checks`成功。
3. 点击`Merge pull request`，再点`Confirm merge`。

普通CI会运行本地合成实验、重新训练小型BC/PPO并复算已保存的证据，不调用OpenAI API。没有额外的手动Actions任务需要启动。

## 人工意见的处理

项目维护者已选择不填写人工意见。旧审核表和冻结数据保留原状，不代填、不把助手参考改称人工金标准。当前真实材料结果注明“未进行人工复核”，可以作为探索证据；它不阻塞查询环境、BC或后续策略研究。

这也意味着目前不能把7/8的参考一致率解释为独立人工验证的真实抽取准确率。以后如取得新的独立标注，另存数据版本并用已有响应离线重评分。

## 可选的GitHub页面设置

- 个人主页点击`Edit profile`，可补充姓名、简介、学校和地区。
- 进入仓库首页，点击右侧`About`旁齿轮，在`Topics`填写`python`、`logistics`、`optimization`、`mixed-integer-programming`等主题，再保存。
- 许可证需要单独确定授权范围。当前没有添加MIT；这不影响Python识别、代码运行或实验推进。

以上页面设置均不是科研验收条件。后续确实需要手动操作时，在本文件注明具体入口和原因。

## English

No human-review form, API rerun, key transfer or rented GPU is required. The eight real-quantity cases and 16 real-notice clarification cases are already archived.

### Merge the current change

1. Open the repository's `Pull requests` and select the shared-start PPO and bilingual-documentation PR.
2. Review `Files changed` and the experiment results; wait for `Python offline checks` to succeed.
3. Click `Merge pull request`, then `Confirm merge`.

CI runs local synthetic experiments, retrains the small BC/PPO policies and verifies saved evidence. It makes no OpenAI API calls, and there is no additional manual Actions workflow to start.

### Human review

The maintainer has chosen not to fill out human-review forms. Frozen review records remain unchanged; assistant references are not relabeled as human gold. Real-source results remain exploratory and unreviewed. This does not block environment or policy research, but the 7/8 reference agreement cannot be interpreted as independently human-validated extraction accuracy. Any future independent labels should be stored as a separate version and used for offline rescoring.

### Optional GitHub settings

The profile's `Edit profile` control manages personal information. The repository's `About` gear manages topics such as `python`, `logistics`, `optimization` and `mixed-integer-programming`. A license requires a separate licensing decision; no MIT license has been added. These settings are not research acceptance criteria. Any future required manual action will be documented here with its location and reason.
