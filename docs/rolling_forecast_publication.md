# 预测证据发布状态 / Forecast archive publication status

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

本地实验和完整复算已完成，331项测试及wheel安装检查通过，新研究共有73份文件。自动审批先拒绝公开上传`traces-05.jsonl`，随后也拒绝包含已准备轨迹的提交，理由是此前明确授权只覆盖三份敏感性文件，未覆盖新的预测证据。因此本PR只提交代码、研究报告和摘要清单；全部73份新证据文件均等待明确公开上传授权，不纳入分支。不修改原文件字节、不拆分、不重新编码以绕过拒绝。

已完成[全部轨迹字段检查与独立物理审核](../data_sources/rolling_forecast_artifact_audit.json)：32份轨迹文件、352轨迹、4,224期，与再生成的合成任务、源码和文件哈希匹配。轨迹只允许合成任务ID、固定方法名、SHA256及数值字段，不含自由文本、真实公司订单或API密钥。完整策略重执行另已通过。这项检查解释内容范围，不替代公开上传授权。

目的地是公开仓库`nomoretry/semiconductor-logistics-decarbonization`的`benchmark_results/rolling_forecast_development/`。下表列明全部73份文件的原始SHA256：32份预测、32份轨迹，以及配置、任务、校准、选参、结果、计时、汇总、运行版本和manifest。公开后任何人均可读取这些合成实验记录。核准文字可以是：

> 我批准将预测研究清单中的73份证据文件，按清单SHA256公开上传到nomoretry/semiconductor-logistics-decarbonization。

## English

The local experiment and complete replay are finished; all 331 tests and wheel checks passed. The study contains 73 files. Automatic approval review first stopped the upload of `traces-05.jsonl`, then rejected the commit containing the already prepared traces, because prior explicit approval covered three sensitivity files rather than the new forecast evidence. This draft PR therefore includes only code, research reports and checksum metadata. All 73 new evidence files await explicit public-upload approval and are excluded from the branch. No original artifact is changed, split or re-encoded to bypass the rejection.

The [complete trace-field inspection and independent physical audit](../data_sources/rolling_forecast_artifact_audit.json) covers 32 trace files, 352 trajectories and 4,224 periods, matching regenerated synthetic tasks and source/artifact hashes. Allowed trace values are generated task IDs, fixed method names, SHA256 hex and numerical fields, with no free text, actual company orders or API keys. Full policy reexecution also passed. These checks describe content; they do not substitute for public-upload authorization.

The destination is the public repository `nomoretry/semiconductor-logistics-decarbonization`, directory `benchmark_results/rolling_forecast_development/`. The 73 pending files and original digests are listed below: 32 forecast files, 32 trace files, and configuration, tasks, calibration, selection, outcomes, timing, summary, runtime and manifest. Publication makes these synthetic experiment records readable by anyone.

## 待上传清单 / Pending files

| 文件 / File | 字节 / Bytes | SHA256 |
|---|---:|---|
| `calibration.jsonl` | 18376 | `660970afa796d619cc9de1dbcb1216bbe3cb3e38330578cfbaf918007d2666e2` |
| `config.json` | 623 | `a88486f28402367d44f3ec9302d018f85f42236ff2eea4b32949d67786c9f9c2` |
| `forecasts-00.jsonl` | 54493 | `faeadac19bd7316bf5d8239f5c5a2e6b5b385a381f93e6f316244164c142cf84` |
| `forecasts-01.jsonl` | 54573 | `3212481a9e56632537bb0ad5c1bc48abed85ab6c9bc593bacea58e0e0427c78f` |
| `forecasts-02.jsonl` | 53846 | `e6623a3b23b3ce7679e8ddd1ab8e505f53107d2cf32bf45e3405edecd2f3b9d6` |
| `forecasts-03.jsonl` | 53934 | `415914705d9000f5b1a2c2b3d0396880b6751dfc7e1930b72ce22055c0c8dd60` |
| `forecasts-04.jsonl` | 54503 | `accedd9b08aa453867b0cbad7aef4513b3a88a75dd2468b9f05656132ea2fab2` |
| `forecasts-05.jsonl` | 54602 | `10a409469c7ee683a3506eaff9d3e47362ea5368e371c05d83aa7fcedcc35b3d` |
| `forecasts-06.jsonl` | 53470 | `54138655d0ade0f570d476d87a768e063421a280cae1a9de205723e142d1b38e` |
| `forecasts-07.jsonl` | 54442 | `4cf368160552800917e06411d81a2ca8a88e642768e27e40cd60f6107c8c9df7` |
| `forecasts-08.jsonl` | 55368 | `3df5710a72afc0e7729e9828d2a009bc1c3ded586bf2fdf998296f7b2248baf7` |
| `forecasts-09.jsonl` | 54269 | `040af5b5540f9fa53e37ea0ccc6194ac9deb6fbdebca4954d24a90da0834cd1c` |
| `forecasts-10.jsonl` | 54104 | `89be98af9e2203abe42b57da34355f032773e1e1d9e82cd8d363dd1c343ea1c3` |
| `forecasts-11.jsonl` | 54640 | `e940a792ef39c9d9e29735861f399ad0bfdb9e8ecdcfdbb8ff1b1b8839dfc35f` |
| `forecasts-12.jsonl` | 55131 | `95873c77e8250ec3bb29c157c8880b6b433434be0be830d71da6a1b9eac9c816` |
| `forecasts-13.jsonl` | 54428 | `cf688e1fccf1ac774c82a5903d1a9e3dfb407b4bdfe4100ec0dab833712bf2d1` |
| `forecasts-14.jsonl` | 54842 | `ff3b39b487dc5f4c5ad9415d4438211306206c453591ab6c9033226fe2e390bf` |
| `forecasts-15.jsonl` | 55030 | `8d0135b621c35c58e51d0cb8d64e2d6b9cfcf475f68a61a1163d88b78b3032af` |
| `forecasts-16.jsonl` | 54870 | `861727c82c8494abd2f80810699e9bbead3e17082b05a672a84fe59b3ba63d69` |
| `forecasts-17.jsonl` | 55096 | `b822692a2609903a433383aa9a24152b758dd2f97e88de94dc2a0ad81fd180d0` |
| `forecasts-18.jsonl` | 54809 | `5b5c3549dda750ae2f65b9a8daabf413bd31f873c44e32f1c5b4fac02096d7a3` |
| `forecasts-19.jsonl` | 53747 | `9d2ea5262b51af47e446e3ece5b6be6926894552858d251b2465ab1ddfb93c7f` |
| `forecasts-20.jsonl` | 54388 | `33ce54701874fe341afe80d1c345863fd0c4aa5498c8a507dfcf1ed105de28c8` |
| `forecasts-21.jsonl` | 54184 | `c2f6bccc596204dc9dbee57b506951d6a440125538927bbd54f3fb32590cf8f6` |
| `forecasts-22.jsonl` | 53757 | `142860b876c7a3faef81060a8e84cffc45a4cb6c8b175ffc3d61c76e2d32cc98` |
| `forecasts-23.jsonl` | 55023 | `fc63824cd3af858771376b26691271ddffac71f8772080783e6c4e4975178343` |
| `forecasts-24.jsonl` | 54858 | `ade48d8ea9d3c8e65eedded60bd04a259806c37e3becb9fc11e9fc317ccc1edc` |
| `forecasts-25.jsonl` | 55413 | `cffc8b6ebd8fc43a10db32643b6515181817a0fb53925f8f8c00ad431032ac9c` |
| `forecasts-26.jsonl` | 55023 | `dd7ac32930a717d6c78050385b886d17a41655c8c5da10b8163082c8a5107026` |
| `forecasts-27.jsonl` | 55715 | `d3851fe2b616519e20f3ffb10ff0cb286ccb5ed2aeb2018c511ffc65b548d8a4` |
| `forecasts-28.jsonl` | 55640 | `a613f82cd025ce43005a9df40d347fb6e1270a43784bd98556d5e14c4688042f` |
| `forecasts-29.jsonl` | 55291 | `017e9cd2b37bda572ed193570c9f1a9a433086d0132fad3413edd6ebcfe51472` |
| `forecasts-30.jsonl` | 55626 | `c30d97419ab900a14bd16d8afed728c9af9f3dfeefcdb20e519abd52120ea5cf` |
| `forecasts-31.jsonl` | 55090 | `571be7f39ed86e90187ce1a8c47ac6e427eb38d2b972380b3b47164f977b923c` |
| `manifest.json` | 8678 | `41d3b351f6c5e2a5f89ccda82856dad77db209aedbc6dfc5b77672a0358be3c0` |
| `outcomes.jsonl` | 127066 | `930a409cea4663225cdf9c312923660d8414bfc169ce58aba94596e18ab4d16c` |
| `runtime.json` | 67 | `8fb0db89206baabe597889d2a498653e30ff0bc72223bb0cb64c6fe1eaf6a2df` |
| `selection.json` | 691 | `1c9023c4d9b1c58295ecd12afd1c6bc00dad54f91ed79b3a5c57d780f2a2fbe9` |
| `summary.json` | 60820 | `1b975a09b70bf398365303f0acbace340b34f0c0e190b94b46977cc1314b220a` |
| `tasks.json` | 103288 | `94eed0d813188d334e16c3f1df9d3486d8889313bd6316be299c1e741d2fb192` |
| `timing.jsonl` | 119107 | `d037632b833bae4ec26c2f594fb154c9658deff2e289dac237371258e9cd1622` |
| `traces-00.jsonl` | 127560 | `13ef04c4daa33e3097417f0bdc03090a6979d605697a11d0f131a94f51aebf7f` |
| `traces-01.jsonl` | 127848 | `5f95b70084a4be8af4ae7f71893806616cdd7d237a1b177db763ef05989f715a` |
| `traces-02.jsonl` | 127173 | `7f2d40dd7b012e8781ba0fc53b05400385c9306c43ac7f199607fe7718092e46` |
| `traces-03.jsonl` | 127270 | `2efe8adfda0bf58f2d52f33e090eb348450fcbebd532192f4256f8978a62b7db` |
| `traces-04.jsonl` | 128093 | `fdf45add67ffa3f69dc5ece58559d8af359042a7becb0fac37fe0ca102f141e6` |
| `traces-05.jsonl` | 127783 | `bbcd09f3871a338f6e1ac7f639e65d5c7983419630bfa8c3859aa13f9e0b6f66` |
| `traces-06.jsonl` | 126261 | `c760e117f7d3cb624aeb8f3d979dfb915bc10d7d6e5ee9c55da9f6e54a445e9f` |
| `traces-07.jsonl` | 127627 | `83ca1dfcaab640789da56f165370d63cf6fde8d01068799f69a1d999025cf7fa` |
| `traces-08.jsonl` | 127819 | `c62b363062a34b919f31b2cbd03a7488911c95cc6c78d9c29cb108f67f4bf7bc` |
| `traces-09.jsonl` | 126441 | `16be40d1d5254564a31ab7f6346ac065a365ea313850ff84a048a08ff821e3ed` |
| `traces-10.jsonl` | 126422 | `12e5bf2e7a0d02e3793439d93c99d974eedc94eda77d043b016a7db922cfd073` |
| `traces-11.jsonl` | 127243 | `f8ca7c0fe4637eb9cc315098f925ba6d088b6e88b84d555ec5a18e41346cd2ae` |
| `traces-12.jsonl` | 127941 | `47ec381dce23f3f07d82ffc1dd6acb559b078c563296d37c6d5e28af5b4db6a5` |
| `traces-13.jsonl` | 126707 | `7f2b94ef87cb4081b98a0fa5456734ace39f35925f1aa354097bea0a185c777b` |
| `traces-14.jsonl` | 127456 | `f5e4658beec15f994d337793e3d5d5fb2d771c0b5bf7d99d44cabc198b2b1dfd` |
| `traces-15.jsonl` | 127564 | `fcf66e752e0e81421d32f385f1ffaaf4c2919bdfea66dfec1e5b7014cd5e1a32` |
| `traces-16.jsonl` | 127663 | `0454e6df1370fa772ed05cd13443876407810c4d15d2eacb72cd174ef5d51b62` |
| `traces-17.jsonl` | 128557 | `fa891679150784d422f932c5930c6efb95702a267f7f67abc74be518d509ebe3` |
| `traces-18.jsonl` | 127736 | `75c2a0cffd84f127f002845850f3623242fc27445c12752f7c885ed9c7cd9402` |
| `traces-19.jsonl` | 127103 | `7939666e0bd840ef68e3a0823a2e882538872c3dbba06cbd057690fc099e7c0b` |
| `traces-20.jsonl` | 127280 | `49decd876339a26c2aafd2b14cb1777520854b8a3d7014a23d6479451d2dc9fe` |
| `traces-21.jsonl` | 126891 | `9ba28c85c7feed016be9be4bd4e8ac457eb14c6794d3fb908fbadc354091202f` |
| `traces-22.jsonl` | 126625 | `b82822bb1670a8c4403ce6b3a2a7af65cc6df01c689cdc7b576bd1bf6fa8ab6e` |
| `traces-23.jsonl` | 127963 | `581cfa79f1d655ea851df2348f9a2c99d5209e8e5d5d4691382f30757fa8939b` |
| `traces-24.jsonl` | 127235 | `69f80684ff0c493efa0cae6ab721536cb7de1898ed9aa15d662311cfd8631fff` |
| `traces-25.jsonl` | 127902 | `21087ee1e457a3f718e0283d7a1792b5972add7b706972df64bc7b100034a025` |
| `traces-26.jsonl` | 127514 | `433d10219bc8e004dab95a948902d0da811104cf208b61d4fc6618bbc2477ba3` |
| `traces-27.jsonl` | 128147 | `abad70ee2c2cce7aeea8f31e1de36590e86c71f623627fc2bff6b132f0bb727c` |
| `traces-28.jsonl` | 128232 | `ad7e822cfe700c1d38eac74fc89307b864967a27df97111e4a64c0a926efaeeb` |
| `traces-29.jsonl` | 127783 | `04af15ac59c904e9d0b4d8a04a32ed32c13132f5167079856a2760de0545f74c` |
| `traces-30.jsonl` | 128318 | `b9aa7585e70283d7faef3db860a4c74c7ce3f11e5871084599d72a77139a096c` |
| `traces-31.jsonl` | 126918 | `b7e8ff5ff1758898288376a347b32b569a8eb7fe02c2f434351dd56e5fba337e` |

`make verify-forecast`必须继续拒绝没有完整证据包的检出，不能把本地通过解释为当前GitHub检查通过。批准补齐后，再验收当前提交的全部六项CI，并将PR转为可审阅。

`make verify-forecast` must continue to reject checkouts without the complete evidence bundle. Local success is not current-head GitHub CI success. After publication is approved and complete, check all six jobs on the resulting commit and mark the PR ready for review.
