# 验证样例

本文档提供完整的验证步骤，展示 seekdb 和 PowerContext 在项目中的实际作用。

## 前置准备

确保后端和前端已按 [运行说明](run.md) 启动：
- 后端：`http://localhost:8080`
- 前端：`http://localhost:3000`（或直接打开 `frontend/index.html`）
- PowerContext（可选）：`http://127.0.0.1:8000`

---

## 验证样例 1：实验记录 + 语义搜索（seekdb）

### 目标

验证 seekdb 向量检索能够理解自然语言查询，找到语义相关的实验记录。

### 步骤

#### 1.1 录入实验数据

在「实验记录」页面（`experiments.html`），依次添加以下 5 条实验记录：

**实验 1：ResNet50 baseline**
- 所属项目：`image-classification`
- 标题：`ResNet50 baseline without augmentation`
- 状态：成功
- 标签：`cnn,baseline`
- 参数：`{"model": "ResNet50", "learning_rate": 0.01, "batch_size": 32, "epochs": 50}`
- 指标：`{"accuracy": 0.856, "loss": 0.423}`
- 笔记：`基础模型，未使用数据增强。训练过程稳定，但准确率偏低，存在过拟合迹象。`

**实验 2：ResNet50 with augmentation**
- 所属项目：`image-classification`
- 标题：`ResNet50 with data augmentation`
- 状态：成功
- 标签：`cnn,augmentation`
- 参数：`{"model": "ResNet50", "learning_rate": 0.005, "batch_size": 64, "epochs": 80}`
- 指标：`{"accuracy": 0.923, "loss": 0.215}`
- 笔记：`加入随机翻转和裁剪增强。准确率显著提升，过拟合缓解。`

**实验 3：VGG16 comparison**
- 所属项目：`image-classification`
- 标题：`VGG16 with augmentation`
- 状态：成功
- 标签：`cnn,augmentation,vgg`
- 参数：`{"model": "VGG16", "learning_rate": 0.001, "batch_size": 32, "epochs": 100}`
- 指标：`{"accuracy": 0.891, "loss": 0.312}`
- 笔记：`VGG16 比 ResNet50 慢，准确率也略低，参数量更大但效果不如 ResNet。`

**实验 4：Low learning rate experiment**
- 所属项目：`image-classification`
- 标题：`ResNet50 with very low learning rate`
- 状态：不确定
- 标签：`cnn,learning-rate`
- 参数：`{"model": "ResNet50", "learning_rate": 0.0001, "batch_size": 32, "epochs": 50}`
- 指标：`{"accuracy": 0.782, "loss": 0.567}`
- 笔记：`学习率过低导致收敛缓慢，50 个 epoch 后仍未收敛。需要更多 epoch 或提高学习率。`

**实验 5：Failed experiment**
- 所属项目：`image-classification`
- 标题：`ResNet50 with too high learning rate`
- 状态：失败
- 标签：`cnn,learning-rate,failed`
- 参数：`{"model": "ResNet50", "learning_rate": 0.1, "batch_size": 32, "epochs": 30}`
- 指标：`{"accuracy": 0.234, "loss": 2.891}`
- 笔记：`学习率过高导致 loss 爆炸，训练完全失败。需要降低学习率或使用学习率调度器。`

#### 1.2 语义搜索验证

在「语义搜索」页面（`search.html`），依次输入以下查询：

**查询 1：** `哪些实验的准确率超过了90%？`

预期结果：实验 2（accuracy: 0.923）排在最前面。seekdb 向量检索理解"准确率超过90%"的语义，匹配到笔记和指标中相关的实验。

**查询 2：** `学习率较低的实验`

预期结果：实验 4（learning_rate: 0.0001）排在最前面。seekdb 理解"学习率较低"的语义，匹配到相关实验。

**查询 3：** `失败的实验及原因`

预期结果：实验 5（status: failed）排在最前面。seekdb 匹配到笔记中"训练完全失败"的描述。

**查询 4：** `使用数据增强的实验`

预期结果：实验 2 和实验 3 排在前面。seekdb 匹配到标签 `augmentation` 和笔记中的"数据增强"。

### 验证要点

- seekdb 的向量检索能够理解自然语言查询的语义
- 检索结果按语义相关度排序（显示相关度分数）
- 检索结果包含完整的实验信息（参数、指标、笔记）

---

## 验证样例 2：项目追踪（PowerContext）

### 目标

验证 PowerContext 能够持久化项目信息，跨会话记忆。

### 步骤

#### 2.1 创建项目

在「项目管理」页面（`projects.html`）：

1. 填写项目信息：
   - 项目名称：`image-classification`
   - 研究目标：`提升 ImageNet 分类准确率至 95%`
   - 项目描述：`基于 ResNet 架构，探索数据增强和学习率调度对分类性能的影响。`

2. 点击「创建项目」

预期结果：提示"项目已创建（PowerContext 已记忆）"。

#### 2.2 更新项目状态

1. 在「更新项目状态」表单中：
   - 项目名称：`image-classification`
   - 新状态：`进行中`
   - 进展备注：`已完成 5 组实验，ResNet50 + augmentation 效果最佳（92.3%），继续探索学习率调度。`

2. 点击「更新状态」

预期结果：提示"项目状态已更新"。

#### 2.3 验证持久化

1. 刷新页面
2. 点击「刷新」按钮重新加载项目列表

预期结果：项目信息仍然存在，包含最新的状态更新。PowerContext 的记忆是持久化的。

#### 2.4 跨会话验证（可选）

1. 关闭后端服务，重新启动
2. 再次打开项目管理页面

预期结果：项目信息仍然存在。PowerContext 的记忆不随服务重启而丢失。

### 验证要点

- PowerContext 成功存储项目信息（通过 HTTP API）
- 项目信息持久化，刷新/重启后仍然存在
- 可以更新项目状态，PowerContext 记录变更历史

---

## 验证样例 3：实验对比

### 目标

验证实验对比功能，展示参数与结果的对比表。

### 步骤

1. 在「实验对比」页面（`compare.html`），勾选实验 1、2、4、5
2. 点击「生成对比表」

预期结果：

| 维度 | ResNet50 baseline | ResNet50 + aug | Low LR | High LR |
|:---|:---|:---|:---|:---|
| 状态 | 成功 | 成功 | 不确定 | 失败 |
| learning_rate | 0.01 | 0.005 | 0.0001 | 0.1 |
| batch_size | 32 | 64 | 32 | 32 |
| epochs | 50 | 80 | 50 | 30 |
| accuracy | 0.856 | **0.923** ★ | 0.782 | 0.234 |
| loss | 0.423 | **0.215** ★ | 0.567 | 2.891 |

（★ 标记最优值）

### 验证要点

- 对比表自动提取所有参数和指标
- 最优值用 ★ 标记
- 直观展示不同配置对结果的影响

---

## 技术作用总结

| 技术 | 在项目中发挥的作用 | 验证方式 |
|:---|:---|:---|
| **seekdb** | 存储实验记录 embedding，提供语义相似度检索 | 搜索"准确率超过90%"能找到对应实验 |
| **PowerContext** | 持久化项目信息，跨会话记忆 | 刷新/重启后项目信息仍在 |
